import os
import json
import glob
from datetime import datetime
import logging
from pprint import pformat
from ..config.settings import settings
from fastapi import Request, Response
from fastapi.responses import StreamingResponse
from typing import Callable

logger = logging.getLogger(__name__)

def write_log(req_headers, req_body_str, llm_response_accum):
    try:
        # Create log file with the required name format: "YY-MM-DD_HH:MM:ss:mmm.txt"
        log_time = datetime.now()
        filename = log_time.strftime("%Y-%m-%d_%H-%M-%S") + (".%03d" % (log_time.microsecond // 1000)) + ".txt"
        division_line = "-" * 100
        log_content = (
            f"{division_line}\nRequest Headers:\n{division_line}\n\n{pformat(req_headers, indent=2)}\n\n"
            f"{division_line}\nRequest Body:\n-{division_line}\n\n{req_body_str}\n\n"
            f"{division_line}\nLLM Response:\n{division_line}\n\n{llm_response_accum}"
        )
        os.makedirs("logs", exist_ok=True)
        log_path = os.path.join("./logs", filename)
        
        # Write the new log file
        with open(log_path, "w", encoding="utf-8") as f:
            log_content = log_content.replace("\\n\\n", "\r\n\r\n").replace("\\n", "\r\n")  # replace the sequence \n inside json elements to make it more readable
            f.write(log_content)
        
        # Clean up old logs if over limit
        log_files = sorted(glob.glob(os.path.join("./logs", "*.txt")), key=os.path.getmtime)
        max_logs = settings.log_file_limit or 50
        while len(log_files) > max_logs:
            try:
                os.remove(log_files.pop(0))
            except Exception:
                pass
    except Exception as e:
        logger.error(f"Failed to write chat log: {e}", exc_info=True)


async def log_chat_completions(request: Request, call_next: Callable) -> Response:
    # Only intercept the "/v1/chat/completions" endpoint
    if not request.url.path.endswith("/chat/completions"):
        return await call_next(request)
    
    try:
        # Capture request body and headers
        req_body_bytes = await request.body()
        req_body_str = req_body_bytes.decode("utf-8") if req_body_bytes else ""
        req_headers = dict(request.headers)
        
        llm_response_accum = ""
    except Exception as e:    
        logger.error(f"Error capturing request body in log_chat middleware: {e}", exc_info=True)
        response = await call_next(request)
        return response
    
    response = await call_next(request)
    
    try:        
        # If response is streaming, wrap its iterator to accumulate LLM response content
        if "StreamingResponse" in type(response).__name__ or isinstance(response, StreamingResponse):
            original_iterator = response.body_iterator
            async def accumulated_generator():
                nonlocal llm_response_accum
                async for chunk in original_iterator:
                    try:
                        decoded_chunk = chunk.decode("utf-8").strip()
                        if decoded_chunk.startswith("data: ") or decoded_chunk.startswith("{"):
                            if decoded_chunk.startswith("{"):
                                chunks = [decoded_chunk]
                            else:
                                chunks = decoded_chunk.split("data: ")
                            for chunk_data in chunks:
                                try:
                                    data = json.loads(chunk_data.strip())
                                    if "choices" in data and isinstance(data["choices"], list):
                                        for choice in data["choices"]:
                                            if "delta" in choice and "content" in choice["delta"]:
                                                content_piece = choice["delta"]["content"]
                                                if content_piece:
                                                    llm_response_accum += content_piece
                                            else:
                                                if "message" in choice and "content" in choice["message"]:
                                                    content_piece = choice["message"]["content"]
                                                    if content_piece:
                                                        llm_response_accum += content_piece

                                    if "error" in data:
                                        llm_response_accum += decoded_chunk
                                        write_log(req_headers, req_body_str, llm_response_accum)
                                except:
                                    pass
                    except Exception:
                        pass
                    yield chunk
                # After streaming completes, write the log file
                write_log(req_headers, req_body_str, llm_response_accum)
            response.body_iterator = accumulated_generator()
        else:
            # For non-streaming responses, attempt to read full body content
            if hasattr(response, "body") and response.body:
                try:
                    response_data = json.loads(response.body.decode("utf-8"))
                    if "choices" in response_data and isinstance(response_data["choices"], list):
                        first = response_data["choices"][0]
                        if "message" in first and "content" in first["message"]:
                            llm_response_accum = first["message"]["content"]
                except Exception:
                    pass
            # Write log file immediately for non-streaming responses
            write_log(req_headers, req_body_str, llm_response_accum)
        
    except Exception as e:
        logger.error(f"Error in log_chat_completions middleware: {e}", exc_info=True)

    return response