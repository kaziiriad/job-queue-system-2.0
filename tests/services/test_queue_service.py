import pytest
import asyncio
import json
from fakeredis import aioredis
from app.services.queue import JobQueueService
from app.models.schemas import JobModel, JobCreate, JobUpdate
from app.models.enums import PriorityLevel, JobStatus

@pytest.fixture
async def fake_redis():
    return aioredis.FakeRedis()

@pytest.fixture
async def queue_service(fake_redis: aioredis.FakeRedis):
    service = JobQueueService(client=fake_redis)
    return service

@pytest.mark.asyncio
async def test_create_job_successfully(queue_service: JobQueueService):
    job_data = JobCreate(job_title="Test Job", priority=PriorityLevel.normal)
    job = await queue_service.enqueue_job(job_data)
    
    assert job is not None
    assert job.job_id is not None
    assert job.job_title == "Test Job"
    assert job.status == JobStatus.pending
    assert job.priority == PriorityLevel.normal

@pytest.mark.asyncio
async def test_get_job_by_id(queue_service: JobQueueService, fake_redis: aioredis.FakeRedis):
    job_data = JobCreate(job_title="Test Job", priority=PriorityLevel.high)
    job = await queue_service.enqueue_job(job_data)
    
    retrieved_job = await queue_service.get_job(job.job_id)
    
    assert retrieved_job is not None
    assert retrieved_job.job_id == job.job_id
    assert retrieved_job.job_title == job.job_title

@pytest.mark.asyncio
async def test_get_nonexistent_job(queue_service: JobQueueService):
    retrieved_job = await queue_service.get_job("nonexistent_id")
    assert retrieved_job is None

@pytest.mark.asyncio
async def test_enqueue_and_dequeue_job(queue_service: JobQueueService):
    job_data = JobCreate(job_title="Test Job", priority=PriorityLevel.low)
    job = await queue_service.enqueue_job(job_data)
    
    dequeued_job = await queue_service.dequeue_job()
    
    assert dequeued_job is not None
    assert dequeued_job.job_id == job.job_id

@pytest.mark.asyncio
async def test_dequeue_from_empty_queue(queue_service: JobQueueService):
    dequeued_job = await queue_service.dequeue_job()
    assert dequeued_job is None

@pytest.mark.asyncio
async def test_update_job_status(queue_service: JobQueueService):
    job_data = JobCreate(job_title="Test Job", priority=PriorityLevel.high)
    job = await queue_service.enqueue_job(job_data)
    
    update_data = JobUpdate(status=JobStatus.processing)
    updated_job = await queue_service.update_job(job.job_id, update_data)
    
    assert updated_job is not None
    assert updated_job.status == JobStatus.processing
    assert updated_job.updated_at is not None

@pytest.mark.asyncio
async def test_delete_job(queue_service: JobQueueService):
    job_data = JobCreate(job_title="Test Job", priority=PriorityLevel.low)
    job = await queue_service.enqueue_job(job_data)
    
    deleted = await queue_service.delete_job(job.job_id)
    assert deleted is True
    
    retrieved_job = await queue_service.get_job(job.job_id)
    assert retrieved_job is None

@pytest.mark.asyncio
async def test_get_all_jobs(queue_service: JobQueueService):
    await queue_service.enqueue_job(JobCreate(job_title="Job 1", priority=PriorityLevel.high))
    await queue_service.enqueue_job(JobCreate(job_title="Job 2", priority=PriorityLevel.low))
    
    all_jobs = await queue_service.get_all_jobs()
    
    assert len(all_jobs) == 2
    assert {job.job_title for job in all_jobs} == {"Job 1", "Job 2"}

@pytest.mark.asyncio
async def test_get_job_status(queue_service: JobQueueService):
    job_data = JobCreate(job_title="Test Job", priority=PriorityLevel.normal)
    job = await queue_service.enqueue_job(job_data)
    
    status = await queue_service.get_job_status(job.job_id)
    
    assert status == JobStatus.pending

@pytest.mark.asyncio
async def test_job_dependencies(queue_service: JobQueueService):
    job1 = await queue_service.enqueue_job(JobCreate(job_title="Job 1", priority=PriorityLevel.high))
    job2 = await queue_service.enqueue_job(JobCreate(job_title="Job 2", priority=PriorityLevel.low, dependencies=[job1.job_id]))
    
    dependencies = await queue_service.get_job_dependencies(job2.job_id)
    dependents = await queue_service.get_job_dependents(job1.job_id)
    
    assert len(dependencies) == 1
    assert dependencies[0].job_id == job1.job_id
    
    assert len(dependents) == 1
    assert dependents[0].job_id == job2.job_id

@pytest.mark.asyncio
async def test_cancel_job(queue_service: JobQueueService):
    job = await queue_service.enqueue_job(JobCreate(job_title="Test Job", priority=PriorityLevel.high))
    
    cancelled = await queue_service.cancel_job(job.job_id)
    assert cancelled is True
    
    retrieved_job = await queue_service.get_job(job.job_id)
    assert retrieved_job is None
    
    dlq_job = await queue_service.redis_client.hget(queue_service.keys.dead_letter_queue_key(), job.job_id)
    assert dlq_job is not None

@pytest.mark.asyncio
async def test_move_to_dlq(queue_service: JobQueueService):
    job = await queue_service.enqueue_job(JobCreate(job_title="Test Job", priority=PriorityLevel.high))
    
    moved = await queue_service.move_to_dlq(job.job_id)
    assert moved is True
    
    retrieved_job = await queue_service.get_job(job.job_id)
    assert retrieved_job is None
    
    dlq_job = await queue_service.redis_client.hget(queue_service.keys.dead_letter_queue_key(), job.job_id)
    assert dlq_job is not None

@pytest.mark.asyncio
async def test_store_job_result(queue_service: JobQueueService):
    job = await queue_service.enqueue_job(JobCreate(job_title="Test Job", priority=PriorityLevel.high))
    result_data = {"output": "some_value"}
    
    await queue_service.store_job_result(job.job_id, result_data)
    
    result = await queue_service.redis_client.hget(queue_service.keys.job_results_key(), job.job_id)
    assert json.loads(result) == result_data

@pytest.mark.asyncio
async def test_job_failure_and_retry(queue_service: JobQueueService):
    # Create a job with 1 max retry
    job = await queue_service.enqueue_job(JobCreate(job_title="Test Job", priority=PriorityLevel.high, max_retries=1))
    
    # Simulate first failure and update the job to retrying
    update_data_retrying = JobUpdate(status=JobStatus.retrying, error_message="First failure", retry_count=1)
    retrying_job = await queue_service.update_job(job.job_id, update_data_retrying)

    assert retrying_job.status == JobStatus.retrying
    assert retrying_job.retry_count == 1
    
    # Simulate final failure, which should move the job to the DLQ
    update_data_failed = JobUpdate(status=JobStatus.failed, error_message="Final failure")
    failed_job = await queue_service.update_job(job.job_id, update_data_failed)

    assert failed_job.status == JobStatus.failed
    
    # Verify the job is in the DLQ
    dlq_job_raw = await queue_service.redis_client.hget(queue_service.keys.dead_letter_queue_key(), job.job_id)
    assert dlq_job_raw is not None
    
    dlq_job = JobModel.model_validate_json(dlq_job_raw)
    assert dlq_job.status == JobStatus.failed
    assert dlq_job.error_message == "Final failure"

    # Verify the job is no longer in the main queue
    main_queue_job = await queue_service.get_job(job.job_id)
    assert main_queue_job is None
