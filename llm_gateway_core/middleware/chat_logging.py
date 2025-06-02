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
import threading
import queue
import time

logger = logging.getLogger(__name__)

def write_log(req_headers, req_body_str, llm_response_accum, tokens_usage):
    try:
        # Create log file with the required name format: "YY-MM-DD_HH:MM:ss:mmm.txt"
        log_time = datetime.now()
        filename = log_time.strftime("%Y-%m-%d_%H-%M-%S") + (".%03d" % (log_time.microsecond // 1000)) + ".txt"
        division_line = "-" * 100
        log_content = (
            f"{division_line}\nRequest Headers:\n{division_line}\n\n{pformat(req_headers, indent=2)}\n\n"
            f"{division_line}\nRequest Body:\n-{division_line}\n\n{req_body_str}\n\n"
            f"{division_line}\nTokens Usage:\n-{division_line}\n\n"
                f"Input: {tokens_usage['prompt_tokens']}\n"
                f"Output: {tokens_usage['completion_tokens']}\n"
                f"Cached: {tokens_usage['cached_tokens']}\n"
                f"Reasoning: {tokens_usage['reasoning_tokens']}\n"
                f"Total: {tokens_usage['total_tokens']}\n"
                f"Cost: ${tokens_usage['cost']:0.6f}\n\n"
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

class ChunkProcessorThread(threading.Thread):
    def __init__(self, req_headers, req_body_str):
        super().__init__()
        self.req_headers = req_headers
        self.req_body_str = req_body_str
        self.queue = queue.Queue()
        self.llm_response_accum = ""
        self.tokens_usage = {
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "total_tokens": 0,
            "reasoning_tokens": 0,
            "cached_tokens": 0,
            "cost": 0
        }
        self._stop_event = threading.Event()

    def run(self):
        while not self._stop_event.is_set() or self.queue.empty() is False:
            try:
                chunk = self.queue.get(timeout=5)  # wait max 5 seconds for a chunk before ending
            except queue.Empty:
                break

            try:
                chunks = [chunk_part for chunk_part in chunk.decode('utf-8').split("\n\n") if chunk_part.strip()]
                for decoded_chunk in chunks:
                    if not decoded_chunk.startswith("data: {") and \
                       not decoded_chunk.startswith("{"):  # ignore if it is not a json
                        continue

                    if decoded_chunk.startswith("data: "):
                        decoded_chunk = decoded_chunk[len('data: '):].strip()
                    chunk_json = json.loads(decoded_chunk)
                    if "choices" in chunk_json:
                        for choice in chunk_json["choices"]:
                            if "delta" in choice and "content" in choice["delta"]:
                                content_piece = choice["delta"]["content"]
                                if content_piece:
                                    self.llm_response_accum += content_piece
                            elif "message" in choice and "content" in choice["message"]:
                                content_piece = choice["message"]["content"]
                                if content_piece:
                                    self.llm_response_accum += content_piece
                    if "usage" in chunk_json:
                        self.tokens_usage = get_token_usage(chunk_json)

                    if "error" in chunk_json:
                        self.llm_response_accum += decoded_chunk
                        write_log(self.req_headers, self.req_body_str, self.llm_response_accum, self.tokens_usage)
            except Exception as ex:
                logging.error(f"ChatLogging: error processing chunk: {chunk}: {ex}", exc_info=True)
                pass  # errors here must be ignored so the chunk can be streamed

            self.queue.task_done()

        # After finishing processing all chunks, write the log file
        write_log(self.req_headers, self.req_body_str, self.llm_response_accum, self.tokens_usage)

    def enqueue_chunk(self, chunk):
        self.queue.put(chunk)

def _init_tokens_and_response():
    return "", {
        "prompt_tokens": 0,
        "completion_tokens": 0,
        "total_tokens": 0,
        "reasoning_tokens": 0,
        "cached_tokens": 0,
        "cost": 0
    }

async def log_chat_completions(request: Request, call_next: Callable) -> Response:
    # Only intercept the "/v1/chat/completions" endpoint
    if not request.url.path.endswith("/chat/completions"):
        return await call_next(request)

    try:
        # Capture request body and headers
        req_body_bytes = await request.body()
        req_body_str = req_body_bytes.decode("utf-8") if req_body_bytes else ""
        req_headers = dict(request.headers)
    except Exception as e:
        logger.error(f"Error capturing request body in log_chat middleware: {e}", exc_info=True)
        response = await call_next(request)
        return response

    response = await call_next(request)

    try:
        # If response is streaming, wrap its iterator to enqueue chunks for background processing
        if "StreamingResponse" in type(response).__name__ or isinstance(response, StreamingResponse):
            original_iterator = response.body_iterator

            first_chunk = True

            async def enqueueing_generator():
                async for chunk in original_iterator:
                    nonlocal first_chunk
                    if first_chunk : # create the thread to process the chunks
                        chunk_processor_thread = ChunkProcessorThread(req_headers, req_body_str)
                        chunk_processor_thread.start()
                        first_chunk = False

                    # Enqueue chunk for processing
                    chunk_processor_thread.enqueue_chunk(chunk)
                    # Yield chunk immediately for streaming
                    yield chunk

            response.body_iterator = enqueueing_generator()
        else:
            # For non-streaming responses, attempt to read full body content
            llm_response_accum, tokens_usage = _init_tokens_and_response()
            if hasattr(response, "body") and response.body:
                try:
                    response_data = json.loads(response.body.decode("utf-8"))
                    if "choices" in response_data and isinstance(response_data["choices"], list):
                        first = response_data["choices"][0]
                        if "message" in first and "content" in first["message"]:
                            llm_response_accum = first["message"]["content"]
                        if "usage" in response_data:
                            tokens_usage = get_token_usage(response_data)
                except Exception as ex:
                    logging.error(f"ChatLogging: error processing chunk: {response.body}: {ex}", exc_info=True)
            # Write log file immediately for non-streaming responses
            write_log(req_headers, req_body_str, llm_response_accum, tokens_usage)

    except Exception as e:
        logger.error(f"Error in log_chat_completions middleware: {e}", exc_info=True)

    return response

def get_token_usage(chunk_data):
    """
    Extracts token usage information from the chunk data.
    """
    tokens_usage = {
        "prompt_tokens": 0,
        "completion_tokens": 0,
        "total_tokens": 0,
        "reasoning_tokens" : 0,
        "cached_tokes": 0,
        "cost": 0
    }
    try:       
        if "usage" in chunk_data and isinstance(chunk_data["usage"], dict):
            usage = chunk_data["usage"]
            if "prompt_tokens" in usage:
                tokens_usage["prompt_tokens"] = usage["prompt_tokens"]
            if "completion_tokens" in usage:
                tokens_usage["completion_tokens"] = usage["completion_tokens"]
            if "total_tokens" in usage:
                tokens_usage["total_tokens"] = usage["total_tokens"]
            if "cost" in usage:
                tokens_usage["cost"] = usage["cost"]
            if "completion_tokens_details" in usage and \
            "reasoning_tokens" in usage["completion_tokens_details"]:
                tokens_usage["reasoning_tokens"] = usage["completion_tokens_details"]["reasoning_tokens"]
            if "prompt_tokens_details" in usage and \
            "cached_tokens" in usage["prompt_tokens_details"]:
                tokens_usage["cached_tokens"] = usage["prompt_tokens_details"]["cached_tokens"]

            if tokens_usage["reasoning_tokens"]>0:
                tokens_usage["completion_tokens"] = tokens_usage["completion_tokens"] - tokens_usage["reasoning_tokens"]
    except Exception as ex:
        logging.error(f"ChatLogging: error processing tokens usage: {ex}", exc_info=True)
        pass

    return tokens_usage
