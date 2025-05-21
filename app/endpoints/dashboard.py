from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from datetime import datetime, timezone
from redis.asyncio import Redis
from ..core.dependencies import get_redis_client
from ..models.enums import PriorityLevel
from ..services.queue import JobQueueService
from ..utils.redis_keys import RedisKeyManager
from ..core.config import settings
import pathlib
import logging

logger = logging.getLogger(__name__)

dashboard_router = APIRouter(prefix="/dashboard", tags=["Dashboard"])

# Set up Jinja2 templates
templates_path = pathlib.Path(__file__).parent.parent / "templates"
templates = Jinja2Templates(directory=str(templates_path))

@dashboard_router.get("/metrics/queue")
async def get_queue_metrics(redis: Redis = Depends(get_redis_client)):
    service = JobQueueService(redis)
    return {
        "pending_high": await redis.llen(service.keys.priority_queue(PriorityLevel.high)),
        "pending_normal": await redis.llen(service.keys.priority_queue(PriorityLevel.normal)),
        "pending_low": await redis.llen(service.keys.priority_queue(PriorityLevel.low)),
        "processing": await redis.llen(service.keys.processing_queue_key()),
        "dead_letters": await redis.hlen(service.keys.dead_letter_queue_key())
    }

@dashboard_router.get("/metrics/workers")
async def get_worker_metrics(redis: Redis = Depends(get_redis_client)):
    keys = RedisKeyManager(system_prefix=settings.QUEUE_NAME)
    return {
        "active_workers": await redis.scard(keys.active_workers_key()),
        "stale_workers": await redis.zcount(
            keys.worker_heartbeats(), 
            "-inf", 
            datetime.now().timestamp() - 30  # 30s threshold
        )
    }



@dashboard_router.get("/metrics/jobs")
async def get_jobs_result(redis: Redis = Depends(get_redis_client)):
    try:
        keys = RedisKeyManager(system_prefix=settings.QUEUE_NAME)
        job_results = await redis.hgetall(keys.job_results_key())
        
        # Convert job results to a dictionary of strings
        result_dict = {}
        for key, value in job_results.items():
            # Handle both bytes and string keys/values
            key_str = key.decode("utf-8") if isinstance(key, bytes) else key
            value_str = value.decode("utf-8") if isinstance(value, bytes) else value
            result_dict[key_str] = value_str
            
        return result_dict
    except Exception as e:
        logger.error(f"Error getting job results: {e}")
        return {}  # Return empty dict on error

@dashboard_router.get("/", response_class=HTMLResponse)
async def dashboard_view(request: Request, 
                         redis: Redis = Depends(get_redis_client)):
    """
    Render the dashboard HTML template with queue and worker metrics
    """
    try:
        # Get queue metrics
        queue_metrics = await get_queue_metrics(redis)
        
        # Get worker metrics
        worker_metrics = await get_worker_metrics(redis)

        # Get job results
        job_results = await get_jobs_result(redis)
        
        # Format current time for display
        last_updated = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
        
        # Render the template with the metrics data
        return templates.TemplateResponse(
            "dashboard.html", 
            {
                "request": request,  # Required by Jinja2Templates
                "queue_metrics": queue_metrics,
                "worker_metrics": worker_metrics,
                "last_updated": last_updated,
                "job_results": job_results,
            }
        )
    except Exception as e:
        logger.error(f"Error rendering dashboard: {e}")
        # Return a simple error page
        return HTMLResponse(
            content=f"""
            <html>
                <head><title>Dashboard Error</title></head>
                <body>
                    <h1>Error Loading Dashboard</h1>
                    <p>An error occurred while loading the dashboard: {str(e)}</p>
                    <p><a href="/">Return to Home</a></p>
                </body>
            </html>
            """,
            status_code=500
        )

