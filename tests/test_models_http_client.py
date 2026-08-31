from __future__ import annotations

from types import SimpleNamespace

import httpx
import pytest
from fastapi import FastAPI

from llm_gateway_core.api.v1 import models
from llm_gateway_core.config.loader import ProviderDetails


@pytest.mark.asyncio
async def test_models_endpoint_uses_application_http_client(monkeypatch):
    requests = []

    def handler(request):
        requests.append(request)
        return httpx.Response(
            200,
            json={"data": [{"id": "provider/model"}]},
            request=request,
        )

    downstream_client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    app = FastAPI()
    app.include_router(models.router, prefix="/v1/models")
    app.state.http_client = downstream_client
    app.state.config_loader = SimpleNamespace(
        fallback_rules={"gateway/model": {}},
        providers_config={
            "fallback": ProviderDetails(
                baseUrl="https://provider.test/v1", apikey="literal-key"
            )
        },
    )
    monkeypatch.setattr(models.settings, "fallback_provider", "fallback")

    try:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://gateway.test",
        ) as client:
            response = await client.get("/v1/models")
    finally:
        await downstream_client.aclose()

    assert response.status_code == 200
    assert [model["id"] for model in response.json()["data"]] == [
        "gateway/model",
        "provider/model",
    ]
    assert len(requests) == 1
    assert requests[0].url == "https://provider.test/v1/models"
