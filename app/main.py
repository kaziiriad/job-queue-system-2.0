from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from app.core.config import settings
from app.endpoints.dashboard import dashboard_router
from app.endpoints.jobs import job_router
import os

# Setup templates
templates = Jinja2Templates(directory="app/templates")


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


@app.get("/")
async def root():
    return {"message": "Hello World"}

