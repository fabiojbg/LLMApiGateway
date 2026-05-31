#!/bin/bash
set -e

# Print a message about where the logs will be
echo "LLM Gateway starting..."
echo "Container logs will be available in the container only and not persisted to host."
echo "Container database will be persisted to host via volume mount."

# Create logs directory if it doesn't exist
mkdir -p /app/logs

# Create directory for database if it doesn't exist
mkdir -p /app/db

# If providers.json doesn't exist, create a default one so the container starts
# but the user will need to configure their actual providers via the Web UI or manually
if [ ! -f "/app/providers.json" ]; then
    echo "WARNING: providers.json not found, creating with default content."
    echo "Please configure your providers via the Web UI at /v1/ui/rules-editor or mount a custom providers.json."
    echo '[
    {
        "'${FALLBACK_PROVIDER:-openrouter}'": {
            "baseUrl": "https://openrouter.ai/api/v1",
            "apikey": "APIKEY_OPENROUTER"
        }
    }
]' > /app/providers.json
fi

# If models_fallback_rules.json doesn't exist, create a default one
if [ ! -f "/app/models_fallback_rules.json" ]; then
    echo "models_fallback_rules.json not found, creating with default content."
    echo '[
    {
        "gateway_model_name": "llmgateway/default",
        "rotate_models": false,
        "fallback_models": [
            {
                "provider": "'${FALLBACK_PROVIDER:-openrouter}'",
                "model": "openai/gpt-3.5-turbo",
                "retry_delay": 15,
                "retry_count": 3
            }
        ]
    }
]' > /app/models_fallback_rules.json
fi

# Print some useful information
echo "Gateway configured to listen on ${GATEWAY_HOST:-0.0.0.0}:${GATEWAY_PORT:-9100}"
echo "Default fallback provider: ${FALLBACK_PROVIDER:-openrouter}"
echo "Log chat enabled: ${LOG_CHAT_ENABLED:-false}"

# Forward signals to the child process
trap 'kill -TERM $child' SIGTERM SIGINT

# Execute the command
exec "$@" &
child=$!

# Wait for the child process to terminate
wait $child