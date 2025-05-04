import logging
import json5
import copy
import asyncio
import os
from fastapi import APIRouter, Request, HTTPException
from fastapi.responses import StreamingResponse

# Relative imports from the new structure
from ...config.loader import ConfigLoader
from ...config.settings import settings
from ...db.model_rotation_db import ModelRotationDB
from ...services.request_handler import make_llm_request

logger = logging.getLogger(__name__)

# Initialize dependencies needed for this router
# These might be better handled via dependency injection in a more complex setup
config_loader = ConfigLoader()
providers_config = config_loader.load_providers()
fallback_rules = config_loader.load_fallback_rules()
model_rotation_db = ModelRotationDB() # Instantiate DB access

router = APIRouter()

@router.post("/completions")
async def chat_completions(request: Request):
    try:
        request_body_bytes = await request.body()
        request_body_json = json5.loads(request_body_bytes.decode('utf-8'))
        
        payload_to_log = copy.deepcopy(request_body_json)
        payload_to_log["messages"] = "<REMOVED>" # Remove messages from payload for logging
        logging.debug(f"/v1/chat/completions: Request for model \'{payload_to_log['model']}\'. Payload: {payload_to_log}") # Log the payload without messages
    except Exception as e:
        logging.error(f"Error reading request body: {str(e)}", exc_info=True)
        raise HTTPException(status_code=400, detail=f"Error reading request body: {str(e)}")

    requested_model = request_body_json.get("model")
    is_streaming = request_body_json.get("stream", False)

    if not requested_model:
        raise HTTPException(status_code=400, detail="Missing 'model' in request body")

    # 1. Find Routing Rule or Use Fallback
    model_config = fallback_rules.get(requested_model)
    if not model_config:
        logging.warning(f"No specific fallback sequence found for model '{requested_model}'. Using '{settings.fallback_provider}' fallback provider.")

        model_fallbacks_sequence = [{"provider": settings.fallback_provider, "model": requested_model}] # Use the fallback provider as a single-item sequence
        rotate_models = False
        logging.info(f"Using fallback provider: {settings.fallback_provider}")
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

        provider_name = model_fallback_rule.get("provider")
        provider_model = model_fallback_rule.get("model")
        retry_delay = model_fallback_rule.get("retry_delay")
        retry_count = model_fallback_rule.get("retry_count") or 0
        subproviders_ordering = model_fallback_rule.get("providers_order") # openrouter support for subproviders ordering

        logging.info(f"Attempting  model '{requested_model}' in provider: {provider_name} for subproviders ordering: {subproviders_ordering}")

        provider_config = providers_config.get(provider_name)

        provider_base_url = provider_config.baseUrl
        api_key_env_var = provider_config.apikey
        provider_api_key = os.getenv(api_key_env_var)

        # Note: Some providers might not require a key or use other auth methods handled by headers
        if not provider_api_key and api_key_env_var:
             logging.warning(f"API key environment variable '{api_key_env_var}' for provider '{provider_name}' is not set. Proceeding without Authorization header.")

        headers = {
            "Content-Type": "application/json",
            "HTTP-Referer": "https://github.com/fabiojbg/LLMApiGateway",
            "X-Title": "LLMGateway",
            # Add Authorization header only if api_key is present
            **({"Authorization": f"Bearer {provider_api_key}"} if provider_api_key else {})
        }
        
        target_url = f"{provider_base_url.rstrip('/')}/chat/completions" # Ensure single slash

        # --- Handle Different Provider Types ---
        
        while retry_count >= 0:
            # Case 1: Standard Provider (or fallback)
            if not subproviders_ordering or len(subproviders_ordering) <= 0 or model_fallback_rule["use_provider_order_as_fallback"]== False: 

                logging.info(f"Attempting model '{provider_model}' in provider: '{provider_name}'")
                payload = copy.deepcopy(request_body_json)
                payload["model"] = provider_model # Override model if needed

                # Make the request
                response_data, error_detail = await make_llm_request(target_url, headers, payload, is_streaming)
                #response_data = None # for debugging only
                #error_detail = 'test error' # for debugging only

                if response_data and error_detail is None:
                    logging.info(f"Connection success to model '{provider_model}' in provider '{provider_name}'. Starting streaming response...")
                    return response_data # Success! Return the response.
                else:
                    payload["messages"] = "<REMOVED>" # Remove messages from payload for logging
                    logging.warning(f"Failed attempt with model '{provider_model}' via '{provider_name}'.\r\n" \
                                    f"Error: {error_detail}\r\n" \
                                    f"Target Url: {target_url}\r\n" \
                                    f"Payload: {payload}")
                    last_error_detail = f"Model {provider_model} failed with provider '{provider_name}': {error_detail}"
                    logging.debug(f"Continuing to next provider after attempt failed for '{provider_model}' in '{provider_name}'.") # Added log

            # Case 2: Provider with sub-provider ordering (e.g., OpenRouter). Call each sub-provider in order instead of letting this to openrouter
            else:
                logging.info(f"Provider '{provider_name}' uses sub-provider ordering. Target model: {provider_model}. Order: {subproviders_ordering}")
                
                for sub_provider in subproviders_ordering:
                    logging.info(f"Attempting model '{provider_model}' on sub-provider: '{sub_provider}' in '{provider_name}'")
                    payload = copy.deepcopy(request_body_json)
                    payload["model"] = provider_model # real provider model name
                    
                    # Add provider ordering info to the request (specific to providers like OpenRouter)
                    payload["provider"] = {"order": [sub_provider]} # Assuming it goes in the body based on old v1 logic
                    payload["allow_fallbacks"] = False

                    # Make the request for this specific sub-provider
                    
                    response_data, error_detail = await make_llm_request(target_url, headers, payload, is_streaming)
                    #response_data = None # for debugging only
                    #error_detail = 'test error' # for debugging only

                        
                    if response_data and error_detail is None:
                        logging.info(f"Connection success with model '{provider_model}' in provider '{provider_name}' via '{sub_provider}'. Starting streaming response...")
                        return response_data # Success! Return the response.
                    else:
                        logging.warning(f"Failed attempt with model '{provider_model}' via '{provider_name}' and subprovider '{sub_provider}'.\r\n" \
                                        f"Error: {error_detail}\r\n" \
                                        f"Target Url: {target_url}\r\n" \
                                        f"Payload: {payload}")
                        last_error_detail = f"Model '{provider_model}' failed from provider '{provider_name}' and sub-provider {sub_provider} : {error_detail}"
                        # Continue to the next sub-provider in the inner loop

                # If all sub-providers failed, continue to the next main provider in the outer loop
                logging.warning(f"All sub-providers for '{provider_name}' failed.")

            if retry_count > 0 and retry_delay>0 and retry_delay<120:
                logging.info(f"RETRYING {provider_model} in {retry_delay} seconds... {retry_count-1} attempts left.")
                await asyncio.sleep(retry_delay)
            retry_count -= 1

    # 3. If all providers failed
    logging.error(f"All providers failed for model '{requested_model}'. Last error: {last_error_detail}")
    raise HTTPException(status_code=503, detail=f"All configured providers failed for model '{requested_model}'. Last error: {last_error_detail}")

# Example of how to potentially add other endpoints to this router
# @router.get("/some_other_chat_endpoint")
# async def some_other_chat_endpoint():
#     return {"message": "Another chat endpoint"}
