import pytest
import asyncio
from fakeredis import aioredis
from app.services.queue import JobQueueService
from app.services.worker import WorkerService
from app.services.monitor import MonitorService
from app.models.schemas import JobCreate
from app.models.enums import PriorityLevel, JobStatus

@pytest.fixture
async def fake_redis():
    return aioredis.FakeRedis()

@pytest.fixture
async def queue_service(fake_redis: aioredis.FakeRedis):
    return JobQueueService(client=fake_redis)

@pytest.fixture
async def worker_service(fake_redis: aioredis.FakeRedis):
    return WorkerService(client=fake_redis)

@pytest.fixture
async def monitor_service(fake_redis: aioredis.FakeRedis):
    return MonitorService(client=fake_redis)

@pytest.mark.asyncio
async def test_job_lifecycle(queue_service: JobQueueService, worker_service: WorkerService, monitor_service: MonitorService):
    # 1. Create a job
    job_data = JobCreate(job_title="Integration Test Job", priority=PriorityLevel.high)
    job = await queue_service.enqueue_job(job_data)
    assert job.status == JobStatus.pending

    # 2. Process the job with a worker
    await worker_service.register_worker()
    success, result = await worker_service.process_next_job()
    assert success is True
    assert result.status == JobStatus.completed

    # 3. Verify the job status with the monitor
    job_status = await monitor_service.get_job_status(job.job_id)
    assert job_status == JobStatus.completed
