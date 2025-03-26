from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import StreamingResponse
from fastapi.middleware.cors import CORSMiddleware
import httpx
import os
from dotenv import load_dotenv
from typing import Optional
import logging
from logging.config import dictConfig
from pydantic import BaseModel
from middleware.logging import log_middleware
from middleware.auth import api_key_auth
from config import settings, configure_logging

# Initialize logging
configure_logging()

# Initialize FastAPI
app = FastAPI()

# Add middleware
app.middleware("http")(log_middleware)
app.middleware("http")(api_key_auth)

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
        
        # Check if client wants streaming
        is_streaming = request.query_params.get("stream", "").lower() == "true"
        
        if is_streaming:
            # Handle streaming response
            target_response = await client.stream(
                "POST",
                f"{settings.target_server_url}/chat/completions",
                headers=headers,
                params=request.query_params,
                content=body
            )
            
            async def stream_generator():
                async with target_response as response:
                    async for chunk in response.aiter_bytes():
                        yield chunk
            
            return StreamingResponse(
                stream_generator(),
                media_type="application/json"
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

if __name__ == "__main__":
    import uvicorn
    from config import settings
    load_dotenv()  # Ensure .env is loaded
    uvicorn.run(
        app, 
        host="0.0.0.0", 
        port=int(os.getenv("GATEWAY_PORT", "8000"))
    )
