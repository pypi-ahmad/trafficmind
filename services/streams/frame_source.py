"""Frame-source abstraction — reads frames from RTSP, files, or test patterns.

Each source is a context manager that yields frames.  The worker owns the
read loop; the source only knows how to open, read one frame, and close.
"""

from __future__ import annotations

import abc
import logging
from pathlib import Path
from urllib.parse import unquote, urlparse

import cv2
import numpy as np

from services.streams.schemas import SourceKind

logger = logging.getLogger(__name__)


def _resolve_local_video_path(
    source_kind: SourceKind,
    source_uri: str,
    source_config: dict,
) -> Path:
    """Resolve file-like sources to a local path the worker can open."""

    candidate_uri = source_uri

    if source_kind == SourceKind.UPLOAD and source_uri.startswith("upload://"):
        upload_path = (
            source_config.get("local_path")
            or source_config.get("file_path")
            or source_config.get("path")
        )
        if not upload_path:
            msg = (
                "Upload sources require source_config.local_path, source_config.file_path, "
                "or source_config.path for worker execution."
            )
            raise ValueError(msg)
        candidate_uri = str(upload_path)

    if candidate_uri.startswith("file://"):
        parsed = urlparse(candidate_uri)
        path_text = unquote(parsed.path)
        if parsed.netloc:
            path_text = f"//{parsed.netloc}{path_text}"
        if len(path_text) >= 3 and path_text[0] == "/" and path_text[2] == ":":
            path_text = path_text[1:]
        return Path(path_text)

    return Path(candidate_uri)


class FrameSource(abc.ABC):
    """Abstract frame reader."""

    @abc.abstractmethod
    def open(self) -> None:
        """Open the underlying capture device / file."""

    @abc.abstractmethod
    def read(self) -> tuple[bool, np.ndarray | None]:
        """Read the next frame.  Returns (ok, frame)."""

    @abc.abstractmethod
    def release(self) -> None:
        """Release resources."""

    @property
    @abc.abstractmethod
    def fps_hint(self) -> float:
        """Reported or estimated frames-per-second."""

    @property
    @abc.abstractmethod
    def resolution(self) -> tuple[int, int]:
        """(width, height) of the source, or (0, 0) if unknown."""

    @property
    @abc.abstractmethod
    def is_live(self) -> bool:
        """True for real-time sources (RTSP, webcam).  False for files."""

    def __enter__(self) -> FrameSource:
        self.open()
        return self

    def __exit__(self, *_: object) -> None:
        self.release()


class OpenCvSource(FrameSource):
    """OpenCV VideoCapture-backed source for RTSP, files, and webcam devices."""

    def __init__(
        self,
        uri: str | int,
        *,
        source_kind: SourceKind,
        loop: bool = False,
    ) -> None:
        self._uri = uri
        self._source_kind = source_kind
        self._loop = loop and not self._is_live_kind
        self._capture: cv2.VideoCapture | None = None

    @property
    def _is_live_kind(self) -> bool:
        return self._source_kind in {SourceKind.RTSP, SourceKind.TEST}

    def open(self) -> None:
        cap = cv2.VideoCapture(self._uri)
        if not cap.isOpened():
            msg = f"Cannot open video source: {self._uri}"
            raise IOError(msg)
        self._capture = cap
        logger.info(
            "Opened %s source: %s  resolution=%dx%d  fps=%.1f",
            self._source_kind.value,
            self._uri,
            *self.resolution,
            self.fps_hint,
        )

    def read(self) -> tuple[bool, np.ndarray | None]:
        if self._capture is None:
            return False, None
        ok, frame = self._capture.read()
        if not ok and self._loop:
            self._capture.set(cv2.CAP_PROP_POS_FRAMES, 0)
            ok, frame = self._capture.read()
        return ok, frame if ok else None

    def release(self) -> None:
        if self._capture is not None:
            self._capture.release()
            self._capture = None
            logger.info("Released %s source: %s", self._source_kind.value, self._uri)

    @property
    def fps_hint(self) -> float:
        if self._capture is None:
            return 0.0
        fps = self._capture.get(cv2.CAP_PROP_FPS)
        return fps if fps and fps > 0 else 25.0

    @property
    def resolution(self) -> tuple[int, int]:
        if self._capture is None:
            return (0, 0)
        return (
            int(self._capture.get(cv2.CAP_PROP_FRAME_WIDTH)),
            int(self._capture.get(cv2.CAP_PROP_FRAME_HEIGHT)),
        )

    @property
    def is_live(self) -> bool:
        return self._is_live_kind


class TestPatternSource(FrameSource):
    """Generates synthetic frames with a moving rectangle — for testing without a camera."""

    __test__ = False

    def __init__(
        self,
        *,
        width: int = 640,
        height: int = 480,
        fps: float = 25.0,
        max_frames: int | None = None,
    ) -> None:
        self._width = width
        self._height = height
        self._fps = fps
        self._max_frames = max_frames
        self._frame_index = 0

    def open(self) -> None:
        self._frame_index = 0
        logger.info("Opened test pattern source: %dx%d @%.0f fps", self._width, self._height, self._fps)

    def read(self) -> tuple[bool, np.ndarray | None]:
        if self._max_frames is not None and self._frame_index >= self._max_frames:
            return False, None

        frame = np.full((self._height, self._width, 3), 40, dtype=np.uint8)
        x = (self._frame_index * 4) % self._width
        y = self._height // 3
        cv2.rectangle(frame, (x, y), (x + 60, y + 40), (0, 200, 255), -1)
        cv2.putText(
            frame,
            f"F{self._frame_index}",
            (10, 30),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.8,
            (255, 255, 255),
            1,
        )
        self._frame_index += 1
        return True, frame

    def release(self) -> None:
        logger.info("Released test pattern source after %d frames", self._frame_index)

    @property
    def fps_hint(self) -> float:
        return self._fps

    @property
    def resolution(self) -> tuple[int, int]:
        return (self._width, self._height)

    @property
    def is_live(self) -> bool:
        return False


def create_frame_source(
    source_kind: SourceKind,
    source_uri: str,
    *,
    source_config: dict | None = None,
    loop: bool = False,
) -> FrameSource:
    """Factory: build the appropriate FrameSource from a source kind and URI."""

    config = source_config or {}

    if source_kind == SourceKind.TEST:
        return TestPatternSource(
            width=config.get("width", 640),
            height=config.get("height", 480),
            fps=config.get("fps", 25.0),
            max_frames=config.get("max_frames"),
        )

    if source_kind == SourceKind.RTSP:
        return OpenCvSource(source_uri, source_kind=SourceKind.RTSP, loop=False)

    if source_kind in {SourceKind.FILE, SourceKind.UPLOAD}:
        path = _resolve_local_video_path(source_kind, source_uri, config)
        if not path.exists():
            msg = f"Video file not found: {source_uri}"
            raise FileNotFoundError(msg)
        return OpenCvSource(str(path), source_kind=source_kind, loop=loop)

    msg = f"Unsupported source kind: {source_kind}"
    raise ValueError(msg)
