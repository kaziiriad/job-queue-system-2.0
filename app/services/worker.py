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
        self._notification_event = asyncio.Event()

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
        """
        Deregister the worker from the system.
        """
        if not self.worker_id:
            raise HTTPException(status_code=400, detail="Worker not registered")

        # First, unsubscribe from the pub/sub channel if we have a pubsub object
        if hasattr(self, 'pubsub') and self.pubsub:
            try:
                await self.pubsub.unsubscribe(f"{self.queue_name}:new_job")
                await self.pubsub.close()
                self.logger.info("Unsubscribed from new job notifications")
            except Exception as e:
                self.logger.warning(f"Error unsubscribing from pub/sub: {e}")

        # Then remove worker from active workers and heartbeats
        def pipeline_operations(pipe):
            pipe.srem(self.keys.active_workers_key(), self.worker_id)
            pipe.zrem(self.keys.worker_heartbeats(), self.worker_id)
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
    
    async def _wait_for_notification(self):
        """
        Wait for a new job notification.
        """
        # This future will be set when a new job notification is received
        if not hasattr(self, '_notification_event'):
            self._notification_event = asyncio.Event()
        
        # Wait for the event to be set
        await self._notification_event.wait()
        
        # Clear the event for next time
        self._notification_event.clear()

    async def _listen_for_new_jobs(self):
        """
        Listen for new job notifications via Redis pub/sub.
        """
        try:
            while True:
                message = await self.pubsub.get_message(ignore_subscribe_messages=True)
                if message and message['type'] == 'message':
                    self.logger.debug(f"Received job notification: {message}")
                    # Set the event to wake up the worker
                    if hasattr(self, '_notification_event'):
                        self._notification_event.set()
                await asyncio.sleep(0.1)  # Short sleep to avoid tight loop
        except Exception as e:
            self.logger.error(f"Error in pub/sub listener: {e}")
        finally:
            # Make sure to close the pubsub connection
            try:
                if hasattr(self, 'pubsub') and self.pubsub:
                    await self.pubsub.unsubscribe(f"{self.queue_name}:new_job")
                    await self.pubsub.close()
            except Exception as e:
                self.logger.error(f"Error closing pubsub: {e}")

    async def run(self):
        """
        Run the worker to process jobs from the queue.
        """
        try:
            await self.register_worker()
            
            # Create heartbeat task
            heartbeat_task = asyncio.create_task(self._heartbeat_task())
            
            # Set up pub/sub for new job notifications
            self.pubsub = self.redis_client.pubsub()
            await self.pubsub.subscribe(f"{self.queue_name}:new_job")
            self.logger.info(f"Worker {self.worker_id} listening for new jobs on {self.queue_name}:new_job")
            
            # Create pub/sub listener task
            pubsub_task = asyncio.create_task(self._listen_for_new_jobs())
            
            # Initial sleep time
            sleep_time = 1.0
            max_sleep_time = self.max_backoff
            
            while True:
                success, result = await self.process_next_job()
                
                if success:
                    # Reset sleep time on successful job processing
                    sleep_time = 1.0
                    self.logger.info(f"Processed job successfully: {result.status}")
                else:
                    if "No jobs available to process" in result.error_message:
                        if self.consecutive_empty_jobs > self.empty_threshold:
                            # Use exponential backoff when no jobs are available
                            self.logger.info(f"No jobs available. Sleeping for {sleep_time}s")
                            
                            # Wait for either the sleep time or a new job notification
                            try:
                                await asyncio.wait_for(self._wait_for_notification(), timeout=sleep_time)
                                # If we get here, we were notified of a new job
                                sleep_time = 1.0  # Reset sleep time
                                self.logger.info("Woken up by new job notification")
                            except asyncio.TimeoutError:
                                # No notification received, increase sleep time
                                sleep_time = min(sleep_time * 2, max_sleep_time)
                        else:
                            # Short sleep before the backoff threshold is reached
                            await asyncio.sleep(0.1)
                    else:
                        # For other errors, log them but don't increase sleep time
                        self.logger.error(f"Job processing error: {result.error_message}")
                        await asyncio.sleep(1)  # Short sleep before retry
        except asyncio.CancelledError:
            self.logger.info("Worker received cancellation signal")
        except Exception as e:
            self.logger.error(f"Worker failed: {e}")
        finally:
            # Clean up tasks and connections
            if 'heartbeat_task' in locals():
                heartbeat_task.cancel()
            if 'pubsub_task' in locals():
                pubsub_task.cancel()
            
            # Deregister worker
            if self.worker_id:
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
