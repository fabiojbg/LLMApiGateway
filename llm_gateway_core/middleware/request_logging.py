import time
import logging
import uuid
from fastapi import Request
from typing import Callable
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import Response

# Use a logger specific to this module
logger = logging.getLogger(__name__)

class RequestLoggingMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        start_time = time.time()
        request_id = str(uuid.uuid4()) # Generate a unique ID for each request

        # Skip logging for health checks
        if request.url.path == "/health":
            return await call_next(request)

        # Log incoming request details
        logger.info(
            f"Incoming request | ID: {request_id} | Method: {request.method} | "
            f"Path: {request.url.path} | Client: {request.client.host if request.client else 'Unknown'}"
        )
        # Optionally log headers (be careful with sensitive info)
        # logger.debug(f"Request Headers | ID: {request_id} | Headers: {dict(request.headers)}")

        try:
            response = await call_next(request)
            duration = round((time.time() - start_time) * 1000, 2) # Calculate duration in ms

            # Log outgoing response details
            logger.info(
                f"Request completed | ID: {request_id} | Status: {response.status_code} | Duration: {duration}ms"
            )
            # Add request ID to response headers
            response.headers["X-Request-ID"] = request_id

        except Exception as e:
            duration = round((time.time() - start_time) * 1000, 2)
            logger.error(
                f"Request failed | ID: {request_id} | Error: {str(e)} | Duration: {duration}ms",
                exc_info=True # Include traceback for errors
            )
            # Re-raise the exception so FastAPI's exception handling can take over
            raise e

        return response

# Keep the functional style middleware as well if preferred, but class-based is often cleaner
async def log_middleware_functional(request: Request, call_next: Callable):
    start_time = time.time()
    request_id = str(uuid.uuid4())

    if request.url.path == "/health":
        return await call_next(request)

    logger.info(f"Incoming request | ID: {request_id} | Method: {request.method} | Path: {request.url.path} | Client: {request.client.host if request.client else 'Unknown'}")

    try:
        response = await call_next(request)
        duration = round((time.time() - start_time) * 1000, 2)
        logger.info(f"Request completed | ID: {request_id} | Status: {response.status_code} | Duration: {duration}ms")
        # Add request ID header if it's a standard Response object
        if hasattr(response, "headers"):
             response.headers["X-Request-ID"] = request_id
    except Exception as e:
        duration = round((time.time() - start_time) * 1000, 2)
        logger.error(f"Request failed | ID: {request_id} | Error: {str(e)} | Duration: {duration}ms", exc_info=True)
        raise e

    return response
