# LLM API Gateway

A simple gateway that forwards OpenAI-compatible API requests to a target server.

## Features

- OpenAI-compatible API endpoints
- Fixed API key authentication for clients
- Request/response logging
- Streaming support for chat completions

## Setup

1. Install dependencies:
```bash
pip install -r requirements.txt
```

2. Create `.env` file:
```bash
cp .env.example .env
```

3. Configure environment variables in `.env`:
- `TARGET_SERVER_URL`: URL of target OpenAI-compatible server
- `TARGET_API_KEY`: API key for target server
- `GATEWAY_API_KEY`: Fixed API key clients must use

## Running

Start the server:
```bash
uvicorn main:app --reload
```

## API Usage

Make requests with the gateway API key in the Authorization header:
```
Authorization: Bearer {GATEWAY_API_KEY}
```

### Supported Endpoints

- `GET /v1/models` - List available models
- `GET /v1/chat/completions` - Chat completions (supports streaming)

## Logging

Logs are stored in `logs/gateway.log` in JSON format.
