# Distributed Job Queue System 2.0

A distributed job queue system built with FastAPI, Redis, and Docker. This system allows you to create, manage, and monitor jobs with different priority levels, dependencies, and automatic worker scaling.

## Features

- **Job Queue Management**: Create, cancel, and monitor jobs with different priority levels
- **Worker Auto-scaling**: Automatically scale workers based on queue size
- **Web Dashboard**: Real-time monitoring of queue metrics and worker status
- **Job Management UI**: User-friendly interface for creating and managing jobs
- **Fault Tolerance**: Automatic retry mechanism and dead-letter queue for failed jobs
- **Dependency Management**: Define job dependencies to ensure proper execution order

## Architecture

The system consists of four main components:

1. **API Service**: FastAPI application that provides REST endpoints for job management
2. **Worker Service**: Processes jobs from the queue with configurable concurrency
3. **Monitor Service**: Monitors queue health and scales workers as needed
4. **Redis**: Used as the message broker and for storing job metadata

## Prerequisites

- Docker and Docker Compose
- Docker Swarm (for production deployments with auto-scaling)

## Setup Instructions

### Development Setup

1. **Clone the repository**:
   ```bash
   git clone https://github.com/kaziiriad/job-queue-system-2.0.git
   cd job-queue-system-2.0
   ```

2. **Build the Docker images**:
   ```bash
   docker build -t job-queue-api:latest -f Dockerfile.job_queue .
   docker build -t job-queue-worker:latest -f Dockerfile.worker .
   docker build -t job-queue-monitor:latest -f Dockerfile.monitor .
   ```

3. **Start the services with Docker Compose**:
   ```bash
   docker-compose up -d
   ```

4. **Access the application**:
   - Dashboard: http://localhost:8000/dashboard/
   - Job Management: http://localhost:8000/jobs/manage
   - API Documentation: http://localhost:8000/docs

### Production Setup with Docker Swarm

1. **Initialize Docker Swarm** (if not already done):
   ```bash
   docker swarm init
   ```

2. **Deploy the stack**:
   ```bash
   docker stack deploy -c docker-compose.yml job-queue
   ```

3. **Scale workers manually** (if needed):
   ```bash
   docker service scale job-queue_worker=3
   ```

## Configuration

The system can be configured using environment variables:

### API Service
- `REDIS_HOST`: Redis host (default: "redis")
- `REDIS_PORT`: Redis port (default: 6379)
- `REDIS_DB`: Redis database number (default: 0)
- `QUEUE_NAME`: Prefix for Redis keys (default: "job_queue")

### Worker Service
- `REDIS_HOST`: Redis host (default: "redis")
- `REDIS_PORT`: Redis port (default: 6379)
- `REDIS_URL`: Redis URL (default: "redis://redis:6379/0")
- `QUEUE_NAME`: Prefix for Redis keys (default: "job_queue")

### Monitor Service
- `REDIS_HOST`: Redis host (default: "redis")
- `REDIS_PORT`: Redis port (default: 6379)
- `MIN_WORKER_REPLICAS`: Minimum number of workers (default: 1)
- `MAX_WORKER_REPLICAS`: Maximum number of workers (default: 5)
- `MONITOR_CHECK_INTERVAL`: Interval for checking queue status (default: 30 seconds)
- `WORKER_SCALE_THRESHOLD`: Job count threshold for scaling (default: 10)

## API Usage Examples

### Create a Job

```bash
curl -X POST http://localhost:8000/jobs/create \
  -H "Content-Type: application/json" \
  -d '{
    "job_title": "Example Job",
    "priority": "high",
    "max_retries": 3
  }'
```

### Get Job Status

```bash
curl -X GET http://localhost:8000/jobs/{job_id}
```

### Cancel a Job

```bash
curl -X POST http://localhost:8000/jobs/cancel/{job_id}
```

## Project Structure

```
job-queue-system-2.0/
├── app/
│   ├── core/
│   │   ├── __init__.py
│   │   ├── config.py
│   │   └── dependencies.py
│   ├── endpoints/
│   │   ├── __init__.py
│   │   ├── dashboard.py
│   │   └── jobs.py
│   ├── models/
│   │   ├── __init__.py
│   │   ├── enums.py
│   │   └── schemas.py
│   ├── services/
│   │   ├── __init__.py
│   │   ├── monitor.py
│   │   ├── queue.py
│   │   └── worker.py
│   ├── templates/
│   │   ├── dashboard.html
│   │   ├── home.html
│   │   └── job_management.html
│   ├── utils/
│   │   ├── __init__.py
│   │   ├── redis_keys.py
│   │   └── redis_ops.py
│   ├── __init__.py
│   └── main.py
├── scripts/
│   └── __init__.py
├── tests/
│   └── __init__.py
├── Dockerfile.job_queue
├── Dockerfile.monitor
├── Dockerfile.worker
├── README.md
├── __init__.py
├── docker-compose.yml
├── image-dashboard.png
├── image-home.png
├── image-job-create.png
├── pyproject.toml
└── uv.lock
```

## Troubleshooting

### Common Issues

1. **Redis Connection Issues**:
   - Check if Redis is running: `docker ps | grep redis`
   - Verify Redis connection settings in environment variables

2. **Worker Not Processing Jobs**:
   - Check worker logs: `docker service logs job-queue_worker`
   - Verify worker registration in Redis

3. **Monitor Service Errors**:
   - For Docker Swarm scaling issues, ensure Docker socket is mounted
   - Check monitor logs: `docker service logs job-queue_monitor`

## License

[MIT License](LICENSE)

## Contributing

Contributions are welcome! Please feel free to submit a Pull Request.
