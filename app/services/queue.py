from datetime import datetime
import json
from typing import List, Optional
from fastapi import HTTPException
from pydantic import ValidationError
from ..models.schemas import JobCreate, JobModel, JobUpdate
from ..models.enums import JobStatus, PriorityLevel
from ..core.config import settings
from ..utils.redis_ops import execute_pipeline
from ..utils.redis_keys import RedisKeyManager
from collections import defaultdict
import logging
from uuid import UUID, uuid4

logger = logging.getLogger(__name__)


class JobQueueService:
    def __init__(self, client, queue_name: str = settings.REDIS_QUEUE):  # default queue name is 'video_processing_queue'):
        # self.dlq_name = f"{queue_name}:dlq"
        self.redis_client = client
        self.queue_name = queue_name
        self.keys = RedisKeyManager(system_prefix=queue_name)

    async def enqueue_job(self, job: JobCreate) -> dict:
        new_job = JobModel.from_jobcreate(job)
        job_id = new_job.job_id
        priority = new_job.priority
        dependencies = new_job.dependencies or []
        
        def pipeline_operations(pipe):
            # Convert the Pydantic model to JSON string
            pipe.hset(
                self.queue_name,
                job_id,
                new_job.model_dump_json()
            )
            pipe.lpush(self.keys.priority_queue(priority), job_id)  # Add job to the priority-specific processing queue            
            for dep in dependencies:
                pipe.sadd(self.keys.dependencies_key(job_id), dep)
                pipe.sadd(self.keys.dependents_key(dep), job_id)
            
            return {
                "message": "Job added to the queue",
                "job_id": job_id,
                "priority": priority.value,
            }

        return await execute_pipeline(self.redis_client, pipeline_operations)
    
    async def dequeue_job(self) -> Optional[JobModel]:
        # Dequeue a job from the queue by priority
        for priority in [PriorityLevel.high, PriorityLevel.normal, PriorityLevel.low]:
            processing_queue = self.keys.processing_queue()
            job_id = await self.redis_client.brpoplpush(
                self.keys.priority_queue(priority),
                processing_queue,
                timeout=1  # Block for 1 second
            )

            if job_id:
                job_json = await self.redis_client.hget(self.queue_name, job_id)
                if job_json:
                    return JobModel.model_validate_json(job_json.decode('utf-8'))
        return None

    async def get_job(self, job_id: str) -> Optional[JobModel]:
        job_json = await self.redis_client.hget(self.queue_name, job_id)

        return JobModel.model_validate_json(job_json) if job_json else None
        
    async def update_job(self, job_id: str, job_update: JobUpdate) -> JobModel:
        job = await self.get_job(job_id)
        if not job:
            raise HTTPException(status_code=404, detail="Job not found")

        updated_job = JobModel.from_jobupdate(job_update, job)

        def pipeline_operations(pipe):
            pipe.hset(
                self.queue_name,
                job_id,
                updated_job.model_dump_json()
            )
            return updated_job

        return await execute_pipeline(self.redis_client, pipeline_operations)
    
    async def delete_job(self, job_id: str) -> bool:
        job = await self.get_job(job_id)
        if not job:
            raise HTTPException(status_code=404, detail="Job not found")

        def pipeline_operations(pipe):
            pipe.hdel(self.queue_name, job_id)
            pipe.delete(self.keys.dependencies_key(job_id))
            pipe.delete(self.keys.dependents_key(job_id))
            return True

        return await execute_pipeline(self.redis_client, pipeline_operations)
    
    async def get_job_dependencies(self, job_id: str) -> List[JobModel]:
        dependencies = await self.redis_client.smembers(self.keys.dependencies_key(job_id))

        if not dependencies:
            return []

        jobs = []
        for dep in dependencies:
            dep_job = await self.get_job(dep.decode('utf-8'))
            if dep_job:
                jobs.append(dep_job)

        return jobs
    async def get_job_dependents(self, job_id: str) -> List[JobModel]:
        dependents = await self.redis_client.smembers(self.keys.dependents_key(job_id))
        if not dependents:
            return []
            
        jobs = []
        for dep in dependents:
            dep_job = await self.get_job(dep.decode('utf-8'))
            if dep_job:
                jobs.append(dep_job)

        return jobs
    
    async def get_all_jobs(self) -> List[JobModel]:
        job_ids = await self.redis_client.hkeys(self.queue_name)
        jobs = []
        for job_id in job_ids:
            job = await self.get_job(job_id.decode('utf-8'))
            if job:
                jobs.append(job)
        return jobs
    
    async def get_job_status(self, job_id: str) -> JobStatus:
        job = await self.get_job(job_id)
        if not job:
            raise HTTPException(status_code=404, detail="Job not found")

        return job.status
    
    async def cancel_job(self, job_id: str) -> bool:
        job = await self.get_job(job_id)
        if not job:
            raise HTTPException(status_code=404, detail="Job not found")

        # Fetch dependents first
        dependents = await self.get_job_dependents(job_id)

        def pipeline_operations(pipe):
            # Cancel dependents
            for dep_job in dependents:
                if dep_job.status not in [JobStatus.completed, JobStatus.failed]:
                    new_dep_job = JobModel.from_jobupdate(
                        JobUpdate(status=JobStatus.cancelled), dep_job
                    )
                    pipe.hset(
                        self.queue_name,
                        dep_job.job_id,
                        new_dep_job.model_dump_json()
                    )

            # Cancel main job and move to DLQ
            new_job = JobModel.from_jobupdate(JobUpdate(status=JobStatus.cancelled), job)
            pipe.hset(
                self.keys.dead_letter_queue_key(),
                job_id,
                new_job.model_dump_json()
            )
            pipe.hdel(self.queue_name, job_id)
            return True

        return await execute_pipeline(self.redis_client, pipeline_operations)