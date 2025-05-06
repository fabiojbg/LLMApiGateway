import logging
import json5
from fastapi import APIRouter, Request, HTTPException, Body
from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse
from pathlib import Path
from pydantic import ValidationError

# Assuming ModelFallbackConfig is the Pydantic model for the entire rules structure (list of rules)
# If ModelFallbackConfig is for a single rule, we'd need a List[ModelFallbackConfig]
from llm_gateway_core.config.loader import ModelFallbackConfig # Adjust if Pydantic models are elsewhere

logger = logging.getLogger(__name__)

editor_router = APIRouter()

# Path to the models_fallback_rules.json file
# This should ideally come from a shared configuration or the ConfigLoader instance
# For now, constructing it similarly to how ConfigLoader does.
FALLBACK_RULES_FILENAME = "models_fallback_rules.json"
CONFIG_FILE_PATH = Path(__file__).parent.parent.parent.parent / FALLBACK_RULES_FILENAME

HTML_DIR = Path(__file__).parent.parent.parent.parent / "static" # project_root/static

# The router itself will be included with a prefix like /v1 or /admin in main.py
@editor_router.get("/ui/rules-editor", response_class=HTMLResponse, tags=["Config Editor UI"])
async def get_editor_page(request: Request):
    """Serves the HTML page for the configuration editor."""
    editor_html_path = HTML_DIR / "rules-editor.html"
    if not editor_html_path.exists():
        logger.error(f"Editor HTML file not found at {editor_html_path}")
        raise HTTPException(status_code=404, detail="Editor page not found.")
    try:
        with open(editor_html_path, "r") as f:
            html_content = f.read()
        return HTMLResponse(content=html_content)
    except Exception as e:
        logger.error(f"Error reading editor HTML file: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Could not load editor page.")

# If router is included with prefix /v1, this becomes /v1/config/models-rules
@editor_router.get("/config/models-rules", response_class=PlainTextResponse, tags=["Config Editor API"])
async def get_models_rules_text(request: Request):
    """Fetches the current raw text content of models_fallback_rules.json."""
    if not CONFIG_FILE_PATH.exists():
        logger.error(f"Configuration file {CONFIG_FILE_PATH.name} not found.")
        raise HTTPException(status_code=404, detail=f"{CONFIG_FILE_PATH.name} not found.")
    try:
        with open(CONFIG_FILE_PATH, "r", encoding="utf-8") as f:
            content = f.read()
        return PlainTextResponse(content=content)
    except Exception as e:
        logger.error(f"Error reading {CONFIG_FILE_PATH.name}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Could not read {CONFIG_FILE_PATH.name}.")

# If router is included with prefix /v1, this becomes /v1/config/models-rules
@editor_router.post("/config/models-rules", tags=["Config Editor API"])
async def save_models_rules(request: Request, payload_text: str = Body(..., media_type="text/plain")):
    """
    Validates and saves the updated models_fallback_rules.json.
    Triggers a configuration reload on success.
    """
    config_loader = request.app.state.config_loader
    if not config_loader:
        logger.error("ConfigLoader not found in application state.")
        raise HTTPException(status_code=500, detail="Internal server error: ConfigLoader not available.")

    try:
        parsed_for_validation = json5.loads(payload_text)

        if not isinstance(parsed_for_validation, list):
            raise HTTPException(
                status_code=400, 
                detail="Invalid format: Expected a list of rule objects."
            )
        
        _ = [ModelFallbackConfig(**item) for item in parsed_for_validation] # Perform validation
        
        with open(CONFIG_FILE_PATH, "w", encoding="utf-8") as f:
            f.write(payload_text)

        logger.info(f"Successfully wrote updated configuration (with comments) to {CONFIG_FILE_PATH.name}.")

        # Attempt to reload the configuration
        if config_loader.reload_fallback_rules():
            logger.info(f"Configuration {CONFIG_FILE_PATH.name} reloaded successfully.")
            return {"message": f"{CONFIG_FILE_PATH.name} updated and reloaded successfully."}
        else:
            logger.error(f"Configuration {CONFIG_FILE_PATH.name} was updated, but failed to reload.")
            # The file is updated, but the running config might be stale. This is a critical state.
            raise HTTPException(status_code=500, detail=f"{CONFIG_FILE_PATH.name} updated, but failed to reload. Check server logs.")

    except ValidationError as ve:
        logger.error(f"Validation error saving {CONFIG_FILE_PATH.name}: {ve.errors()}", exc_info=False) # No need for full stack trace for validation
        # Provide detailed validation errors to the client
        return JSONResponse(status_code=400, content={"detail": "Validation Error", "errors": ve.errors()})
    except Exception as e:
        logger.error(f"Error saving {CONFIG_FILE_PATH.name}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Could not save {CONFIG_FILE_PATH.name}.")
