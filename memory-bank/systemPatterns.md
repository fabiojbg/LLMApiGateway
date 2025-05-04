# System Patterns

## Module Responsibilities

### API Layer (`llm_gateway_core/api/v1/`)
- `chat.py`: Defines `/v1/chat/completions` endpoint router
- `models.py`: Defines `/v1/models` endpoint router
- Delegates request handling to `services/request_handler.py`

### Service Layer (`llm_gateway_core/services/`)
- `request_handler.py`: Core business logic including:
  - Interpreting models_fallback_rules.json
  - Managing model rotation state
  - Determining provider attempt sequence
  - Making httpx calls to providers
  - Handling streaming/non-streaming responses
  - Managing retries and fallback logic

### Configuration (`llm_gateway_core/config/`)
- `loader.py`: Loads and parses providers.json and models_fallback_rules.json
- `settings.py`: Pydantic settings management

### Database (`llm_gateway_core/db/`)
- `model_rotation_db.py`: SQLite rotation state management with schema:
```sql
CREATE TABLE IF NOT EXISTS rotation_state (
    api_key TEXT,
    gateway_model TEXT,
    current_index INTEGER,
    PRIMARY KEY (api_key, gateway_model)
);
```

### Middleware (`llm_gateway_core/middleware/`)
- `auth.py`: Authentication middleware
- `chat_logging.py`: Chat-specific logging
- `request_logging.py`: General request logging

## Configuration Loading Flow
1. Environment variables (.env)
2. providers.json (via ConfigLoader)
3. models_fallback_rules.json (via ConfigLoader)
4. Runtime settings (via Pydantic Settings)
