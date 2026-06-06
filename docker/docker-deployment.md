# Docker Deployment Guide for LLM Gateway

This guide explains how to deploy the LLM Gateway using Docker.

## Prerequisites

- Docker installed on your system
- Docker Compose installed (optional, for easier deployment)
- Basic understanding of Docker concepts
- API keys for at least one LLM provider

## Quick Start

The fastest way to get started is using Docker Compose:

```bash
# 1. Create necessary directories
mkdir -p data/db data/logs

# 2. Copy and edit the configuration files
# (you must customize these files before starting the container)
cp providers.json.example providers.json
cp models_fallback_rules.json.example models_fallback_rules.json
cp .env.example .env

# 3. Edit the .env file to set your API keys
nano .env

# 4. Start the container
docker-compose up -d
```

> **Note:** The container requires `.env`, `providers.json`, and `models_fallback_rules.json` to be present and correctly mounted. If any of these files are missing or unconfigured, the container will fail to start with a clear error message in the logs.

## Manual Docker Deployment

If you prefer to use Docker CLI directly:

```bash
# 1. Create necessary directories
mkdir -p data/db data/logs

# 2. Copy and edit the configuration files
cp providers.json.example providers.json
cp models_fallback_rules.json.example models_fallback_rules.json

# 3. Build the image
docker build -t llm-gateway:latest .

# 4. Run the container
docker run -d \
  --name llm-gateway \
  -p 9100:9100 \
  -v "$(pwd)/providers.json:/app/providers.json" \
  -v "$(pwd)/models_fallback_rules.json:/app/models_fallback_rules.json" \
  -v "$(pwd)/data/db:/app/db" \
  -v "$(pwd)/data/logs:/app/logs" \
  -e GATEWAY_API_KEY=your-secure-api-key \
  -e APIKEY_OPENROUTER=your-openrouter-key \
  -e APIKEY_OPENAI=your-openai-key \
  -e LOG_CHAT_ENABLED=true \
  -e FALLBACK_PROVIDER=openrouter \
  llm-gateway:latest
```

## Configuration

### Required Environment Variables

- `GATEWAY_API_KEY`: API key for accessing the gateway
- At least one provider API key (e.g., `APIKEY_OPENROUTER`)

### Optional Environment Variables

- `GATEWAY_PORT`: Port to run the gateway (default: 9100)
- `LOG_FILE_LIMIT`: Maximum log files to keep (default: 15)
- `LOG_CHAT_ENABLED`: Enable chat logging (default: true)
- `FALLBACK_PROVIDER`: Default fallback provider (default: openrouter)

### Provider API Keys

Set any of these environment variables for the providers you want to use:

- `APIKEY_OPENROUTER`: OpenRouter API key
- `APIKEY_OPENAI`: OpenAI API key
- `APIKEY_GOOGLE`: Google API key
- `APIKEY_NEBIUS`: Nebius API key
- `APIKEY_TOGETHER`: Together API key
- `APIKEY_KLUSTERAI`: KlusterAI API key
- `APIKEY_REQUESTY`: Requesty API key
- `APIKEY_XAI`: xAI API key

## Volume Mounts

### Required Mounts

1. **providers.json**: `-v ./providers.json:/app/providers.json`

   - Contains provider configurations
   - Read-write enabled so the Web UI Editor can save changes

2. **models_fallback_rules.json**: `-v ./models_fallback_rules.json:/app/models_fallback_rules.json`

   - Contains fallback rules and model rotation settings
   - Read-write enabled so the Web UI Editor can save changes

3. **Database**: `-v ./data/db:/app/db`
   - Persists SQLite database for model rotation state
   - Read-write access required

4. **Logs**: `-v ./data/logs:/app/logs`
   - Persists application chat and access logs
   - Read-write access required

## Managing the Container

### View Logs

```bash
# Docker CLI
docker logs llm-gateway

# Docker Compose
docker-compose logs
```

### Restart Container

```bash
# Docker CLI
docker restart llm-gateway

# Docker Compose
docker-compose restart
```

### Stop Container

```bash
# Docker CLI
docker stop llm-gateway

# Docker Compose
docker-compose down
```

## Accessing the Gateway

Once the container is running, you can access:

- Web UI: `http://localhost:9100`
- API: `http://localhost:9100/v1/chat/completions`

Remember to use the `GATEWAY_API_KEY` in your requests as:

```
Authorization: Bearer your-gateway-api-key
```

## Common Issues

### Container not starting

Check the logs for errors:

```bash
docker logs llm-gateway
```

### API calls failing

Verify that:

1. You've provided the correct API keys
2. Your `providers.json` file is correctly configured
3. You're including the `Authorization` header in your requests

### Database persistence issues

Make sure the volume mount for the database is correct and the directory has appropriate permissions:

```bash
ls -la data/db
```

## Upgrading

To upgrade to a newer version:

```bash
# Pull latest code and rebuild
git pull
# Restart the service
docker compose down
# Rebuild image and start container
docker compose up --build -d

```

## Production Considerations

For production deployments, consider:

1. Using a reverse proxy (e.g., Nginx) for SSL termination
2. Setting up proper monitoring and alerts
3. Implementing regular database backups
4. Using Docker secrets for sensitive API keys instead of environment variables