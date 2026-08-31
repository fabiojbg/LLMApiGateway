import asyncio
import logging
from fastapi import APIRouter, Request, HTTPException, Body
from fastapi.responses import HTMLResponse, PlainTextResponse
from pathlib import Path

from llm_gateway_core.config.loader import (
    ConfigPersistenceError,
    ConfigValidationError,
)

editor_router = APIRouter()

# Path to the configuration files
# These should ideally come from a shared configuration or the ConfigLoader instance
# For now, constructing them similarly to how ConfigLoader does.
PROJECT_ROOT = Path(__file__).parent.parent.parent.parent
FALLBACK_RULES_FILENAME = "models_fallback_rules.json"
PROVIDERS_FILENAME = "providers.json"

FALLBACK_RULES_CONFIG_FILE_PATH = PROJECT_ROOT / FALLBACK_RULES_FILENAME
PROVIDERS_CONFIG_FILE_PATH = PROJECT_ROOT / PROVIDERS_FILENAME

HTML_DIR = PROJECT_ROOT / "static"  # project_root/static


# The router itself will be included with a prefix like /v1 or /admin in main.py
@editor_router.get(
    "/ui/rules-editor", response_class=HTMLResponse, tags=["Config Editor UI"]
)
async def get_editor_page(request: Request):
    """Serves the HTML page for the configuration editor."""
    editor_html_path = HTML_DIR / "rules-editor.html"
    if not editor_html_path.exists():
        logging.error(f"Editor HTML file not found at {editor_html_path}")
        raise HTTPException(status_code=404, detail="Editor page not found.")
    try:
        with open(editor_html_path, "r") as f:
            html_content = f.read()
        return HTMLResponse(content=html_content)
    except Exception as e:
        logging.error(f"Error reading editor HTML file: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Could not load editor page.")


# If router is included with prefix /v1, this becomes /v1/config/models-rules
@editor_router.get(
    "/config/models-rules", response_class=PlainTextResponse, tags=["Config Editor API"]
)
async def get_models_rules_text(request: Request):
    """Fetches the current raw text content of models_fallback_rules.json."""
    if not FALLBACK_RULES_CONFIG_FILE_PATH.exists():
        logging.error(
            f"Configuration file {FALLBACK_RULES_CONFIG_FILE_PATH.name} not found."
        )
        raise HTTPException(
            status_code=404, detail=f"{FALLBACK_RULES_CONFIG_FILE_PATH.name} not found."
        )
    try:
        with open(FALLBACK_RULES_CONFIG_FILE_PATH, "r", encoding="utf-8") as f:
            content = f.read()
        return PlainTextResponse(content=content)
    except Exception as e:
        logging.error(
            f"Error reading {FALLBACK_RULES_CONFIG_FILE_PATH.name}: {e}", exc_info=True
        )
        raise HTTPException(
            status_code=500,
            detail=f"Could not read {FALLBACK_RULES_CONFIG_FILE_PATH.name}.",
        )


# If router is included with prefix /v1, this becomes /v1/config/models-rules
@editor_router.post("/config/models-rules", tags=["Config Editor API"])
async def save_models_rules(
    request: Request, payload_text: str = Body(..., media_type="text/plain")
):
    """Validate, atomically save, and activate fallback rules."""
    config_loader = request.app.state.config_loader
    if not config_loader:
        logging.error("ConfigLoader not found in application state.")
        raise HTTPException(
            status_code=500, detail="Internal server error: ConfigLoader not available."
        )

    try:
        await asyncio.to_thread(config_loader.apply_fallback_rules, payload_text)
    except ConfigValidationError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    except ConfigPersistenceError as error:
        logging.error("Could not persist fallback rules: %s", error, exc_info=True)
        raise HTTPException(
            status_code=500, detail="Could not save fallback rules."
        ) from error

    return {
        "message": (
            f"{config_loader.fallback_rules_path.name} updated and reloaded "
            "successfully."
        )
    }


# --- Endpoints for providers.json ---


@editor_router.get(
    "/config/providers", response_class=PlainTextResponse, tags=["Config Editor API"]
)
async def get_providers_text(request: Request):
    """Fetches the current raw text content of providers.json."""
    if not PROVIDERS_CONFIG_FILE_PATH.exists():
        logging.error(
            f"Configuration file {PROVIDERS_CONFIG_FILE_PATH.name} not found."
        )
        raise HTTPException(
            status_code=404, detail=f"{PROVIDERS_CONFIG_FILE_PATH.name} not found."
        )
    try:
        with open(PROVIDERS_CONFIG_FILE_PATH, "r", encoding="utf-8") as f:
            content = f.read()
        return PlainTextResponse(content=content)
    except Exception as e:
        logging.error(
            f"Error reading {PROVIDERS_CONFIG_FILE_PATH.name}: {e}", exc_info=True
        )
        raise HTTPException(
            status_code=500, detail=f"Could not read {PROVIDERS_CONFIG_FILE_PATH.name}."
        )


@editor_router.post("/config/providers", tags=["Config Editor API"])
async def save_providers_config(
    request: Request, payload_text: str = Body(..., media_type="text/plain")
):
    """Validate, atomically save, and activate providers."""
    config_loader = request.app.state.config_loader
    if not config_loader:
        logging.error("ConfigLoader not found in application state.")
        raise HTTPException(
            status_code=500, detail="Internal server error: ConfigLoader not available."
        )

    try:
        await asyncio.to_thread(config_loader.apply_providers, payload_text)
    except ConfigValidationError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    except ConfigPersistenceError as error:
        logging.error("Could not persist providers: %s", error, exc_info=True)
        raise HTTPException(
            status_code=500, detail="Could not save providers."
        ) from error

    return {
        "message": (
            f"{config_loader.providers_path.name} updated and reloaded successfully."
        )
    }
