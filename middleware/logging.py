import time
import logging
from fastapi import Request
from typing import Callable
from fastapi.responses import StreamingResponse

logger = logging.getLogger(__name__)

async def log_middleware(request: Request, call_next: Callable):
    start_time = time.time()
    
    # Skip logging for health checks
    if request.url.path == "/health":
        return await call_next(request)
    
    # Log request
    request_id = request.headers.get("X-Request-ID", "none")
    logger.info({
        "message": "Incoming request",
        "method": request.method,
        "path": request.url.path,
        "request_id": request_id,
        "client": request.client.host if request.client else None
    })

    try:
        response = await call_next(request)
    except Exception as e:
        logger.error({
            "message": "Request failed",
            "error": str(e),
            "request_id": request_id,
            "duration": round((time.time() - start_time) * 1000, 2)
        })
        raise

    # Handle streaming response differently
    if isinstance(response, StreamingResponse):
        return response

    # Log response
    logger.info({
        "message": "Request completed",
        "method": request.method,
        "path": request.url.path,
        "status_code": response.status_code,
        "request_id": request_id,
        "duration": round((time.time() - start_time) * 1000, 2)
    })

    return response
