import logging
import json5
from fastapi import APIRouter, Request, HTTPException, Body
from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse
from pathlib import Path
from pydantic import ValidationError

# Assuming ModelFallbackConfig is the Pydantic model for the entire rules structure (list of rules)
# If ModelFallbackConfig is for a single rule, we'd need a List[ModelFallbackConfig]
from llm_gateway_core.config.loader import ModelFallbackConfig, ProviderConfig # Adjust if Pydantic models are elsewhere

editor_router = APIRouter()

# Path to the configuration files
# These should ideally come from a shared configuration or the ConfigLoader instance
# For now, constructing them similarly to how ConfigLoader does.
PROJECT_ROOT = Path(__file__).parent.parent.parent.parent
FALLBACK_RULES_FILENAME = "models_fallback_rules.json"
PROVIDERS_FILENAME = "providers.json"

FALLBACK_RULES_CONFIG_FILE_PATH = PROJECT_ROOT / FALLBACK_RULES_FILENAME
PROVIDERS_CONFIG_FILE_PATH = PROJECT_ROOT / PROVIDERS_FILENAME

HTML_DIR = PROJECT_ROOT / "static" # project_root/static

# The router itself will be included with a prefix like /v1 or /admin in main.py
@editor_router.get("/ui/rules-editor", response_class=HTMLResponse, tags=["Config Editor UI"])
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
@editor_router.get("/config/models-rules", response_class=PlainTextResponse, tags=["Config Editor API"])
async def get_models_rules_text(request: Request):
    """Fetches the current raw text content of models_fallback_rules.json."""
    if not FALLBACK_RULES_CONFIG_FILE_PATH.exists():
        logging.error(f"Configuration file {FALLBACK_RULES_CONFIG_FILE_PATH.name} not found.")
        raise HTTPException(status_code=404, detail=f"{FALLBACK_RULES_CONFIG_FILE_PATH.name} not found.")
    try:
        with open(FALLBACK_RULES_CONFIG_FILE_PATH, "r", encoding="utf-8") as f:
            content = f.read()
        return PlainTextResponse(content=content)
    except Exception as e:
        logging.error(f"Error reading {FALLBACK_RULES_CONFIG_FILE_PATH.name}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Could not read {FALLBACK_RULES_CONFIG_FILE_PATH.name}.")

# If router is included with prefix /v1, this becomes /v1/config/models-rules
@editor_router.post("/config/models-rules", tags=["Config Editor API"])
async def save_models_rules(request: Request, payload_text: str = Body(..., media_type="text/plain")):
    """
    Validates and saves the updated models_fallback_rules.json.
    Triggers a configuration reload on success.
    """
    config_loader = request.app.state.config_loader
    if not config_loader:
        logging.error("ConfigLoader not found in application state.")
        raise HTTPException(status_code=500, detail="Internal server error: ConfigLoader not available.")

    try:
        parsed_for_validation = json5.loads(payload_text)

        if not isinstance(parsed_for_validation, list):
            raise HTTPException(
                status_code=400, 
                detail="Invalid format: Expected a list of rule objects."
            )
        
        _ = [ModelFallbackConfig(**item) for item in parsed_for_validation] # Perform validation
        
        with open(FALLBACK_RULES_CONFIG_FILE_PATH, "w", encoding="utf-8") as f:
            f.write(payload_text)

        logging.info(f"Successfully wrote updated configuration (with comments) to {FALLBACK_RULES_CONFIG_FILE_PATH.name}.")

        # Attempt to reload the configuration
        if config_loader.reload_fallback_rules():
            logging.info(f"Configuration {FALLBACK_RULES_CONFIG_FILE_PATH.name} reloaded successfully.")
            return {"message": f"{FALLBACK_RULES_CONFIG_FILE_PATH.name} updated and reloaded successfully."}
        else:
            logging.error(f"Configuration {FALLBACK_RULES_CONFIG_FILE_PATH.name} was updated, but failed to reload.")
            # The file is updated, but the running config might be stale. This is a critical state.
            raise HTTPException(status_code=500, detail=f"{FALLBACK_RULES_CONFIG_FILE_PATH.name} updated, but failed to reload. Check server logs.")

    except ValidationError as ve:
        logging.error(f"Validation error saving {FALLBACK_RULES_CONFIG_FILE_PATH.name}: {ve.errors()}", exc_info=False) # No need for full stack trace for validation
        # Provide detailed validation errors to the client
        return JSONResponse(status_code=400, content={"detail": "Validation Error", "errors": ve.errors()})
    except Exception as e:
        logging.error(f"Error saving {FALLBACK_RULES_CONFIG_FILE_PATH.name}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Could not save {FALLBACK_RULES_CONFIG_FILE_PATH.name}: Error = {e}")


# --- Endpoints for providers.json ---

@editor_router.get("/config/providers", response_class=PlainTextResponse, tags=["Config Editor API"])
async def get_providers_text(request: Request):
    """Fetches the current raw text content of providers.json."""
    if not PROVIDERS_CONFIG_FILE_PATH.exists():
        logging.error(f"Configuration file {PROVIDERS_CONFIG_FILE_PATH.name} not found.")
        raise HTTPException(status_code=404, detail=f"{PROVIDERS_CONFIG_FILE_PATH.name} not found.")
    try:
        with open(PROVIDERS_CONFIG_FILE_PATH, "r", encoding="utf-8") as f:
            content = f.read()
        return PlainTextResponse(content=content)
    except Exception as e:
        logging.error(f"Error reading {PROVIDERS_CONFIG_FILE_PATH.name}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Could not read {PROVIDERS_CONFIG_FILE_PATH.name}.")

@editor_router.post("/config/providers", tags=["Config Editor API"])
async def save_providers_config(request: Request, payload_text: str = Body(..., media_type="text/plain")):
    """
    Validates and saves the updated providers.json.
    Triggers a providers configuration reload on success.
    """
    config_loader = request.app.state.config_loader
    if not config_loader:
        logging.error("ConfigLoader not found in application state.")
        raise HTTPException(status_code=500, detail="Internal server error: ConfigLoader not available.")

    try:
        parsed_for_validation = json5.loads(payload_text)

        if not isinstance(parsed_for_validation, list):
            raise HTTPException(
                status_code=400,
                detail="Invalid format: Expected a list of provider objects."
            )
        
        # Validate each item in the list against the ProviderConfig Pydantic model
        _ = [ProviderConfig(**item) for item in parsed_for_validation]
        
        with open(PROVIDERS_CONFIG_FILE_PATH, "w", encoding="utf-8") as f:
            f.write(payload_text)

        logging.info(f"Successfully wrote updated providers configuration (with comments) to {PROVIDERS_CONFIG_FILE_PATH.name}.")

        # Attempt to reload the providers configuration
        if hasattr(config_loader, 'reload_providers_config') and config_loader.reload_providers_config():
            logging.info(f"Providers configuration {PROVIDERS_CONFIG_FILE_PATH.name} reloaded successfully.")
            return {"message": f"{PROVIDERS_CONFIG_FILE_PATH.name} updated and reloaded successfully."}
        elif not hasattr(config_loader, 'reload_providers_config'):
            logging.error(f"ConfigLoader does not have 'reload_providers_config' method. {PROVIDERS_CONFIG_FILE_PATH.name} was updated, but not reloaded.")
            raise HTTPException(status_code=500, detail=f"{PROVIDERS_CONFIG_FILE_PATH.name} updated, but not reloaded (method missing). Check server logs.")
        else:
            logging.error(f"Providers configuration {PROVIDERS_CONFIG_FILE_PATH.name} was updated, but failed to reload.")
            raise HTTPException(status_code=500, detail=f"{PROVIDERS_CONFIG_FILE_PATH.name} updated, but failed to reload. Check server logs.")

    except ValidationError as ve:
        logging.error(f"Validation error saving {PROVIDERS_CONFIG_FILE_PATH.name}: {ve.errors()}", exc_info=False)
        return JSONResponse(status_code=400, content={"detail": "Validation Error", "errors": ve.errors()})
    except Exception as e:
        logging.error(f"Error saving {PROVIDERS_CONFIG_FILE_PATH.name}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Could not save {PROVIDERS_CONFIG_FILE_PATH.name}. Error = {e}")
