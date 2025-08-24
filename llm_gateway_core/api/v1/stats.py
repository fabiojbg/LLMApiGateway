import logging
from datetime import datetime, timedelta
from fastapi import APIRouter, Request, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse
from pathlib import Path

# Import the TokensUsageDB
from llm_gateway_core.db.tokens_usage_db import TokensUsageDB

stats_router = APIRouter()

PROJECT_ROOT = Path(__file__).parent.parent.parent.parent
HTML_DIR = PROJECT_ROOT / "static"

@stats_router.get("/ui/usage-stats", response_class=HTMLResponse, tags=["Usage Stats UI"])
async def get_usage_stats_page(request: Request):
    """Serves the HTML page for the token usage statistics viewer."""
    stats_html_path = HTML_DIR / "usage-stats.html"
    if not stats_html_path.exists():
        logging.error(f"Usage stats HTML file not found at {stats_html_path}")
        raise HTTPException(status_code=404, detail="Usage statistics page not found.")
    try:
        with open(stats_html_path, "r") as f:
            html_content = f.read()
        return HTMLResponse(content=html_content)
    except Exception as e:
        logging.error(f"Error reading usage stats HTML file: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Could not load usage statistics page.")

@stats_router.get("/api/usage-stats/{period}", response_class=JSONResponse, tags=["Usage Stats API"])
async def get_aggregated_stats(request: Request, period: str):
    """
    Fetches aggregated token usage statistics by the specified period and model.
    """
    tokens_usage_db: TokensUsageDB = request.app.state.tokens_usage_db
    if not tokens_usage_db:
        logging.error("TokensUsageDB not found in application state.")
        raise HTTPException(status_code=500, detail="Internal server error: TokensUsageDB not available.")
    
    try:
        # Validate period input
        if period not in ['hour', 'day', 'week', 'month']:
            raise HTTPException(status_code=400, detail="Invalid period. Must be 'hour', 'day', 'week', or 'month'.")

        # Calculate start_date based on period
        end_date = datetime.now()
        start_date = None
        if period == 'hour':
            start_date = end_date - timedelta(hours=24)
        elif period == 'day':
            start_date = end_date - timedelta(weeks=2)
        elif period == 'week':
            start_date = end_date - timedelta(weeks=15)
        elif period == 'month':
            start_date = end_date - timedelta(days=365) # Approximately 12 months

        aggregated_data = tokens_usage_db.get_aggregated_usage(period, start_date=start_date, end_date=end_date)
        return JSONResponse(content=aggregated_data)
    except HTTPException as he:
        raise he
    except Exception as e:
        logging.error(f"Error fetching aggregated usage statistics for period '{period}': {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Could not retrieve usage statistics: {e}")

@stats_router.get("/api/usage-records", response_class=JSONResponse, tags=["Usage Stats API"])
async def get_usage_records(request: Request, limit: int = 25, offset: int = 0):
    """
    Fetches the latest token usage records with pagination.
    """
    tokens_usage_db: TokensUsageDB = request.app.state.tokens_usage_db
    if not tokens_usage_db:
        logging.error("TokensUsageDB not found in application state.")
        raise HTTPException(status_code=500, detail="Internal server error: TokensUsageDB not available.")
    
    try:
        records = tokens_usage_db.get_latest_usage_records(limit=limit, offset=offset)
        total_records = tokens_usage_db.get_total_records_count()
        return JSONResponse(content={"records": records, "total_records": total_records})
    except HTTPException as he:
        raise he
    except Exception as e:
        logging.error(f"Error fetching usage records: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Could not retrieve usage records: {e}")
