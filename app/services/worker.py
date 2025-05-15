import asyncio
from datetime import datetime, timezone
from typing import Optional
import uuid  # Import uuid module explicitly
import logging
from fastapi import HTTPException
from redis.asyncio import Redis

# Use relative imports
from ..core.dependencies import get_redis_client
from ..models.schemas import JobModel, JobUpdate, JobResult, Worker
from ..models.enums import JobStatus
from ..core.config import settings
from ..utils.redis_keys import RedisKeyManager
from ..utils.redis_ops import execute_pipeline
from .queue import JobQueueService

class WorkerService:
    def __init__(self, client: Redis, queue_name: str = settings.QUEUE_NAME):
        self.redis_client = client
        self.queue_name = queue_name
        self.keys = RedisKeyManager(system_prefix=queue_name)
        self.job_queue_service = JobQueueService(client=self.redis_client, queue_name=self.queue_name)
        self.logger = logging.getLogger(__name__)
        self.worker = None
        self.worker_id = None
        self.worker_heartbeat_interval = 10  # seconds
        # self.worker_heartbeat_timeout = 30

        # Backoff strategy parameters
        self.max_backoff = 60  # Maximum sleep time in seconds
        self.initial_backoff = 1  # Start with 1 second
        self.current_backoff = self.initial_backoff
        self.consecutive_empty_jobs = 0
        self.empty_threshold = 3  # Number of consecutive empty jobs before starting backoff
        
        # Event to wake up worker when new job is available
        self.new_job_event = asyncio.Event()

    async def register_worker(self) -> Optional[dict]:
        # Fix: Use uuid.uuid4() to generate a random UUID
        self.worker_id = str(uuid.uuid4())
        # Convert datetime to ISO format string for last_heartbeat
        current_time_iso = datetime.now(timezone.utc).isoformat()
        
        self.worker = Worker(
            worker_id=self.worker_id,
            status='active',
            last_heartbeat=current_time_iso,  # Use string format instead of datetime object
            queue_name=self.queue_name
        )
        def pipeline_operations(pipe):
            
            pipe.zadd(
                self.keys.worker_heartbeats(),
                {self.worker_id: datetime.now(timezone.utc).timestamp()}
            )
            pipe.sadd(self.keys.active_workers_key(), self.worker_id)
            return {
                "message": "Worker registered",
                "worker_id": self.worker_id,
            }
        return await execute_pipeline(self.redis_client, pipeline_operations)
        # return self.worker
    
    async def deregister_worker(self):
        if not self.worker_id:
            raise HTTPException(status_code=400, detail="Worker not registered")

        def pipeline_operations(pipe):
            pipe.srem(self.keys.active_workers_key(), self.worker_id)
            pipe.zrem(self.keys.worker_heartbeats(), self.worker_id)
            pipe.unsubscribe(f"{self.queue_name}:new_job")

            self.logger.info(f"Worker {self.worker_id} deregistered.")

        await execute_pipeline(self.redis_client, pipeline_operations)
        self.worker = None
        self.worker_id = None

    async def send_heartbeat(self) -> Optional[dict]:

        if not self.worker_id:
            raise HTTPException(status_code=400, detail="Worker not registered")
        
        await self.redis_client.zadd(
            self.keys.worker_heartbeats(),
            {self.worker_id: datetime.now(timezone.utc).timestamp()}
        )
    
    # async def check_stale_workers(self):
    #     current_time = datetime.now(timezone.utc).timestamp()
    #     stale_workers = await self.redis_client.zrangebyscore(
    #         self.keys.worker_heartbeats(),
    #         min=0,
    #         max=current_time - self.worker_heartbeat_timeout
    #     )
    #     return stale_workers
    
    # async def mark_worker_as_dead(self, stale_workers: list[UUID]):
    #     def pipeline_operations(pipe):
    #         for worker_id in stale_workers:
    #             pipe.srem(self.keys.active_workers(), worker_id)
    #             pipe.zrem(self.keys.worker_heartbeats(), worker_id)
    #             self.logger.info(f"Worker {worker_id} marked as dead.")
                
        
    #     await execute_pipeline(self.redis_client, pipeline_operations)

    async def _heartbeat_task(self):
        while True:
            await self.send_heartbeat()
            await asyncio.sleep(self.worker_heartbeat_interval)

            
    async def _check_dependencies(self, job: JobModel) -> bool:
        dependencies = await self.job_queue_service.get_job_dependencies(job.job_id)
        for dep in dependencies:
            if dep.status in [JobStatus.cancelled, JobStatus.failed]:
                self.logger.error(f"Dependency {dep.job_id} failed. Cancelling job {job.job_id}.")
                await self.job_queue_service.cancel_job(job.job_id)
                return False
            while dep.status not in [JobStatus.completed]:
                await asyncio.sleep(1)
                dep = await self.job_queue_service.get_job(dep.job_id)
        return True
    
    async def _process_job(self, job: JobModel) -> JobResult:
        try:
            # Simulate job processing
            for i in range(10):
                await asyncio.sleep(1)  # Simulate work
                self.logger.info(f"Processing job {job.job_id}...\nProgress {(i + 1) * 10}%")
                if job.status == JobStatus.cancelled:
                    self.logger.info(f"Job {job.job_id} cancelled. Exiting...")
                    await self.job_queue_service.update_job(
                        job.job_id,
                        JobUpdate(status=JobStatus.cancelled)
                    )
                    return JobResult(job_id=job.job_id, status=JobStatus.cancelled)
                elif job.status == JobStatus.failed:
                    self.logger.error(f"Job {job.job_id} failed. Exiting...")
                    await self.job_queue_service.update_job(
                        job.job_id,
                        JobUpdate(status=JobStatus.failed)
                    )
                    return JobResult(job_id=job.job_id, status=JobStatus.failed)
                # asyncio.sleep(1)
            await self.job_queue_service.update_job(
                job.job_id,
                JobUpdate(status=JobStatus.completed)
            )
            
            return JobResult(status=JobStatus.completed)

        except Exception as e:
            await self.job_queue_service.update_job(
                job.job_id,
                JobUpdate(status=JobStatus.failed, error_message=str(e))
            )
            return JobResult(job_id=job.job_id, status=JobStatus.failed, error_message=str(e))

    async def process_next_job(self) -> tuple[bool, Optional[JobResult]]:
        job = await self.job_queue_service.dequeue_job()
        if not job:
            self.consecutive_empty_jobs += 1
            if self.consecutive_empty_jobs > self.empty_threshold:
                if self.consecutive_empty_jobs == self.empty_threshold + 1:
                    self.logger.info("No jobs available. Entering backoff mode.")

            return False, JobResult(status=JobStatus.failed, error_message="No jobs available to process")
        self.consecutive_empty_jobs = 0
        self.current_backoff = self.initial_backoff

        try:
            if job.retry_count >= job.max_retries:
                await self.job_queue_service.move_to_dlq(job)
                await self.job_queue_service.store_job_result(job.job_id, result=JobResult(status=JobStatus.failed, error_message="Max retries exceeded").model_dump())
                return False, JobResult(status=JobStatus.failed, error_message="Max retries exceeded")
            # Check dependencies
            if not await self._check_dependencies(job):
                return False, JobResult(job_id=job.job_id, status=JobStatus.cancelled)

            for attempt in range(job.max_retries):
                try:
                    result = await self._process_job(job)
                    await self.job_queue_service.store_job_result(job.job_id, result=result.model_dump())
                    return True, JobResult(status=JobStatus.completed)
                except Exception as e:
                    job.retry_count += 1
                    await self.job_queue_service.update_job(job.job_id, JobUpdate(
                        status=JobStatus.retrying,
                        retry_count=job.retry_count,
                        error_message=f"Attempt {attempt+1} failed: {str(e)}"
                    ))
            result = JobResult(status=JobStatus.failed, error_message="Max retries exceeded")
            await self.job_queue_service.move_to_dlq(job)
            await self.job_queue_service.store_job_result(job.job_id, result=result.model_dump())
            return False, result
        except Exception as e:
            self.logger.error(f"Error processing job: {e}")
            return False, JobResult(status=JobStatus.failed, error_message=str(e))
    
    async def _job_listener_task(self):
        """Listen for new job notifications via Redis pub/sub"""
        pubsub = self.redis_client.pubsub()
        await pubsub.subscribe(f"{self.queue_name}:new_job")
        
        self.logger.info(f"Worker {self.worker_id} listening for new jobs on {self.queue_name}:new_job")
        
        try:
            async for message in pubsub.listen():
                if message['type'] == 'message':
                    self.logger.debug(f"Received job notification: {message}")
                    # Wake up the worker
                    self.new_job_event.set()
        except Exception as e:
            self.logger.error(f"Error in job listener: {e}")
        finally:
            await pubsub.unsubscribe(f"{self.queue_name}:new_job")

    async def run(self):
        try:
            await self.register_worker()
            heartbeat_task = asyncio.create_task(self._heartbeat_task())
            # Start job listener task
            job_listener_task = asyncio.create_task(self._job_listener_task())
            while True:
                success, result = await self.process_next_job()
                if not success and result.error_message == "No jobs available to process":
                    if self.consecutive_empty_jobs > self.empty_threshold:
                        # Calculate backoff with exponential increase (capped at max_backoff)
                        sleep_time = min(self.current_backoff, self.max_backoff)
                        self.logger.info(f"No jobs available. Sleeping for {sleep_time} seconds.")
                        
                        # Either wait for the backoff time or until a new job notification
                        try:
                            # Clear any previous event triggers
                            self.new_job_event.clear()
                            # Wait for either the timeout or the event to be set
                            await asyncio.wait_for(self.new_job_event.wait(), timeout=sleep_time)
                            self.logger.info("Woken up by new job notification")
                        except asyncio.TimeoutError:
                            # Timeout occurred (expected), continue processing
                            pass
                        
                        # Increase backoff for next time if we reach this point
                        self.current_backoff = min(self.current_backoff * 2, self.max_backoff)
                    else:
                        # Short sleep before the backoff threshold is reached
                        await asyncio.sleep(0.1)
                elif not success:
                    self.logger.info(f"Job processing failed: {result.error_message}")
                    await asyncio.sleep(0.1)  # Short pause
                else:
                    # Job processed successfully
                    await asyncio.sleep(0.1)  # Short pause
                    

        except asyncio.CancelledError:
            self.logger.info("Worker received cancellation signal")

            heartbeat_task.cancel()
            job_listener_task.cancel()

            await self.deregister_worker()

        except Exception as e:
            self.logger.error(f"Worker failed: {e}")
            if self.worker_id:  # Only try to deregister if we have a worker_id
                await self.deregister_worker()


if __name__ == "__main__":
    import sys
    import os
    import logging
    
    # Configure logging
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    
    # Add the parent directory to sys.path when running as main script
    sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../..')))

    async def main():
        # Fix: Await the get_redis_client function
        redis_client = await get_redis_client()
        worker = WorkerService(client=redis_client, queue_name=settings.QUEUE_NAME)
        await worker.run()

    asyncio.run(main())  # Run the worker
