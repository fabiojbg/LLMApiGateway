from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import StreamingResponse
from fastapi.middleware.cors import CORSMiddleware
import httpx
import os
from typing import Optional
import logging
from logging.config import dictConfig
from pydantic import BaseModel
from middleware.chat_logging import log_chat_completions
from middleware.auth import api_key_auth
from config import settings, configure_logging
import json
from pathlib import Path

# Load provider mapping
provider_mapping = []
try:
    with open(Path(__file__).parent / "openrouter_provider_mapping.json") as f:
        provider_mapping = json.load(f)
except Exception as e:
    logging.warning(f"Failed to load openrouter_provider_mapping.json: {str(e)}")

# Initialize logging
configure_logging()

# Initialize FastAPI
app = FastAPI()

# Add middleware
app.middleware("http")(api_key_auth)
app.middleware("http")(log_chat_completions)

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# HTTP client
client = httpx.AsyncClient()

@app.get("/v1/models")
async def get_models():
    try:
        headers = {
            "Authorization": f"Bearer {settings.target_api_key}",
            "Content-Type": "application/json"
        }
        
        response = await client.get(
            f"{settings.target_server_url}/models",
            headers=headers
        )
        
        return response.json()
    except httpx.HTTPStatusError as e:
        raise HTTPException(
            status_code=e.response.status_code,
            detail=e.response.text
        )
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=str(e)
        )

@app.post("/v1/chat/completions")
async def chat_completions(request: Request):
    try:
        headers = {
            "Authorization": f"Bearer {settings.target_api_key}",
            "Content-Type": "application/json"
        }
        
        # Forward the request body if present
        body = await request.body()
        
        body_str = body.decode('utf-8')
        try:
            body_json = json.loads(body_str)
            # Check if model exists in provider mapping and injection is enabled
            if settings.provider_injection_enabled and "model" in body_json:
                for mapping in provider_mapping:
                    if mapping["model"] == body_json["model"]:
                        body_json["provider"] = {"order": mapping["providers"]}
                        body_str = json.dumps(body_json)
                        body = body_str.encode('utf-8')
                        break
        except json.JSONDecodeError:
            pass  # Maintain original behavior if JSON parsing fails
            
        # Check if client wants streaming
        is_streaming = json.loads(body_str).get("stream") is True

        if is_streaming:
            # Handle streaming response
            async def stream_generator():
                async with client.stream(
                    "POST",
                    f"{settings.target_server_url}/chat/completions",
                    headers=headers,
                    params=request.query_params,
                    content=body,
                    timeout=None
                ) as response:
                    response.raise_for_status()
                    async for chunk in response.aiter_bytes():
                        yield chunk
            
            return StreamingResponse(
                stream_generator(),
                media_type="text/event-stream",
                headers={
                    "Transfer-Encoding": "chunked",
                    "X-Accel-Buffering": "no"
                }
            )
        else:
            # Handle normal response
            response = await client.post(
                f"{settings.target_server_url}/chat/completions",
                headers=headers,
                params=request.query_params,
                content=body
            )
            return response.json()            
        
    except Exception as e:
        print( "Error: " + str(e))
        raise HTTPException(
            status_code=500,
            detail=str(e)
        )

if __name__ == "__main__":
    import uvicorn
    from config import settings
    uvicorn.run(
        app, 
        host="0.0.0.0", 
        port=settings.gateway_port,
        log_level="debug",
    )
