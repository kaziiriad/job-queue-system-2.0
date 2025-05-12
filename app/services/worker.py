import asyncio
from datetime import datetime, timezone
from typing import Optional
from uuid import UUID
import logging
from fastapi import HTTPException
from redis.asyncio import RedisCluster
from app.core.dependencies import get_redis_client
from app.models.schemas import JobModel, JobUpdate, JobResult, Worker
from app.models.enums import JobStatus
from app.core.config import settings
from app.utils.redis_keys import RedisKeyManager
from app.utils.redis_ops import execute_pipeline
from app.services.queue import JobQueueService
# from ..core.dependencies import get_redis_client

class WorkerService:
    def __init__(self, client: RedisCluster, queue_name: str = settings.QUEUE_NAME):
        self.redis_client = client
        self.queue_name = queue_name
        self.keys = RedisKeyManager(system_prefix=queue_name)
        self.job_queue_service = JobQueueService(client=self.redis_client, queue_name=self.queue_name)
        self.logger = logging.getLogger(__name__)
        self.worker = None
        self.worker_id = None
        self.worker_heartbeat_interval = 10  # seconds
        # self.worker_heartbeat_timeout = 30

    async def register_worker(self) -> Optional[dict]:
        self.worker_id = str(UUID())
        self.worker = Worker(
            worker_id=self.worker_id,
            status='active',
            last_heartbeat=datetime.now(timezone.utc),
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

    async def process_next_job(self) -> tuple[bool, JobResult]:
        job = await self.job_queue_service.dequeue_job()
        if not job:
            return False, JobResult(status=JobStatus.failed, error_message="No jobs")

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

    async def run(self):
        try:
            await self.register_worker()
            asyncio.create_task(self._heartbeat_task())
            while True:
                await self.process_next_job()
                await asyncio.sleep(0.1)  # Prevent tight loop
        except asyncio.CancelledError:
            await self.deregister_worker()
        except Exception as e:
            self.logger.error(f"Worker failed: {e}")
            await self.deregister_worker()


if __name__ == "__main__":

    async def main():
        worker = WorkerService(client=get_redis_client(), queue_name=settings.QUEUE_NAME)
        await worker.run()

    asyncio.run(main())  # Run the worker

   