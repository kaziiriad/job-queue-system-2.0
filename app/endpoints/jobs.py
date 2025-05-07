from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException
from pydantic import ValidationError
from typing import List, Optional
from uuid import UUID
from redis.asyncio import RedisCluster
from ..models.schemas import JobCreate, JobModel, JobUpdate
from ..models.enums import JobStatus, PriorityLevel
from ..services.queue import JobQueueService
from ..core.dependencies import get_redis_client
from ..core.config import settings
from ..utils.redis_keys import RedisKeyManager

job_router = APIRouter(prefix="/jobs", tags=["Jobs"])

@job_router.post("/create", response_model=JobModel)
async def create_job(job_create: JobCreate, redis_client: RedisCluster = Depends(get_redis_client)):
    """
    Create a new job in the queue.
    """
    try:
        job_service = JobQueueService(client=redis_client)
        job_response = await job_service.enqueue_job(job_create)
        return job_response
    except ValidationError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@job_router.get("/{job_id}", response_model=JobModel)
async def get_job(job_id: str, redis_client: RedisCluster = Depends(get_redis_client)):
    """
    Get a job by its ID.
    """
    try:
        job_service = JobQueueService(client=redis_client)
        job_response = await job_service.get_job(job_id)
        return job_response
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    # Handle specific exceptions as needed


@job_router.get("/metrics/queue")
async def get_queue_metrics(redis: RedisCluster = Depends(get_redis_client)):
    service = JobQueueService(redis)
    return {
        "pending_high": await redis.llen(service.keys.priority_queue(PriorityLevel.high)),
        "pending_normal": await redis.llen(service.keys.priority_queue(PriorityLevel.normal)),
        "pending_low": await redis.llen(service.keys.priority_queue(PriorityLevel.low)),
        "processing": await redis.scard(service.keys.processing_queue()),
        "dead_letters": await redis.hlen(service.keys.dead_letter_queue_key())
    }

@job_router.get("/metrics/workers")
async def get_worker_metrics(redis: RedisCluster = Depends(get_redis_client)):
    keys = RedisKeyManager(system_prefix=settings.QUEUE_NAME)
    return {
        "active_workers": await redis.scard(keys.active_workers),
        "stale_workers": await redis.zcount(
            keys.worker_heartbeats, 
            "-inf", 
            datetime.now().timestamp() - 30  # 30s threshold
        )
    }
