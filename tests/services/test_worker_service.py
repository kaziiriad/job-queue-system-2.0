
import pytest
import asyncio
from fakeredis import aioredis
from app.services.worker import WorkerService
from app.services.queue import JobQueueService
from app.models.schemas import JobCreate
from app.models.enums import PriorityLevel

@pytest.fixture
async def fake_redis():
    return aioredis.FakeRedis()

@pytest.fixture
async def queue_service(fake_redis: aioredis.FakeRedis):
    return JobQueueService(client=fake_redis)

@pytest.fixture
async def worker_service(fake_redis: aioredis.FakeRedis):
    return WorkerService(client=fake_redis)

@pytest.mark.asyncio
async def test_register_worker(worker_service: WorkerService):
    result = await worker_service.register_worker()
    assert result["message"] == "Worker registered"
    assert worker_service.worker_id is not None

@pytest.mark.asyncio
async def test_deregister_worker(worker_service: WorkerService):
    await worker_service.register_worker()
    await worker_service.deregister_worker()
    assert worker_service.worker_id is None

@pytest.mark.asyncio
async def test_send_heartbeat(worker_service: WorkerService, fake_redis: aioredis.FakeRedis):
    await worker_service.register_worker()
    await worker_service.send_heartbeat()
    heartbeat = await fake_redis.zscore(worker_service.keys.worker_heartbeats(), worker_service.worker_id)
    assert heartbeat is not None

@pytest.mark.asyncio
async def test_process_next_job(worker_service: WorkerService, queue_service: JobQueueService):
    await queue_service.enqueue_job(JobCreate(job_title="Test Job", priority=PriorityLevel.high))
    
    success, result = await worker_service.process_next_job()
    
    assert success is True
    assert result.status == "completed"

@pytest.mark.asyncio
async def test_process_next_job_empty_queue(worker_service: WorkerService):
    success, result = await worker_service.process_next_job()
    
    assert success is False
    assert "No jobs available to process" in result.error_message

