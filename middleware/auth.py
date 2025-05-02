from fastapi import Request, HTTPException
from fastapi.security import APIKeyHeader
from settings import Settings

api_key_header = APIKeyHeader(name="Authorization", auto_error=False)

async def api_key_auth(request: Request, call_next):
    
    # Skip auth for health checks
    if request.url.path == "/health":
        return await call_next(request)

    # Get API key from header
    api_key = await api_key_header(request)
    if not api_key:
        raise HTTPException(
            status_code=401,
            detail="Missing API Key"
        )

    # Validate API key
    if api_key != f"Bearer {Settings.gateway_api_key}":
        raise HTTPException(
            status_code=403,
            detail="Invalid API Key"
        )

    return await call_next(request)
