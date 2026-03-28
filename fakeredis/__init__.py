"""Lightweight in-repo fakeredis substitute for async stream unit tests."""

from __future__ import annotations

from collections import defaultdict
from typing import Any

from redis.exceptions import ResponseError


class FakeAsyncRedis:
    def __init__(self, decode_responses: bool = True):
        self.decode_responses = decode_responses
        self._streams: dict[str, list[tuple[str, dict[str, str]]]] = defaultdict(list)
        self._groups: dict[str, dict[str, dict[str, Any]]] = defaultdict(dict)
        self._counter = 0

    async def aclose(self) -> None:
        return None

    async def dbsize(self) -> int:
        return sum(len(messages) for messages in self._streams.values())

    async def xgroup_create(self, stream: str, group: str, id: str = "$", mkstream: bool = False):
        if group in self._groups[stream]:
            raise ResponseError("BUSYGROUP Consumer Group name already exists")
        if mkstream and stream not in self._streams:
            self._streams[stream] = []
        self._groups[stream][group] = {"name": group, "pending": 0, "last-delivered-id": id}
        return True

    async def xgroup_destroy(self, stream: str, group: str) -> int:
        if group in self._groups.get(stream, {}):
            del self._groups[stream][group]
            return 1
        return 0

    async def xinfo_groups(self, stream: str):
        groups = self._groups.get(stream)
        if not groups:
            raise ResponseError("NOGROUP No such key")
        return list(groups.values())

    async def xgroup_setid(self, stream: str, group: str, id: str):
        if group not in self._groups.get(stream, {}):
            raise ResponseError("NOGROUP No such key")
        self._groups[stream][group]["last-delivered-id"] = id
        return True

    async def xadd(self, stream: str, fields: dict[str, Any], **kwargs):
        self._counter += 1
        msg_id = f"{self._counter}-0"
        self._streams[stream].append((msg_id, {k: str(v) for k, v in fields.items()}))
        return msg_id

    async def xlen(self, stream: str) -> int:
        return len(self._streams.get(stream, []))

    async def xreadgroup(self, groupname: str, consumername: str, streams: dict[str, str], count: int = 10, block: int = 0):
        results = []
        for stream, _marker in streams.items():
            if groupname not in self._groups.get(stream, {}):
                raise ResponseError("NOGROUP No such key")
            messages = self._streams.get(stream, [])[:count]
            if messages:
                results.append((stream, messages))
        return results

    async def xack(self, stream: str, group: str, *ids: str) -> int:
        return len(ids)

    async def xinfo_stream(self, stream: str):
        messages = self._streams.get(stream, [])
        last_id = messages[-1][0] if messages else "0-0"
        return {"last-generated-id": last_id}
