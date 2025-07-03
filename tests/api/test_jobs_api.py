import pytest
from fastapi.testclient import TestClient
from app.main import app
from app.core.dependencies import get_redis_client
from fakeredis import aioredis

@pytest.fixture
def client(fake_redis: aioredis.FakeRedis):
    app.dependency_overrides[get_redis_client] = lambda: fake_redis
    with TestClient(app) as c:
        yield c
    app.dependency_overrides = {}

@pytest.fixture
async def fake_redis():
    return aioredis.FakeRedis()

def test_create_job_api(client: TestClient):
    response = client.post("/jobs/create", json={"job_title": "API Test Job", "priority": "high"})
    assert response.status_code == 200
    data = response.json()
    assert data["job_title"] == "API Test Job"
    assert data["status"] == "pending"

def test_get_job_api(client: TestClient):
    # Create a job first
    create_response = client.post("/jobs/create", json={"job_title": "API Get Test", "priority": "low"})
    assert create_response.status_code == 200
    job_id = create_response.json()["job_id"]

    # Now get the job
    get_response = client.get(f"/jobs/{job_id}")
    assert get_response.status_code == 200
    data = get_response.json()
    assert data["job_id"] == job_id
    assert data["job_title"] == "API Get Test"
