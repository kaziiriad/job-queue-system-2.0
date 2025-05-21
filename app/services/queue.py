import json
from typing import List, Optional
from fastapi import HTTPException
from ..models.schemas import JobCreate, JobModel, JobUpdate
from ..models.enums import JobStatus, PriorityLevel
from ..core.config import settings
from ..utils.redis_ops import execute_pipeline # type: ignore
from ..utils.redis_keys import RedisKeyManager # type: ignore
import logging

logger = logging.getLogger(__name__)


class JobQueueService:
    def __init__(self, client, queue_name: str = settings.QUEUE_NAME):  # default queue name is 'video_processing_queue'):
        # self.dlq_name = f"{queue_name}:dlq"
        self.redis_client = client
        self.queue_name = queue_name
        self.keys = RedisKeyManager(system_prefix=queue_name)

    async def enqueue_job(self, job: JobCreate) -> JobModel:
        """
        Create a new job and add it to the appropriate priority queue.
        """
        try:
            # Create a new JobModel from JobCreate
            new_job = JobModel.from_jobcreate(job)
            job_id = new_job.job_id
            priority = new_job.priority
            dependencies = new_job.dependencies or []
            
            logger.debug(f"Created job: {new_job.model_dump()}")
            
            def pipeline_operations(pipe):
                # Store the complete job data
                pipe.hset(
                    self.queue_name,
                    job_id,
                    new_job.model_dump_json()
                )
                
                # Add job to the priority-specific processing queue
                pipe.lpush(self.keys.priority_queue(priority), job_id)
                
                # Notify about new job
                pipe.publish(f"{self.queue_name}:new_job", job_id)
                
                # Handle dependencies
                for dep in dependencies:
                    pipe.sadd(self.keys.job_dependencies_key(job_id), dep)
                    pipe.sadd(self.keys.job_dependents_key(dep), job_id)
                
                return new_job

            return await execute_pipeline(self.redis_client, pipeline_operations)
        except Exception as e:
            logger.error(f"Error enqueueing job: {e}")
            raise HTTPException(status_code=500, detail=f"Failed to enqueue job: {str(e)}")
    
    async def dequeue_job(self) -> Optional[JobModel]:
        """
        Dequeue a job from the queue by priority.
        """
        try:
            for priority in [PriorityLevel.high, PriorityLevel.normal, PriorityLevel.low]:
                processing_queue = self.keys.processing_queue_key()
                job_id = await self.redis_client.brpoplpush(
                    self.keys.priority_queue(priority),
                    processing_queue,
                    timeout=1  # Block for 1 second
                )

                if job_id:
                    # Handle both bytes and string job_id
                    if isinstance(job_id, bytes):
                        job_id = job_id.decode('utf-8')
                    
                    job_json = await self.redis_client.hget(self.queue_name, job_id)
                    if job_json:
                        # Handle both bytes and string job_json
                        if isinstance(job_json, bytes):
                            job_json = job_json.decode('utf-8')
                        
                        return JobModel.model_validate_json(job_json)
            return None
        except Exception as e:
            logger.error(f"Error dequeuing job: {e}")
            raise HTTPException(status_code=500, detail=f"Failed to dequeue job: {str(e)}")

    async def get_job(self, job_id: str) -> Optional[JobModel]:
        """
        Get a job by its ID.
        """
        try:
            job_json = await self.redis_client.hget(self.queue_name, job_id)
            
            if not job_json:
                return None
                
            # Handle both bytes and string job data
            if isinstance(job_json, bytes):
                job_json = job_json.decode('utf-8')
                
            return JobModel.model_validate_json(job_json)
        except Exception as e:
            logger.error(f"Error getting job {job_id}: {e}")
            raise HTTPException(status_code=500, detail=f"Failed to get job: {str(e)}")
        
    # async def update_job(self, job_id: str, job_update: JobUpdate) -> JobModel:
    #     job = await self.get_job(job_id)
    #     if not job:
    #         raise HTTPException(status_code=404, detail="Job not found")

    #     updated_job = JobModel.from_jobupdate(job_update, job)

    #     def pipeline_operations(pipe):
    #         pipe.hset(
    #             self.queue_name,
    #             job_id,
    #             updated_job.model_dump_json()
    #         )
    #         pipe.delete(self.keys.processing_queue_key(job_id))

    #         if job_update.status == JobStatus.completed:
    #             pipe.publish(f"{self.queue_name}:job_completed", job_id)
    #         return updated_job

    #     return await execute_pipeline(self.redis_client, pipeline_operations)
        
    async def update_job(self, job_id: str, job_update: JobUpdate) -> JobModel:
        job = await self.get_job(job_id)
        if not job:
            raise HTTPException(status_code=404, detail="Job not found")

        updated_job = JobModel.from_jobupdate(job_update, job)

        def pipeline_operations(pipe):
            # Update the job in the main hash
            pipe.hset(
                self.queue_name,
                job_id,
                updated_job.model_dump_json()
            )
            
            # Remove from processing queue
            pipe.lrem(self.keys.processing_queue_key(), 0, job_id)
            
            if job_update.status == JobStatus.completed:
                # Publish completion event
                pipe.publish(f"{self.queue_name}:job_completed", job_id)
                
                # Store result if provided
                # if hasattr(job_update, 'result') and job_update.result:
                #     pipe.hset(
                #         self.keys.job_results_key(),
                #         job_id,
                #         json.dumps(job_update.result)
                #     )
                    
                # Optionally set expiration on the job data
                # pipe.expire(f"{self.queue_name}:job:{job_id}", 86400)  # 24 hours
                
            elif job_update.status == JobStatus.failed:
                # Publish failure event
                pipe.publish(f"{self.queue_name}:job_failed", job_id)
                
                # Store error information
                if job_update.error_message:
                    pipe.hset(
                        self.keys.job_errors_key(),
                        job_id,
                        job_update.error_message
                    )
                
                # If retries are exhausted, move to DLQ
                if job.retry_count >= job.max_retries:
                    pipe.hset(
                        self.keys.dead_letter_queue_key(),
                        job_id,
                        updated_job.model_dump_json()
                    )
                    pipe.publish(f"{self.queue_name}:job_to_dlq", job_id)
                else:
                    # If retries not exhausted, the worker should handle requeuing
                    pass
            
            return updated_job

        return await execute_pipeline(self.redis_client, pipeline_operations)
    

    async def delete_job(self, job_id: str) -> bool:
        job = await self.get_job(job_id)
        if not job:
            raise HTTPException(status_code=404, detail="Job not found")

        def pipeline_operations(pipe):
            pipe.hdel(self.queue_name, job_id)
            pipe.delete(self.keys.job_dependencies_key(job_id))
            pipe.delete(self.keys.job_dependents_key(job_id))
            return True

        return await execute_pipeline(self.redis_client, pipeline_operations)
    
    async def get_job_dependencies(self, job_id: str) -> List[JobModel]:
        """
        Get all dependencies for a job.
        """
        try:
            dependencies = await self.redis_client.smembers(self.keys.job_dependencies_key(job_id))

            if not dependencies:
                return []

            jobs = []
            for dep in dependencies:
                # Handle both bytes and string dependency IDs
                dep_id = dep.decode('utf-8') if isinstance(dep, bytes) else dep
                
                dep_job = await self.get_job(dep_id)
                if dep_job:
                    jobs.append(dep_job)

            return jobs
        except Exception as e:
            logger.error(f"Error getting job dependencies for {job_id}: {e}")
            raise HTTPException(status_code=500, detail=f"Failed to get job dependencies: {str(e)}")
    async def get_job_dependents(self, job_id: str) -> List[JobModel]:
        """
        Get all jobs that depend on this job.
        """
        try:
            dependents = await self.redis_client.smembers(self.keys.job_dependents_key(job_id))
            
            if not dependents:
                return []
                
            jobs = []
            for dep in dependents:
                # Handle both bytes and string dependent IDs
                dep_id = dep.decode('utf-8') if isinstance(dep, bytes) else dep
                
                dep_job = await self.get_job(dep_id)
                if dep_job:
                    jobs.append(dep_job)

            return jobs
        except Exception as e:
            logger.error(f"Error getting job dependents for {job_id}: {e}")
            raise HTTPException(status_code=500, detail=f"Failed to get job dependents: {str(e)}")
    
    async def get_all_jobs(self) -> List[JobModel]:
        """
        Get all jobs from the queue.
        """
        try:
            job_ids = await self.redis_client.hkeys(self.queue_name)
            jobs = []
            for job_id in job_ids:
                # Handle both bytes and string job_ids
                if isinstance(job_id, bytes):
                    job_id = job_id.decode('utf-8')
                
                job = await self.get_job(job_id)
                if job:
                    jobs.append(job)
            return jobs
        except Exception as e:
            logger.error(f"Error getting all jobs: {e}")
            raise HTTPException(status_code=500, detail=f"Failed to get jobs: {str(e)}")
    
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
    async def move_to_dlq(self, job_id: str) -> bool:
        job = await self.get_job(job_id)
        if not job:
            raise HTTPException(status_code=404, detail="Job not found")

        def pipeline_operations(pipe):
            new_job = JobModel.from_jobupdate(JobUpdate(status=JobStatus.failed), job)
            pipe.hset(
                self.keys.dead_letter_queue_key(),
                job_id,
                new_job.model_dump_json()
            )
            pipe.hdel(self.queue_name, job_id)
            return True

        return await execute_pipeline(self.redis_client, pipeline_operations)
    
    async def store_job_result(self, job_id: str, result: dict):
        await self.redis_client.hset(
            self.keys.job_results_key(),
            job_id,
            json.dumps(result)
        )
