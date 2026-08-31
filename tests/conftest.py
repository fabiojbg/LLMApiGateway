from __future__ import annotations

from collections.abc import AsyncIterator, Iterable

import httpx


class ChunkStream(httpx.AsyncByteStream):
    """Small controllable HTTPX stream used by downstream-provider tests."""

    def __init__(self, chunks: Iterable[bytes]):
        self._chunks = list(chunks)

    async def __aiter__(self) -> AsyncIterator[bytes]:
        for chunk in self._chunks:
            yield chunk


async def response_body(response) -> bytes:
    chunks = []
    async for chunk in response.body_iterator:
        if isinstance(chunk, str):
            chunk = chunk.encode()
        chunks.append(chunk)
    return b"".join(chunks)
