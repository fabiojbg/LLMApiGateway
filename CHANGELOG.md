[v1.11]
---
### Features
- **New coding agents integration** 
  - Now you can download ready-to-use configuration files for OpenCode and GitHub Copilot. Go to the Rules Editor, select the Agents Integration tab and download the configuration files for OpenCode or GitHub Copilot and follow the instructions to integrate LLMApiGateway models with your coding agents.  

- **New Cost/Million field**: added the "Cost per Million" column to the usage statistics page. This field allows you to compare the cost of models you're using.

- **Enhanced request logging for debugging** (`/v1/chat/completions`): the request middleware now logs request headers (with sensitive fields like `Authorization`, `api-key`, `x-api-key`, and `proxy-authorization` masked) and the request payload (with `messages` and `tools` excluded) to ease troubleshooting.
- **Root redirect**: `/` now redirects to the rules editor (`/v1/ui/rules-editor`) instead of returning an error.

### Docker & Deployment
- Adjusted Docker container configuration and `docker-compose.yml` for cleaner deployments.
- Container logs are now redirected to the host path `./data/logs`.
- Added `models_fallback_rules.json.example` and `providers.json.example` files for easier onboarding.
- Docker entrypoint script and deployment documentation improvements.

[v1.10]
---
- New pages to track token and cost consumption.
- Fixed bug where non-streaming requests were not logged or tracked in stats.

