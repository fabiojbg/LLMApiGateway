import logging
import os
import tempfile
import threading
from pathlib import Path
from typing import Any, Dict, List, Optional

import json5
from pydantic import (
    BaseModel,
    Field,
    RootModel,
    StrictInt,
    ValidationError,
    field_validator,
    model_validator,
)

from .settings import settings


class ConfigError(RuntimeError):
    """Base exception for configuration loading and updates."""


class ConfigValidationError(ConfigError):
    """Raised when configuration text is structurally or semantically invalid."""


class ConfigPersistenceError(ConfigError):
    """Raised when a validated configuration cannot be persisted."""


class ProviderDetails(BaseModel):
    baseUrl: str
    apikey: str


class ProviderConfig(RootModel[Dict[str, ProviderDetails]]):
    """A single provider entry, keyed by its provider name."""

    @model_validator(mode="before")
    @classmethod
    def check_single_key_and_structure(cls, data: Any) -> Any:
        if not isinstance(data, dict):
            raise ValueError("Provider entry must be a dictionary.")
        if len(data) != 1:
            raise ValueError(
                "Provider entry dictionary must contain exactly one key "
                "(the provider name)."
            )
        return data


class FallbackModelRule(BaseModel):
    provider: str
    model: str
    use_provider_order_as_fallback: bool = False
    providers_order: Optional[List[str]] = None
    retry_delay: Optional[StrictInt] = Field(
        default=None, ge=1, le=settings.max_retry_delay_seconds
    )
    retry_count: Optional[StrictInt] = Field(
        default=None, ge=0, le=settings.max_retry_count
    )
    custom_body_params: Dict[str, Any] = Field(default_factory=dict)
    custom_headers: Dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_retry_configuration(self) -> "FallbackModelRule":
        if (self.retry_count or 0) > 0 and self.retry_delay is None:
            raise ValueError(
                "retry_delay is required when retry_count is greater than zero."
            )
        return self


class ModelFallbackConfig(BaseModel):
    gateway_model_name: str
    fallback_models: List[FallbackModelRule]
    rotate_models: bool = False

    @field_validator("rotate_models", mode="before")
    @classmethod
    def validate_rotate_models(cls, value: Any) -> Any:
        if isinstance(value, str):
            return value.lower() == "true"
        return value


class ConfigLoader:
    def __init__(
        self,
        providers_filename: str = "providers.json",
        fallback_rules_filename: str = "models_fallback_rules.json",
        temp_dir: Optional[Path] = None,
    ):
        project_root = Path(__file__).parent.parent.parent
        self.providers_path = project_root / providers_filename
        self.fallback_rules_path = project_root / fallback_rules_filename
        self.temp_dir = temp_dir if temp_dir is not None else (project_root / "app_data")
        self.providers_config: Dict[str, ProviderDetails] = {}
        self.fallback_rules: Dict[str, Dict[str, Any]] = {}
        self._update_lock = threading.RLock()

    def load_providers(self) -> Dict[str, ProviderDetails]:
        """Load providers for startup, raising ConfigError on any failure."""
        with self._update_lock:
            payload_text = self._read_required_file(self.providers_path)
            providers = self._parse_and_validate_providers(
                payload_text, self.fallback_rules
            )
            self.providers_config = providers

        logging.info(
            "Successfully loaded and validated providers from %s", self.providers_path
        )
        logging.info("Loaded providers: %s", list(providers))
        return providers

    def load_fallback_rules(self) -> Dict[str, Dict[str, Any]]:
        """Load fallback rules for startup, raising ConfigError on invalid data."""
        with self._update_lock:
            if not self.fallback_rules_path.exists():
                logging.warning(
                    "Model fallback rules file not found at %s. "
                    "Proceeding without fallback rules.",
                    self.fallback_rules_path,
                )
                self.fallback_rules = {}
                return {}

            if not self.providers_config:
                self.load_providers()

            payload_text = self._read_required_file(self.fallback_rules_path)
            rules = self._parse_and_validate_fallback_rules(
                payload_text, self.providers_config
            )
            self.fallback_rules = rules

        logging.info(
            "Successfully loaded and validated model fallback rules from %s",
            self.fallback_rules_path,
        )
        logging.info("Loaded model rules for: %s", list(rules))
        return rules

    def reload_fallback_rules(self) -> bool:
        """Reload fallback rules from disk without changing state on failure."""
        try:
            with self._update_lock:
                if not self.providers_config:
                    self.load_providers()
                payload_text = self._read_required_file(self.fallback_rules_path)
                rules = self._parse_and_validate_fallback_rules(
                    payload_text, self.providers_config
                )
                self.fallback_rules = rules
            return True
        except ConfigError as error:
            logging.error("Could not reload fallback rules: %s", error)
            return False

    def reload_providers_config(self) -> bool:
        """Reload providers from disk without changing state on failure."""
        try:
            with self._update_lock:
                payload_text = self._read_required_file(self.providers_path)
                providers = self._parse_and_validate_providers(
                    payload_text, self.fallback_rules
                )
                self.providers_config = providers
            return True
        except ConfigError as error:
            logging.error("Could not reload providers: %s", error)
            return False

    def apply_fallback_rules(self, payload_text: str) -> None:
        """Validate, atomically persist, and activate new fallback rules."""
        with self._update_lock:
            rules = self._parse_and_validate_fallback_rules(
                payload_text, self.providers_config
            )
            self._atomic_write(self.fallback_rules_path, payload_text)
            self.fallback_rules = rules

    def apply_providers(self, payload_text: str) -> None:
        """Validate, atomically persist, and activate new providers."""
        with self._update_lock:
            providers = self._parse_and_validate_providers(
                payload_text, self.fallback_rules
            )
            self._atomic_write(self.providers_path, payload_text)
            self.providers_config = providers

    def _parse_and_validate_providers(
        self,
        payload_text: str,
        fallback_rules: Dict[str, Dict[str, Any]],
    ) -> Dict[str, ProviderDetails]:
        try:
            raw_provider_list = json5.loads(payload_text)
            if not isinstance(raw_provider_list, list):
                raise ValueError("Expected a list of provider objects.")

            providers: Dict[str, ProviderDetails] = {}
            for item in raw_provider_list:
                validated_entry = ProviderConfig.model_validate(item)
                provider_name, provider_details = next(
                    iter(validated_entry.root.items())
                )
                if provider_name in providers:
                    raise ValueError(f"Duplicate provider '{provider_name}'.")
                providers[provider_name] = provider_details

            self._perform_provider_semantic_validation(providers, fallback_rules)
            return providers
        except ConfigValidationError:
            raise
        except (ValidationError, ValueError, TypeError) as error:
            raise ConfigValidationError(
                f"Invalid providers configuration: {error}"
            ) from error

    def _parse_and_validate_fallback_rules(
        self,
        payload_text: str,
        providers: Dict[str, ProviderDetails],
    ) -> Dict[str, Dict[str, Any]]:
        try:
            raw_rules = json5.loads(payload_text)
            if not isinstance(raw_rules, list):
                raise ValueError("Expected a list of rule objects.")

            fallback_rules: Dict[str, Dict[str, Any]] = {}
            for item in raw_rules:
                rule = ModelFallbackConfig.model_validate(item)
                if rule.gateway_model_name in fallback_rules:
                    raise ValueError(
                        f"Duplicate gateway model '{rule.gateway_model_name}'."
                    )
                fallback_rules[rule.gateway_model_name] = {
                    "fallback_models": [
                        model.model_dump(exclude_none=True)
                        for model in rule.fallback_models
                    ],
                    "rotate_models": rule.rotate_models,
                }

            self._validate_fallback_rules_for_providers(fallback_rules, providers)
            return fallback_rules
        except ConfigValidationError:
            raise
        except (ValidationError, ValueError, TypeError) as error:
            raise ConfigValidationError(
                f"Invalid fallback rules configuration: {error}"
            ) from error

    def _perform_provider_semantic_validation(
        self,
        providers_to_validate: Dict[str, ProviderDetails],
        fallback_rules: Optional[Dict[str, Dict[str, Any]]] = None,
    ) -> None:
        fallback_provider_name = settings.fallback_provider
        if (
            fallback_provider_name
            and fallback_provider_name not in providers_to_validate
        ):
            raise ConfigValidationError(
                f"Fallback provider '{fallback_provider_name}' defined in settings "
                "was not found in the providers configuration."
            )

        self._validate_fallback_rules_for_providers(
            fallback_rules or {}, providers_to_validate
        )

        for provider_name, config in providers_to_validate.items():
            if not os.getenv(config.apikey):
                logging.warning(
                    "Environment variable '%s' for provider '%s' is not set.",
                    config.apikey,
                    provider_name,
                )

    def _validate_fallback_rules_for_providers(
        self,
        fallback_rules: Dict[str, Dict[str, Any]],
        providers: Dict[str, ProviderDetails],
    ) -> None:
        for gateway_model_name, config in fallback_rules.items():
            fallback_models = config.get("fallback_models", [])
            if not fallback_models:
                raise ConfigValidationError(
                    f"Gateway model '{gateway_model_name}' must have at least one "
                    "fallback model defined."
                )

            for fallback_model in fallback_models:
                provider = fallback_model.get("provider")
                model = fallback_model.get("model")
                if not model:
                    raise ConfigValidationError(
                        f"Model is missing from a fallback rule for "
                        f"'{gateway_model_name}'."
                    )
                if provider not in providers:
                    raise ConfigValidationError(
                        f"Invalid provider '{provider}' used in fallback rule for "
                        f"'{gateway_model_name}'."
                    )

    def _validate_providers(self) -> None:
        """Validate the currently loaded providers and rule references."""
        self._perform_provider_semantic_validation(
            self.providers_config, self.fallback_rules
        )

    def _validate_fallback_rules(self) -> None:
        """Validate currently loaded fallback rules against current providers."""
        self._validate_fallback_rules_for_providers(
            self.fallback_rules, self.providers_config
        )

    @staticmethod
    def _read_required_file(path: Path) -> str:
        if not path.exists():
            raise ConfigError(f"Configuration file not found at {path}.")
        try:
            return path.read_text(encoding="utf-8")
        except OSError as error:
            raise ConfigError(
                f"Could not read configuration file {path}: {error}"
            ) from error

    def _atomic_write(
        self,
        path: Path,
        payload_text: str,
        temp_dir: Optional[Path] = None,
    ) -> None:
        target_temp_dir = temp_dir or self.temp_dir
        temporary_path: Optional[Path] = None
        try:
            target_temp_dir.mkdir(parents=True, exist_ok=True)
            path.parent.mkdir(parents=True, exist_ok=True)
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                newline="",
                prefix=f".{path.name}.",
                suffix=".tmp",
                dir=target_temp_dir,
                delete=False,
            ) as temporary_file:
                temporary_path = Path(temporary_file.name)
                temporary_file.write(payload_text)
                temporary_file.flush()
                os.fsync(temporary_file.fileno())

            try:
                os.replace(temporary_path, path)
                temporary_path = None
            except OSError:
                # In containerized environments (e.g. Docker with single-file bind mounts),
                # os.replace can fail with EBUSY (mount point) or EXDEV (cross-device link).
                # In this case, fall back to writing directly to the target file.
                with open(path, "w", encoding="utf-8", newline="") as dest_file:
                    dest_file.write(payload_text)
                    dest_file.flush()
                    os.fsync(dest_file.fileno())
        except Exception as error:
            raise ConfigPersistenceError(
                f"Could not persist configuration file {path}: {error}"
            ) from error
        finally:
            if temporary_path is not None:
                try:
                    temporary_path.unlink(missing_ok=True)
                except OSError:
                    logging.exception(
                        "Could not remove temporary configuration file %s",
                        temporary_path,
                    )
