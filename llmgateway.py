from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import StreamingResponse
from fastapi.middleware.cors import CORSMiddleware
import httpx
import os
from typing import Optional, Dict, Any
import logging
from logging.config import dictConfig
from pydantic import BaseModel
from middleware.logging import log_middleware
from middleware.chat_logging import log_chat_completions
from middleware.auth import api_key_auth
from config import configure_logging
import json
from pathlib import Path
import sys
import asyncio # Added for potential delays/retries if needed later
import copy # Added for deep copying request body
from db.model_rotation import ModelRotationDB
from config_loader import FallbackModelRule, ProviderDetails # Import corrected for type hints
from infra.llm_request import LLMRequest
from config_loader import ConfigLoader
from settings import Settings
from chat_logging import write_log_complete

# Initialize logging
configure_logging()

# Initialize model rotation database
model_rotation_db = ModelRotationDB()

# Initialize configuration loader
config_loader = ConfigLoader()
providers_config = config_loader.load_providers()
fallback_rules = config_loader.load_fallback_rules()
    
app = FastAPI()

# Add middleware
app.middleware("http")(log_middleware)
app.middleware("http")(api_key_auth)
if Settings.log_chat_messages:
    app.middleware("http")(log_chat_completions)

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# HTTP client
# Increased default timeout
client = httpx.AsyncClient(timeout=httpx.Timeout(300.0, connect=60.0)) 

@app.get("/v1/models")
async def get_models(): 
    """Returns the list of models available in the gateway with the models in the fallback provider"""
    try:
        response = {}
        response["object"] = "list"
        response["data"] = [{"id": model_name, "object": "model", "owned_by": "llmgateway"} for model_name in fallback_rules.keys()]
        
        # call fallback provider /models and append it to the response
        fallback_provider_name = Settings.fallback_provider
        fallback_provider_config: Optional[ProviderDetails] = providers_config.get(fallback_provider_name)
        if not fallback_provider_config:
            logging.error(f"Fallback provider '{fallback_provider_name}' configuration not found.")
            raise HTTPException(status_code=500, detail=f"Configuration error: Fallback provider '{fallback_provider_name}' not found.")
        
        # Correctly access attributes of the ProviderDetails object
        fallback_provider_base_url = fallback_provider_config.baseUrl 
        fallback_provider_api_key_env_var = fallback_provider_config.apikey
        fallback_provider_api_key = os.getenv(fallback_provider_api_key_env_var) if fallback_provider_api_key_env_var else None
        headers = {
            "Content-Type": "application/json",
            **({"Authorization": f"Bearer {fallback_provider_api_key}"} if fallback_provider_api_key else {})
        }
        target_url = f"{fallback_provider_base_url.rstrip('/')}/models"
        logging.info(f"Calling fallback provider '{fallback_provider_name}' for models list from {target_url}")
        response_from_fallback = await client.get(target_url, headers=headers, timeout=None)
        if response_from_fallback.status_code >= 400:
            logging.warning(f"Downstream error {response_from_fallback.status_code} from {target_url}: {response_from_fallback.text}")
            raise HTTPException(status_code=response_from_fallback.status_code, detail=response_from_fallback.text)
        #continue if no error
        try:
            response_from_fallback_json = response_from_fallback.json()
            if "error" in response_from_fallback_json or "detail" in response_from_fallback_json:
                error_detail = response_from_fallback_json.get("error", {}).get("message") or response_from_fallback_json.get("detail")
                logging.warning(f"Error detected in non-stream response from {target_url}: {error_detail}")
                raise HTTPException(status_code=500, detail=error_detail)
            # Append the models from the fallback provider to the response
            for model in response_from_fallback_json["data"]:
                if model["id"] not in [m["id"] for m in response["data"]]:
                    response["data"].append(model)
        except json.JSONDecodeError as json_err:
            logging.error(f"Invalid JSON response from {target_url}: {response_from_fallback.text[:100]}...")
            raise HTTPException(status_code=500, detail=f"Invalid JSON response from {target_url}: {response_from_fallback.text[:100]}...")

        return response
    except httpx.HTTPStatusError as e:
        raise HTTPException(
            status_code=e.response.status_code,
            detail=e.response.text
        )
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=str(e)
        )

# --- V2 Endpoint ---
@app.post("/v1/chat/completions")
async def chat_completions(request: Request):
    try:
        request_body_bytes = await request.body()
        request_body_json = json.loads(request_body_bytes.decode('utf-8'))
        
        payload_to_log = copy.deepcopy(request_body_json)
        payload_to_log["messages"] = "<REMOVED>" # Remove messages from payload for logging
        logging.debug(f"/v2/chat/completions: Request for model \'{payload_to_log['model']}\'. Payload: {payload_to_log}") # Log the payload without messages
    except json.JSONDecodeError:
        logging.error("Failed to decode request body JSON", exc_info=True)
        raise HTTPException(status_code=400, detail="Invalid JSON body")
    except Exception as e:
        logging.error(f"Error reading request body: {str(e)}", exc_info=True)
        raise HTTPException(status_code=400, detail=f"Error reading request body: {str(e)}")

    requested_model = request_body_json.get("model")
    is_streaming = request_body_json.get("stream", False)

    if not requested_model:
        raise HTTPException(status_code=400, detail="Missing 'model' in request body")

    # 1. Find Routing Rule or Use Fallback
    # model_config is a dictionary loaded from fallback_rules.json, not a ModelFallbackConfig object
    model_config: Optional[Dict[str, Any]] = fallback_rules.get(requested_model) 
    if not model_config:
        logging.warning(f"No specific fallback sequence found for model '{requested_model}'. Using '{Settings.fallback_provider}' fallback provider.")

        model_fallbacks_sequence = [{"provider": Settings.fallback_provider, "model": requested_model}] # Use the fallback provider as a single-item sequence
        rotate_models = False
        logging.info(f"Using fallback provider: {Settings.fallback_provider}")
    else:
        model_fallbacks_sequence = model_config["fallback_models"]
        rotate_models = model_config["rotate_models"]
        logging.info(f"Found routing rule for model '{requested_model}'. Provider sequence length: {len(model_fallbacks_sequence)}")
        logging.info(f"Model rotation is {'enabled' if rotate_models else 'disabled'} for model '{requested_model}'")

    # Get API key from request headers
    api_key = request.headers.get("Authorization", "").replace("Bearer ", "")

    # If model rotation is enabled, determine the starting index
    start_index = 0
    if rotate_models and len(model_fallbacks_sequence) > 1:
        start_index = model_rotation_db.get_next_model_index(
            api_key=api_key,
            gateway_model=requested_model,
            total_models=len(model_fallbacks_sequence)
        )
        logging.info(f"Model rotation: Starting with model index {start_index} for '{requested_model}'")

    # Reorder the sequence to start from the selected index if rotation is enabled
    if rotate_models and len(model_fallbacks_sequence) > 1:
        # Create a new sequence starting from the selected index
        reordered_sequence = model_fallbacks_sequence[start_index:] + model_fallbacks_sequence[:start_index]
        model_fallbacks_sequence = reordered_sequence


    # 2. Iterate Through Providers and Attempt Requests
    last_error_detail = "No providers were attempted."
    for model_fallback_rule in model_fallbacks_sequence:

        # Access dictionary keys instead of attributes for fallback rules
        provider_name = model_fallback_rule["provider"]
        provider_model = model_fallback_rule["model"]
        subproviders_ordering = model_fallback_rule.get("providers_order") # Use .get() for optional field

        logging.info(f"Attempting provider: {provider_name} for model '{requested_model}' and subproviders ordering: {subproviders_ordering}")

        provider_config: Optional[ProviderDetails] = providers_config.get(provider_name) # Accessing the dict is correct here
        if not provider_config:
            logging.error(f"Configuration for provider '{provider_name}' not found. Skipping.")
            last_error_detail = f"Configuration for provider '{provider_name}' not found."
            continue

        provider_base_url = provider_config.baseUrl
        api_key_env_var = provider_config.apikey
        provider_api_key = os.getenv(api_key_env_var)

        # Note: Some providers might not require a key or use other auth methods handled by headers
        if not provider_api_key and api_key_env_var:
             logging.warning(f"API key environment variable '{api_key_env_var}' for provider '{provider_name}' is not set. Proceeding without Authorization header.")

        headers = {
            "Content-Type": "application/json",
            "X-Title": "LLMGateway",
            "HTTP-Referer": "https://github.com/fabiojbg/LLMApiGateway",
            # Add Authorization header only if api_key is present
            **({"Authorization": f"Bearer {provider_api_key}"} if provider_api_key else {})
        }
        
        target_url = f"{provider_base_url.rstrip('/')}/chat/completions" # Ensure single slash

        # --- Handle Different Provider Types ---
        
        # Case 1: Provider with sub-provider ordering (e.g., OpenRouter). Call each sub-provider in order instead of letting this to openrouter
        if subproviders_ordering and len(subproviders_ordering) > 0 and model_fallback_rule["use_provider_order_as_fallback"]== True: 
            logging.info(f"Provider '{provider_name}' uses sub-provider ordering. Target model: {provider_model}. Order: {subproviders_ordering}")
            
            for sub_provider in subproviders_ordering:
                logging.info(f"Attempting sub-provider: {sub_provider} via {provider_name} for {provider_model}")
                payload = copy.deepcopy(request_body_json)
                payload["model"] = provider_model # real provider model name                
                # Add provider ordering info to the request (specific to providers like OpenRouter)
                if provider_name == "openrouter":
                    payload["provider"] = {"order": [sub_provider]} # Assuming it goes in the body based on old v1 logic
                    payload["allow_fallbacks"] = False
                    additional_params = model_fallback_rule.get("additional_payload_params", {})
                    if additional_params:
                        for key, value in additional_params.items():
                            payload[key] = value

                # Make the request for this specific sub-provider                
                response_data, error_detail = await LLMRequest.execute(client, target_url, headers, payload, is_streaming)
                #response_data = None # for debugging only
                #error_detail = 'test error' # for debugging only

                if response_data and error_detail is None:
                    logging.info(f"Connection success with provider '{provider_name}' via '{sub_provider}' for model '{provider_model}'. Starting streaming response...")
                    return response_data # Success! Return the response.
                else:
                    logging.warning(f"Failed attempt with sub-provider '{sub_provider}' via '{provider_name}'. Error: {error_detail}")
                    logging.warning(f"Failed attempt with model '{provider_model}' via '{provider_name}' and subprovider '{sub_provider}'.\r\n" \
                                    f"Error: {error_detail}\r\n" \
                                    f"Target Url: {target_url}\r\n" \
                                    f"Payload: {payload}")
                    last_error_detail = f"Provider '{provider_name}' failed via sub-provider {sub_provider}: {error_detail}"
                    # Continue to the next sub-provider in the inner loop

            # If all sub-providers failed, continue to the next main provider in the outer loop
            logging.warning(f"All sub-providers for '{provider_name}' failed.")
            continue

        # Case 2: Standard Provider (or fallback)
        else:
            logging.info(f"Attempting standard provider '{provider_name}' with target model: {provider_model}")
            payload = copy.deepcopy(request_body_json)
            payload["model"] = provider_model # Override model if needed
            if provider_name == "openrouter" :
                if subproviders_ordering and len(subproviders_ordering) > 0:
                    payload["provider"] = {"order": subproviders_ordering} 
                    payload["allow_fallbacks"] = False
                additional_params = model_fallback_rule.get("additional_payload_params", {})
                if additional_params:
                    for key, value in additional_params.items():
                        payload[key] = value

            # Make the request
            response_data, error_detail = await LLMRequest.execute(client, target_url, headers, payload, is_streaming)
            #response_data = None # for debugging only
            #error_detail = 'test error' # for debugging only

            if response_data and error_detail is None:
                logging.info(f"Connection success with provider '{provider_name}' for model '{provider_model}'. Starting streaming response...")
                return response_data # Success! Return the response.
            else:
                payload["messages"] = "<REMOVED>" # Remove messages from payload for logging
                logging.warning(f"Failed attempt with model '{provider_model}' via '{provider_name}'.\r\n" \
                                f"Error: {error_detail}\r\n" \
                                f"Target Url: {target_url}\r\n" \
                                f"Payload: {payload}")
                last_error_detail = f"Provider '{provider_name}' failed: {error_detail}"
                logging.debug(f"Continuing to next main provider after standard attempt failed for '{provider_name}'.") # Added log
                # Continue to the next provider in the outer loop
                continue

    # 3. If all providers failed
    logging.error(f"All providers failed for model '{requested_model}'. Last error: {last_error_detail}")
    raise HTTPException(status_code=503, detail=f"All configured providers failed for model '{requested_model}'. Last error: {last_error_detail}")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        app, 
        host="0.0.0.0", 
        port=Settings.gateway_port, 
        log_level="debug",
    )
