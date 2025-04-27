# ///script
# dependencies = ["fastapi", "httpx", "python-dotenv", 
#                 "pydantic", "uvicorn", "python-json-logger"]
# ///
from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import StreamingResponse
from fastapi.middleware.cors import CORSMiddleware
import httpx
import os
from typing import Optional
import logging
from logging.config import dictConfig
from pydantic import BaseModel
from middleware.logging import log_middleware
from middleware.chat_logging import log_chat_completions
from middleware.auth import api_key_auth
from config import settings, configure_logging
import json
from pathlib import Path
import sys
import asyncio # Added for potential delays/retries if needed later
import copy # Added for deep copying request body
from db.model_rotation import ModelRotationDB
from config_loader import FallbackModelRule, ProviderDetails # Import corrected for type hints

# Initialize logging
configure_logging() # Ensure logging is configured before first use

# Initialize model rotation database
model_rotation_db = ModelRotationDB()

# Initialize configuration loader
from config_loader import ConfigLoader
config_loader = ConfigLoader()
providers_config = config_loader.load_providers()
fallback_rules = config_loader.load_fallback_rules()
    
# Initialize FastAPI
app = FastAPI()

# Add middleware
app.middleware("http")(log_middleware)
app.middleware("http")(api_key_auth)
if settings.log_chat_messages:
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
        fallback_provider_name = settings.fallback_provider
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
            # Add Authorization header only if api_key is present
            **({"Authorization": f"Bearer {provider_api_key}"} if provider_api_key else {})
        }
        
        target_url = f"{provider_base_url.rstrip('/')}/chat/completions" # Ensure single slash

        # --- Handle Different Provider Types ---
        
        # Case 1: Provider with sub-provider ordering (e.g., OpenRouter). Call each sub-provider in order instead of letting this to openrouter
        if subproviders_ordering and len(subproviders_ordering) > 0: 
            logging.info(f"Provider '{provider_name}' uses sub-provider ordering. Target model: {provider_model}. Order: {subproviders_ordering}")
            
            for sub_provider in subproviders_ordering:
                logging.info(f"Attempting sub-provider: {sub_provider} via {provider_name} for {provider_model}")
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

            # Make the request
            response_data, error_detail = await make_llm_request(target_url, headers, payload, is_streaming)
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


# --- Helper Function for making the actual request ---
async def make_llm_request(target_url: str, headers: dict, payload: dict, is_streaming: bool):
    """Makes the downstream request and handles streaming/non-streaming responses."""
    first_chunk = True
    error_in_stream = False
    error_detail = None

    payload_to_log = copy.deepcopy(payload)
    payload_to_log["messages"] = "<REMOVED>" # Remove messages from payload for logging
    logging.debug(f"make_llm_request(): Sending request for model \'{payload_to_log['model']}\'. Payload: {payload_to_log}") # Log the payload without messages
    try:
        if is_streaming:
            async def stream_generator():
                nonlocal first_chunk, error_in_stream, error_detail
                async with client.stream("POST", target_url, headers=headers, json=payload, timeout=None) as response:
                    # Check initial status code for non-2xx errors before streaming
                    if response.status_code >= 400:
                         error_detail = await response.aread()
                         error_detail = error_detail.decode('utf-8')
                         logging.error(f"Downstream error {response.status_code} from {target_url}: {error_detail}")
                         error_in_stream = True # Mark error to prevent further processing
                         # Do not raise here, let the outer function handle failover
                         return # Stop the generator

                    # Stream the response
                    async for chunk in response.aiter_bytes():
                        chunk_str = None
                        try:
                            # Decode chunk to check content
                            chunk_str = chunk.decode('utf-8')

                            # Check if this chunk should be ignored for 'first chunk' error check
                            if chunk_str.startswith(": OPENROUTER PROCESSING"): # treat OpenRouter initial and not usefull chunks as ignored
                                logging.debug(f"Ignoring chunk for first_chunk check: {chunk_str[:100]}...")
                                # Yield the chunk but skip the first_chunk logic below
                                #if chunk:
                                #    yield chunk
                                continue # Process next chunk

                            # If it's not an ignored chunk AND we are still looking for the first *real* chunk
                            if first_chunk:
                                first_chunk = False # Mark that we've found the first *real* chunk
                                logging.debug(f"Processing first *real* chunk from {target_url}: {chunk_str[:100]}...")
                                # Check this first *real* chunk for error messages
                                if '"error"' in chunk_str or '"detail"' in chunk_str:
                                     try:
                                         # Attempt to parse as JSON to get detail
                                         error_json = json.loads(chunk_str.replace("data: ", "").strip())
                                         error_detail = error_json.get("error", {}).get("message") or error_json.get("detail")
                                     except Exception as json_e: # Catch specific JSON errors
                                         logging.warning(f"Failed to parse potential error JSON in first chunk: {json_e}. Falling back to raw chunk.")
                                         error_detail = chunk_str # Fallback to raw chunk
                                     logging.warning(f"Error detected in first *real* stream chunk from {target_url}: {error_detail}")
                                     error_in_stream = True
                                     return # Stop the generator, do not yield the error chunk

                        except UnicodeDecodeError:
                            # If chunk is not UTF-8, we can't check its content.
                            # If we were still looking for the first chunk, we can't check this one.
                            # We'll proceed, but log it. The first *decodable* non-ignored chunk will be checked.
                            logging.warning(f"Could not decode chunk from {target_url} as UTF-8. Skipping content check for this chunk.")
                            if first_chunk:
                                # We can't check this as the first chunk, but we need to eventually set first_chunk to False.
                                # Let's assume it's not an error chunk and proceed.
                                # The *next* decodable, non-ignored chunk will become the 'first_chunk' to check.
                                # Alternatively, we could set first_chunk = False here, meaning we miss checking this undecodable one.
                                # Let's stick to checking the first *decodable* non-ignored chunk.
                                pass # Keep first_chunk = True until a decodable, non-ignored chunk arrives

                        # Yield the current chunk if it's not empty (and wasn't an error chunk that caused a return)
                        if chunk:
                            yield chunk
                        else: 
                            logging.debug(f"Skipping empty chunk received from {target_url}")
                            pass


            # Check for error *before* returning the StreamingResponse
            gen = stream_generator()
            # Need to 'prime' the generator to catch immediate errors like status code errors
            try:
                first_yield = await gen.__anext__()
                # If we got here, the first chunk (or status code) was okay (or it was empty)
            except StopAsyncIteration:
                 # Generator finished immediately, likely due to an error detected before first yield
                 if error_in_stream:
                     return None, error_detail # Signal error
                 # Or it could be a genuinely empty successful stream                 
                 pass # Continue to return the (now exhausted) generator below

            if error_in_stream:
                 return None, error_detail # Signal error based on check within generator

            # If no immediate error, return the (potentially primed) generator
            async def combined_generator():
                nonlocal error_in_stream
                # Yield the first chunk if it was successfully retrieved
                if not first_chunk and not error_in_stream: # first_chunk is False if priming succeeded
                    logging.debug(f"Yielding first chunk from {target_url}: {first_yield[:200]}...")  
                    yield first_yield
                # Yield the rest
                async for chunk in gen:
                    logging.debug(f"Yielding chunk from {target_url}: {chunk[:200]}...")  
                    chunk_str = chunk.decode('utf-8')
                    if chunk_str.startswith("data:") and '"code":' in chunk_str : # try if is an error chunk(openrouter)
                            # Attempt to parse as JSON to get detail
                            try:
                                error_json = json.loads(chunk_str.replace("data: ", "").strip())
                                error_detail = error_json.get("error", {}).get("message") or error_json.get("detail")
                            except:
                                error_detail = chunk_str # Fallback to raw chunk
                            logging.warning(f"Error detected in stream chunk from {target_url}: {error_detail}")
                            error_in_stream = True
                            error_detail = chunk_str

                    yield chunk

            return StreamingResponse(
                combined_generator(),
                media_type="text/event-stream",
                headers={"Transfer-Encoding": "chunked", "X-Accel-Buffering": "no"}
            ), error_detail
        else:
            # Non-streaming request
            response = await client.post(target_url, headers=headers, json=payload, timeout=None)
            
            # Check for HTTP errors
            if response.status_code >= 400:
                error_detail = response.text
                logging.warning(f"Downstream error {response.status_code} from {target_url}: {error_detail}")
                return None, error_detail # Signal error

            # Check for errors in the JSON response body
            try:
                response_json = response.json()
                if "error" in response_json or "detail" in response_json:
                     error_detail = response_json.get("error", {}).get("message") or response_json.get("detail")
                     logging.warning(f"Error detected in non-stream response from {target_url}: {error_detail}")
                     return None, error_detail # Signal error
                return response_json, None # Success
            except json.JSONDecodeError as json_err:
                 # Handle cases where the response is not valid JSON despite a 2xx status
                 error_detail = f"Invalid JSON response from {target_url}: {response.text[:100]}..."
                 logging.error(error_detail, exc_info=True)
                 return None, error_detail # Signal error

    except httpx.RequestError as e:
        # Handle network errors, timeouts, etc.
        error_detail = f"RequestError connecting to {target_url}: {str(e)}"
        logging.error(error_detail, exc_info=True)
        return None, error_detail # Signal error
    except Exception as e:
        # Catch unexpected errors during request processing
        error_detail = f"Unexpected error during request to {target_url}: {str(e)}"
        logging.error(error_detail, exc_info=True)
        return None, error_detail # Signal error

if __name__ == "__main__":
    import uvicorn
    from config import settings
    uvicorn.run(
        app, 
        host="0.0.0.0", 
        port=settings.gateway_port, # not working, must be defined in the command line with --port parameter
        log_level="debug",
    )
