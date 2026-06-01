---
trigger: always_on
description: Project explanation and work instructions
applyTo: '**'
---

# Project briefing
This project is a personal LLM Gateway that allows developers to use LLMs from different LLM providers with features like fault tolerance, model load balancing, customized model requests, call retries, and more.
The LLM Gateway works locally as an OpenAI-compatible LLM API provider with advanced fallback support for models in case of response failures.

# Project Guidelines

- working with the project: To know what the project is about and how it is structured, read the README.md  and the sections 'Project Structure' and 'Module Responsibilities' below.
- Pay attention to the MCP Tools available to use them whenever necessary.
- If you planned a long task with multiple steps, use the Task Manager tool, if available, to manage the steps of the plan
- Keep the sections "Project Structure" and "Module Responsibilities" in this file(.clinerules) in sync with new capabilities

## Code Style & Patterns

-   Generate API clients using fastAPI
-   Prefer use object oriented approach

## Package management

- This project supports pip and uv package managers. Although uv is preferable and uou must mantain the requirements.txt and pyproject.toml in any change of the project dependencies

## Project Structure

- The project is structured to separate concerns and maintain a clean architecture. 
You must mantain this structure updated in case of any change in it or in file´s responsabilities

```
/Project_Root_Folder/
├── .env.example
├── .gitignore
├── .clinerules  # this file
├── LICENSE
├── README.md
├── main.py                 # <--- FastAPI app setup, middleware, lifespan, Uvicorn runner
├── models_fallback_rules.json
├── providers.json
├── pyproject.toml
├── requirements.txt
├── db/                     # Keep the actual DB file location consistent
│   └── llmgateway_rotation.db
├── images/
│   └── cline-example.png
├── llm_gateway_core/       # <--- Main Application Package
│   ├── __init__.py
│   ├── api/                # <--- API Routers
│   │   ├── __init__.py
│   │   └── v1/
│   │       ├── __init__.py
│   │       ├── chat.py     # <--- Defines /v1/chat/completions router
│   │       ├── models.py   # <--- Defines /v1/models router
│   │       ├── editor.py   # <--- Defines /v1/ui/rules-editor and /v1/config/models-rules routers
│   │       └── stats.py    # <--- Defines /v1/ui/usage-stats and /v1/usage/tokens routers
│   ├── services/           # <--- Core Business Logic
│   │   ├── __init__.py
│   │   └── request_handler.py # <--- Handles routing, provider calls, fallback, rotation
│   ├── config/             # <--- Configuration Loading & Settings
│   │   ├── __init__.py
│   │   ├── settings.py     # <--- Pydantic settings
│   │   └── loader.py       # <--- Loads providers.json, rules.json
│   ├── db/                 # <--- Database Interaction Layer
│   │   ├── __init__.py
│   │   ├── model_rotation_db.py # <--- Rotation state logic
│   │   └── tokens_usage_db.py # <--- Tokens usage state logic
│   ├── middleware/         # <--- Request Middleware
│   │   ├── __init__.py
│   │   ├── auth.py
│   │   ├── chat_logging.py
│   │   └── request_logging.py # <--- Renamed from logging.py
│   └── utils/              # <--- Utility Functions
│       ├── __init__.py
│       └── logging_setup.py # <--- Logging configuration
├── logs/                   # <--- Runtime log files (structure unchanged)
├── static/                 # <--- Static files for the web editor
│   ├── editor.html         # <--- HTML for the rules editor
│   ├── editor.css          # <--- CSS for the rules editor
│   ├── editor.js           # <--- JavaScript for the rules editor
│   ├── usage-stats.html    # <--- HTML for the usage statistics
│   ├── usage-stats.css     # <--- CSS for the usage statistics
│   └── usage-stats.js      # <--- JavaScript for the usage statistics
└── memory-bank/            # <--- Project context files (structure unchanged)
```

## Module Responsibilities

Here is a brief overview of the key modules and their responsibilities:
You must mantain this section updated to allways reflect the actual module responsibilities

*   **`main.py`:** Initializes the FastAPI application, includes API routers from `llm_gateway_core/api/v1/` (including the editor router), applies middleware, handles startup/shutdown events (including `ConfigLoader` initialization and making it available via `app.state`), serves static files from `static/`, and runs the Uvicorn server.
*   **`llm_gateway_core/api/v1/chat.py`:** Defines the `APIRouter` for the `/v1/chat/completions` endpoint. Delegates request handling to `services/request_handler.py`.
*   **`llm_gateway_core/api/v1/models.py`:** Defines the `APIRouter` for the `/v1/models` endpoint. Delegates request handling to `services/request_handler.py`.
*   **`llm_gateway_core/api/v1/editor.py`:** Defines the `APIRouter` for:
    *   `GET /v1/ui/rules-editor`: Serves the HTML page for the `models_fallback_rules.json` editor.
    *   `GET /v1/config/models-rules`: Fetches the current content of `models_fallback_rules.json`.
    *   `POST /v1/config/models-rules`: Validates, saves the updated `models_fallback_rules.json`, and triggers a configuration reload via `ConfigLoader`.
*   **`llm_gateway_core/api/v1/stats.py`:** Defines the `APIRouter` for:
    *   `GET /v1/ui/usage-stats`: Serves the HTML page for the usage statistics.
    *   `GET /v1/api/usage-stats/{period}`: Fetches aggregated token usage statistics by period and model from `db/tokens_usage_db.py`.
    *   `GET /v1/api/usage-records`: Fetches the latest N token usage records with pagination from `db/tokens_usage_db.py`.
*   **`llm_gateway_core/services/request_handler.py`:** Encapsulates the core logic for handling incoming requests. This includes:
    *   Interpreting `models_fallback_rules.json` (obtained from `ConfigLoader`).
    *   Managing model rotation state using `db/model_rotation_db.py`.
    *   Determining the sequence of provider attempts (routing).
    *   Making `httpx` calls to downstream providers.
    *   Handling streaming/non-streaming responses.
    *   Managing retries and fallback logic.
    *   Fetching model lists for the `/v1/models` endpoint.
*   **`llm_gateway_core/config/loader.py`:** Contains the `ConfigLoader` class responsible for reading, parsing, and validating `providers.json` and `models_fallback_rules.json`. Includes the `reload_fallback_rules()` method for dynamic updates of the model rules.
*   **`llm_gateway_core/config/settings.py`:** Contains the Pydantic `Settings` class.
*   **`llm_gateway_core/db/model_rotation_db.py`:** Contains the `ModelRotationDB` class for interacting with the SQLite database for model rotation state.
*   **`llm_gateway_core/db/tokens_usage_db.py`:** Contains the `TokensUsageDB` class for interacting with the SQLite database for storing and retrieving tokens usage statistics.
*   **`llm_gateway_core/middleware/`:** Contains the middleware functions (authentication, chat logging, request logging).
*   **`llm_gateway_core/utils/logging_setup.py`:** Contains the logging configuration logic.
