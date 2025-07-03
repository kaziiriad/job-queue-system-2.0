import pytest
import asyncio
from fakeredis import aioredis
from app.services.monitor import MonitorService
from datetime import datetime, timezone, timedelta

@pytest.fixture
async def fake_redis():
    return aioredis.FakeRedis()

from unittest.mock import AsyncMock, patch

@pytest.fixture
async def monitor_service(fake_redis: aioredis.FakeRedis):
    service = MonitorService(client=fake_redis, worker_heartbeat_timeout=30, worker_scale_threshold=10)
    return service

@pytest.mark.asyncio
async def test_scale_workers_up(monitor_service: MonitorService):
    with patch.object(monitor_service, '_get_queue_metrics', new_callable=AsyncMock) as mock_get_metrics, \
         patch.object(monitor_service, '_scale_up_worker', new_callable=AsyncMock) as mock_scale_up:
        
        # Simulate high load
        mock_get_metrics.return_value = {"pending_high": 15, "pending_normal": 0, "pending_low": 0}
        
        await monitor_service.scale_workers()
        
        mock_scale_up.assert_called_once()


@pytest.mark.asyncio
async def test_check_stale_workers(monitor_service: MonitorService):
    # Add a current worker
    await monitor_service.redis_client.zadd(
        monitor_service.keys.worker_heartbeats(),
        {"current_worker": datetime.now(timezone.utc).timestamp()}
    )
    
    # Add a stale worker
    stale_timestamp = (datetime.now(timezone.utc) - timedelta(seconds=60)).timestamp()
    await monitor_service.redis_client.zadd(
        monitor_service.keys.worker_heartbeats(),
        {"stale_worker": stale_timestamp}
    )
    
    stale_workers = await monitor_service.check_stale_workers()
    
    assert "stale_worker" in stale_workers
    assert "current_worker" not in stale_workers

@pytest.mark.asyncio
async def test_mark_worker_as_dead(monitor_service: MonitorService):
    stale_worker_id = "stale_worker_1"
    
    # Add the worker to active workers and heartbeats
    await monitor_service.redis_client.sadd(monitor_service.keys.active_workers_key(), stale_worker_id)
    await monitor_service.redis_client.zadd(
        monitor_service.keys.worker_heartbeats(),
        {stale_worker_id: (datetime.now(timezone.utc) - timedelta(seconds=60)).timestamp()}
    )
    
    await monitor_service.mark_worker_as_dead([stale_worker_id])
    
    # Verify the worker is removed
    assert not await monitor_service.redis_client.sismember(monitor_service.keys.active_workers_key(), stale_worker_id)
    assert await monitor_service.redis_client.zscore(monitor_service.keys.worker_heartbeats(), stale_worker_id) is None
