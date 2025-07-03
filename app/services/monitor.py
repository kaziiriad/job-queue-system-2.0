import asyncio
from datetime import datetime, timezone
from uuid import UUID

import aioboto3
from app.core.config import settings
from app.core.dependencies import get_redis_client
from app.utils.redis_keys import RedisKeyManager
from app.utils.redis_ops import execute_pipeline
from redis.asyncio import Redis
import logging
import aiohttp
import sys
from app.services.queue import JobQueueService


from app.models.enums import JobStatus
from app.models.schemas import JobModel

class MonitorService:
    def __init__(self, client: Redis, queue_name: str = settings.QUEUE_NAME, *args, **kwargs):
        self.redis_client = client
        self.queue_name = queue_name
        self.keys = RedisKeyManager(system_prefix=queue_name)
        self.logger = logging.getLogger(__name__)
        self.worker_heartbeat_timeout = kwargs.get('worker_heartbeat_timeout', 30)
        self.worker_scale_threshold = kwargs.get('worker_scale_threshold', 10)
        self.scale_cooldown_seconds = kwargs.get('scale_cooldown_seconds', 60) # Default to 60 seconds
        self.last_scale_action_time = datetime.now(timezone.utc)
        self.queue_service = JobQueueService(client=self.redis_client, queue_name=self.queue_name)
        
        # Initialize Docker client with error handling
        self.docker_client = None
        if not settings.RUNNING_IN_CLOUD:
            try:
                import docker
                self.docker_client = docker.from_env()
                self.logger.info("Docker client initialized successfully")
            except Exception as e:
                self.logger.warning(f"Failed to initialize Docker client: {e}")
                self.logger.warning("Worker scaling with Docker will be disabled")
        
        # Initialize AWS session if running in cloud
        self.aws_session = None
        if settings.RUNNING_IN_CLOUD:
            try:
                self.aws_session = aioboto3.Session(
                    aws_access_key_id=settings.AWS_ACCESS_KEY_ID,
                    aws_secret_access_key=settings.AWS_SECRET_ACCESS_KEY,
                    region_name=settings.AWS_REGION,
                )
                self.logger.info("AWS session initialized successfully")
            except Exception as e:
                self.logger.warning(f"Failed to initialize AWS session: {e}")
                self.logger.warning("Worker scaling with AWS will be disabled")

    async def get_job_status(self, job_id: str) -> JobStatus:
        job = await self.queue_service.get_job(job_id)
        if not job:
            return JobStatus.not_found
        return job.status

    async def check_stale_workers(self) -> list[str]:
        current_time = datetime.now(timezone.utc).timestamp()
        stale_workers = await self.redis_client.zrangebyscore(
            self.keys.worker_heartbeats(),
            min=0,
            max=current_time - self.worker_heartbeat_timeout
        )
        return [worker.decode("utf-8") if isinstance(worker, bytes) else worker for worker in stale_workers]

    

    async def _get_queue_metrics(self):
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(f"{settings.BASE_URL}/dashboard/metrics/queue") as response:
                    if response.status == 200:
                        return await response.json()
                    else:
                        self.logger.error(f"Failed to get queue metrics: {response.status}")
                        return None
        except Exception as e:
            self.logger.error(f"Error fetching queue metrics: {e}")
            return None
    
    async def mark_worker_as_dead(self, stale_workers: list[str]):
        def pipeline_operations(pipe):
            for worker_id in stale_workers:
                pipe.srem(self.keys.active_workers_key(), worker_id)
                pipe.zrem(self.keys.worker_heartbeats(), worker_id)
                self.logger.info(f"Worker {worker_id} marked as dead.")

        await execute_pipeline(self.redis_client, pipeline_operations)

    
                
    async def scale_workers(self):
        try:
            queue_metrics = await self._get_queue_metrics()
            if not queue_metrics:
                return
            
            pending_jobs = queue_metrics.get("pending_high", 0) + queue_metrics.get("pending_normal", 0) + queue_metrics.get("pending_low", 0) 
            active_workers = await self.redis_client.scard(self.keys.active_workers_key())
            
            self.logger.info(f"Pending jobs: {pending_jobs}")
            self.logger.info(f"Active workers: {active_workers}")
        
            if active_workers == 0 and pending_jobs > 0:
                self.logger.info("No active workers but pending jobs exist. Scaling up.")
                await self._scale_up_worker()
            elif active_workers > 0:
                jobs_per_worker = pending_jobs // active_workers
                self.logger.info(f"Jobs per active worker: {jobs_per_worker}")
                if jobs_per_worker > self.worker_scale_threshold:
                    await self._scale_up_worker()
                elif jobs_per_worker < self.worker_scale_threshold // 2:
                    await self._scale_down_worker()
        except Exception as e:
            self.logger.error(f"Error scaling workers: {e}")
    
    async def _scale_up_worker(self):
        if (datetime.now(timezone.utc) - self.last_scale_action_time).total_seconds() < self.scale_cooldown_seconds:
            self.logger.info(f"Scaling up skipped due to cooldown. Remaining: {self.scale_cooldown_seconds - (datetime.now(timezone.utc) - self.last_scale_action_time).total_seconds():.2f}s")
            return

        if settings.RUNNING_IN_CLOUD and self.aws_session:
            try:
                async with self.aws_session.client("autoscaling") as autoscaling:
                    response = await autoscaling.describe_auto_scaling_groups(
                        AutoScalingGroupNames=[settings.AWS_ASG_NAME],
                    )
                    if not response['AutoScalingGroups']:
                        self.logger.error(f"Auto Scaling Group {settings.AWS_ASG_NAME} not found")
                        return
                    
                    asg = response['AutoScalingGroups'][0]
                    current_capacity = asg['DesiredCapacity']
                    max_size = asg['MaxSize']

                    if current_capacity < max_size:
                        new_capacity = min(current_capacity + 1, max_size)
                        self.logger.info(f"Scaling up workers from {current_capacity} to {new_capacity}")

                        await autoscaling.set_desired_capacity(
                            AutoScalingGroupName=settings.AWS_ASG_NAME,
                            DesiredCapacity=new_capacity,
                            HonorCooldown=True
                        )
                        self.logger.info(f"Successfully scaled up to {new_capacity} workers")
                        self.last_scale_action_time = datetime.now(timezone.utc)
                    else:
                        self.logger.info(f"Already at maximum capacity ({max_size}), cannot scale up further")
            except Exception as e:
                self.logger.error(f"Error scaling up workers in AWS: {e}")
        elif not settings.RUNNING_IN_CLOUD and self.docker_client:
            try:
                # Scale docker container.
                service_name = settings.DOCKER_SERVICE_NAME
                services = self.docker_client.services.list(filters={"name": service_name})
                if not services:
                    self.logger.error(f"Service {service_name} not found")
                    return
                
                service = services[0]
                current_replicas = service.attrs["Spec"]["Mode"]["Replicated"]["Replicas"]
                max_replicas = getattr(settings, "MAX_WORKER_REPLICAS", 5)

                if current_replicas < max_replicas:
                    new_replicas = min(current_replicas + 1, max_replicas)
                    self.logger.info(f"Scaling up workers from {current_replicas} to {new_replicas}")

                    service.scale(new_replicas)
                    self.logger.info(f"Successfully scaled up to {new_replicas} workers")
                    self.last_scale_action_time = datetime.now(timezone.utc)
                else:
                    self.logger.info(f"Already at maximum capacity ({max_replicas}), cannot scale up further")
            except Exception as e:
                self.logger.error(f"Error scaling up workers in Docker: {e}")
        else:
            self.logger.warning("Worker scaling is not available (neither AWS nor Docker is configured)")

        
    async def _scale_down_worker(self):
        if (datetime.now(timezone.utc) - self.last_scale_action_time).total_seconds() < self.scale_cooldown_seconds:
            self.logger.info(f"Scaling down skipped due to cooldown. Remaining: {self.scale_cooldown_seconds - (datetime.now(timezone.utc) - self.last_scale_action_time).total_seconds():.2f}s")
            return

        if settings.RUNNING_IN_CLOUD and self.aws_session:
            try:
                # Get current ASG details
                async with self.aws_session.client("autoscaling") as autoscaling:
                    response = await autoscaling.describe_auto_scaling_groups(
                        AutoScalingGroupNames=[settings.AWS_ASG_NAME]
                    )
                    
                    if not response['AutoScalingGroups']:
                        self.logger.error(f"Auto Scaling Group {settings.AWS_ASG_NAME} not found")
                        return
                        
                    asg = response['AutoScalingGroups'][0]
                    current_capacity = asg['DesiredCapacity']
                    min_size = asg['MinSize']
                    
                    if current_capacity > min_size:
                        new_capacity = max(current_capacity - 1, min_size)
                        self.logger.info(f"Scaling down workers from {current_capacity} to {new_capacity}")
                        
                        await autoscaling.set_desired_capacity(
                            AutoScalingGroupName=settings.AWS_ASG_NAME,
                            DesiredCapacity=new_capacity,
                            HonorCooldown=True
                        )
                        self.logger.info(f"Successfully scaled down to {new_capacity} workers")
                        self.last_scale_action_time = datetime.now(timezone.utc)
                    else:
                        self.logger.info(f"Already at minimum capacity ({min_size}), cannot scale down further")
            except Exception as e:
                self.logger.error(f"Failed to scale down workers in AWS: {e}")
        elif not settings.RUNNING_IN_CLOUD and self.docker_client:
            try:
                service_name = settings.DOCKER_SERVICE_NAME
                services = self.docker_client.services.list(filters={"name": service_name})
                
                if not services:
                    self.logger.error(f"Docker service {service_name} not found")
                    return
                    
                service = services[0]
                current_replicas = service.attrs["Spec"]["Mode"]["Replicated"]["Replicas"]
                min_replicas = getattr(settings, "MIN_WORKER_REPLICAS", 1)
                
                if current_replicas > min_replicas:
                    new_replicas = max(current_replicas - 1, min_replicas)
                    self.logger.info(f"Scaling down Docker service from {current_replicas} to {new_replicas} replicas")
                    
                    service.scale(new_replicas)
                    self.logger.info(f"Successfully scaled Docker service to {new_replicas} replicas")
                    self.last_scale_action_time = datetime.now(timezone.utc)
                else:
                    self.logger.info(f"Already at minimum Docker replicas ({min_replicas}), cannot scale down further")
            except Exception as e:
                self.logger.error(f"Failed to scale down Docker service: {e}")
        else:
            self.logger.warning("Worker scaling is not available (neither AWS nor Docker is configured)")
        
    async def run(self):
        """
        Run the monitor service to continuously monitor the job queue
        and worker status, scaling as needed.
        """
        self.logger.info(f"Starting monitor service for queue: {self.queue_name}")
        try:
            while True:
                # Check for stale workers and mark them as dead
                stale_workers = await self.check_stale_workers()
                if stale_workers:
                    self.logger.info(f"Found {len(stale_workers)} stale workers: {stale_workers}")
                    await self.mark_worker_as_dead(stale_workers)
                
                # Check queue metrics and scale workers if needed
                await self.scale_workers()
                
                # Sleep before next check cycle
                await asyncio.sleep(getattr(settings, "MONITOR_CHECK_INTERVAL", 30))
        except asyncio.CancelledError:
            self.logger.info("Monitor service shutting down gracefully")
        except Exception as e:
            self.logger.error(f"Monitor service encountered an error: {e}")
            raise        


logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

logger = logging.getLogger(__name__)

async def main():
    try:
        logger.info("Starting monitor service")
        
        # Get Redis client
        redis_client = await get_redis_client()
        
        # Create and run monitor service
        monitor = MonitorService(
            client=redis_client,
            queue_name=settings.QUEUE_NAME,
            worker_heartbeat_timeout=getattr(settings, "WORKER_HEARTBEAT_TIMEOUT", 30),
            worker_scale_threshold=getattr(settings, "WORKER_SCALE_THRESHOLD", 10)
        )
        
        await monitor.run()
    except Exception as e:
        logger.error(f"Monitor service failed: {e}")
        sys.exit(1)

if __name__ == "__main__":
    asyncio.run(main())
