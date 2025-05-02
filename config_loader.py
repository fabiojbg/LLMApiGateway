import json
import logging
import os
import sys
from pathlib import Path
from typing import List, Dict, Any, Optional
from pydantic import BaseModel, Field, ValidationError, field_validator
from settings import Settings
from config import configure_logging

class ProviderDetails(BaseModel):
    baseUrl: str
    apikey: str

class FallbackModelRule(BaseModel):
    provider: str
    model: str
    use_provider_order_as_fallback: bool = False
    providers_order: Optional[List[str]] = None

class ModelFallbackConfig(BaseModel):
    gateway_model_name: str
    fallback_models: List[FallbackModelRule]
    rotate_models: bool = False

    @field_validator('rotate_models', mode='before')
    def validate_rotate_models(cls, v):
        if isinstance(v, str):
            return v.lower() == 'true'
        return v


class ConfigLoader:
    def __init__(self, providers_filename: str = "providers.json",
                 fallback_rules_filename: str = "models_fallback_rules.json"):
        self.providers_path = Path(__file__).parent / providers_filename
        self.fallback_rules_path = Path(__file__).parent / fallback_rules_filename
        self.providers_config: Dict[str, ProviderDetails] = {}
        self.fallback_rules: Dict[str, Dict[str, Any]] = {}

    def load_providers(self) -> Dict[str, ProviderDetails]:
        """Loads and validates provider configurations from the JSON file."""

        if not self.providers_path.exists():
            logging.error(f"Provider configuration file not found at {self.providers_path}")
            sys.exit(1)
        
        try:
            with open(self.providers_path) as f:
                raw_mapping = json.load(f)

            providers_config_temp = {}
            for item in raw_mapping:
                if not isinstance(item, dict) or len(item) != 1:
                    raise ValueError("Each provider entry must be a dictionary with a single key (provider name).")
                provider_name = list(item.keys())[0]
                provider_details_raw = list(item.values())[0]
                providers_config_temp[provider_name] = ProviderDetails(**provider_details_raw)

            self.providers_config = providers_config_temp
            self._validate_providers()
            logging.info(f"Successfully loaded and validated providers from {self.providers_path}")
            logging.info(f"Loaded providers: {list(self.providers_config.keys())}")
            return self.providers_config

        except (json.JSONDecodeError, ValidationError, ValueError) as e:
            logging.error(f"Failed to load or validate '{self.providers_path.name}': {str(e)}", exc_info=True)
            sys.exit(1)
        except Exception as e:
            logging.error(f"An unexpected error occurred while loading providers: {str(e)}", exc_info=True)
            sys.exit(1)

    def _validate_providers(self):
        """Performs post-load validation on provider configurations."""
        fallback_provider_name = Settings.fallback_provider
        if fallback_provider_name not in self.providers_config:
            logging.error(f"Fallback provider '{fallback_provider_name}' defined in settings not found in providers configuration.")
            sys.exit(1)

        for provider_name, config in self.providers_config.items():
            # Pydantic already validates baseUrl and apikey presence
            env_api_key = os.getenv(config.apikey)
            if not env_api_key:
                # Changed from error to warning as per original logic, but maybe should be error?
                logging.warning(f"Environment variable '{config.apikey}' for provider '{provider_name}' is not set.")
                # sys.exit(1) # Decide if this should be a fatal error

    def load_fallback_rules(self) -> Dict[str, Dict[str, Any]]:
        """Loads and validates model fallback rules from the JSON file."""
        if not self.fallback_rules_path.exists():
            logging.warning(f"Model fallback rules file not found at {self.fallback_rules_path}. Proceeding without fallback rules.")
            return {}

        try:
            with open(self.fallback_rules_path) as f:
                raw_rules = json.load(f)

            fallback_rules_temp = {}
            validated_rules = [ModelFallbackConfig(**item) for item in raw_rules]

            for rule in validated_rules:
                fallback_rules_temp[rule.gateway_model_name] = {
                    "fallback_models": [fm.model_dump(exclude_none=True) for fm in rule.fallback_models],
                    "rotate_models": rule.rotate_models
                }

            self.fallback_rules = fallback_rules_temp
            self._validate_fallback_rules()
            logging.info(f"Successfully loaded and validated model fallback rules from {self.fallback_rules_path}")
            logging.info(f"Loaded model rules for: {list(self.fallback_rules.keys())}")
            return self.fallback_rules

        except (json.JSONDecodeError, ValidationError) as e:
            logging.error(f"Failed to load or validate '{self.fallback_rules_path.name}': {str(e)}", exc_info=True)
            sys.exit(1)
        except Exception as e:
            logging.error(f"An unexpected error occurred while loading fallback rules: {str(e)}", exc_info=True)
            sys.exit(1)

    def _validate_fallback_rules(self):
        """Performs post-load validation on fallback rules."""
        if not self.providers_config:
             logging.error("Provider configuration must be loaded before validating fallback rules.")
             sys.exit(1)

        for gateway_model_name, config in self.fallback_rules.items():
            fallback_models = config.get("fallback_models", [])
            if not fallback_models:
                logging.error(f"Gateway model '{gateway_model_name}' must have at least one fallback model defined.")
                sys.exit(1)

            for fallback_model_rule in fallback_models:
                provider = fallback_model_rule.get("provider")
                model = fallback_model_rule.get("model")

                if not provider:
                    logging.error(f"'provider' is missing for a fallback rule under '{gateway_model_name}'.")
                    sys.exit(1)
                if not model:
                     logging.error(f"'model' is missing for a fallback rule under '{gateway_model_name}' (provider: {provider}).")
                     sys.exit(1)
                if provider not in self.providers_config:
                    logging.error(f"Invalid provider '{provider}' used in fallback rule for '{gateway_model_name}'. Provider not found in configuration.")
                    sys.exit(1)

