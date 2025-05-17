from fastapi.responses import StreamingResponse
import httpx
import logging
import json5
import copy 

# --- Helper Function for making the actual request ---
async def make_llm_request(target_url: str, headers: dict, payload: dict, is_streaming: bool):
    """Makes the downstream request and handles streaming/non-streaming responses."""
    looking_first_chunk = True
    error_in_stream = False
    error_detail = None
    tokens_usage = None

    client = httpx.AsyncClient(timeout=httpx.Timeout(300.0, connect=60.0)) 
    payload_to_log = copy.deepcopy(payload)
    payload_to_log["messages"] = "<REMOVED>" # Remove messages from payload for logging
    logging.debug(f"make_llm_request(): Sending request for model \'{payload_to_log['model']}\'. Payload: {payload_to_log}") # Log the payload without messages
    try:
        if is_streaming:
            async def stream_generator():
                nonlocal looking_first_chunk, error_in_stream, error_detail, tokens_usage
                async with client.stream("POST", target_url, headers=headers, json=payload, timeout=None) as response:
                    # Check initial status code for non-2xx errors before streaming
                    if response.status_code >= 400:
                         error_detail = await response.aread()
                         error_detail = error_detail.decode('utf-8')
                         logging.error(f"Downstream error {response.status_code} from {target_url}: {error_detail}")
                         error_in_stream = True 
                         return # Stop the generator

                    # Stream the response
                    async for chunk in response.aiter_bytes():
                        try:
                            chunks =  [chunk_part for chunk_part in chunk.decode('utf-8').split("\n\n") if chunk_part.strip()] 
                            for chunk_str in chunks:
                                if not chunk_str.startswith("data: {"): 
                                    logging.debug(f"Passing dummy chunk through: {chunk_str[:1000]}...")
                                    continue

                                if looking_first_chunk:
                                    looking_first_chunk = False 
                                    logging.debug(f"Processing first *real* chunk from {target_url}: {chunk_str[:1000]}...")
                                    chunk_json = json5.loads(chunk_str[len("data: "):])
                                    if "error" in chunk_json or "detail" in chunk_json:
                                        error_detail = chunk_str 
                                        error_in_stream = True
                                        logging.warning(f"Error detected in first *real* stream chunk from {target_url}: {error_detail}")
                                        return 

                        except UnicodeDecodeError:
                            logging.warning(f"Could not decode chunk from {target_url} as UTF-8. Skipping content check for this chunk.")
                            if looking_first_chunk:
                                pass 

                        if chunk:
                            yield chunk
                        else: 
                            logging.debug(f"Skipping empty chunk received from {target_url}")                           

            gen = stream_generator()
            first_content_chunk_candidate = None
            # Prime until the first real data chunk
            while True:
                try:
                    chunk = await gen.__anext__()
                except StopAsyncIteration:
                    break
                try:
                    parts = [p for p in chunk.decode('utf-8').split("\n\n") if p.strip()]
                    real_found = False
                    for part in parts:
                        if part.startswith("data: {"):
                            real_found = True
                            data_json = json5.loads(part[len("data: "):])
                            if "error" in data_json or "detail" in data_json:
                                error_detail = part
                                error_in_stream = True
                            else:
                                first_content_chunk_candidate = chunk
                            break
                    if real_found:
                        break
                except UnicodeDecodeError:
                    continue

            if error_in_stream:
                return None, error_detail

            async def combined_generator():
                nonlocal error_in_stream, error_detail

                # Yield the first real data chunk
                if first_content_chunk_candidate is not None:
                    logging.debug(f"Yielding first real chunk from {target_url}: {first_content_chunk_candidate[:1000]}...")
                    yield first_content_chunk_candidate
                    # Yield the rest
                async for chunk in gen:
                    try:
                        chunks =  [chunk_part for chunk_part in chunk.decode('utf-8').split("\n\n") if chunk_part.strip()] 
                        if( len(chunks) > 1):
                            logging.debug(f"Multi chunks received {target_url}: {chunk[:1000]}...")  

                        for chunk_str in chunks:
                            if not chunk_str.startswith("data: {"):
                                continue
                            chunk_json = json5.loads(chunk_str[len("data: "):])
                            if "code" in chunk_json : # try if is an error chunk(openrouter)
                                # Attempt to parse as JSON to get detail
                                try:
                                    error_detail = chunk_json.get("error", {}).get("message") or chunk_json.get("detail")
                                except:
                                    error_detail = chunk_str # Fallback to raw chunk
                                logging.warning(f"Error detected in stream chunk from {target_url}: {error_detail}")
                                error_in_stream = True
                                error_detail = chunk_str

                            if "usage" in chunk_json:
                                tokens_usage = chunk_json.get("usage")

                    except:
                        logging.warning(f"Could not decode chunk from {target_url} as UTF-8. Skipping content check for this chunk.")
                        
                    logging.debug(f"Yielding chunk from {target_url}: {chunk[:1000]}...")  
                    yield chunk

                logging.debug(f"Finished streaming from {target_url}. Token Usage: {tokens_usage if tokens_usage else ''}")

            return StreamingResponse(
                combined_generator(),
                media_type="text/event-stream",
                headers={"Transfer-Encoding": "chunked", "X-Accel-Buffering": "no"}
            ), error_detail
        
        else:
            serialized_payload = json5.dumps(payload).encode("utf-8")
            # Non-streaming request
            response = await client.post(target_url, headers=headers, content=serialized_payload, timeout=None)
            logging.debug(f"Response received from {target_url}")
            
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
