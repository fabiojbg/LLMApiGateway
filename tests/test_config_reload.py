from __future__ import annotations

import copy
import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from llm_gateway_core.api.v1 import rules_editor
from llm_gateway_core.config import loader as loader_module
from llm_gateway_core.config.loader import (
    ConfigError,
    ConfigLoader,
    ConfigPersistenceError,
    ConfigValidationError,
    ProviderDetails,
)


@pytest.fixture
def config_loader(monkeypatch, tmp_path):
    monkeypatch.setattr(loader_module.settings, "fallback_provider", None)
    loader = ConfigLoader()
    loader.providers_path = tmp_path / "providers.json"
    loader.fallback_rules_path = tmp_path / "models_fallback_rules.json"
    loader.temp_dir = tmp_path / "app_data"
    loader.providers_config = {
        "known": ProviderDetails(baseUrl="https://known.test/v1", apikey="APIKEY_KNOWN")
    }
    return loader


def request_for(loader):
    return SimpleNamespace(
        app=SimpleNamespace(state=SimpleNamespace(config_loader=loader))
    )


def rule_payload(gateway_model: str, provider: str = "known") -> str:
    return (
        "[\n"
        f'  {{"gateway_model_name":"{gateway_model}","fallback_models":[\n'
        f'    {{"provider":"{provider}","model":"provider-model"}}\n'
        "  ]}\n"
        "]"
    )


def providers_payload(*provider_names: str) -> str:
    entries = ",\n".join(
        (
            f'  {{"{name}":{{"baseUrl":"https://{name}.test/v1",'
            f'"apikey":"APIKEY_{name.upper()}"}}}}'
        )
        for name in provider_names
    )
    return f"[\n{entries}\n]"


def test_reload_fallback_rules_updates_memory_after_valid_file(config_loader):
    config_loader.fallback_rules_path.write_text(
        rule_payload("gateway/new"), encoding="utf-8"
    )

    assert config_loader.reload_fallback_rules() is True
    assert config_loader.fallback_rules["gateway/new"]["fallback_models"][0] == {
        "provider": "known",
        "model": "provider-model",
        "use_provider_order_as_fallback": False,
        "custom_body_params": {},
        "custom_headers": {},
    }


@pytest.mark.asyncio
async def test_failed_rules_update_preserves_file_and_in_memory_state(config_loader):
    original = rule_payload("gateway/original")
    config_loader.fallback_rules_path.write_text(original, encoding="utf-8")
    assert config_loader.reload_fallback_rules() is True
    original_memory = copy.deepcopy(config_loader.fallback_rules)

    with pytest.raises(HTTPException) as exc_info:
        await rules_editor.save_models_rules(
            request_for(config_loader), rule_payload("gateway/bad", "missing")
        )

    assert exc_info.value.status_code == 400
    assert config_loader.fallback_rules_path.read_text(encoding="utf-8") == original
    assert config_loader.fallback_rules == original_memory


@pytest.mark.asyncio
async def test_failed_providers_update_preserves_file_and_memory(config_loader):
    original = providers_payload("known")
    config_loader.providers_path.write_text(original, encoding="utf-8")
    config_loader.fallback_rules = {
        "gateway/in-use": {
            "fallback_models": [{"provider": "known", "model": "model"}],
            "rotate_models": False,
        }
    }
    original_memory = copy.deepcopy(config_loader.providers_config)

    with pytest.raises(HTTPException) as exc_info:
        await rules_editor.save_providers_config(
            request_for(config_loader), providers_payload("replacement")
        )

    assert exc_info.value.status_code == 400
    assert config_loader.providers_path.read_text(encoding="utf-8") == original
    assert config_loader.providers_config == original_memory


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "endpoint",
    [rules_editor.save_models_rules, rules_editor.save_providers_config],
)
async def test_endpoint_maps_structural_validation_to_400(config_loader, endpoint):
    with pytest.raises(HTTPException) as exc_info:
        await endpoint(request_for(config_loader), "{not: 'a list'}")

    assert exc_info.value.status_code == 400


def test_provider_update_requires_configured_fallback_provider(
    monkeypatch, config_loader
):
    monkeypatch.setattr(loader_module.settings, "fallback_provider", "required")

    with pytest.raises(ConfigValidationError, match="Fallback provider 'required'"):
        config_loader.apply_providers(providers_payload("known"))


@pytest.mark.parametrize("target", ["rules", "providers"])
def test_atomic_update_preserves_comments_exactly(config_loader, target):
    if target == "rules":
        payload = (
            "[\n  // keep this rule comment\n"
            '  {gateway_model_name:"gateway/commented", fallback_models:['
            '{provider:"known", model:"model"}]}\n]'
        )
        config_loader.apply_fallback_rules(payload)
        path = config_loader.fallback_rules_path
    else:
        payload = (
            "[\n  // keep this provider comment\n"
            '  {known:{baseUrl:"https://known.test/v1", '
            'apikey:"APIKEY_KNOWN"}}\n]'
        )
        config_loader.apply_providers(payload)
        path = config_loader.providers_path

    assert path.read_text(encoding="utf-8") == payload


@pytest.mark.parametrize("target", ["rules", "providers"])
def test_persistence_failure_preserves_file_state_and_removes_temporary(
    monkeypatch, config_loader, target
):
    if target == "rules":
        path = config_loader.fallback_rules_path
        original = rule_payload("gateway/original")
        path.write_text(original, encoding="utf-8")
        config_loader.reload_fallback_rules()
        state_before = copy.deepcopy(config_loader.fallback_rules)
        apply = config_loader.apply_fallback_rules
        payload = rule_payload("gateway/new")
    else:
        path = config_loader.providers_path
        original = providers_payload("known")
        path.write_text(original, encoding="utf-8")
        state_before = copy.deepcopy(config_loader.providers_config)
        apply = config_loader.apply_providers
        payload = providers_payload("known", "new")

    def fail(*_args, **_kwargs):
        raise OSError("simulated fsync failure")

    monkeypatch.setattr(os, "fsync", fail)

    with pytest.raises(ConfigPersistenceError, match="Could not persist"):
        apply(payload)

    current_state = (
        config_loader.fallback_rules
        if target == "rules"
        else config_loader.providers_config
    )
    assert path.read_text(encoding="utf-8") == original
    assert current_state == state_before
    assert list(config_loader.temp_dir.glob(f".{path.name}.*.tmp")) == []


@pytest.mark.parametrize("target", ["rules", "providers"])
def test_atomic_write_falls_back_when_os_replace_fails_on_bind_mount(
    monkeypatch, config_loader, target
):
    if target == "rules":
        path = config_loader.fallback_rules_path
        original = rule_payload("gateway/original")
        path.write_text(original, encoding="utf-8")
        config_loader.reload_fallback_rules()
        apply = config_loader.apply_fallback_rules
        payload = rule_payload("gateway/new")
    else:
        path = config_loader.providers_path
        original = providers_payload("known")
        path.write_text(original, encoding="utf-8")
        apply = config_loader.apply_providers
        payload = providers_payload("known", "new")

    def fail_replace(src, dst):
        # Simulate Linux docker bind-mount Errno 16 Device or resource busy
        raise OSError(16, "Device or resource busy")

    monkeypatch.setattr(os, "replace", fail_replace)

    # Should succeed via the direct-write fallback without raising
    apply(payload)

    assert path.read_text(encoding="utf-8") == payload
    # Temporary file in temp_dir should be deleted
    assert list(config_loader.temp_dir.glob(f".{path.name}.*.tmp")) == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("endpoint", "path_attribute", "payload"),
    [
        (
            rules_editor.save_models_rules,
            "fallback_rules_path",
            rule_payload("gateway/new"),
        ),
        (
            rules_editor.save_providers_config,
            "providers_path",
            providers_payload("known"),
        ),
    ],
)
async def test_endpoint_maps_persistence_failure_to_500(
    monkeypatch, config_loader, endpoint, path_attribute, payload
):
    def fail(*_args, **_kwargs):
        raise ConfigPersistenceError("simulated persistence failure")

    method_name = (
        "apply_fallback_rules"
        if path_attribute == "fallback_rules_path"
        else "apply_providers"
    )
    monkeypatch.setattr(config_loader, method_name, fail)

    with pytest.raises(HTTPException) as exc_info:
        await endpoint(request_for(config_loader), payload)

    assert exc_info.value.status_code == 500


def test_concurrent_updates_are_serialized_and_keep_file_in_sync(
    monkeypatch, config_loader
):
    original_atomic_write = config_loader._atomic_write
    counter_lock = threading.Lock()
    active_writes = 0
    maximum_active_writes = 0

    def tracked_atomic_write(path, payload):
        nonlocal active_writes, maximum_active_writes
        with counter_lock:
            active_writes += 1
            maximum_active_writes = max(maximum_active_writes, active_writes)
        time.sleep(0.03)
        try:
            original_atomic_write(path, payload)
        finally:
            with counter_lock:
                active_writes -= 1

    monkeypatch.setattr(config_loader, "_atomic_write", tracked_atomic_write)
    payloads = [rule_payload("gateway/one"), rule_payload("gateway/two")]

    with ThreadPoolExecutor(max_workers=2) as executor:
        list(executor.map(config_loader.apply_fallback_rules, payloads))

    persisted = config_loader.fallback_rules_path.read_text(encoding="utf-8")
    active_gateway_model = next(iter(config_loader.fallback_rules))
    assert maximum_active_writes == 1
    assert persisted in payloads
    assert active_gateway_model in persisted


def test_startup_load_raises_configuration_exception_instead_of_system_exit(
    config_loader,
):
    with pytest.raises(ConfigError, match="not found"):
        config_loader.load_providers()


@pytest.mark.parametrize(
    "retry_fields",
    [
        '"retry_count":-1',
        '"retry_count":1',
        '"retry_count":1,"retry_delay":0',
        '"retry_count":"1","retry_delay":1',
        '"retry_count":1,"retry_delay":"1"',
        f'"retry_count":{loader_module.settings.max_retry_count + 1},'
        '"retry_delay":1',
        (
            '"retry_count":1,"retry_delay":'
            f'{loader_module.settings.max_retry_delay_seconds + 1}'
        ),
    ],
)
def test_invalid_retry_configuration_is_rejected(config_loader, retry_fields):
    payload = (
        '[{"gateway_model_name":"gateway/retry","fallback_models":['
        '{"provider":"known","model":"provider-model",'
        f'{retry_fields}'
        "}]}]"
    )

    with pytest.raises(ConfigValidationError, match="retry"):
        config_loader.apply_fallback_rules(payload)


def test_valid_retry_configuration_is_preserved(config_loader):
    payload = (
        '[{"gateway_model_name":"gateway/retry","fallback_models":['
        '{"provider":"known","model":"provider-model",'
        '"retry_count":2,"retry_delay":5}]}]'
    )

    config_loader.apply_fallback_rules(payload)

    retry_rule = config_loader.fallback_rules["gateway/retry"]["fallback_models"][0]
    assert retry_rule["retry_count"] == 2
    assert retry_rule["retry_delay"] == 5


def test_atomic_write_creates_temp_file_in_temp_dir(monkeypatch, config_loader):
    recorded_dirs = []
    original_named_temporary_file = loader_module.tempfile.NamedTemporaryFile

    def tracking_named_temporary_file(*args, **kwargs):
        recorded_dirs.append(kwargs.get("dir"))
        return original_named_temporary_file(*args, **kwargs)

    monkeypatch.setattr(
        loader_module.tempfile, "NamedTemporaryFile", tracking_named_temporary_file
    )

    payload = rule_payload("gateway/temp-test")
    config_loader.apply_fallback_rules(payload)

    assert recorded_dirs == [config_loader.temp_dir]
    assert config_loader.fallback_rules_path.read_text(encoding="utf-8") == payload
