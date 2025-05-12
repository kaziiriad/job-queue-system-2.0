from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from datetime import datetime, timezone
from redis.asyncio import RedisCluster
from app.core.dependencies import get_redis_client
from app.models.enums import PriorityLevel
from app.services.queue import JobQueueService
from app.utils.redis_keys import RedisKeyManager
from app.core.config import settings
import pathlib

dashboard_router = APIRouter(prefix="/dashboard", tags=["Dashboard"])

# Set up Jinja2 templates
templates_path = pathlib.Path(__file__).parent.parent / "templates"
templates = Jinja2Templates(directory=str(templates_path))

@dashboard_router.get("/metrics/queue")
async def get_queue_metrics(redis: RedisCluster = Depends(get_redis_client)):
    service = JobQueueService(redis)
    return {
        "pending_high": await redis.llen(service.keys.priority_queue(PriorityLevel.high)),
        "pending_normal": await redis.llen(service.keys.priority_queue(PriorityLevel.normal)),
        "pending_low": await redis.llen(service.keys.priority_queue(PriorityLevel.low)),
        "processing": await redis.scard(service.keys.processing_queue()),
        "dead_letters": await redis.hlen(service.keys.dead_letter_queue_key())
    }

@dashboard_router.get("/metrics/workers")
async def get_worker_metrics(redis: RedisCluster = Depends(get_redis_client)):
    keys = RedisKeyManager(system_prefix=settings.QUEUE_NAME)
    return {
        "active_workers": await redis.scard(keys.active_workers_key),
        "stale_workers": await redis.zcount(
            keys.worker_heartbeats, 
            "-inf", 
            datetime.now().timestamp() - 30  # 30s threshold
        )
    }



@dashboard_router.get("/metrics/jobs")
async def get_jobs_result(redis: RedisCluster = Depends(get_redis_client)):
    
    keys = RedisKeyManager(system_prefix=settings.QUEUE_NAME)
    job_results = redis.hgetall(keys.job_results_key())
    return job_results

@dashboard_router.get("/", response_class=HTMLResponse)
async def dashboard_view(request: Request, 
                         redis: RedisCluster = Depends(get_redis_client)):
    """
    Render the dashboard HTML template with queue and worker metrics
    """
    # Get queue metrics
    queue_metrics = await get_queue_metrics(redis)
    
    # Get worker metrics
    worker_metrics = await get_worker_metrics(redis)

    # Get job results
    job_results = await get_jobs_result(redis)
    job_results = {key.decode("utf-8"): value.decode("utf-8") for key, value in job_results.items()}  # Convert bytes to strings
    
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

