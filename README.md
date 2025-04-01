
# LLM Gateway for OpenRouter with Provider Order Injection

A FastAPI-based proxy for OpenAI-compatible API servers with advanced logging, authentication, and provider mapping. Designed for use with **OpenRouter**, this gateway lets you inject preferred provider orders per model via **openrouter_provider_mapping.json**, enabling OpenRouter to use your specified provider priorities. This resolves the lack of this functionality in OpenRouter, Cline, and RooCode.  [See Provider Mapping section](#provider-mappping).
The gateway also allows logging all chat requests to the /logs folder to help inspect the messages and the workings of the agents and the models. 

## Features

- OpenAI-compatible API endpoints
  - `/v1/models` - List available models
  - `/v1/chat/completions` - Chat completions (**supports streaming**)
- API key authentication middleware
- Three-layer logging system:
  - Request/response logging (JSON format)
  - Detailed chat completion logging (text files)
  - Error logging
- Provider model mapping (OpenRouter compatible)
- Health check endpoint (`/health`)
- CORS enabled by default
- Configurable log rotation

## Configuration

Create `.env` file from example:
```bash
cp .env.example .env
```
 .env configuration example for OpenRouter:
 ```bash
# Target OpenAI-compatible server URL
TARGET_SERVER_URL=https://openrouter.ai/api/v1

# API key for the target server
TARGET_API_KEY=<Your OpenRouterKey>

# Fixed API key that clients must use to access this gateway
# Use it in the Authorization: Bearer <ThisGatewayApiKey>)
GATEWAY_API_KEY=<ThisGatewayApiKey>

# Maximum number of log files to keep (older files will be deleted)
LOG_FILE_LIMIT=10

# Enable/Disable automatic model provider order injection (true/false).
PROVIDER_INJECTION_ENABLED=true

#Enable/disable logging of chat messages to the /logs folder (true/false)
LOG_CHAT_ENABLED=false
```

### Environment Variables

| Variable | Description | Default |
|----------|-------------|---------|
| `TARGET_SERVER_URL` | URL of target OpenAI-compatible server | *required* |
| `TARGET_API_KEY` | API key for target server | *required* |
| `GATEWAY_API_KEY` | Fixed API key clients must use | *required* |
| `LOG_FILE_LIMIT` | Max number of chat log files to keep | `15` |
| `PROVIDER_INJECTION_ENABLED` | Enable provider model mapping | `true` |

### Provider Mapping

This configuration defines which provider's ordering should be injected into the request according to the model being used.

Configure model mappings in `openrouter_provider_mapping.json`:
```json
[
    {
        "model": "deepseek/deepseek-chat-v3-0324",
        "providers": ["DeepInfra", "Parasail", "Hyperbolic"]
    },
    {
        "model": "deepseek/deepseek-chat-v3-0324:free",
        "providers": ["Chutes", "Targon"]
    }
]
```

## Running

### Development
```bash
uvicorn main:app --reload --port 9000
```

### Production
```bash
uvicorn main:app --host 0.0.0.0 --port 9000
```

## API Usage

### Authentication
Include the gateway API key in the Authorization header:
```
Authorization: Bearer {GATEWAY_API_KEY}
```

### Endpoints

#### GET /v1/models
Lists available models from the target server.

#### POST /v1/chat/completions
- Supports both streaming and non-streaming responses
- When `PROVIDER_INJECTION_ENABLED=true`, injects provider information based on model mapping
- Set `"stream": true` in request body for streaming responses

## Logging

### Structured Logs
- Location: `logs/gateway.log`
- JSON format
- Includes:
  - Request metadata
  - Response status codes
  - Processing time
  - Errors

### Chat Completions Logs
- Location: `logs/` directory
- Text format with timestamps
- Includes:
  - Request headers
  - Full request body
  - LLM response content
- Automatically rotated (oldest files deleted when over limit)

## Middleware

1. **Authentication**:
   - Validates API key
   - Skips auth for `/health` endpoint

2. **Request Logging**:
   - Tracks request duration
   - Logs request metadata
   - Handles streaming responses

3. **Chat Logging**:
   - Detailed logging of chat completions
   - Handles both streaming and non-streaming
   - Creates timestamped log files

## Dependencies

- fastapi==0.109.0
- uvicorn==0.27.0
- httpx==0.27.0
- python-dotenv==1.0.0
- python-json-logger==2.0.7
- pydantic==2.6.1
- pydantic-settings==2.2.1
