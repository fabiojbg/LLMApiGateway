from __future__ import annotations

from types import SimpleNamespace

import httpx
import pytest
from fastapi import FastAPI

from llm_gateway_core.api.v1 import chat
from llm_gateway_core.config.loader import ProviderDetails


def make_app(*fallback_models):
    app = FastAPI()
    app.include_router(chat.router, prefix="/v1/chat")
    app.state.config_loader = SimpleNamespace(
        providers_config={
            rule["provider"]: ProviderDetails(
                baseUrl=f"https://{rule['provider']}.test/v1", apikey="literal-key"
            )
            for rule in fallback_models
        },
        fallback_rules={
            "gateway/test": {
                "rotate_models": False,
                "fallback_models": list(fallback_models),
            }
        },
    )
    app.state.http_client = object()
    return app


def rule(provider, model, **extra):
    return {
        "provider": provider,
        "model": model,
        "use_provider_order_as_fallback": False,
        **extra,
    }


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "first_error",
    [
        "RequestError connecting: timeout",
        "Downstream HTTP 503",
        "Invalid JSON response",
        "Empty provider stream",
    ],
    ids=["timeout", "http-error", "invalid-json", "empty-stream"],
)
async def test_chat_uses_next_provider_after_a_signaled_failure(
    monkeypatch, first_error
):
    app = make_app(rule("first", "model-a"), rule("second", "model-b"))
    calls = []

    async def fake_request(http_client, target_url, headers, payload, is_streaming):
        assert http_client is app.state.http_client
        calls.append((target_url, payload["model"]))
        if len(calls) == 1:
            return None, first_error
        return {"id": "fallback-ok", "model": payload["model"]}, None

    monkeypatch.setattr(chat, "make_llm_request", fake_request)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://gateway.test"
    ) as client:
        response = await client.post(
            "/v1/chat/completions",
            json={"model": "gateway/test", "messages": [{"role": "user", "content": "hi"}]},
        )

    assert response.status_code == 200
    assert response.json()["model"] == "model-b"
    assert calls == [
        ("https://first.test/v1/chat/completions", "model-a"),
        ("https://second.test/v1/chat/completions", "model-b"),
    ]


@pytest.mark.asyncio
async def test_incomplete_retry_configuration_fails_as_provider_error(monkeypatch):
    app = make_app(rule("first", "model-a", retry_count=1))

    async def fail_request(*args, **kwargs):
        return None, "provider failed"

    monkeypatch.setattr(chat, "make_llm_request", fail_request)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app, raise_app_exceptions=False),
        base_url="http://gateway.test",
    ) as client:
        response = await client.post(
            "/v1/chat/completions",
            json={"model": "gateway/test", "messages": []},
        )

    assert response.status_code == 503


@pytest.mark.asyncio
async def test_retry_uses_exact_attempt_count_and_sleeps_only_between_attempts(
    monkeypatch,
):
    app = make_app(
        rule("first", "model-a", retry_count=2, retry_delay=7)
    )
    calls = []
    sleeps = []

    async def fail_request(_client, _url, _headers, payload, _streaming):
        calls.append(payload.copy())
        return None, "provider failed"

    async def record_sleep(delay):
        sleeps.append(delay)

    monkeypatch.setattr(chat, "make_llm_request", fail_request)
    monkeypatch.setattr(chat.asyncio, "sleep", record_sleep)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://gateway.test"
    ) as client:
        response = await client.post(
            "/v1/chat/completions",
            json={"model": "gateway/test", "messages": [{"role": "user"}]},
        )

    assert response.status_code == 503
    assert len(calls) == 3
    assert sleeps == [7, 7]
    assert all(call["messages"] == [{"role": "user"}] for call in calls)


@pytest.mark.asyncio
async def test_rotation_ignores_retry_configuration(monkeypatch):
    app = make_app(
        rule("first", "model-a", retry_count=3, retry_delay=9),
        rule("second", "model-b", retry_count=2, retry_delay=8),
    )
    app.state.config_loader.fallback_rules["gateway/test"]["rotate_models"] = True
    calls = []
    sleeps = []

    async def fail_request(_client, _url, _headers, payload, _streaming):
        calls.append(payload["model"])
        return None, "provider failed"

    async def record_sleep(delay):
        sleeps.append(delay)

    monkeypatch.setattr(chat, "make_llm_request", fail_request)
    monkeypatch.setattr(chat.asyncio, "sleep", record_sleep)
    monkeypatch.setattr(
        chat.model_rotation_db, "get_next_model_index", lambda **_kwargs: 0
    )
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://gateway.test"
    ) as client:
        response = await client.post(
            "/v1/chat/completions",
            json={"model": "gateway/test", "messages": []},
        )

    assert response.status_code == 503
    assert calls == ["model-a", "model-b"]
    assert sleeps == []


@pytest.mark.asyncio
async def test_missing_provider_configuration_returns_503(monkeypatch):
    app = make_app(rule("missing", "model-a"))
    app.state.config_loader.providers_config = {}

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app, raise_app_exceptions=False),
        base_url="http://gateway.test",
    ) as client:
        response = await client.post(
            "/v1/chat/completions",
            json={"model": "gateway/test", "messages": []},
        )

    assert response.status_code == 503
    assert "is not configured" in response.json()["detail"]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("override_val", "expected_provider", "expected_reasoning"),
    [
        (
            "true",
            {"sort": "throughput", "quantizations": ["fp8"]},
            "high",
        ),
        (
            True,
            {"sort": "throughput", "quantizations": ["fp8"]},
            "high",
        ),
        (
            "false",
            {"sort": "caller_sort"},
            "caller_low",
        ),
        (
            False,
            {"sort": "caller_sort"},
            "caller_low",
        ),
        (
            None,
            {"sort": "caller_sort"},
            "caller_low",
        ),
    ],
    ids=["string-true", "bool-true", "string-false", "bool-false", "no-override"],
)
async def test_custom_body_params_override_behavior(
    monkeypatch, override_val, expected_provider, expected_reasoning
):
    custom_params = {
        "provider": {"sort": "throughput", "quantizations": ["fp8"]},
        "reasoning_effort": "high",
        "injected_extra": "gateway_value",
    }
    if override_val is not None:
        custom_params["override"] = override_val

    app = make_app(rule("first", "model-a", custom_body_params=custom_params))
    captured_payloads = []

    async def fake_request(http_client, target_url, headers, payload, is_streaming):
        captured_payloads.append(payload.copy())
        return {"id": "ok", "model": payload["model"]}, None

    monkeypatch.setattr(chat, "make_llm_request", fake_request)

    caller_body = {
        "model": "gateway/test",
        "messages": [{"role": "user", "content": "hi"}],
        "provider": {"sort": "caller_sort"},
        "reasoning_effort": "caller_low",
    }

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://gateway.test"
    ) as client:
        response = await client.post("/v1/chat/completions", json=caller_body)

    assert response.status_code == 200
    assert len(captured_payloads) == 1
    sent_payload = captured_payloads[0]

    # Verify override parameter itself is never passed downstream
    assert "override" not in sent_payload
    # Verify expected values based on override mode
    assert sent_payload["provider"] == expected_provider
    assert sent_payload["reasoning_effort"] == expected_reasoning
    # Non-conflicting params should always be added
    assert sent_payload["injected_extra"] == "gateway_value"

