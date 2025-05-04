from fastapi import Request, HTTPException
from fastapi.security import APIKeyHeader
from settings import settings

api_key_header = APIKeyHeader(name="Authorization", auto_error=False)

from fastapi.responses import JSONResponse
from fastapi import status

async def api_key_auth(request: Request, call_next):
    
    # Skip auth for health checks
    if request.url.path == "/health":
        return await call_next(request)

    try:
        # Get API key from header
        api_key = await api_key_header(request)
        if not api_key:
            raise HTTPException(
                status_code=401,
                detail="Missing API Key"
            )

        # Validate API key
        if api_key != f"Bearer {settings.gateway_api_key}":
            raise HTTPException(
                status_code=403,
                detail="Invalid API Key"
            )

        response = await call_next(request)
        return response

    except HTTPException as exc:
        return JSONResponse(
            status_code=exc.status_code,
            content={"detail": exc.detail}
        )
