[v1.20]
---
### Architecture & Testing
- **Project Refactoring & Comprehensive Test Suite**:
  - Refactored core modules into a clean architecture separating API routers, configuration loading (`ConfigLoader`), request handling, SQLite databases, and middleware.
  - Added centralized Pydantic settings management (`settings.py`) and managed downstream HTTP client lifespan.
  - Implemented extensive pytest test suite covering chat fallback, rotation concurrency, streaming/non-streaming responses, configuration reload, and token usage persistence.

### Data Organization & Docker
- **Relocated Data & Logs to `app_data/`**:
  - Reorganized local SQLite database storage (`llmgateway_rotation.db`, `tokens_usage.db`) and log files under the new `app_data/` folder (`app_data/db/` and `app_data/logs/`).
  - Updated Docker configurations and entrypoints to map data volumes cleanly under `docker_volumes/`.

### Logging & Database
- **Enhanced Chat & Token Logging in Database**:
  - Improved request logging and token usage recording in SQLite for both streaming and non-streaming responses.
  - Added diagnostic messaging in chat logs explaining possible causes when an LLM produces no response content.

### Bug Fixes
- **Dynamic Model Lists & Integrations**:
  - Fixed an issue where `/v1/models`, `/AsOpenCodeFormat`, and `/AsGitHubCopilotFormat` endpoints did not dynamically reflect updated fallback rules and provider configurations from application state.
- **Fix /chat/completions authorization**: the /chat/completions endpoint was not working when the GATEWAY_API_KEY was set.


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

