import os
import json
from datetime import datetime
from pprint import pformat
from fastapi import Request, Response
from fastapi.responses import StreamingResponse
from typing import Callable

def write_log(req_headers, req_body_str, llm_response_accum):
    # Create log file with the required name format: "YY-MM-DD_HH:MM:ss:mmm.txt"
    log_time = datetime.now()
    filename = log_time.strftime("%Y-%m-%d_%H-%M-%S") + (".%03d" % (log_time.microsecond // 1000)) + ".txt"
    log_content = (
        f"-----------------\nRequest Headers:\n-----------------\n\n{pformat(req_headers, indent=2)}\n\n"
        f"-----------------\nRequest Body:\n-----------------\n\n{req_body_str}\n\n"
        f"-----------------\nLLM Response:\n-----------------\n\n{llm_response_accum}"
    )
    os.makedirs("logs", exist_ok=True)
    with open(os.path.join(".\\logs", filename), "w", encoding="utf-8") as f:
        f.write(log_content)

async def log_chat_completions(request: Request, call_next: Callable) -> Response:
    # Only intercept the "/v1/chat/completions" endpoint
    if request.url.path != "/v1/chat/completions":
        return await call_next(request)
    
    # Capture request body and headers
    req_body_bytes = await request.body()
    req_body_str = req_body_bytes.decode("utf-8") if req_body_bytes else ""
    req_headers = dict(request.headers)
    
    llm_response_accum = ""
    
    response = await call_next(request)
    
    # If response is streaming, wrap its iterator to accumulate LLM response content
    if isinstance(response, StreamingResponse):
        original_iterator = response.body_iterator
        async def accumulated_generator():
            nonlocal llm_response_accum
            async for chunk in original_iterator:
                try:
                    decoded_chunk = chunk.decode("utf-8")
                    if decoded_chunk.startswith("data: "):
                        json_part = decoded_chunk[6:].strip()
                    else:
                        json_part = decoded_chunk
                    data = json.loads(json_part)
                    if "choices" in data and isinstance(data["choices"], list):
                        for choice in data["choices"]:
                            if "delta" in choice and "content" in choice["delta"]:
                                content_piece = choice["delta"]["content"]
                                if content_piece:
                                    llm_response_accum += content_piece
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
    
    return response
