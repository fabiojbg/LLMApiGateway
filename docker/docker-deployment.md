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
mkdir -p config data/db

# 2. Edit the configuration templates
# (you need to customize these files)
nano providers.json
nano models_fallback_rules.json

# 3. Edit the docker-compose.yml file to set your API keys
# (you need to customize this file)
nano docker-compose.yml

# 4. Start the container
docker-compose up -d
```

## Manual Docker Deployment

If you prefer to use Docker CLI directly:

```bash
# 1. Create necessary directories
mkdir -p config data/db

# 2. Edit the configuration templates
# (you need to customize these files)
nano providers.json
nano models_fallback_rules.json

# 3. Build the image
docker build -t llm-gateway:latest .

# 4. Run the container
docker run -d \
  --name llm-gateway \
  -p 9000:9000 \
  -v "$(pwd)/providers.json:/app/providers.json:ro" \
  -v "$(pwd)/models_fallback_rules.json:/app/models_fallback_rules.json:ro" \
  -v "$(pwd)/data/db:/app/db" \
  -e GATEWAY_API_KEY=your-secure-api-key \
  -e APIKEY_OPENROUTER=your-openrouter-key \
  -e APIKEY_OPENAI=your-openai-key \
  -e LOG_CHAT_ENABLED=false \
  -e FALLBACK_PROVIDER=openrouter \
  llm-gateway:latest
```

## Configuration

### Required Environment Variables

- `GATEWAY_API_KEY`: API key for accessing the gateway
- At least one provider API key (e.g., `APIKEY_OPENROUTER`)

### Optional Environment Variables

- `GATEWAY_PORT`: Port to run the gateway (default: 9000)
- `LOG_FILE_LIMIT`: Maximum log files to keep (default: 15)
- `LOG_CHAT_ENABLED`: Enable chat logging (default: false)
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

1. **providers.json**: `-v ./providers.json:/app/providers.json:ro`

   - Contains provider configurations
   - Mounted read-only for security

2. **models_fallback_rules.json**: `-v ./models_fallback_rules.json:/app/models_fallback_rules.json:ro`

   - Contains fallback rules and model rotation settings
   - Mounted read-only for security

3. **Database**: `-v ./data/db:/app/db`
   - Persists SQLite database for model rotation state
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

- Web UI: `http://localhost:9000/v1/ui/rules-editor`
- API: `http://localhost:9000/v1/chat/completions`

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
docker-compose build

# Restart the service
docker-compose down
docker-compose up -d
```

## Production Considerations

For production deployments, consider:

1. Using a reverse proxy (e.g., Nginx) for SSL termination
2. Setting up proper monitoring and alerts
3. Implementing regular database backups
4. Using Docker secrets for sensitive API keys instead of environment variables
