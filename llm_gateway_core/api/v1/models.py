import logging
import os
import httpx
import json5
from fastapi import APIRouter, HTTPException

# Relative imports from the new structure
from ...config.loader import ConfigLoader
from ...config.settings import settings

logger = logging.getLogger(__name__)

# Initialize dependencies needed for this router
config_loader = ConfigLoader()
providers_config = config_loader.load_providers()
fallback_rules = config_loader.load_fallback_rules()

# Initialize HTTP client (consider sharing a client instance across the app via dependency injection later)
http_client = httpx.AsyncClient(timeout=httpx.Timeout(60.0, connect=10.0)) # Shorter timeout for models endpoint

router = APIRouter()

@router.get("/asOpenCode")
async def get_models_as_opencode(includefallback: bool = False):
    """
    Returns a JSON compatible with opencode.json for configuring this gateway as a provider.
    """
    # Call the existing get_models to get the list
    models_data = await get_models()
    
    opencode_models = {}
    for model_info in models_data.get("data", []):
        model_id = model_info.get("id")
        if not model_id:
            continue
            
        # If includefallback is False, we only keep models defined in our fallback_rules (local models)
        if not includefallback and model_id not in fallback_rules:
            continue
            
        # Try to extract context and output limits
        context_length = 400000
        max_completion_tokens = 32000
        
        top_provider = model_info.get("top_provider", {})
        if "context_length" in top_provider and top_provider["context_length"] is not None:
            context_length = top_provider["context_length"]
        if "max_completion_tokens" in top_provider and top_provider["max_completion_tokens"] is not None:
            max_completion_tokens = top_provider["max_completion_tokens"]
            
        opencode_models[model_id] = {
            "name": model_info.get("name", model_id),
            "limit": {
                "context": context_length,
                "output": max_completion_tokens
            }
        }
        
    api_key = settings.gateway_api_key or "12345678"
    
    return {
        "$schema": "https://opencode.ai/config.json",
        "provider": {
            "llm-gateway-local": {
                "npm": "@ai-sdk/openai-compatible",
                "name": "LLM Gateway (local)",
                "options": {
                    "baseURL": f"http://localhost:{settings.gateway_port}/v1",
                    "apiKey": api_key,
                    "headers": {
                        "Authorization": f"Bearer {api_key}"
                    }
                },
                "models": opencode_models
            }
        }
    }

@router.get("") # Route relative to the prefix defined in v1/__init__.py
async def get_models():
    """
    Returns a combined list of models available through the gateway's
    routing rules and the configured fallback provider.
    """
    gateway_models = {} # Use dict to avoid duplicates easily
    # 1. Add models defined in the gateway's fallback rules
    for model_name in fallback_rules.keys():
        gateway_models[model_name] = {
            "id": model_name,
            "object": "model",
            "owned_by": "llmgateway" # Indicate it's available via the gateway rules
        }

    # 2. Fetch and add models from the fallback provider
    fallback_provider_name = settings.fallback_provider
    if not fallback_provider_name:
        logger.warning("No fallback_provider configured in settings. Skipping fallback provider models list.")
    else:
        fallback_provider_config = providers_config.get(fallback_provider_name)
        if not fallback_provider_config:
            logger.error(f"Configuration error: Fallback provider '{fallback_provider_name}' not found in providers config.")
            # Proceed without fallback models, or raise an internal error? For now, proceed.
        else:
            fallback_provider_base_url = fallback_provider_config.baseUrl
            fallback_provider_api_key_env_var = fallback_provider_config.apikey

            if not fallback_provider_base_url:
                logger.error(f"Configuration error: 'baseUrl' missing for fallback provider '{fallback_provider_name}'.")
            else:
                fallback_provider_api_key = os.getenv(fallback_provider_api_key_env_var) if fallback_provider_api_key_env_var else None
                if not fallback_provider_api_key and fallback_provider_api_key_env_var:
                    logger.warning(f"API key env var '{fallback_provider_api_key_env_var}' for fallback provider '{fallback_provider_name}' not set.")

                headers = {
                    "Content-Type": "application/json",
                    **({"Authorization": f"Bearer {fallback_provider_api_key}"} if fallback_provider_api_key else {})
                }
                target_url = f"{fallback_provider_base_url.rstrip('/')}/models" # Standard OpenAI path

                try:
                    logger.info(f"Fetching models list from fallback provider '{fallback_provider_name}' at {target_url}")
                    response_fallback = await http_client.get(target_url, headers=headers)

                    # Check for downstream errors
                    if response_fallback.status_code >= 400:
                        error_text = response_fallback.text
                        logger.warning(f"Downstream error {response_fallback.status_code} fetching models from {target_url}: {error_text[:500]}...")
                        # Don't raise immediately, allow gateway models to still be returned
                    else:
                        # Attempt to parse JSON and merge models
                        try:
                            fallback_models_data = response_fallback.json()
                            if isinstance(fallback_models_data.get("data"), list):
                                for model_info in fallback_models_data["data"]:
                                    model_id = model_info.get("id")
                                    if model_id and model_id not in gateway_models: # Add only if not already defined by gateway rules
                                        # Add provider info for clarity
                                        model_info["owned_by"] = model_info.get("owned_by", fallback_provider_name)
                                        model_info["source_provider"] = fallback_provider_name
                                        gateway_models[model_id] = model_info
                                logger.info(f"Successfully merged models from fallback provider '{fallback_provider_name}'.")
                            else:
                                logger.warning(f"Unexpected format in response from {target_url}. 'data' field missing or not a list.")

                        except (json5.JSONDecodeError, ValueError) as json_err: # Use standard json or ValueError
                            logger.error(f"Invalid JSON response fetching models from {target_url}: {response_fallback.text[:500]}...", exc_info=True)

                except httpx.RequestError as e:
                    logger.error(f"RequestError fetching models from fallback provider {target_url}: {e}", exc_info=True)
                except Exception as e:
                     logger.error(f"Unexpected error fetching models from fallback provider {target_url}: {e}", exc_info=True)


    # 3. Format final response
    # Separate gateway rule models (from fallback_rules) and fallback provider models
    gateway_rule_models = [info for model_id, info in gateway_models.items() if model_id in fallback_rules]
    
    fallback_provider_models = sorted(
        [info for model_id, info in gateway_models.items() if model_id not in fallback_rules],
        key=lambda x: x['id']
    )
    # Gateway rule models first, then fallback provider models
    response_list = gateway_rule_models + fallback_provider_models
    return {
        "object": "list",
        "data": response_list
    }

# Consider adding a shutdown event to close the httpx client if it's managed here
# @router.on_event("shutdown")
# async def shutdown_event():
#     await http_client.aclose()
