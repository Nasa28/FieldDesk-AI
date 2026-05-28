"""Postgres connection helpers for the worker."""

from __future__ import annotations

from contextlib import contextmanager
from typing import Iterator

import psycopg
from psycopg_pool import ConnectionPool  # type: ignore[import-not-found]


_pool: ConnectionPool | None = None


def init_pool(dsn: str, min_size: int = 1, max_size: int = 8) -> ConnectionPool:
    global _pool
    if _pool is None:
        _pool = ConnectionPool(conninfo=dsn, min_size=min_size, max_size=max_size, open=True)
    return _pool


def get_pool() -> ConnectionPool:
    if _pool is None:
        raise RuntimeError("connection pool not initialized; call init_pool first")
    return _pool


@contextmanager
def conn() -> Iterator[psycopg.Connection]:
    pool = get_pool()
    with pool.connection() as c:
        yield c
