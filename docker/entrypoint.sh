#!/bin/bash
set -e

# Print a message about where the logs will be
echo "LLM Gateway starting..."
echo "Container logs will be available in the container only and not persisted to host."
echo "Container database will be persisted to host via volume mount."

# Check if providers.json exists
if [ ! -f "/app/providers.json" ]; then
    echo "ERROR: providers.json not found. Please mount this file as a volume."
    echo "Example: -v ./providers.json:/app/providers.json:ro"
    exit 1
fi

# Create logs directory if it doesn't exist
mkdir -p /app/logs

# Create directory for database if it doesn't exist
mkdir -p /app/db

# If models_fallback_rules.json doesn't exist, use the template or create a default one
if [ ! -f "/app/models_fallback_rules.json" ]; then
    if [ -f "/app/docker/models_fallback_rules.json.template" ]; then
        echo "models_fallback_rules.json not found, copying from template."
        cp /app/docker/models_fallback_rules.json.template /app/models_fallback_rules.json
    else
        echo "models_fallback_rules.json not found and template not available, creating with default content."
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
fi

# Print some useful information
echo "Gateway configured to listen on ${GATEWAY_HOST:-0.0.0.0}:${GATEWAY_PORT:-9000}"
echo "Default fallback provider: ${FALLBACK_PROVIDER:-openrouter}"
echo "Log chat enabled: ${LOG_CHAT_ENABLED:-false}"

# Forward signals to the child process
trap 'kill -TERM $child' SIGTERM SIGINT

# Execute the command
exec "$@" &
child=$!

# Wait for the child process to terminate
wait $child