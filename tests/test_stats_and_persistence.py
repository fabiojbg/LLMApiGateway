from __future__ import annotations

import os
import sqlite3
import subprocess
import sys
import threading
from datetime import datetime, timedelta

import httpx
import pytest
from fastapi import FastAPI

from llm_gateway_core.api.v1.stats import stats_router
from llm_gateway_core.config.settings import settings
from llm_gateway_core.db.tokens_usage_db import TokensUsageDB, TokensUsageDBError


def make_stats_app(database) -> FastAPI:
    application = FastAPI()
    application.state.tokens_usage_db = database
    application.include_router(stats_router, prefix="/v1")
    return application


def test_empty_query_results_are_distinct_from_database_failures(tmp_path):
    database = TokensUsageDB(str(tmp_path / "usage.db"))

    assert database.get_latest_usage_records() == []
    assert database.get_total_records_count() == 0
    assert database.get_aggregated_usage("day") == []

    database.db_path = tmp_path

    with pytest.raises(TokensUsageDBError):
        database.get_latest_usage_records()
    with pytest.raises(TokensUsageDBError):
        database.get_total_records_count()
    with pytest.raises(TokensUsageDBError):
        database.get_aggregated_usage("day")


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "path",
    ["/v1/api/usage-records", "/v1/api/usage-stats/day"],
)
async def test_database_query_failures_map_to_http_500(path):
    class FailingDatabase:
        def get_latest_usage_records(self, *_args):
            raise TokensUsageDBError("simulated records failure")

        def get_total_records_count(self):
            raise TokensUsageDBError("simulated count failure")

        def get_aggregated_usage(self, *_args):
            raise TokensUsageDBError("simulated aggregate failure")

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(
            app=make_stats_app(FailingDatabase()), raise_app_exceptions=False
        ),
        base_url="http://gateway.test",
    ) as client:
        response = await client.get(path)

    assert response.status_code == 500


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "query",
    [
        "limit=0",
        f"limit={settings.usage_records_max_limit + 1}",
        "offset=-1",
        f"offset={settings.usage_records_max_offset + 1}",
    ],
)
async def test_usage_record_pagination_is_bounded(query):
    class DatabaseThatMustNotBeCalled:
        def get_latest_usage_records(self, *_args):
            raise AssertionError("query validation should run first")

        def get_total_records_count(self):
            raise AssertionError("query validation should run first")

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=make_stats_app(DatabaseThatMustNotBeCalled())),
        base_url="http://gateway.test",
    ) as client:
        response = await client.get(f"/v1/api/usage-records?{query}")

    assert response.status_code == 422


@pytest.mark.asyncio
async def test_stats_database_operations_run_off_the_event_loop():
    event_loop_thread = threading.get_ident()
    worker_threads = []

    class TrackingDatabase:
        def get_latest_usage_records(self, *_args):
            worker_threads.append(threading.get_ident())
            return []

        def get_total_records_count(self):
            worker_threads.append(threading.get_ident())
            return 0

        def get_aggregated_usage(self, *_args):
            worker_threads.append(threading.get_ident())
            return []

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=make_stats_app(TrackingDatabase())),
        base_url="http://gateway.test",
    ) as client:
        records_response = await client.get("/v1/api/usage-records")
        aggregate_response = await client.get("/v1/api/usage-stats/day")

    assert records_response.status_code == 200
    assert aggregate_response.status_code == 200
    assert len(worker_threads) == 3
    assert all(thread_id != event_loop_thread for thread_id in worker_threads)


def test_cleanup_removes_only_records_older_than_retention(tmp_path):
    database = TokensUsageDB(str(tmp_path / "usage.db"))
    old_timestamp = (datetime.now() - timedelta(days=181)).isoformat()
    with sqlite3.connect(database.db_path) as connection:
        connection.execute(
            "INSERT INTO tokens_usage (timestamp, model) VALUES (?, ?)",
            (old_timestamp, "old-model"),
        )
    database.insert_usage({"model": "current-model"})

    deleted_count = database.cleanup_old_records(retention_days=180)

    assert deleted_count == 1
    assert database.get_total_records_count() == 1
    assert database.get_latest_usage_records()[0]["model"] == "current-model"


def test_external_environment_wins_over_dotenv_file():
    environment = os.environ.copy()
    environment["FALLBACK_PROVIDER"] = "external-provider"
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "from llm_gateway_core.config.settings import settings; "
                "print(settings.fallback_provider)"
            ),
        ],
        check=True,
        capture_output=True,
        text=True,
        env=environment,
    )

    assert result.stdout.strip() == "external-provider"


def test_fallback_provider_has_openrouter_default():
    assert type(settings).model_fields["fallback_provider"].default == "openrouter"
