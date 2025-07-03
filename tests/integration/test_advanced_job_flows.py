import pytest
import asyncio
from fakeredis import aioredis
from app.services.queue import JobQueueService
from app.services.worker import WorkerService
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

@pytest.mark.asyncio
async def test_job_with_dependencies(queue_service: JobQueueService, worker_service: WorkerService):
    # 1. Create parent job
    parent_job_data = JobCreate(job_title="Parent Job", priority=PriorityLevel.high)
    parent_job = await queue_service.enqueue_job(parent_job_data)

    # 2. Create child job with dependency
    child_job_data = JobCreate(job_title="Child Job", priority=PriorityLevel.high, dependencies=[parent_job.job_id])
    child_job = await queue_service.enqueue_job(child_job_data)

    # 3. Process jobs
    await worker_service.register_worker()
    # The first call to process_next_job should process the parent job
    success1, result1 = await worker_service.process_next_job()
    assert success1 is True
    assert result1.status == JobStatus.completed

    # The second call should process the child job
    success2, result2 = await worker_service.process_next_job()
    assert success2 is True
    assert result2.status == JobStatus.completed

    # 4. Verify job statuses
    parent_job_status = await queue_service.get_job_status(parent_job.job_id)
    child_job_status = await queue_service.get_job_status(child_job.job_id)
    assert parent_job_status == JobStatus.completed
    assert child_job_status == JobStatus.completed

@pytest.mark.asyncio
async def test_job_failure_and_dlq(queue_service: JobQueueService, worker_service: WorkerService):
    # 1. Create a job that will fail
    job_data = JobCreate(job_title="Failing Job", priority=PriorityLevel.high, max_retries=1)
    job = await queue_service.enqueue_job(job_data)

    # 2. Simulate worker processing and failing
    await worker_service.register_worker()

    # First attempt (fails)
    # We can't directly make the worker fail, so we'll manually update the job status
    # to simulate a worker reporting a failure.
    from app.models.schemas import JobUpdate
    await queue_service.update_job(job.job_id, JobUpdate(status=JobStatus.failed, error_message="Attempt 1 failed"))

    # 3. Worker tries to process again, but it will be in a failed state.
    # The worker's `process_next_job` will see the failure and move it to the DLQ.
    # To make this test simpler, we'll directly call the logic that moves the job to the DLQ.
    await queue_service.move_to_dlq(job.job_id)

    # 4. Verify the job is in the DLQ
    dlq_job_raw = await queue_service.redis_client.hget(queue_service.keys.dead_letter_queue_key(), job.job_id)
    assert dlq_job_raw is not None

    # 5. Verify the job is no longer in the main queue
    main_queue_job = await queue_service.get_job(job.job_id)
    assert main_queue_job is None
