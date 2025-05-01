# System Patterns

## Fallback Implementation
```python
def handle_chat_completion(request: ChatRequest):
    try:
        rule = get_fallback_rule(request.model)
        providers = get_provider_sequence(rule, request.api_key)
        
        for provider_config in providers:
            try:
                response = call_provider(provider_config, request)
                update_rotation_index(rule, request.api_key)
                return response
            except ProviderError as e:
                log_failure(provider_config, e)
                continue
                
        raise ServiceUnavailableError()
    except Exception as e:
        log_system_error(e)
        raise
```

## Model Rotation
- Implemented in `db/model_rotation.py`
- Uses SQLite database with schema:
```sql
CREATE TABLE IF NOT EXISTS rotation_state (
    api_key TEXT,
    gateway_model TEXT,
    current_index INTEGER,
    PRIMARY KEY (api_key, gateway_model)
);
```
- Increments index modulo number of fallback models
- Reset on configuration changes

## Configuration Loading
- Hierarchical config loading:
  1. Environment variables (.env)
  2. providers.json
  3. models_fallback_rules.json
  4. Runtime overrides (future)
