"""Shared FastAPI dependency aliases."""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.app.db.session import get_db_session

DbSession = Annotated[AsyncSession, Depends(get_db_session)]