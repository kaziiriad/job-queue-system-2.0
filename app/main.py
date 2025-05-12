from fastapi import FastAPI, Request, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.responses import HTMLResponse
from .core.config import settings
from .endpoints.dashboard import dashboard_router
from .endpoints.jobs import job_router
from .core.dependencies import get_redis_client
from .services.queue import JobQueueService
from .models.enums import JobStatus
import os
from datetime import datetime
import pathlib

# Setup templates with correct path
templates_path = pathlib.Path(__file__).parent / "templates"
templates = Jinja2Templates(directory=str(templates_path))


app = FastAPI(
    title="Job Queue API",
    description="API for managing job queues",
    version="1.0.0",
)

# Mount static files directory if it exists
static_dir = os.path.join(os.path.dirname(__file__), "static")
if os.path.exists(static_dir):
    app.mount("/static", StaticFiles(directory=static_dir), name="static")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(dashboard_router)
app.include_router(job_router)

@app.get("/", response_class=HTMLResponse)
async def home(request: Request, redis = Depends(get_redis_client)):
    """
    Render the home page with system statistics.
    """
    try:
        # Get job statistics
        job_service = JobQueueService(redis)
        
        # Get all jobs
        jobs = await job_service.get_all_jobs()
        
        # Count jobs by status
        pending_jobs = sum(1 for job in jobs if job.status in [JobStatus.pending, JobStatus.retrying])
        processing_jobs = sum(1 for job in jobs if job.status == JobStatus.processing)
        completed_jobs = sum(1 for job in jobs if job.status == JobStatus.completed)
        failed_jobs = sum(1 for job in jobs if job.status in [JobStatus.failed, JobStatus.cancelled])
        
        stats = {
            "pending_jobs": pending_jobs,
            "processing_jobs": processing_jobs,
            "completed_jobs": completed_jobs,
            "failed_jobs": failed_jobs
        }
    except Exception as e:
        # Log the error but still render the template with empty stats
        print(f"Error fetching job statistics: {str(e)}")
        stats = {
            "pending_jobs": 0,
            "processing_jobs": 0,
            "completed_jobs": 0,
            "failed_jobs": 0
        }
    
    # Get current year for copyright
    current_year = datetime.now().year
    
    return templates.TemplateResponse(
        "home.html",
        {
            "request": request,
            "stats": stats,
            "current_year": current_year
        }
    )

