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

# Load old provider mapping
provider_mapping = []
try:
    with open(Path(__file__).parent / "openrouter_provider_mapping.json") as f:
        provider_mapping = json.load(f)
except Exception as e:
    logging.warning(f"Failed to load openrouter_provider_mapping.json: {str(e)}")
    sys.exit(1)  # Exit if critical error occurs


# Load new provider mapping for v2
providers_config = {}
models_config = {}
try:
    mapping_path = Path(__file__).parent / "provider_mapping.json"
    if mapping_path.exists():
        with open(mapping_path) as f:
            full_mapping = json.load(f)
            # Normalize provider config into a dictionary for easy lookup
            providers_config = {
                list(p.keys())[0]: list(p.values())[0] 
                for p in full_mapping.get("providers", [])
            }
            # Normalize model routing rules into a dictionary
            models_config = {
                m["model"]: m["providers"] 
                for m in full_mapping.get("models", [])
            }
            logging.info(f"Successfully loaded provider mapping from {mapping_path}")
            # Log loaded provider names for verification
            logging.info(f"Loaded providers: {list(providers_config.keys())}")
            # Log loaded model rule keys for verification
            logging.info(f"Loaded model rules for: {list(models_config.keys())}")
    else:
        logging.warning(f"Provider mapping file not found at {mapping_path}")
except Exception as e:
    logging.error(f"Failed to load or parse provider_mapping.json: {str(e)}", exc_info=True)
    sys.exit(1)  # Exit if critical error occurs
    # Consider raising an error or exiting if mapping is critical
    providers_config = {}
    models_config = {}


# Initialize logging
configure_logging() # Ensure logging is configured before first use

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
    try:
        headers = {
            "Authorization": f"Bearer {settings.target_api_key}",
            "Content-Type": "application/json"
        }
        
        response = await client.get(
            f"{settings.target_server_url}/models",
            headers=headers
        )
        
        return response.json()
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

@app.post("/v1/chat/completions")
async def chat_completions(request: Request):
    try:
        headers = {
            "Authorization": f"Bearer {settings.target_api_key}",
            "Content-Type": "application/json"
        }
        
        # Forward the request body if present
        body = await request.body()
        
        body_str = body.decode('utf-8')
        try:
            body_json = json.loads(body_str)
            # Check if model exists in provider mapping and injection is enabled
            if settings.provider_injection_enabled and "model" in body_json:
                for mapping in provider_mapping:
                    if mapping["model"] == body_json["model"]:
                        body_json["provider"] = {"order": mapping["providers"]}
                        body_str = json.dumps(body_json)
                        body = body_str.encode('utf-8')
                        break
        except json.JSONDecodeError:
            print("Failed to decode JSON body: ", body_str)
            pass  # Maintain original behavior if JSON parsing fails
            
        # Check if client wants streaming
        is_streaming = json.loads(body_str).get("stream") is True

        if is_streaming:
            # Handle streaming response
            async def stream_generator():
                async with client.stream(
                    "POST",
                    f"{settings.target_server_url}/chat/completions",
                    headers=headers,
                    params=request.query_params,
                    content=body,
                    timeout=None
                ) as response:
                    response.raise_for_status()
                    async for chunk in response.aiter_bytes():
                        if b'"error"' in chunk:
                            print("Error in stream response: ", chunk)
                        yield chunk
            
            return StreamingResponse(
                stream_generator(),
                media_type="text/event-stream",
                headers={
                    "Transfer-Encoding": "chunked",
                    "X-Accel-Buffering": "no"
                }
            )
        else:
            # Handle normal response
            response = await client.post(
                f"{settings.target_server_url}/chat/completions",
                headers=headers,
                params=request.query_params,
                content=body
            )
            return response.json()            
        
    except Exception as e:
        print( "Error: " + str(e))
        raise HTTPException(
            status_code=500,
            detail=str(e)
        )


import copy # Added for deep copying request body

# --- Helper Function for making the actual request ---
async def make_request(target_url: str, headers: dict, payload: dict, is_streaming: bool):
    """Makes the downstream request and handles streaming/non-streaming responses."""
    first_chunk = True
    error_in_stream = False
    error_detail = None

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
                        if first_chunk:
                            first_chunk = False
                            # Check first chunk for error messages (common pattern)
                            try:
                                chunk_str = chunk.decode('utf-8')
                                if '"error"' in chunk_str or '"detail"' in chunk_str:
                                     # Attempt to parse as JSON to get detail
                                     try:
                                         error_json = json.loads(chunk_str.replace("data: ", "").strip())
                                         error_detail = error_json.get("error", {}).get("message") or error_json.get("detail")
                                     except:
                                         error_detail = chunk_str # Fallback to raw chunk
                                     logging.warning(f"Error detected in first stream chunk from {target_url}: {error_detail}")
                                     error_in_stream = True
                                     # Do not yield the error chunk, stop the generator
                                     return
                            except UnicodeDecodeError:
                                pass # Ignore if chunk is not valid UTF-8
                        
                        # Only yield non-empty chunks
                        if chunk: 
                            yield chunk
                        else:
                            # Optionally log that an empty chunk was received and skipped
                            print(f"Skipping empty chunk received from {target_url}")
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
                # Yield the first chunk if it was successfully retrieved
                if not first_chunk and not error_in_stream: # first_chunk is False if priming succeeded
                    yield first_yield
                # Yield the rest
                async for chunk in gen:
                    yield chunk

            return StreamingResponse(
                combined_generator(),
                media_type="text/event-stream",
                headers={"Transfer-Encoding": "chunked", "X-Accel-Buffering": "no"}
            ), None
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


# --- V2 Endpoint ---
@app.post("/v2/chat/completions")
async def chat_completions_v2(request: Request):
    try:
        request_body_bytes = await request.body()
        request_body_json = json.loads(request_body_bytes.decode('utf-8'))
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

    logging.info(f"Received v2 request for model: {requested_model}, streaming: {is_streaming}")

    # 1. Find Routing Rule or Use Fallback
    provider_sequence = models_config.get(requested_model)
    if not provider_sequence:
        logging.warning(f"No specific rule found for model '{requested_model}'. Using fallback provider.")
        fallback_provider_name = settings.fallback_provider
        if not fallback_provider_name:
            logging.error("Fallback provider requested but FALLBACK_PROVIDER environment variable is not set.")
            raise HTTPException(status_code=500, detail="Fallback provider not configured")
        
        if fallback_provider_name not in providers_config:
             logging.error(f"Fallback provider '{fallback_provider_name}' not found in providers configuration.")
             raise HTTPException(status_code=500, detail=f"Configured fallback provider '{fallback_provider_name}' is invalid.")

        # Construct a sequence containing only the fallback provider rule
        # The structure mimics the rule format: [{ "provider_name": {} }]
        provider_sequence = [{fallback_provider_name: {}}] 
        logging.info(f"Using fallback provider: {fallback_provider_name}")
    else:
         logging.info(f"Found routing rule for model '{requested_model}'. Provider sequence length: {len(provider_sequence)}")


    # 2. Iterate Through Providers and Attempt Requests
    last_error_detail = "No providers were attempted."
    for provider_rule in provider_sequence:
        provider_name = list(provider_rule.keys())[0]
        provider_rule_details = provider_rule[provider_name] # Contains modelname, providers_order, or models

        logging.info(f"Attempting provider: {provider_name}")

        provider_config = providers_config.get(provider_name)
        if not provider_config:
            logging.error(f"Configuration missing for provider '{provider_name}' specified in routing rule for model '{requested_model}'. Skipping.")
            last_error_detail = f"Configuration missing for provider '{provider_name}'"
            continue # Skip to the next provider in the main sequence

        base_url = provider_config.get("baseUrl")
        api_key_env_var = provider_config.get("apikey")
        is_multiple_models = provider_config.get("multiple_models", False)

        if not base_url:
             logging.error(f"Configuration for provider '{provider_name}' is missing 'baseUrl'. Skipping.")
             last_error_detail = f"Configuration for provider '{provider_name}' is missing 'baseUrl'"
             continue

        api_key = os.getenv(api_key_env_var) if api_key_env_var else None
        # Note: Some providers might not require a key or use other auth methods handled by headers
        if not api_key and api_key_env_var:
             logging.warning(f"API key environment variable '{api_key_env_var}' for provider '{provider_name}' is not set. Proceeding without Authorization header.")
             # Decide if this should be a hard error or just a warning
             # continue # Uncomment to make missing keys a hard stop for that provider

        headers = {
            "Content-Type": "application/json",
            # Add Authorization header only if api_key is present
            **({"Authorization": f"Bearer {api_key}"} if api_key else {})
        }
        
        target_url = f"{base_url.rstrip('/')}/chat/completions" # Ensure single slash

        # --- Handle Different Provider Types ---
        
        # Case 1: Provider with sub-provider ordering (e.g., OpenRouter)
        if "providers_order" in provider_rule_details:
            sub_providers = provider_rule_details.get("providers_order", [])
            target_model = provider_rule_details.get("modelname", requested_model) # Use specific modelname if provided
            logging.info(f"Provider '{provider_name}' uses sub-provider ordering. Target model: {target_model}. Order: {sub_providers}")
            
            if not sub_providers:
                 logging.warning(f"Provider '{provider_name}' has 'providers_order' key but the list is empty. Skipping.")
                 last_error_detail = f"Provider '{provider_name}' has empty 'providers_order'"
                 continue

            for sub_provider in sub_providers:
                logging.info(f"Attempting sub-provider: {sub_provider} via {provider_name}")
                payload = copy.deepcopy(request_body_json)
                payload["model"] = target_model # Override model
                
                # Add provider ordering info to the request (specific to providers like OpenRouter)
                # This might need adjustment based on how the target provider expects this info (headers vs body)
                payload["provider"] = {"order": [sub_provider]} # Assuming it goes in the body based on old v1 logic
                payload["allow_fallbacks"] = False

                print("Payload for sub-provider: ", payload) # Debugging line

                # Make the request for this specific sub-provider
                response_data, error_detail = await make_request(target_url, headers, payload, is_streaming)
                
                if response_data:
                    logging.info(f"Success with sub-provider '{sub_provider}' via '{provider_name}'")
                    return response_data # Success! Return the response.
                else:
                    logging.warning(f"Failed attempt with sub-provider '{sub_provider}' via '{provider_name}'. Error: {error_detail}")
                    last_error_detail = f"Sub-provider '{sub_provider}' via '{provider_name}' failed: {error_detail}"
                    # Continue to the next sub-provider in the inner loop

            # If all sub-providers failed, continue to the next main provider in the outer loop
            logging.warning(f"All sub-providers for '{provider_name}' failed.")
            continue 

        # Case 2: Provider with multiple models list (e.g., Requesty)
        elif is_multiple_models and "models" in provider_rule_details:
            target_models = provider_rule_details.get("models", [])
            logging.info(f"Provider '{provider_name}' uses multiple models list. Models: {target_models}")

            if not target_models:
                 logging.warning(f"Provider '{provider_name}' is marked 'multiple_models' but 'models' list is empty or missing in rule. Skipping.")
                 last_error_detail = f"Provider '{provider_name}' has empty 'models' list"
                 continue

            for model_to_try in target_models:
                logging.info(f"Attempting model: {model_to_try} via {provider_name}")
                payload = copy.deepcopy(request_body_json)
                payload["model"] = model_to_try # Override model for this attempt
                
                # Make the request for this specific model
                response_data, error_detail = await make_request(target_url, headers, payload, is_streaming)

                if response_data:
                    logging.info(f"Success with model '{model_to_try}' via '{provider_name}'")
                    return response_data # Success! Return the response.
                else:
                    logging.warning(f"Failed attempt with model '{model_to_try}' via '{provider_name}'.\r\n" \
                                    f"Error: {error_detail}\r\n" \
                                    f"Target Url: {target_url}\r\n" \
                                    f"Payload: {payload}")
                    
                    last_error_detail = f"Model '{model_to_try}' via '{provider_name}' failed: {error_detail}"
                    # Continue to the next model in the inner loop
            
            # If all models failed, continue to the next main provider in the outer loop
            logging.warning(f"All models for '{provider_name}' failed.")
            continue

        # Case 3: Standard Provider (or fallback)
        else:
            target_model = provider_rule_details.get("modelname", requested_model) # Use specific modelname if provided, else original
            logging.info(f"Attempting standard provider '{provider_name}' with target model: {target_model}")
            payload = copy.deepcopy(request_body_json)
            payload["model"] = target_model # Override model if needed

            # Make the request
            response_data, error_detail = await make_request(target_url, headers, payload, is_streaming)

            if response_data:
                logging.info(f"Success with standard provider '{provider_name}'")
                return response_data # Success! Return the response.
            else:
                logging.warning(f"Failed attempt with model '{target_model}' via '{provider_name}'.\r\n" \
                                f"Error: {error_detail}\r\n" \
                                f"Target Url: {target_url}\r\n" \
                                f"Payload: {payload}")
                last_error_detail = f"Provider '{provider_name}' failed: {error_detail}"
                # Continue to the next provider in the outer loop
                continue

    # 3. If all providers failed
    logging.error(f"All providers failed for model '{requested_model}'. Last error: {last_error_detail}")
    raise HTTPException(status_code=503, detail=f"All configured providers failed. Last error: {last_error_detail}")


if __name__ == "__main__":
    import uvicorn
    from config import settings
    uvicorn.run(
        app, 
        host="0.0.0.0", 
        port=settings.gateway_port, # not working, must be defined in the command line with --port parameter
        log_level="debug",
    )
