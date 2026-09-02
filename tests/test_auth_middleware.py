from __future__ import annotations

import httpx
import pytest
from fastapi import FastAPI
from fastapi.responses import JSONResponse

from llm_gateway_core.middleware.auth import api_key_auth
from llm_gateway_core.config.settings import settings


def create_test_app() -> FastAPI:
    app = FastAPI()
    app.middleware("http")(api_key_auth)

    @app.get("/health")
    async def health():
        return {"status": "ok"}

    @app.get("/v1/models")
    async def list_models():
        return {"data": [{"id": "test-model"}]}

    @app.post("/v1/chat/completions")
    async def chat_completions():
        return JSONResponse(
            status_code=200,
            content={"id": "chatcmpl-123", "choices": []},
        )

    return app


@pytest.mark.asyncio
async def test_auth_skips_non_chat_endpoints_even_when_gateway_key_is_set(monkeypatch):
    monkeypatch.setattr(settings, "gateway_api_key", "test-secret-key")
    app = create_test_app()

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://gateway.test",
    ) as client:
        health_resp = await client.get("/health")
        models_resp = await client.get("/v1/models")

    assert health_resp.status_code == 200
    assert health_resp.json() == {"status": "ok"}
    assert models_resp.status_code == 200
    assert models_resp.json() == {"data": [{"id": "test-model"}]}


@pytest.mark.asyncio
async def test_chat_endpoint_without_auth_header_returns_401(monkeypatch):
    monkeypatch.setattr(settings, "gateway_api_key", "test-secret-key")
    app = create_test_app()

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://gateway.test",
    ) as client:
        response = await client.post("/v1/chat/completions", json={"model": "test"})

    assert response.status_code == 401
    assert response.json() == {
        "detail": "Missing or invalid Authorization header (Bearer token expected)"
    }


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "invalid_header",
    [
        "Basic dXNlcjpwYXNz",
        "Token xyz123",
        "Bearer",
        "bearer lowercase",
    ],
)
async def test_chat_endpoint_with_invalid_header_format_returns_401(
    monkeypatch, invalid_header
):
    monkeypatch.setattr(settings, "gateway_api_key", "test-secret-key")
    app = create_test_app()

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://gateway.test",
    ) as client:
        response = await client.post(
            "/v1/chat/completions",
            json={"model": "test"},
            headers={"Authorization": invalid_header},
        )

    assert response.status_code == 401
    assert response.json() == {
        "detail": "Invalid Authorization header format"
    }


@pytest.mark.asyncio
async def test_chat_endpoint_with_wrong_api_key_returns_403(monkeypatch):
    monkeypatch.setattr(settings, "gateway_api_key", "test-secret-key")
    app = create_test_app()

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://gateway.test",
    ) as client:
        response = await client.post(
            "/v1/chat/completions",
            json={"model": "test"},
            headers={"Authorization": "Bearer wrong-key"},
        )

    assert response.status_code == 403
    assert response.json() == {"detail": "Invalid API Key"}


@pytest.mark.asyncio
async def test_chat_endpoint_with_correct_api_key_succeeds(monkeypatch):
    monkeypatch.setattr(settings, "gateway_api_key", "test-secret-key")
    app = create_test_app()

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://gateway.test",
    ) as client:
        response = await client.post(
            "/v1/chat/completions",
            json={"model": "test"},
            headers={"Authorization": "Bearer test-secret-key"},
        )

    assert response.status_code == 200
    assert response.json()["id"] == "chatcmpl-123"


@pytest.mark.asyncio
async def test_chat_endpoint_when_no_gateway_key_configured_allows_request(monkeypatch):
    monkeypatch.setattr(settings, "gateway_api_key", None)
    app = create_test_app()

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://gateway.test",
    ) as client:
        response = await client.post(
            "/v1/chat/completions",
            json={"model": "test"},
            headers={"Authorization": "Bearer any-token"},
        )

    assert response.status_code == 200
    assert response.json()["id"] == "chatcmpl-123"
