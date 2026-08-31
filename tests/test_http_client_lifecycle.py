from __future__ import annotations

from types import SimpleNamespace

import pytest

import main


class FakeConfigLoader:
    def load_providers(self):
        return None

    def load_fallback_rules(self):
        return None


class FakeHTTPClient:
    def __init__(self, **kwargs):
        self.timeout = kwargs["timeout"]
        self.is_closed = False

    async def aclose(self):
        self.is_closed = True


class FakeTokensUsageDB:
    def __init__(self):
        self.cleanup_retention_days = []

    def cleanup_old_records(self, retention_days):
        self.cleanup_retention_days.append(retention_days)
        return 2


@pytest.mark.asyncio
async def test_lifespan_owns_one_shared_http_client_and_closes_it(monkeypatch):
    created_clients = []

    def client_factory(**kwargs):
        client = FakeHTTPClient(**kwargs)
        created_clients.append(client)
        return client

    monkeypatch.setattr(main, "ConfigLoader", FakeConfigLoader)
    monkeypatch.setattr(main, "TokensUsageDB", FakeTokensUsageDB)
    monkeypatch.setattr(main.httpx, "AsyncClient", client_factory)

    application = SimpleNamespace(state=SimpleNamespace())
    async with main.lifespan(application):
        assert len(created_clients) == 1
        assert application.state.http_client is created_clients[0]
        assert not created_clients[0].is_closed
        assert created_clients[0].timeout.connect == main.settings.http_connect_timeout
        assert created_clients[0].timeout.read == main.settings.http_read_timeout
        assert created_clients[0].timeout.write == main.settings.http_write_timeout
        assert created_clients[0].timeout.pool == main.settings.http_pool_timeout
        assert application.state.tokens_usage_db.cleanup_retention_days == [
            main.settings.tokens_usage_retention_days
        ]

    assert created_clients[0].is_closed


@pytest.mark.asyncio
async def test_lifespan_continues_when_retention_cleanup_fails(monkeypatch):
    class FailingTokensUsageDB:
        def cleanup_old_records(self, _retention_days):
            raise main.TokensUsageDBError("simulated cleanup failure")

    created_clients = []

    def client_factory(**kwargs):
        client = FakeHTTPClient(**kwargs)
        created_clients.append(client)
        return client

    monkeypatch.setattr(main, "ConfigLoader", FakeConfigLoader)
    monkeypatch.setattr(main, "TokensUsageDB", FailingTokensUsageDB)
    monkeypatch.setattr(main.httpx, "AsyncClient", client_factory)

    application = SimpleNamespace(state=SimpleNamespace())
    async with main.lifespan(application):
        assert len(created_clients) == 1

    assert created_clients[0].is_closed
