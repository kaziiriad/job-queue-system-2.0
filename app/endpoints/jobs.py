from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from pydantic import ValidationError
from typing import List, Optional
import pathlib
from uuid import UUID
from redis.asyncio import RedisCluster
from ..models.schemas import JobCreate, JobModel, JobUpdate
from ..models.enums import JobStatus, PriorityLevel
from ..services.queue import JobQueueService
from ..core.dependencies import get_redis_client
from ..core.config import settings
from ..utils.redis_keys import RedisKeyManager

job_router = APIRouter(prefix="/jobs", tags=["Jobs"])

# Set up Jinja2 templates
templates_path = pathlib.Path(__file__).parent.parent / "templates"
templates = Jinja2Templates(directory=str(templates_path))


@job_router.get("/manage", response_class=HTMLResponse, tags=["UI"])
async def job_management_ui(request: Request, redis_client: RedisCluster = Depends(get_redis_client)):
    """
    Render the job management UI.
    """
    try:
        job_service = JobQueueService(client=redis_client)
        jobs = await job_service.get_all_jobs()
        
        # Sort jobs by creation date (newest first)
        jobs.sort(key=lambda x: x.created_at, reverse=True)
        
        return templates.TemplateResponse(
            "job_management.html",
            {
                "request": request,
                "jobs": jobs
            }
        )
    except Exception as e:
        # Log the error but still render the template with empty jobs list
        print(f"Error fetching jobs: {str(e)}")
        return templates.TemplateResponse(
            "job_management.html",
            {
                "request": request,
                "jobs": []
            }
        )

@job_router.get("/", response_model=List[JobModel])
async def get_all_jobs(redis_client: RedisCluster = Depends(get_redis_client)):
    """
    Get all jobs.
    """
    try:
        job_service = JobQueueService(client=redis_client)
        jobs = await job_service.get_all_jobs()
        return jobs
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

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

@job_router.put("/{job_id}", response_model=JobModel)
async def update_job(job_id: str, job_update: JobUpdate, redis_client: RedisCluster = Depends(get_redis_client)):
    """
    Update a job by its ID.
    """
    try:
        job_service = JobQueueService(client=redis_client)
        job_response = await job_service.update_job(job_id, job_update)
        return job_response
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    # Handle specific exceptions as needed

@job_router.post("/cancel/{job_id}", response_model=JobModel)
async def cancel_job(job_id: str, redis_client: RedisCluster = Depends(get_redis_client)):
    """
    Cancel a job by its ID.
    """
    try:
        job_service = JobQueueService(client=redis_client)
        job_response = await job_service.cancel_job(job_id)
        return job_response
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    # Handle specific exceptions as needed

