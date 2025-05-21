from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from datetime import datetime, timezone
from redis.asyncio import Redis
import json
from typing import Dict, Any
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
            
            # Try to parse the JSON
            try:
                parsed_value = json.loads(value_str)
                result_dict[key_str] = {
                    "raw": value_str,
                    "parsed": parsed_value
                }
            except json.JSONDecodeError:
                result_dict[key_str] = {
                    "raw": value_str,
                    "parsed": None
                }
            
        return result_dict
    except Exception as e:
        logger.error(f"Error getting job results: {e}")
        return {}  # Return empty dict on error

@dashboard_router.get("/metrics/all-jobs")
async def get_all_jobs(redis: Redis = Depends(get_redis_client)):
    try:
        service = JobQueueService(redis)
        jobs = await service.get_all_jobs()
        return [job.model_dump() for job in jobs]
    except Exception as e:
        logger.error(f"Error getting all jobs: {e}")
        return []

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
        
        # Get all jobs
        all_jobs = await get_all_jobs(redis)
        
        # Create a job status lookup dictionary
        job_status_lookup = {job["job_id"]: job["status"] for job in all_jobs}
        
        # Combine job results with job status
        combined_job_data = {}
        for job_id, result_data in job_results.items():
            combined_job_data[job_id] = {
                "result": result_data,
                "status": job_status_lookup.get(job_id, "unknown")
            }
        
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
                "job_results": combined_job_data,
                "all_jobs": all_jobs
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

