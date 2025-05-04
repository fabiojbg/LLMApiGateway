import logging # <-- Add logging import
from fastapi import Request, HTTPException, status
from fastapi.security import APIKeyHeader
from fastapi.responses import JSONResponse
# Import settings from the new config location
from ..config.settings import settings

api_key_header = APIKeyHeader(name="Authorization", auto_error=False)

async def api_key_auth(request: Request, call_next):
    """
    FastAPI middleware to authenticate requests using an API key in the Authorization header.
    """
    logging.debug(f"INCOMING REQUEST: {request.method} {request.url.path}") # <-- Log incoming request

    # Skip auth for health checks or other public endpoints
    if request.url.path == "/health" or \
       request.url.path.endswith("/models"):
        response = await call_next(request)
        return response

    try:
        auth_header = await api_key_header(request)
        if not auth_header:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Missing or invalid Authorization header (Bearer token expected)"
            )

        api_key = auth_header.split("Bearer ")[1]

        # Validate API key against the one loaded from settings
        if settings.gateway_api_key and api_key != settings.gateway_api_key:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Invalid API Key"
            )
        elif not settings.gateway_api_key:
            # If no gateway_api_key is set in the environment, log a warning
            # and potentially allow requests (or deny all). Current behavior allows.
            # Consider adding stricter behavior if a key is expected but missing.
            # logging.warning("GATEWAY_API_KEY is not set. Allowing request without authentication.")
            pass # Allow request if no key is configured

        # Authentication passed, proceed with the next middleware/route
        # We wrap call_next in its own try-except to log downstream errors
        try:
            response = await call_next(request)
            return response
        except Exception as e:
            # Log errors that occur *after* this middleware
            logging.error(f"Internal server error: {e}", exc_info=True)
            # Re-raise the exception so FastAPI's default error handling can take over
            raise
        
    except HTTPException as exc:
        # Log and return JSON response for authentication errors
        logging.warning(f"Error in authentication. {exc.detail} (Status: {exc.status_code})") # <-- Log auth failure
        return JSONResponse(
            status_code=exc.status_code,
            content={"detail": exc.detail}
        )
    except IndexError:
        # Handle case where "Bearer " is present but no key follows
        return JSONResponse(
            status_code=status.HTTP_401_UNAUTHORIZED,
            content={"detail": "Invalid Authorization header format"}
        )
    except Exception as e:
        # Catch and log unexpected errors *during* the authentication process itself
        logging.error(f"Internal server error: {e}", exc_info=True) # <-- Log unexpected auth error
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={"detail": f"Internal server error. Error: {e}"}
        )
