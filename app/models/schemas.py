from datetime import datetime
from typing import Optional, List, Dict
from pydantic import BaseModel, Field, field_validator
import uuid

from .enums import JobStatus, PriorityLevel



class JobResult(BaseModel):
    status: JobStatus
    progress: float = 0.0
    result: Optional[Dict] = None
    error_message: Optional[str] = None

class JobCreate(BaseModel):
    job_title: str
    priority: PriorityLevel
    status: JobStatus = JobStatus.pending
    dependencies: Optional[List[str]] = None
    max_retries: int = 3

class JobUpdate(BaseModel):
    status: Optional[JobStatus] = None
    priority: Optional[PriorityLevel] = None
    error_message: Optional[str] = None
    retry_count: Optional[int] = Field(None, ge=0)
    updated_at: datetime = Field(default_factory=datetime.now)

    @field_validator('retry_count')
    def validate_retry_count(cls, v):
        if v is not None and v < 0:
            raise ValueError('retry_count must be non-negative')
        return v

class JobModel(BaseModel):
    job_id: str
    job_title : str
    created_at: datetime = Field(default_factory=datetime.now)
    updated_at: Optional[datetime] = None
    status: JobStatus
    priority: PriorityLevel
    dependencies: Optional[List[str]] = None
    # job_request: JobRequest
    error_message: Optional[str] = None
    retry_count: int = Field(default=0, ge=0)  # Default 0, must be >= 0
    max_retries: int = Field(default=3, ge=1)  # Default 3, must be >= 1

    @classmethod
    def from_jobcreate(cls, job_create: JobCreate) -> 'JobModel':
        """Create a JobModel from a JobCreate instance."""
        # Create a dictionary from the JobCreate model
        job_data = job_create.model_dump()
        
        # Add the job_id field
        job_data['job_id'] = str(uuid.uuid4())
        
        # Set default values for fields not in JobCreate
        job_data['created_at'] = datetime.now()
        job_data['retry_count'] = 0
        
        # Create and return the JobModel
        return cls(**job_data)

    @classmethod
    def from_jobupdate(cls, job_update: JobUpdate, existing_job: 'JobModel') -> 'JobModel':
        # Merge the update data into the existing JobModel
        updated_data = existing_job.model_dump(exclude_unset=True)  # Get existing job data as a dictionary
        update_data = job_update.model_dump(exclude_unset=True)    # Get updates as a dictionary

        # Merge the dictionaries
        updated_data.update(update_data)
        updated_data['updated_at'] = datetime.now()  # Always update the timestamp

        # Create a new JobModel instance with the merged data
        return cls(**updated_data)
    
        
    class Config:
        json_encoders = {
            datetime: lambda v: v.isoformat(),
        }

class Worker(BaseModel):
    worker_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    available: bool = True
    last_heartbeat: str = Field(default_factory=lambda: datetime.now().isoformat())
    current_job: Optional[str] = None
    processed_jobs: int = 0
    failed_jobs: int = 0
    start_time: datetime = Field(default_factory=lambda: datetime.now())
    status: Optional[str] = None
    class Config:
        populate_by_name = True
        validate_assignment = True
