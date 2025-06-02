# LLM Gateway Docker Implementation

This directory contains the Docker implementation for the LLM Gateway project.

## Quick Reference

- **Dockerfile**: Multi-stage build for production use
- **docker-compose.yml**: Easy deployment configuration
- **entrypoint.sh**: Container startup script
- **healthcheck.py**: Container health monitoring
- **providers.json.template**: Template for provider configuration
- **models_fallback_rules.json.template**: Template for fallback rules configuration
- **docker-deployment.md**: Comprehensive deployment guide

## Getting Started

1. Create necessary directories:
   ```bash
   mkdir -p config data/db
   ```

2. Edit the configuration files with your details:
   - Edit `providers.json` with your provider details
   - Edit `models_fallback_rules.json` with your fallback rules

3. Deploy using Docker Compose:
   ```bash
   docker-compose up -d
   ```

## Accessing the Gateway

- Web UI: http://localhost:9000/v1/ui/rules-editor
- API: http://localhost:9000/v1/chat/completions

## Configuration

### Required Environment Variables

- `GATEWAY_API_KEY`: API key for accessing the gateway
- At least one provider API key (e.g., `APIKEY_OPENROUTER`)

### Volume Mounts

1. **providers.json**: `-v ./providers.json:/app/providers.json:ro`
2. **models_fallback_rules.json**: `-v ./models_fallback_rules.json:/app/models_fallback_rules.json:ro`
3. **Database**: `-v ./data/db:/app/db`

## Documentation

For detailed deployment instructions, refer to [docker-deployment.md](docker-deployment.md).

## Security Considerations

- The container runs as a non-root user
- Configuration files are mounted read-only
- Sensitive information is passed via environment variables
- The base image is kept minimal for a reduced attack surface