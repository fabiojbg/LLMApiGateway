import logging
import uvicorn
from fastapi import FastAPI, Request, Response
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
from pathlib import Path

# Import components from the new core structure
from llm_gateway_core.config.settings import settings
from llm_gateway_core.config.loader import ConfigLoader
from llm_gateway_core.utils.logging_setup import configure_logging
from llm_gateway_core.middleware.request_logging import RequestLoggingMiddleware # Using class-based
from llm_gateway_core.middleware.auth import api_key_auth # Functional middleware
from llm_gateway_core.middleware.chat_logging import log_chat_completions # Functional middleware
from llm_gateway_core.api.v1 import router as api_v1_router
from llm_gateway_core.api.v1.rules_editor import editor_router as api_v1_editor_router # Import the new editor router
from llm_gateway_core.api.v1.stats import stats_router as api_v1_stats_router # Import the new stats router
from llm_gateway_core.db.tokens_usage_db import TokensUsageDB # Import TokensUsageDB

# --- Application Setup ---

# Configure logging first
configure_logging()
logger = logging.getLogger(__name__)

# Optional: Lifespan context manager for startup/shutdown events
# (e.g., initializing database connections, closing clients)
@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("LLM Gateway v1.10: Application startup...")
    # Initialize ConfigLoader and load configurations
    config_loader = ConfigLoader()
    config_loader.load_providers()
    config_loader.load_fallback_rules()
    app.state.config_loader = config_loader
    logger.info("Service configurations loaded and ConfigLoader attached to app.state.")

    # Initialize TokensUsageDB
    tokens_usage_db = TokensUsageDB()
    app.state.tokens_usage_db = tokens_usage_db
    logger.info("TokensUsageDB initialized and attached to app.state.")

    # Initialize other resources here if needed
    # Example: await database.connect()
    yield
    logger.info("Application shutdown...")
    # Clean up resources here if needed
    # Example: await database.disconnect()
    # Example: await http_client.aclose() # If using a shared client

# Create FastAPI app instance
# Determine project root for static files
PROJECT_ROOT = Path(__file__).parent
STATIC_FILES_DIR = PROJECT_ROOT / "static"
STATIC_FILES_DIR.mkdir(parents=True, exist_ok=True) # Ensure static directory exists

app = FastAPI(
    title="LLMGateway",
    description="A gateway for routing LLM requests with fallback and rotation.",
    version="1.0.0", # Consider making this dynamic
    lifespan=lifespan # Add lifespan manager
)

# --- Middleware Configuration ---

# 1. CORS Middleware (usually first)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_allow_origins if settings.cors_allow_origins else ["*"], # Use settings or default
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 2. Request Logging Middleware (using class-based example)
app.add_middleware(RequestLoggingMiddleware)

# 3. Authentication Middleware (using functional example)
# Note: Order matters. Auth should come before sensitive endpoints.
app.middleware("http")(api_key_auth)

# 4. Chat Completion Logging Middleware (conditional based on settings)
if settings.log_chat_messages:
    logger.info("Chat message logging is ENABLED.")
    app.middleware("http")(log_chat_completions)
else:
    logger.info("Chat message logging is DISABLED.")


# --- API Routers ---

# Include the main v1 API router
app.include_router(api_v1_router, prefix="/v1")
# Include the v1 editor API router, also under /v1 prefix
app.include_router(api_v1_editor_router, prefix="/v1", tags=["Config Editor"])
# Include the v1 stats API router, also under /v1 prefix
app.include_router(api_v1_stats_router, prefix="/v1", tags=["Usage Stats"])

# --- Static Files ---
app.mount("/static", StaticFiles(directory=str(STATIC_FILES_DIR)), name="static")
logger.info(f"Static files mounted from {STATIC_FILES_DIR}")

# --- Basic Health Check Endpoint ---
@app.get("/health", tags=["Health"])
async def health_check():
    """Basic health check endpoint."""
    return {"status": "ok"}

# --- Main Execution Block (for direct running) ---
if __name__ == "__main__":
    logger.info(f"Starting Uvicorn server on host {settings.gateway_host} port {settings.gateway_port}")
    uvicorn.run(
        "main:app", # Point to the app instance in this file
        host=settings.gateway_host,
        port=settings.gateway_port,
        reload=settings.debug_mode, # Enable reload only in debug mode
        log_level=settings.log_level.lower() # Pass the lowercase string name directly
    )
