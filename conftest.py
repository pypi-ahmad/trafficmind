"""Root conftest — shared pytest configuration for the TrafficMind test-suite.

DB-backed tests use ``tests.fixtures.sample_data.make_sqlite_session_factory()``
or per-app dependency overrides.  Add shared cross-module fixtures here only when
they are consumed by two or more test directories.
"""
