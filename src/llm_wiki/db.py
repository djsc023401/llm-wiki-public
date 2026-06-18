from __future__ import annotations

from contextlib import contextmanager
from typing import Iterator

import psycopg
from psycopg.rows import dict_row

from .config import Settings, load_settings


@contextmanager
def connect(settings: Settings | None = None) -> Iterator[psycopg.Connection]:
    resolved = settings or load_settings()
    with psycopg.connect(resolved.database_url, row_factory=dict_row) as conn:
        yield conn


def execute(conn: psycopg.Connection, sql: str, params: tuple | dict | None = None) -> None:
    with conn.cursor() as cur:
        cur.execute(sql, params)


def fetch_one(conn: psycopg.Connection, sql: str, params: tuple | dict | None = None) -> dict | None:
    with conn.cursor() as cur:
        cur.execute(sql, params)
        return cur.fetchone()


def fetch_all(conn: psycopg.Connection, sql: str, params: tuple | dict | None = None) -> list[dict]:
    with conn.cursor() as cur:
        cur.execute(sql, params)
        return list(cur.fetchall())
