#!/bin/bash
set -e

echo "LLM Gateway starting..."
echo "Container logs will be available in the container only and not persisted to host."
echo "Container database will be persisted to host via volume mount."

# Create logs directory if it doesn't exist
mkdir -p /app/logs

# Create directory for database if it doesn't exist
mkdir -p /app/db

# Flag to track if there are configuration errors
CONFIG_ERROR=0

# 1. Check if GATEWAY_API_KEY is set (indicates .env is configured)
if [ -z "${GATEWAY_API_KEY}" ]; then
    echo "========================================================================"
    echo " ERROR: GATEWAY_API_KEY environment variable is not set!"
    echo " Please make sure you have configured your .env file correctly"
    echo " and that it is being loaded (e.g., via env_file in docker-compose)."
    echo "========================================================================"
    CONFIG_ERROR=1
fi

# 2. Check if providers.json exists
if [ ! -f "/app/providers.json" ]; then
    echo "========================================================================"
    echo " ERROR: providers.json is missing!"
    echo " Please copy providers.json.example to providers.json, configure it,"
    echo " and mount it to the container at /app/providers.json."
    echo "========================================================================"
    CONFIG_ERROR=1
fi

# 3. Check if models_fallback_rules.json exists
if [ ! -f "/app/models_fallback_rules.json" ]; then
    echo "========================================================================"
    echo " ERROR: models_fallback_rules.json is missing!"
    echo " Please copy models_fallback_rules.json.example to models_fallback_rules.json,"
    echo " configure it, and mount it to the container at /app/models_fallback_rules.json."
    echo "========================================================================"
    CONFIG_ERROR=1
fi

# If any configuration is missing, exit immediately
if [ $CONFIG_ERROR -ne 0 ]; then
    echo "CRITICAL: LLM Gateway startup failed due to missing configuration files."
    echo "Please refer to the README.md or docker-deployment.md for setup instructions."
    exit 1
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