"""Small async Redis test double for unit tests.

The implementation intentionally covers only the Redis commands exercised by the
backend tests. It keeps tests deterministic without requiring a Redis server or
an external Redis-mocking package.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from fnmatch import fnmatch
from typing import Any

from redis.exceptions import ResponseError


@dataclass
class _StreamState:
    messages: list[tuple[str, dict[str, Any]]] = field(default_factory=list)
    groups: dict[str, int] = field(default_factory=dict)
    pending: dict[str, set[str]] = field(default_factory=dict)


class FakePipeline:
    """Minimal async pipeline that queues commands and executes them in order."""

    def __init__(self, redis: FakeAsyncRedis) -> None:
        self._redis = redis
        self._commands: list[tuple[str, tuple[Any, ...], dict[str, Any]]] = []

    def set(self, *args: Any, **kwargs: Any) -> FakePipeline:
        self._commands.append(("set", args, kwargs))
        return self

    def xadd(self, *args: Any, **kwargs: Any) -> FakePipeline:
        self._commands.append(("xadd", args, kwargs))
        return self

    def publish(self, *args: Any, **kwargs: Any) -> FakePipeline:
        self._commands.append(("publish", args, kwargs))
        return self

    def xtrim(self, *args: Any, **kwargs: Any) -> FakePipeline:
        self._commands.append(("xtrim", args, kwargs))
        return self

    async def execute(self) -> list[Any]:
        results: list[Any] = []
        for name, args, kwargs in self._commands:
            results.append(await getattr(self._redis, name)(*args, **kwargs))
        self._commands.clear()
        return results


class FakeAsyncRedis:
    """In-memory async Redis subset for tests."""

    supports_xautoclaim = False

    def __init__(self, *, decode_responses: bool = True) -> None:
        self.decode_responses = decode_responses
        self._values: dict[str, Any] = {}
        self._hashes: dict[str, dict[str, Any]] = {}
        self._streams: dict[str, _StreamState] = {}
        self._published: list[tuple[str, Any]] = []
        self._counter = 0
        self.closed = False

    async def aclose(self) -> None:
        self.closed = True

    async def ping(self) -> bool:
        return True

    def pipeline(self) -> FakePipeline:
        return FakePipeline(self)

    async def set(self, key: str, value: Any, ex: int | None = None) -> bool:
        self._values[key] = value
        return True

    async def setnx(self, key: str, value: Any) -> bool:
        if key in self._values:
            return False
        self._values[key] = value
        return True

    async def setex(self, key: str, seconds: int, value: Any) -> bool:
        self._values[key] = value
        return True

    async def get(self, key: str) -> Any:
        return self._values.get(key)

    async def mget(self, keys: Iterable[str]) -> list[Any]:
        return [self._values.get(key) for key in keys]

    async def delete(self, *keys: str) -> int:
        deleted = 0
        for key in keys:
            existed = key in self._values or key in self._hashes or key in self._streams
            self._values.pop(key, None)
            self._hashes.pop(key, None)
            self._streams.pop(key, None)
            deleted += int(existed)
        return deleted

    async def exists(self, key: str) -> int:
        return int(key in self._values or key in self._hashes or key in self._streams)

    async def expire(self, key: str, seconds: int) -> bool:
        return bool(await self.exists(key))

    async def dbsize(self) -> int:
        keys = set(self._values) | set(self._hashes) | set(self._streams)
        return len(keys)

    async def incr(self, key: str) -> int:
        value = int(self._values.get(key, 0)) + 1
        self._values[key] = value
        return value

    async def incrby(self, key: str, amount: int) -> int:
        value = int(self._values.get(key, 0)) + int(amount)
        self._values[key] = value
        return value

    async def incrbyfloat(self, key: str, amount: float) -> float:
        value = float(self._values.get(key, 0.0)) + float(amount)
        self._values[key] = value
        return value

    async def hset(
        self, key: str, field: str | None = None, value: Any = None, **kwargs: Any
    ) -> int:
        mapping = kwargs.get("mapping")
        bucket = self._hashes.setdefault(key, {})
        before = len(bucket)
        if mapping is not None:
            bucket.update(mapping)
        elif field is not None:
            bucket[field] = value
        return len(bucket) - before

    async def hget(self, key: str, field: str) -> Any:
        return self._hashes.get(key, {}).get(field)

    async def hgetall(self, key: str) -> dict[str, Any]:
        return dict(self._hashes.get(key, {}))

    async def hdel(self, key: str, *fields: str) -> int:
        bucket = self._hashes.get(key, {})
        deleted = 0
        for hash_field in fields:
            deleted += int(hash_field in bucket)
            bucket.pop(hash_field, None)
        return deleted

    async def keys(self, pattern: str = "*") -> list[str]:
        keys = set(self._values) | set(self._hashes) | set(self._streams)
        return sorted(key for key in keys if fnmatch(key, pattern))

    async def publish(self, channel: str, message: Any) -> int:
        self._published.append((channel, message))
        return 1

    def _stream(self, name: str) -> _StreamState:
        return self._streams.setdefault(name, _StreamState())

    def _next_id(self) -> str:
        self._counter += 1
        return f"{self._counter}-0"

    @staticmethod
    def _id_to_int(message_id: str) -> int:
        try:
            return int(str(message_id).split("-", 1)[0])
        except (TypeError, ValueError):
            return 0

    async def xadd(
        self,
        name: str,
        fields: dict[str, Any],
        id: str = "*",  # noqa: A002 - mirrors redis-py API
        maxlen: int | None = None,
        approximate: bool = True,
    ) -> str:
        stream = self._stream(name)
        message_id = self._next_id() if id == "*" else str(id)
        stream.messages.append((message_id, dict(fields)))
        if maxlen is not None and len(stream.messages) > maxlen:
            del stream.messages[: len(stream.messages) - maxlen]
        return message_id

    async def xtrim(self, name: str, maxlen: int, approximate: bool = True) -> int:
        stream = self._stream(name)
        removed = max(0, len(stream.messages) - maxlen)
        if removed:
            del stream.messages[:removed]
        return removed

    async def xlen(self, name: str) -> int:
        return len(self._streams.get(name, _StreamState()).messages)

    async def xread(
        self,
        streams: dict[str, str],
        count: int | None = None,
        block: int | None = None,
    ) -> list[tuple[str, list[tuple[str, dict[str, Any]]]]]:
        response: list[tuple[str, list[tuple[str, dict[str, Any]]]]] = []
        for name, last_id in streams.items():
            stream = self._streams.get(name)
            if stream is None:
                continue
            last = self._id_to_int(last_id)
            entries = [item for item in stream.messages if self._id_to_int(item[0]) > last]
            if count is not None:
                entries = entries[:count]
            if entries:
                response.append((name, [(mid, dict(fields)) for mid, fields in entries]))
        return response

    async def xgroup_create(
        self,
        name: str,
        groupname: str,
        id: str = "$",  # noqa: A002 - mirrors redis-py API
        mkstream: bool = False,
    ) -> bool:
        if name not in self._streams:
            if not mkstream:
                raise ResponseError("The XGROUP subcommand requires the key to exist")
            self._streams[name] = _StreamState()
        stream = self._streams[name]
        if groupname in stream.groups:
            raise ResponseError("BUSYGROUP Consumer Group name already exists")
        stream.groups[groupname] = len(stream.messages) if id == "$" else self._id_to_int(id)
        stream.pending[groupname] = set()
        return True

    async def xgroup_destroy(self, name: str, groupname: str) -> int:
        stream = self._streams.get(name)
        if stream is None or groupname not in stream.groups:
            return 0
        del stream.groups[groupname]
        stream.pending.pop(groupname, None)
        return 1

    async def xgroup_setid(self, name: str, groupname: str, target_id: str) -> bool:
        stream = self._streams.get(name)
        if stream is None or groupname not in stream.groups:
            raise ResponseError("NOGROUP No such key or consumer group")
        stream.groups[groupname] = (
            len(stream.messages) if target_id == "$" else self._id_to_int(target_id)
        )
        return True

    async def xinfo_groups(self, name: str) -> list[dict[str, Any]]:
        stream = self._streams.get(name)
        if stream is None:
            raise ResponseError("no such key")
        return [
            {
                "name": group,
                "consumers": 0,
                "pending": len(stream.pending.get(group, set())),
                "last-delivered-id": f"{last}-0",
            }
            for group, last in stream.groups.items()
        ]

    async def xinfo_stream(self, name: str) -> dict[str, Any]:
        stream = self._streams.get(name)
        if stream is None:
            raise ResponseError("no such key")
        last_id = stream.messages[-1][0] if stream.messages else "0-0"
        return {"length": len(stream.messages), "last-generated-id": last_id}

    async def xreadgroup(
        self,
        groupname: str,
        consumername: str,
        streams: dict[str, str],
        count: int | None = None,
        block: int | None = None,
    ) -> list[tuple[str, list[tuple[str, dict[str, Any]]]]]:
        response: list[tuple[str, list[tuple[str, dict[str, Any]]]]] = []
        for name, requested_id in streams.items():
            stream = self._streams.get(name)
            if stream is None or groupname not in stream.groups:
                raise ResponseError("NOGROUP No such key or consumer group")
            if requested_id != ">":
                continue
            last = stream.groups[groupname]
            entries = [item for item in stream.messages if self._id_to_int(item[0]) > last]
            if count is not None:
                entries = entries[:count]
            if entries:
                stream.groups[groupname] = self._id_to_int(entries[-1][0])
                stream.pending[groupname].update(message_id for message_id, _fields in entries)
                response.append((name, [(mid, dict(fields)) for mid, fields in entries]))
        return response

    async def xack(self, name: str, groupname: str, *ids: str) -> int:
        stream = self._streams.get(name)
        if stream is None or groupname not in stream.pending:
            return 0
        pending = stream.pending[groupname]
        acked = 0
        for message_id in ids:
            acked += int(message_id in pending)
            pending.discard(message_id)
        return acked

    async def xautoclaim(
        self,
        name: str,
        groupname: str,
        consumername: str,
        min_idle_time: int,
        start_id: str = "0-0",
        count: int | None = None,
    ) -> tuple[str, list[tuple[str, dict[str, Any]]], list[str]]:
        stream = self._streams.get(name)
        if stream is None or groupname not in stream.groups:
            raise ResponseError("NOGROUP No such key or consumer group")
        return "0-0", [], []
