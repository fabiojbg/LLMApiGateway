import json5
import logging
import os
import sys
from pathlib import Path
from typing import List, Dict, Any, Optional
from pydantic import BaseModel, Field, ValidationError, field_validator, RootModel, model_validator

# Import settings using relative path within the package
from .settings import settings

# Note: Pydantic models defined here. Consider moving them to llm_gateway_core/models/config.py
# or similar for better separation if the models directory grows.
class ProviderDetails(BaseModel):
    baseUrl: str
    apikey: str

class ProviderConfig(RootModel[Dict[str, ProviderDetails]]):
    """
    Represents a single entry in the providers.json list, 
    which is a dictionary with one key (provider name) and ProviderDetails as value.
    e.g., {"openai": {"baseUrl": "...", "apikey": "..."}}
    """
    @model_validator(mode='before')
    @classmethod
    def check_single_key_and_structure(cls, data: Any) -> Any:
        if not isinstance(data, dict):
            raise ValueError("Provider entry must be a dictionary.")
        if len(data) != 1:
            raise ValueError("Provider entry dictionary must contain exactly one key (the provider name).")
        
        # Further validation of inner structure can be implicitly handled by Pydantic
        # when it tries to match Dict[str, ProviderDetails]
        # For example, the value associated with the key must match ProviderDetails structure.
        return data

class FallbackModelRule(BaseModel):
    provider: str
    model: str
    use_provider_order_as_fallback: bool = False
    providers_order: Optional[List[str]] = None
    retry_delay: Optional[int] = None
    retry_count: Optional[int] = None
    custom_body_params: Dict[str, Any] = Field(default_factory=dict)
    custom_headers: Dict[str, Any] = Field(default_factory=dict)

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
        # Adjust path to go up two levels from llm_gateway_core/config to project root
        project_root = Path(__file__).parent.parent.parent
        self.providers_path = project_root / providers_filename
        self.fallback_rules_path = project_root / fallback_rules_filename
        self.providers_config: Dict[str, ProviderDetails] = {}
        self.fallback_rules: Dict[str, Dict[str, Any]] = {} # Store validated rules as dicts

    def load_providers(self) -> Dict[str, ProviderDetails]:
        """Loads and validates provider configurations from the JSON file."""

        if not self.providers_path.exists():
            logging.error(f"Provider configuration file not found at {self.providers_path}")
            sys.exit(1)

        try:
            with open(self.providers_path, 'r', encoding='utf-8') as f:
                raw_mapping = json5.load(f)

            providers_config_temp = {}
            for item in raw_mapping:
                if not isinstance(item, dict) or len(item) != 1:
                    raise ValueError("Each provider entry must be a dictionary with a single key (provider name).")
                provider_name = list(item.keys())[0]
                provider_details_raw = list(item.values())[0]
                # Validate using Pydantic model
                providers_config_temp[provider_name] = ProviderDetails(**provider_details_raw)

            self.providers_config = providers_config_temp
            if not self._perform_provider_semantic_validation(self.providers_config, exit_on_error=True):
                # _perform_provider_semantic_validation will log errors and sys.exit if exit_on_error is True
                pass # Should have exited if critical error occurred

            logging.info(f"Successfully loaded and validated providers from {self.providers_path}")
            logging.info(f"Loaded providers: {list(self.providers_config.keys())}")
            return self.providers_config

        except Exception as e:
            logging.error(f"Failed to load or validate '{self.providers_path.name}': {str(e)}", exc_info=True)
            sys.exit(1) # Exit if loading fails

    def _perform_provider_semantic_validation(self, providers_to_validate: Dict[str, ProviderDetails], exit_on_error: bool = False) -> bool:
        """
        Performs semantic validation on a dictionary of provider configurations.
        Checks for fallback provider existence and API key environment variables.
        Returns True if all critical checks pass, False otherwise.
        If exit_on_error is True, calls sys.exit(1) on critical failure.
        """
        all_valid = True
        fallback_provider_name = settings.fallback_provider
        if fallback_provider_name and fallback_provider_name not in providers_to_validate:
            logging.error(f"Fallback provider '{fallback_provider_name}' defined in settings not found in the provided providers configuration.")
            if exit_on_error:
                sys.exit(1)
            all_valid = False # Mark as invalid but continue checking other things if not exiting

        for provider_name, config in providers_to_validate.items():
            env_api_key = os.getenv(config.apikey)
            if not env_api_key:
                logging.warning(f"Environment variable '{config.apikey}' for provider '{provider_name}' is not set. This is a warning.")
        
        return all_valid

    def _validate_providers(self):
        """Legacy wrapper for initial load validation. Calls sys.exit on failure."""
        if not self._perform_provider_semantic_validation(self.providers_config, exit_on_error=True):
            # This path should ideally not be reached if exit_on_error is true and there's an error,
            # but as a safeguard:
            logging.critical("Provider semantic validation failed during initial load.")
            sys.exit(1)


    def load_fallback_rules(self) -> Dict[str, Dict[str, Any]]:
        """Loads and validates model fallback rules from the JSON file."""
        if not self.fallback_rules_path.exists():
            logging.warning(f"Model fallback rules file not found at {self.fallback_rules_path}. Proceeding without fallback rules.")
            return {}

        try:
            with open(self.fallback_rules_path, 'r', encoding='utf-8') as f:
                raw_rules = json5.load(f)

            fallback_rules_temp = {}
            # Validate each rule using the Pydantic model first
            validated_rules = [ModelFallbackConfig(**item) for item in raw_rules]

            # Convert validated Pydantic models back to dictionaries for storage
            # This keeps the return type consistent with the original structure,
            # although returning the Pydantic objects might be cleaner.
            for rule in validated_rules:
                fallback_rules_temp[rule.gateway_model_name] = {
                    "fallback_models": [fm.model_dump(exclude_none=True) for fm in rule.fallback_models],
                    "rotate_models": rule.rotate_models
                }

            self.fallback_rules = fallback_rules_temp
            self._validate_fallback_rules() # Perform post-load validation
            logging.info(f"Successfully loaded and validated model fallback rules from {self.fallback_rules_path}")
            logging.info(f"Loaded model rules for: {list(self.fallback_rules.keys())}")
            return self.fallback_rules

        except Exception as e:
            logging.error(f"Failed to load or validate '{self.fallback_rules_path.name}': {str(e)}", exc_info=True)
            sys.exit(1)

    def reload_fallback_rules(self) -> bool:
        """Reloads and validates model fallback rules from the JSON file.
        Returns True on success, False on failure."""
        if not self.fallback_rules_path.exists():
            logging.error(f"Model fallback rules file not found at {self.fallback_rules_path} during reload.")
            return False

        try:
            with open(self.fallback_rules_path, 'r', encoding='utf-8') as f:
                raw_rules = json5.load(f)

            fallback_rules_temp = {}
            validated_rules = [ModelFallbackConfig(**item) for item in raw_rules]

            for rule in validated_rules:
                fallback_rules_temp[rule.gateway_model_name] = {
                    "fallback_models": [fm.model_dump(exclude_none=True) for fm in rule.fallback_models],
                    "rotate_models": rule.rotate_models
                }
            
            # Perform validation before assigning to self.fallback_rules
            # This requires a temporary way to call _validate_fallback_rules or its logic
            # For simplicity here, we'll assume _validate_fallback_rules can be adapted or its core logic used.
            # A more robust solution might involve passing the temporary rules to a validation method.
            
            # Temporarily assign to a new variable to validate
            potential_new_rules = fallback_rules_temp
            
            # Validate the potential new rules (adapting _validate_fallback_rules logic)
            if not self.providers_config:
                 logging.warning("Providers not loaded. Cannot validate fallback rules during reload.")
                 # Attempt to load providers if not already loaded, but don't exit on failure here.
                 if not self.load_providers(): # Assuming load_providers could also return bool or not exit
                     logging.error("Failed to load providers during fallback rule reload. Validation skipped.")
                     # Decide if to proceed without validation or return False
                     # For now, let's be strict and return False if providers can't be loaded for validation
                     return False


            for gateway_model_name, config in potential_new_rules.items():
                fallback_models = config.get("fallback_models", [])
                if not fallback_models:
                    logging.error(f"During reload, gateway model '{gateway_model_name}' must have at least one fallback model defined.")
                    return False
                for fallback_model_rule in fallback_models:
                    provider = fallback_model_rule.get("provider")
                    model = fallback_model_rule.get("model")
                    if not provider:
                        logging.error(f"During reload, 'provider' is missing for a fallback rule under '{gateway_model_name}'.")
                        return False
                    if not model:
                        logging.error(f"During reload, 'model' is missing for a fallback rule under '{gateway_model_name}' (provider: {provider}).")
                        return False
                    if provider not in self.providers_config:
                        logging.error(f"During reload, invalid provider '{provider}' used in fallback rule for '{gateway_model_name}'. Provider not found.")
                        return False

            # If all validations pass, update the actual instance rules
            self.fallback_rules = potential_new_rules
            logging.info(f"Successfully reloaded and validated model fallback rules from {self.fallback_rules_path}")
            logging.info(f"Reloaded model rules for: {list(self.fallback_rules.keys())}")
            return True

        except ValidationError as ve:
            logging.error(f"Validation error during reload of '{self.fallback_rules_path.name}': {ve.errors()}", exc_info=False) # No need for full stack for validation
            return False
        except Exception as e:
            logging.error(f"Failed to reload or validate '{self.fallback_rules_path.name}': {str(e)}", exc_info=True)
            return False

    def reload_providers_config(self) -> bool:
        """
        Reloads and validates provider configurations from the providers.json file.
        Updates self.providers_config on success.
        Returns True on success, False on failure.
        """
        if not self.providers_path.exists():
            logging.error(f"Provider configuration file not found at {self.providers_path} during reload.")
            return False

        try:
            with open(self.providers_path, 'r', encoding='utf-8') as f:
                raw_provider_list = json5.load(f)

            if not isinstance(raw_provider_list, list):
                logging.error(f"Invalid format in {self.providers_path.name}: Expected a list of provider entries.")
                return False

            potential_new_providers_config: Dict[str, ProviderDetails] = {}
            for item_dict in raw_provider_list:
                # Validate the structure of each item in the list using ProviderConfig
                # ProviderConfig expects a dict like {"provider_name": ProviderDetails_dict}
                validated_entry = ProviderConfig.model_validate(item_dict)
                
                # Extract the provider name and details
                # Since ProviderConfig ensures item_dict has one key after validation:
                provider_name = list(validated_entry.root.keys())[0]
                provider_details = validated_entry.root[provider_name] # This is already a ProviderDetails instance
                potential_new_providers_config[provider_name] = provider_details
            
            # Perform semantic validation on the successfully parsed and structurally validated providers
            if not self._perform_provider_semantic_validation(potential_new_providers_config, exit_on_error=False):
                logging.error(f"Semantic validation failed during reload of {self.providers_path.name}.")
                return False # Semantic validation failed (e.g., fallback provider missing)

            # If all validations pass, update the actual instance config
            self.providers_config = potential_new_providers_config
            logging.info(f"Successfully reloaded and validated providers from {self.providers_path}")
            logging.info(f"Reloaded providers: {list(self.providers_config.keys())}")
            return True

        except ValidationError as ve:
            logging.error(f"Validation error during reload of '{self.providers_path.name}': {ve.errors()}", exc_info=False)
            return False
        except Exception as e:
            logging.error(f"Failed to reload or validate '{self.providers_path.name}': {str(e)}", exc_info=True)
            return False

    def _validate_fallback_rules(self):
        """Performs post-load validation on fallback rules."""
        if not self.providers_config:
             # Ensure providers are loaded first if validation depends on them
             logging.warning("Providers not loaded yet. Loading providers before validating fallback rules.")
             self.load_providers()
             if not self.providers_config:
                 logging.error("Failed to load providers, cannot validate fallback rules.")
                 sys.exit(1)


        for gateway_model_name, config in self.fallback_rules.items():
            fallback_models = config.get("fallback_models", [])
            if not fallback_models:
                logging.error(f"Gateway model '{gateway_model_name}' must have at least one fallback model defined.")
                sys.exit(1)

            for fallback_model_rule in fallback_models:
                # Access dictionary keys directly now
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
