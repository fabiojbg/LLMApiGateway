# LLM Gateway Docker Implementation

This directory contains the Docker implementation for the LLM Gateway project.

## Quick Reference

- **Dockerfile**: Multi-stage build for production use
- **docker-compose.yml**: Easy deployment configuration
- **entrypoint.sh**: Container startup script
- **healthcheck.py**: Container health monitoring
- **providers.json.example**: Template for provider configuration (in root)
- **models_fallback_rules.json.example**: Template for fallback rules configuration (in root)
- **docker-deployment.md**: Comprehensive deployment guide

## Getting Started

1. Create necessary directories:
   ```bash
   mkdir -p config data/db
   ```

2. Create the configuration files from the provided examples in the root directory:
   - `cp .env.example .env`
   - `cp providers.json.example providers.json`
   - `cp models_fallback_rules.json.example models_fallback_rules.json`

3. Edit the configuration files with your details before build the image and containers or use the Web UI after deployment.

   > **Note:** If `providers.json` and `models_fallback_rules.json` do not exist on the host, the entrypoint script will automatically generate sensible default versions so the container can start. You can then configure them via the Web UI.

4. Deploy using Docker Compose:
   ```bash
   docker-compose up -d
   ```

## Accessing the Gateway

- Web UI: http://localhost:9100/v1/ui/rules-editor
- API: http://localhost:9100/v1/chat/completions

## Configuration

### Required Environment Variables

- `GATEWAY_API_KEY`: API key for accessing the gateway
- At least one provider API key (e.g., `APIKEY_OPENROUTER`)

### Volume Mounts

1. **providers.json**: `-v ./providers.json:/app/providers.json` (read-write enabled so the Web UI can save changes)
2. **models_fallback_rules.json**: `-v ./models_fallback_rules.json:/app/models_fallback_rules.json` (read-write enabled so the Web UI can save changes)
3. **Database**: `-v ./data/db:/app/db`

## Documentation

For detailed deployment instructions, refer to [docker-deployment.md](docker-deployment.md).

## Security Considerations

- The container runs as a non-root user
- Sensitive information is passed via environment variables
- The base image is kept minimal for a reduced attack surface