from __future__ import annotations

import asyncio
import sqlite3
import threading
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace

import pytest
from fastapi import Request
from fastapi.responses import JSONResponse, StreamingResponse

from llm_gateway_core.db.model_rotation_db import ModelRotationDB
from llm_gateway_core.middleware import chat_logging


def test_rotation_sequence_starts_at_zero_and_wraps(tmp_path):
    database = ModelRotationDB(str(tmp_path / "sequence.db"))

    indexes = [
        database.get_next_model_index("client-key", "gateway/model", 3)
        for _ in range(5)
    ]

    assert indexes == [0, 1, 2, 0, 1]
    with sqlite3.connect(database.db_path) as connection:
        assert connection.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
        assert database.busy_timeout_ms == 30_000


@pytest.mark.parametrize("repeat", range(3))
def test_rotation_allocates_each_slot_evenly_under_concurrency(tmp_path, repeat):
    total_models = 8
    call_count = 80
    database = ModelRotationDB(str(tmp_path / f"rotation-{repeat}.db"))

    with ThreadPoolExecutor(max_workers=24) as executor:
        indexes = list(
            executor.map(
                lambda _: database.get_next_model_index("client-key", "gateway/model", total_models),
                range(call_count),
            )
        )

    assert set(indexes) == set(range(total_models))
    assert Counter(indexes) == Counter({index: call_count // total_models for index in range(total_models)})


def _request(body: bytes = b'{"model":"gateway/model"}', usage_db=None) -> Request:
    pending_messages = [
        {"type": "http.request", "body": body, "more_body": False}
    ]

    async def receive():
        if pending_messages:
            return pending_messages.pop(0)
        return {"type": "http.disconnect"}

    app = SimpleNamespace(state=SimpleNamespace(tokens_usage_db=usage_db))
    return Request(
        {
            "type": "http",
            "http_version": "1.1",
            "method": "POST",
            "scheme": "http",
            "path": "/v1/chat/completions",
            "raw_path": b"/v1/chat/completions",
            "query_string": b"",
            "headers": [],
            "client": ("127.0.0.1", 12345),
            "server": ("testserver", 80),
            "app": app,
        },
        receive,
    )


async def _consume(response) -> bytes:
    chunks = []
    async for chunk in response.body_iterator:
        chunks.append(chunk.encode() if isinstance(chunk, str) else chunk)
    return b"".join(chunks)


@pytest.mark.asyncio
async def test_error_chunk_persists_token_usage_exactly_once(monkeypatch):
    writes = []
    monkeypatch.setattr(chat_logging, "write_log", lambda *args: writes.append(args))

    async def response_body():
        yield b'data: {"error":{"message":"failed"}}\n\n'

    upstream_response = StreamingResponse(
        response_body(), media_type="text/event-stream"
    )
    response = await chat_logging.log_chat_completions(
        _request(), lambda _: asyncio.sleep(0, result=upstream_response)
    )
    body = await _consume(response)

    assert b'"error"' in body
    assert len(writes) == 1
    assert '"error"' in writes[0][2]


@pytest.mark.asyncio
async def test_stream_logging_survives_a_long_interval_between_chunks(monkeypatch):
    writes = []
    monkeypatch.setattr(chat_logging, "write_log", lambda *args: writes.append(args))
    release_late_chunk = asyncio.Event()

    async def response_body():
        yield b'data: {"choices":[{"delta":{"content":"early"}}]}\n\n'
        await release_late_chunk.wait()
        yield b'data: {"choices":[{"delta":{"content":"late"}}]}\n\n'

    upstream_response = StreamingResponse(
        response_body(), media_type="text/event-stream"
    )
    response = await chat_logging.log_chat_completions(
        _request(), lambda _: asyncio.sleep(0, result=upstream_response)
    )
    iterator = response.body_iterator
    first_chunk = await anext(iterator)
    await asyncio.sleep(0)
    assert writes == []

    release_late_chunk.set()
    remaining_chunks = [chunk async for chunk in iterator]

    assert b"early" in first_chunk
    assert any(b"late" in chunk for chunk in remaining_chunks)
    assert len(writes) == 1
    assert writes[0][2] == "earlylate"


@pytest.mark.asyncio
async def test_non_error_chunk_persists_token_usage_once(monkeypatch):
    writes = []
    monkeypatch.setattr(chat_logging, "write_log", lambda *args: writes.append(args))

    async def response_body():
        yield (
            b'data: {"choices":[{"delta":{"content":"ok"}}],'
            b'"usage":{"prompt_tokens":2,"completion_tokens":1,"total_tokens":3}}\n\n'
        )

    upstream_response = StreamingResponse(
        response_body(), media_type="text/event-stream"
    )
    response = await chat_logging.log_chat_completions(
        _request(), lambda _: asyncio.sleep(0, result=upstream_response)
    )
    await _consume(response)

    assert len(writes) == 1
    assert writes[0][2] == "ok"
    assert writes[0][3]["total_tokens"] == 3


@pytest.mark.asyncio
async def test_non_streaming_response_uses_app_database_and_persists_once(monkeypatch):
    writes = []
    app_usage_db = object()
    event_loop_thread = threading.get_ident()

    def record_write(*args):
        writes.append((args, threading.get_ident()))

    monkeypatch.setattr(chat_logging, "write_log", record_write)
    upstream_response = JSONResponse(
        {
            "choices": [{"message": {"content": "complete"}}],
            "usage": {
                "prompt_tokens": 4,
                "completion_tokens": 2,
                "total_tokens": 6,
            },
        }
    )

    response = await chat_logging.log_chat_completions(
        _request(usage_db=app_usage_db),
        lambda _: asyncio.sleep(0, result=upstream_response),
    )

    assert response is upstream_response
    assert len(writes) == 1
    assert writes[0][0][2] == "complete"
    assert writes[0][0][3]["total_tokens"] == 6
    assert writes[0][0][4] is app_usage_db
    assert writes[0][1] != event_loop_thread


@pytest.mark.asyncio
async def test_non_event_stream_wrapper_collects_json_response(monkeypatch):
    writes = []
    monkeypatch.setattr(chat_logging, "write_log", lambda *args: writes.append(args))
    encoded_body = (
        b'{"choices":[{"message":{"content":"wrapped"}}],'
        b'"usage":{"prompt_tokens":1,"completion_tokens":2,"total_tokens":3}}'
    )

    async def response_body():
        yield encoded_body[:37]
        yield encoded_body[37:]

    upstream_response = StreamingResponse(
        response_body(), media_type="application/json"
    )
    response = await chat_logging.log_chat_completions(
        _request(), lambda _: asyncio.sleep(0, result=upstream_response)
    )

    assert await _consume(response) == encoded_body
    assert len(writes) == 1
    assert writes[0][2] == "wrapped"
    assert writes[0][3]["total_tokens"] == 3


@pytest.mark.asyncio
async def test_empty_stream_persists_once(monkeypatch):
    writes = []
    monkeypatch.setattr(chat_logging, "write_log", lambda *args: writes.append(args))

    async def response_body():
        if False:
            yield b""

    upstream_response = StreamingResponse(
        response_body(), media_type="text/event-stream"
    )
    response = await chat_logging.log_chat_completions(
        _request(), lambda _: asyncio.sleep(0, result=upstream_response)
    )
    assert await _consume(response) == b""

    assert len(writes) == 1
    assert writes[0][2] == ""


@pytest.mark.asyncio
async def test_call_next_error_persists_once_and_propagates(monkeypatch):
    writes = []
    monkeypatch.setattr(chat_logging, "write_log", lambda *args: writes.append(args))

    async def failed_call_next(_request):
        raise RuntimeError("endpoint failed")

    with pytest.raises(RuntimeError, match="endpoint failed"):
        await chat_logging.log_chat_completions(_request(), failed_call_next)

    assert len(writes) == 1
    assert writes[0][2] == ""


@pytest.mark.asyncio
async def test_stream_cancellation_persists_once(monkeypatch):
    writes = []
    monkeypatch.setattr(chat_logging, "write_log", lambda *args: writes.append(args))
    never_release = asyncio.Event()

    async def response_body():
        yield b'data: {"choices":[{"delta":{"content":"before-cancel"}}]}\n\n'
        await never_release.wait()
        yield b"unreachable"

    upstream_response = StreamingResponse(
        response_body(), media_type="text/event-stream"
    )
    response = await chat_logging.log_chat_completions(
        _request(), lambda _: asyncio.sleep(0, result=upstream_response)
    )
    iterator = response.body_iterator
    await anext(iterator)
    pending_chunk = asyncio.create_task(anext(iterator))
    await asyncio.sleep(0)
    pending_chunk.cancel()
    with pytest.raises(asyncio.CancelledError):
        await pending_chunk

    assert len(writes) == 1
    assert writes[0][2] == "before-cancel"


@pytest.mark.asyncio
async def test_request_body_is_bounded(monkeypatch):
    writes = []
    monkeypatch.setattr(chat_logging, "write_log", lambda *args: writes.append(args))
    monkeypatch.setattr(chat_logging.settings, "log_chat_request_max_chars", 4)
    upstream_response = JSONResponse(
        {"choices": [{"message": {"content": "ok"}}]}
    )

    await chat_logging.log_chat_completions(
        _request(body=b"123456789"),
        lambda _: asyncio.sleep(0, result=upstream_response),
    )

    assert len(writes) == 1
    assert writes[0][1] == "1234"


@pytest.mark.asyncio
async def test_response_limit_does_not_hide_later_usage(monkeypatch):
    writes = []
    monkeypatch.setattr(chat_logging, "write_log", lambda *args: writes.append(args))
    monkeypatch.setattr(chat_logging.settings, "log_chat_response_max_chars", 3)

    async def response_body():
        yield b'data: {"choices":[{"delta":{"content":"abcdef"}}]}\n\n'
        yield b'data: {"usage":{"prompt_tokens":5,"completion_tokens":2,"total_tokens":7}}\n\n'

    upstream_response = StreamingResponse(
        response_body(), media_type="text/event-stream"
    )
    response = await chat_logging.log_chat_completions(
        _request(), lambda _: asyncio.sleep(0, result=upstream_response)
    )
    await _consume(response)

    assert len(writes) == 1
    assert writes[0][2] == "abc"
    assert writes[0][3]["total_tokens"] == 7


def test_concurrent_log_writes_use_unique_filenames(monkeypatch, tmp_path):
    class UsageDB:
        def insert_usage(self, _tokens_usage):
            return None

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(chat_logging.settings, "log_file_limit", 100)
    usage = chat_logging._default_tokens_usage()

    with ThreadPoolExecutor(max_workers=16) as executor:
        list(
            executor.map(
                lambda _: chat_logging.write_log({}, "{}", "response", usage, UsageDB()),
                range(40),
            )
        )

    log_files = list((tmp_path / "logs").glob("*.txt"))
    assert len(log_files) == 40
    assert len({path.name for path in log_files}) == 40


def test_write_log_empty_response_writes_placeholder(monkeypatch, tmp_path):
    class UsageDB:
        def insert_usage(self, _tokens_usage):
            return None

    monkeypatch.chdir(tmp_path)
    usage = chat_logging._default_tokens_usage()
    chat_logging.write_log({}, "{}", "", usage, UsageDB())

    log_files = list((tmp_path / "logs").glob("*.txt"))
    assert len(log_files) == 1
    content = log_files[0].read_text(encoding="utf-8")
    assert (
        "<No content. This may be caused by the call to 'tools' or 'mcps' as the model's last request>"
        in content
    )

