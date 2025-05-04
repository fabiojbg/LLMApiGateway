# This file marks llm_gateway_core/api/v1 as a Python package
# and can be used to aggregate routers from this version.

from fastapi import APIRouter
from .chat import router as chat_router
from .models import router as models_router # Import the new models router

# Aggregate all routers for v1
router = APIRouter()
router.include_router(chat_router, prefix="/chat", tags=["Chat Completions V1"])
router.include_router(models_router, prefix="/models", tags=["Models V1"]) # Include the models router

# You could add other v1 routers here
