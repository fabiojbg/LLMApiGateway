import time
import logging
import uuid
import json
from fastapi import Request
from typing import Callable
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import Response

# Use a logger specific to this module
#logger = logging.getLogger(__name__)

class RequestLoggingMiddleware:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)

        request = Request(scope, receive)
        start_time = time.time()
        request_id = str(uuid.uuid4()) # Generate a unique ID for each request

        # Skip logging for health checks
        if request.url.path == "/health":
            return await self.app(scope, receive, send)

        logging.info(f"RequestLoggingMiddleware processing {request.method} {request.url.path}")
        # Log incoming request details
        logging.info(
            f"Incoming request | ID: {request_id} | Method: {request.method} | "
            f"Path: {request.url.path} | Client: {request.client.host if request.client else 'Unknown'}"
        )
        
        # Log request headers (masking sensitive info)
        sensitive_headers = {"authorization", "api-key", "x-api-key", "proxy-authorization"}
        masked_headers = {}
        for k, v in request.headers.items():
            if k.lower() in sensitive_headers:
                masked_headers[k] = "********"
            else:
                masked_headers[k] = v
        
        logging.info(f"Request Headers | ID: {request_id} | Headers: {masked_headers}")

        body_bytes = b""
        try:
            if "chat/completion" in request.url.path and request.method == "POST":
                body_bytes = await request.body()
                
                try:
                    payload = json.loads(body_bytes.decode("utf-8"))
                    if "messages" in payload:
                        payload["messages"] = "[MESSAGES EXCLUDED]"
                    if "tools" in payload:
                        payload["tools"] = "[TOOLS EXCLUDED]"
                    logging.info(f"Request Payload | ID: {request_id} | Payload: {json.dumps(payload, ensure_ascii=False)}")
                except json.JSONDecodeError:
                    # Ignore if the body is not a valid JSON
                    pass
        except Exception as e:
            logging.error(f"Error logging request payload | ID: {request_id} | Error: {str(e)}")

        # Create a custom receive to pass the body bytes downstream
        receive_called = False
        async def custom_receive():
            nonlocal receive_called
            if body_bytes and not receive_called:
                receive_called = True
                return {"type": "http.request", "body": body_bytes, "more_body": False}
            return await receive()

        status_code = 500
        async def custom_send(message):
            nonlocal status_code
            if message["type"] == "http.response.start":
                status_code = message.get("status", 500)
                headers = message.setdefault("headers", [])
                headers.append((b"x-request-id", request_id.encode("latin-1")))
            await send(message)

        try:
            await self.app(scope, custom_receive, custom_send)
            duration = round((time.time() - start_time) * 1000, 2)
            logging.info(f"Request completed | ID: {request_id} | Status: {status_code} | Duration: {duration}ms")
        except Exception as e:
            duration = round((time.time() - start_time) * 1000, 2)
            logging.error(f"Request failed | ID: {request_id} | Error: {str(e)} | Duration: {duration}ms", exc_info=True)
            raise e

# Keep the functional style middleware as well if preferred, but class-based is often cleaner
async def log_middleware_functional(request: Request, call_next: Callable):
    start_time = time.time()
    request_id = str(uuid.uuid4())

    if request.url.path == "/health":
        return await call_next(request)

    logging.info(f"Incoming request | ID: {request_id} | Method: {request.method} | Path: {request.url.path} | Client: {request.client.host if request.client else 'Unknown'}")

    # Log request headers (masking sensitive info)
    sensitive_headers = {"authorization", "api-key", "x-api-key", "proxy-authorization"}
    masked_headers = {
        k: ("********" if k.lower() in sensitive_headers else v)
        for k, v in request.headers.items()
    }
    logging.info(f"Request Headers | ID: {request_id} | Headers: {masked_headers}")

    try:
        response = await call_next(request)
        duration = round((time.time() - start_time) * 1000, 2)
        logging.info(f"Request completed | ID: {request_id} | Status: {response.status_code} | Duration: {duration}ms")
        # Add request ID header if it's a standard Response object
        if hasattr(response, "headers"):
             response.headers["X-Request-ID"] = request_id
    except Exception as e:
        duration = round((time.time() - start_time) * 1000, 2)
        logging.error(f"Request failed | ID: {request_id} | Error: {str(e)} | Duration: {duration}ms", exc_info=True)
        raise e

    return response
