# Active Context

## Current Focus
- Initializing the Memory Bank based on the project README and file structure.
- Establishing baseline documentation for future work.

## Recent Changes

## Next Steps
- Review the generated files for accuracy and completeness against the README.

## Key Patterns & Preferences (Initial Observations)
- Configuration is split across `.env`, `providers.json`, and `models_fallback_rules.json`.
- Core logic resides in `llmgateway.py`.
- Model rotation state is persisted in a SQLite DB (`db/model_rotation.py`).
- Logging is configurable via `.env` and handled in `middleware/`.
- LLM calls with streaming support is handled in `infra

## Learnings & Insights
- The project provides a robust solution for LLM API fault tolerance.
- The configuration allows for flexible fallback and rotation strategies.
- Understanding the interaction between the configuration files and the core logic is crucial.
