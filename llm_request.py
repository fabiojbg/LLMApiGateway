from fastapi.responses import StreamingResponse
import httpx
import logging
import json5
import copy # Added for deep copying request body

# --- Helper Function for making the actual request ---
async def make_llm_request(target_url: str, headers: dict, payload: dict, is_streaming: bool):
    """Makes the downstream request and handles streaming/non-streaming responses."""
    first_chunk = True
    error_in_stream = False
    error_detail = None

    client = httpx.AsyncClient(timeout=httpx.Timeout(300.0, connect=60.0)) 
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
                        try:
                            # Decode chunk to check content
                            chunk_str = chunk.decode('utf-8')

                            # Check if this chunk should be ignored for 'first chunk' error check
                            if chunk_str.startswith(": OPENROUTER PROCESSING"): # treat OpenRouter initial and not usefull chunks as ignored
                                logging.debug(f"Ignoring dummy chunk: {chunk_str[:1000]}...")
                                continue # Process next chunk

                            # If it's not an ignored chunk AND we are still looking for the first *real* chunk
                            if first_chunk:
                                first_chunk = False # Mark that we've found the first *real* chunk
                                logging.debug(f"Processing first *real* chunk from {target_url}: {chunk_str[:1000]}...")
                                # Check this first *real* chunk for error messages
                                if '"error"' in chunk_str or '"detail"' in chunk_str:
                                     try:
                                         # Attempt to parse as JSON to get detail
                                         error_json = json5.loads(chunk_str.replace("data: ", "").strip())
                                         error_detail = error_json.get("error", {}).get("message") or error_json.get("detail")
                                     except Exception as json_e: # Catch specific JSON errors
                                         logging.warning(f"Failed to parse potential error JSON in first chunk: {json_e}. Falling back to raw chunk.")
                                         error_detail = chunk_str # Fallback to raw chunk
                                     logging.warning(f"Error detected in first *real* stream chunk from {target_url}: {error_detail}")
                                     error_in_stream = True
                                     return # Stop the generator, do not yield the error chunk

                        except UnicodeDecodeError:
                            logging.warning(f"Could not decode chunk from {target_url} as UTF-8. Skipping content check for this chunk.")
                            if first_chunk:
                                pass # Keep first_chunk = True until a decodable, non-ignored chunk arrives

                        # Yield the current chunk if it's not empty (and wasn't an error chunk that caused a return)
                        if chunk:
                            yield chunk
                        else: 
                            logging.debug(f"Skipping empty chunk received from {target_url}")                           


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
                    logging.debug(f"Yielding first chunk from {target_url}: {first_yield[:1000]}...")  
                    yield first_yield
                # Yield the rest
                async for chunk in gen:
                    try:
                        chunk_str = chunk.decode('utf-8')
                        if chunk_str.startswith("data:") and '"code":' in chunk_str : # try if is an error chunk(openrouter)
                            # Attempt to parse as JSON to get detail
                            try:
                                error_json = json5.loads(chunk_str.replace("data: ", "").strip())
                                error_detail = error_json.get("error", {}).get("message") or error_json.get("detail")
                            except:
                                error_detail = chunk_str # Fallback to raw chunk
                            logging.warning(f"Error detected in stream chunk from {target_url}: {error_detail}")
                            error_in_stream = True
                            error_detail = chunk_str
                    except:
                        logging.warning(f"Could not decode chunk from {target_url} as UTF-8. Skipping content check for this chunk.")
                        
                    logging.debug(f"Yielding chunk from {target_url}: {chunk[:1000]}...")  
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
            except json5.JSONDecodeError as json_err:
                 # Handle cases where the response is not valid JSON despite a 2xx status
                 error_detail = f"Invalid JSON response from {target_url}: {response.text[:1000]}..."
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
