from __future__ import annotations

import httpx
import pytest

from llm_gateway_core.services import request_handler

from conftest import ChunkStream, response_body


def install_downstream(monkeypatch, handler):
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return client


@pytest.mark.asyncio
async def test_non_stream_response_returns_decoded_json(monkeypatch):
    expected = {"id": "chat-1", "choices": [{"message": {"content": "ok"}}]}
    client = install_downstream(
        monkeypatch,
        lambda request: httpx.Response(200, json=expected, request=request),
    )
    try:
        response, error = await request_handler.make_llm_request(
            client,
            "https://provider.test/chat/completions", {}, {"model": "model-a"}, False
        )
    finally:
        await client.aclose()

    assert response == expected
    assert error is None


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("handler", "expected_error"),
    [
        (
            lambda request: (_ for _ in ()).throw(
                httpx.ReadTimeout("provider stalled", request=request)
            ),
            "RequestError connecting",
        ),
        (
            lambda request: httpx.Response(
                503, text="provider unavailable", request=request
            ),
            "provider unavailable",
        ),
    ],
    ids=["timeout", "http-error"],
)
async def test_non_stream_transport_failures_are_signaled_for_fallback(
    monkeypatch, handler, expected_error
):
    client = install_downstream(monkeypatch, handler)
    try:
        response, error = await request_handler.make_llm_request(
            client,
            "https://provider.test/chat/completions", {}, {"model": "model-a"}, False
        )
    finally:
        await client.aclose()

    assert response is None
    assert expected_error in error


@pytest.mark.asyncio
async def test_invalid_json_is_signaled_with_a_specific_parse_error(monkeypatch):
    client = install_downstream(
        monkeypatch,
        lambda request: httpx.Response(200, text="not-json", request=request),
    )
    try:
        response, error = await request_handler.make_llm_request(
            client,
            "https://provider.test/chat/completions", {}, {"model": "model-a"}, False
        )
    finally:
        await client.aclose()

    assert response is None
    assert error.startswith("Invalid JSON response")


@pytest.mark.asyncio
async def test_streaming_response_forwards_complete_sse_events(monkeypatch):
    chunks = [
        b'data: {"choices":[{"delta":{"content":"hello"}}]}\n\n',
        b'data: {"usage":{"total_tokens":1}}\n\n',
        b"data: [DONE]\n\n",
    ]
    client = install_downstream(
        monkeypatch,
        lambda request: httpx.Response(
            200,
            headers={"content-type": "text/event-stream"},
            stream=ChunkStream(chunks),
            request=request,
        ),
    )
    try:
        response, error = await request_handler.make_llm_request(
            client,
            "https://provider.test/chat/completions", {}, {"model": "model-a"}, True
        )
        body = await response_body(response)
    finally:
        await client.aclose()

    assert error is None
    assert body == b"".join(chunks)


@pytest.mark.asyncio
async def test_fragmented_sse_event_is_reassembled_without_data_loss(monkeypatch):
    chunks = [
        b'data: {"choices":[{"delta":',
        b'{"content":"hello"}}]}\n\n',
        b"data: [DONE]\n\n",
    ]
    client = install_downstream(
        monkeypatch,
        lambda request: httpx.Response(
            200,
            headers={"content-type": "text/event-stream"},
            stream=ChunkStream(chunks),
            request=request,
        ),
    )
    try:
        response, error = await request_handler.make_llm_request(
            client,
            "https://provider.test/chat/completions", {}, {"model": "model-a"}, True
        )
        body = await response_body(response)
    finally:
        await client.aclose()

    assert error is None
    assert body == b"".join(chunks)


@pytest.mark.asyncio
async def test_empty_stream_is_signaled_for_fallback(monkeypatch):
    client = install_downstream(
        monkeypatch,
        lambda request: httpx.Response(
            200,
            headers={"content-type": "text/event-stream"},
            stream=ChunkStream([]),
            request=request,
        ),
    )
    try:
        response, error = await request_handler.make_llm_request(
            client,
            "https://provider.test/chat/completions", {}, {"model": "model-a"}, True
        )
    finally:
        await client.aclose()

    assert response is None
    assert "empty" in error.lower()


@pytest.mark.asyncio
async def test_many_keep_alives_exceed_prefetch_limit_and_close_stream(monkeypatch):
    upstream_response = None
    chunks = [b": keep-alive\n\n"] * 4

    def handler(request):
        nonlocal upstream_response
        upstream_response = httpx.Response(
            200,
            headers={"content-type": "text/event-stream"},
            stream=ChunkStream(chunks),
            request=request,
        )
        return upstream_response

    monkeypatch.setattr(
        request_handler.settings, "http_stream_prefetch_max_events", 2
    )
    monkeypatch.setattr(
        request_handler.settings, "http_stream_prefetch_max_bytes", 1_000
    )
    client = install_downstream(monkeypatch, handler)
    try:
        response, error = await request_handler.make_llm_request(
            client,
            "https://provider.test/chat/completions",
            {},
            {"model": "model-a"},
            True,
        )
    finally:
        await client.aclose()

    assert response is None
    assert "prefetch limit exceeded" in error.lower()
    assert "3 events" in error
    assert upstream_response.is_closed


@pytest.mark.asyncio
async def test_prefetch_byte_limit_is_enforced_before_first_data_event(monkeypatch):
    upstream_response = None

    def handler(request):
        nonlocal upstream_response
        upstream_response = httpx.Response(
            200,
            headers={"content-type": "text/event-stream"},
            stream=ChunkStream([b":" + b"x" * 32]),
            request=request,
        )
        return upstream_response

    monkeypatch.setattr(
        request_handler.settings, "http_stream_prefetch_max_events", 100
    )
    monkeypatch.setattr(
        request_handler.settings, "http_stream_prefetch_max_bytes", 16
    )
    client = install_downstream(monkeypatch, handler)
    try:
        response, error = await request_handler.make_llm_request(
            client,
            "https://provider.test/chat/completions",
            {},
            {"model": "model-a"},
            True,
        )
    finally:
        await client.aclose()

    assert response is None
    assert "prefetch limit exceeded" in error.lower()
    assert "33 bytes" in error
    assert upstream_response.is_closed


@pytest.mark.asyncio
async def test_stream_parser_accepts_crlf_and_ignores_keep_alive_events(monkeypatch):
    chunks = [
        b": keep-alive\r\n\r\n",
        b"event: message\r\ndata: {\"choices\":[{\"delta\":",
        b"{\"content\":\"hello\"}}]}\r\n\r\n",
        b"data: [DONE]\r\n\r\n",
    ]
    client = install_downstream(
        monkeypatch,
        lambda request: httpx.Response(
            200,
            headers={"content-type": "text/event-stream"},
            stream=ChunkStream(chunks),
            request=request,
        ),
    )
    try:
        response, error = await request_handler.make_llm_request(
            client,
            "https://provider.test/chat/completions",
            {},
            {"model": "model-a"},
            True,
        )
        body = await response_body(response)
    finally:
        await client.aclose()

    assert error is None
    assert body == b"".join(chunks)
    assert "transfer-encoding" not in response.headers


@pytest.mark.asyncio
async def test_error_in_first_sse_event_is_signaled_and_stream_is_closed(monkeypatch):
    upstream_response = None

    def handler(request):
        nonlocal upstream_response
        upstream_response = httpx.Response(
            200,
            headers={"content-type": "text/event-stream"},
            stream=ChunkStream([b'data: {"error":{"message":"capacity"}}\n\n']),
            request=request,
        )
        return upstream_response

    client = install_downstream(monkeypatch, handler)
    try:
        response, error = await request_handler.make_llm_request(
            client,
            "https://provider.test/chat/completions",
            {},
            {"model": "model-a"},
            True,
        )
    finally:
        await client.aclose()

    assert response is None
    assert error == "capacity"
    assert upstream_response.is_closed


@pytest.mark.asyncio
async def test_error_after_first_sse_event_ends_stream_without_fallback(monkeypatch):
    chunks = [
        b'data: {"choices":[{"delta":{"content":"hello"}}]}\n\n',
        b'data: {"error":{"message":"capacity"}}\n\n',
        b'data: {"choices":[{"delta":{"content":"ignored"}}]}\n\n',
    ]
    upstream_response = None

    def handler(request):
        nonlocal upstream_response
        upstream_response = httpx.Response(
            200,
            headers={"content-type": "text/event-stream"},
            stream=ChunkStream(chunks),
            request=request,
        )
        return upstream_response

    client = install_downstream(monkeypatch, handler)
    try:
        response, error = await request_handler.make_llm_request(
            client,
            "https://provider.test/chat/completions",
            {},
            {"model": "model-a"},
            True,
        )
        body = await response_body(response)
    finally:
        await client.aclose()

    assert error is None
    assert body == b"".join(chunks[:2])
    assert upstream_response.is_closed


@pytest.mark.asyncio
async def test_consumer_cancellation_closes_upstream_stream(monkeypatch):
    chunks = [
        b'data: {"choices":[{"delta":{"content":"hello"}}]}\n\n',
        b'data: {"choices":[{"delta":{"content":"later"}}]}\n\n',
    ]
    upstream_response = None

    def handler(request):
        nonlocal upstream_response
        upstream_response = httpx.Response(
            200,
            headers={"content-type": "text/event-stream"},
            stream=ChunkStream(chunks),
            request=request,
        )
        return upstream_response

    client = install_downstream(monkeypatch, handler)
    try:
        response, error = await request_handler.make_llm_request(
            client,
            "https://provider.test/chat/completions",
            {},
            {"model": "model-a"},
            True,
        )
        iterator = response.body_iterator
        assert await iterator.__anext__() == chunks[0]
        await iterator.aclose()
    finally:
        await client.aclose()

    assert error is None
    assert upstream_response.is_closed


@pytest.mark.asyncio
@pytest.mark.parametrize("is_streaming", [False, True])
async def test_client_timeouts_are_preserved_for_downstream_calls(
    monkeypatch, is_streaming
):
    observed_timeout = None

    def handler(request):
        nonlocal observed_timeout
        observed_timeout = request.extensions["timeout"]
        if is_streaming:
            return httpx.Response(
                200,
                stream=ChunkStream([b'data: {"choices":[]}\n\n']),
                request=request,
            )
        return httpx.Response(200, json={"choices": []}, request=request)

    timeout = httpx.Timeout(connect=1, read=2, write=3, pool=4)
    client = httpx.AsyncClient(
        transport=httpx.MockTransport(handler), timeout=timeout
    )
    try:
        response, error = await request_handler.make_llm_request(
            client,
            "https://provider.test/chat/completions",
            {},
            {"model": "model-a"},
            is_streaming,
        )
        if is_streaming:
            await response_body(response)
    finally:
        await client.aclose()

    assert error is None
    assert observed_timeout == {
        "connect": 1,
        "read": 2,
        "write": 3,
        "pool": 4,
    }
