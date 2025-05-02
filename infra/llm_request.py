import httpx
import logging
import json
from typing import Optional, Tuple, Any
from fastapi.responses import StreamingResponse
import copy

class LLMRequest:
    @staticmethod
    async def execute(client: httpx.AsyncClient, target_url: str, headers: dict, payload: dict, is_streaming: bool) -> Tuple[Optional[Any], Optional[str]]:
        """Makes the downstream request and handles streaming/non-streaming responses."""
        looking_first_chunk = True
        error_in_stream = False
        error_detail = None

        payload_to_log = copy.deepcopy(payload)
        payload_to_log["messages"] = "<REMOVED>" # Remove messages from payload for logging
        logging.debug(f"LLMRequest.execute(): Sending request for model \'{payload_to_log['model']}\'. Payload: {payload_to_log}") # Log the payload without messages
        try:
            if is_streaming:
                async def stream_generator():
                    nonlocal looking_first_chunk, error_in_stream, error_detail
                    async with client.stream("POST", target_url, headers=headers, json=payload, timeout=None) as response:
                        # Check initial status code for non-2xx errors before streaming
                        if response.status_code >= 400:
                            error_detail = await response.aread()
                            error_detail = error_detail.decode('utf-8')
                            logging.info("--------------HTTP RESPONSE ERROR ----------------------")
                            logging.error(f"Downstream error {response.status_code} from {target_url}: {error_detail}")
                            error_in_stream = True # Mark error to prevent further processing
                            return # Stop the generator

                        # Waits first *real* chunk to verify if there is an error (the intial chunks of openrouter are not useful)
                        async for chunk in response.aiter_bytes():
                            chunk_str = None
                            try:
                                # Decode chunk to check content
                                chunk_str = chunk.decode('utf-8')

                                # Check if this chunk should be ignored for 'first chunk' error check
                                if chunk_str.startswith(":"): # stream comment -> ignore
                                    logging.debug(f"Ignoring comment chunk for first_chunk check: {chunk_str[:100]}...")
                                    continue # Process next chunk

                                # If it's not an ignored chunk AND we are still looking for the first *real* chunk
                                if looking_first_chunk:
                                    looking_first_chunk = False # Mark that we've found the first *real* chunk
                                    logging.debug(f"Processing first *real* chunk from {target_url}: {chunk_str[:100]}...")
                                    has_error = None
                                    # Check for errors within the first stream chunk (e.g., OpenRouter error format)
                                    if chunk_str.startswith("data:"):
                                        try:
                                            error_detail_json = json.loads(chunk_str.replace("data: ", "").strip())
                                            has_error = error_detail_json.get("error", {}).get("message")
                                        except Exception as json_parse_exception:
                                            logging.warning(f"Failed to parse potential error JSON in first chunk: {json_parse_exception}.")
                                        if has_error:
                                            logging.error(f"--------------- FIRST CHUNK ERROR ----------------------")
                                            logging.error(f"Error detected in first stream chunk from {target_url}: {error_detail_json}")
                                            error_in_stream = True
                                            # Don't yield the error chunk itself, let the calling function handle the error signal
                                            return # Stop the generator on error                                   

                            except UnicodeDecodeError:
                                # If chunk is not UTF-8, we can't check its content.
                                logging.error(f"Could not decode chunk from {target_url} as UTF-8. Skipping content check for this chunk.")
                                if looking_first_chunk:
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
                except StopAsyncIteration:
                    if error_in_stream:
                        return None, error_detail # Signal error
                    pass # Continue to return the (now exhausted) generator below

                if error_in_stream:
                    return None, error_detail # Signal error based on check within generator

                # If no immediate error, return the (potentially primed) generator
                async def combined_generator():
                    nonlocal error_in_stream, error_detail # Ensure error_detail can be modified
                    if not looking_first_chunk and not error_in_stream: # first_chunk is False if priming succeeded
                        logging.debug(f"Yielding first chunk from {target_url}: {first_yield[:400]}...")  
                        yield first_yield

                    async for chunk in gen:
                        logging.debug(f"Yielding chunk from {target_url}: {chunk[:400]}...")  
                        try:
                            chunk_str = chunk.decode('utf-8')
                            # Check for errors within the stream (e.g., OpenRouter error format)
                            if chunk_str.startswith("data:"):
                                has_error = None
                                try:
                                    error_detail_json = json.loads(chunk_str.replace("data: ", "").strip())
                                    has_error = error_detail_json.get("error", {}).get("message")
                                except Exception as json_parse_exception:
                                    logging.warning(f"Failed to parse potential error JSON: {json_parse_exception}.")
                                if has_error:
                                    logging.error(f"--------------- CHUNK ERROR ----------------------")
                                    logging.error(f"Error detected in stream chunk from {target_url}: {error_detail_json}")
                                    error_in_stream = True
                                    # Don't yield the error chunk itself, let the calling function handle the error signal
                                    return # Stop the generator on error
                        except UnicodeDecodeError:
                            logging.warning(f"Could not decode chunk from {target_url} as UTF-8 during combined generation.")
                            pass

                            yield chunk 

                # After the combined_generator finishes (or is stopped by return), check error_in_stream
                # This check seems redundant here as errors should be handled by returning None, error_detail below
                # Let's rely on the return value check after calling combined_generator

                # Return the StreamingResponse *only if* no error was detected during priming or streaming
                if not error_in_stream:
                    return StreamingResponse(
                        combined_generator(),
                        media_type="text/event-stream",
                        headers={"Transfer-Encoding": "chunked", "X-Accel-Buffering": "no"}
                    ), None # Signal success
                else:
                    return None, error_detail # Signal error

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
                    error_detail = response_json.get("error", {}).get("message")
                    if error_detail:
                        logging.warning(f"Error detected in non-stream response from {target_url}: {response_json}")
                        return None, error_detail # Signal error
                    
                    return response_json, None # Success
                except json.JSONDecodeError as json_err:
                    error_detail = f"Invalid JSON response from {target_url}: {response_json}..."
                    logging.error(error_detail, exc_info=True)
                    return None, error_detail # Signal error

        except httpx.RequestError as e:
            error_detail = f"RequestError connecting to {target_url}: {str(e)}"
            logging.error(error_detail, exc_info=True)
            return None, error_detail # Signal error
        except Exception as e:
            error_detail = f"Unexpected error during request to {target_url}: {str(e)}"
            logging.error(error_detail, exc_info=True)
            return None, error_detail # Signal error
