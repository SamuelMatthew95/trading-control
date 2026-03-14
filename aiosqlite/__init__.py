"""Minimal local aiosqlite-compatible shim for async sqlite usage in tests."""

from __future__ import annotations

import asyncio
import sqlite3
import types
from typing import Any, Iterable, Optional


class Cursor:
    def __init__(self, cursor: sqlite3.Cursor):
        self._cursor = cursor
        self.arraysize = cursor.arraysize

    @property
    def description(self):
        return self._cursor.description

    @property
    def rowcount(self):
        return self._cursor.rowcount

    @property
    def lastrowid(self):
        return self._cursor.lastrowid

    async def execute(self, sql: str, parameters: Iterable[Any] | None = None):
        if parameters is None:
            await asyncio.to_thread(self._cursor.execute, sql)
        else:
            await asyncio.to_thread(self._cursor.execute, sql, tuple(parameters))
        return self

    async def executemany(self, sql: str, seq_of_parameters):
        await asyncio.to_thread(self._cursor.executemany, sql, seq_of_parameters)
        return self

    async def fetchone(self):
        return await asyncio.to_thread(self._cursor.fetchone)

    async def fetchmany(self, size: Optional[int] = None):
        if size is None:
            return await asyncio.to_thread(self._cursor.fetchmany)
        return await asyncio.to_thread(self._cursor.fetchmany, size)

    async def fetchall(self):
        return await asyncio.to_thread(self._cursor.fetchall)

    async def close(self):
        await asyncio.to_thread(self._cursor.close)


class Connection:
    def __init__(self, conn: sqlite3.Connection):
        self._conn = conn
        self._thread = types.SimpleNamespace(daemon=False)

    async def cursor(self):
        cur = await asyncio.to_thread(self._conn.cursor)
        return Cursor(cur)

    async def execute(self, sql: str, parameters: Iterable[Any] | None = None):
        cur = await self.cursor()
        await cur.execute(sql, parameters)
        return cur

    async def commit(self):
        await asyncio.to_thread(self._conn.commit)

    async def rollback(self):
        await asyncio.to_thread(self._conn.rollback)

    async def close(self):
        await asyncio.to_thread(self._conn.close)

    async def create_function(self, *args, **kwargs):
        await asyncio.to_thread(self._conn.create_function, *args, **kwargs)

    @property
    def isolation_level(self):
        return self._conn.isolation_level

    @isolation_level.setter
    def isolation_level(self, value):
        self._conn.isolation_level = value

    @property
    def row_factory(self):
        return self._conn.row_factory

    @row_factory.setter
    def row_factory(self, value):
        self._conn.row_factory = value

    @property
    def text_factory(self):
        return self._conn.text_factory

    @text_factory.setter
    def text_factory(self, value):
        self._conn.text_factory = value

    @property
    def total_changes(self):
        return self._conn.total_changes

    @property
    def in_transaction(self):
        return self._conn.in_transaction

    def __await__(self):
        async def _wrap():
            return self

        return _wrap().__await__()


def connect(database: str, **kwargs):
    kwargs.setdefault("check_same_thread", False)
    conn = sqlite3.connect(database, **kwargs)
    return Connection(conn)


# DB-API exception attributes expected by SQLAlchemy aiosqlite dialect
Warning = sqlite3.Warning
Error = sqlite3.Error
InterfaceError = sqlite3.InterfaceError
DatabaseError = sqlite3.DatabaseError
DataError = sqlite3.DataError
OperationalError = sqlite3.OperationalError
IntegrityError = sqlite3.IntegrityError
InternalError = sqlite3.InternalError
ProgrammingError = sqlite3.ProgrammingError
NotSupportedError = sqlite3.NotSupportedError

sqlite_version = sqlite3.sqlite_version
sqlite_version_info = sqlite3.sqlite_version_info
