from datetime import datetime, timezone
from uuid import UUID

import aioboto3.session
from app.core.config import settings
from app.utils.redis_keys import RedisKeyManager
from app.utils.redis_ops import execute_pipeline
from redis.asyncio import RedisCluster
import logging
import aiohttp
import aioboto3
import docker


class MonitorService:
    def __init__(self, client: RedisCluster, queue_name: str = settings.QUEUE_NAME, *args, **kwargs):
        self.redis_client = client
        self.queue_name = queue_name
        self.keys = RedisKeyManager(system_prefix=queue_name)
        self.logger = logging.getLogger(__name__)
        self.worker_heartbeat_timeout = kwargs.get('worker_heartbeat_timeout', 30)
        self.worker_scale_threshold = kwargs.get('worker_scale_threshold', 10)
        self.docker_client = docker.from_env()
        self.aws_session = aioboto3.session(
                aws_access_key_id=settings.AWS_ACCESS_KEY_ID,
                aws_secret_access_key=settings.AWS_SECRET_ACCESS_KEY,
                region_name=settings.AWS_REGION,
                
            )

    async def check_stale_workers(self) -> list[str]:
        current_time = datetime.now(timezone.utc).timestamp()
        stale_workers = await self.redis_client.zrangebyscore(
            self.keys.worker_heartbeats(),
            min=0,
            max=current_time - self.worker_heartbeat_timeout
        )
        return [worker.decode("utf-8") for worker in stale_workers]

    

    async def _get_queue_metrics(self):
        async with aiohttp.ClientSession() as session:
            async with session.get(f"{settings.BASE_URL}/dashboard/metrics/queue") as response:
                return await response.json() if response.status == 200 else None
    
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
            self.logger.info(f"Pending jobs: {pending_jobs}")
            self.logger.info(f"Active workers: {await self.redis_client.scard(self.keys.active_workers_key())}")
        
            if pending_jobs > self.worker_scale_threshold:
                await self._scale_up_worker()
            elif pending_jobs < self.worker_scale_threshold // 2:
                await self._scale_down_worker()

    
        except Exception as e:
            self.logger.error(f"Error scaling workers: {e}")
    
    async def _scale_up_worker(self):
        if settings.RUNNING_IN_CLOUD:

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
                    else:
                        self.logger.info(f"Already at maximum capacity ({max_size}), cannot scale up further")
            
            except Exception as e:
                self.logger.error(f"Error scaling up workers in AWS: {e}")

                
        else:
            try:
                # Scale docker container.
                service_name = settings.DOCKER_SERVICE_NAME
                services = self.docker_client.services.list(filters={"name": service_name})
                if not services:
                    self.logger.error(f"Service {service_name} not found")
                    return
                service = services[0]
                current_replicas = service.attrs["Spec"]["Mode"]["Replicated"]["Replicas"]
                max_replicas = settings.MAX_WORKER_REPLICAS

                if current_replicas < max_replicas:
                    new_replicas = min(current_replicas + 1, max_replicas)
                    self.logger.info(f"Scaling up workers from {current_replicas} to {new_replicas}")

                    service.scale(new_replicas)
                    self.logger.info(f"Successfully scaled up to {new_replicas} workers")
                else:
                    self.logger.info(f"Already at minimum capacity ({current_replicas}), cannot scale up further")

            except Exception as e:
                self.logger.error(f"Error scaling up workers in Docker: {e}")

        
    async def _scale_down_worker(self):
        if settings.RUNNING_IN_CLOUD:
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
                    else:
                        self.logger.info(f"Already at minimum capacity ({min_size}), cannot scale down further")
            except Exception as e:
                self.logger.error(f"Failed to scale down workers in AWS: {e}")
        else:
            # Scale using Docker
            try:
                service_name = settings.DOCKER_SERVICE_NAME
                services = self.docker_client.services.list(filters={"name": service_name})
                
                if not services:
                    self.logger.error(f"Docker service {service_name} not found")
                    return
                    
                service = services[0]
                current_replicas = service.attrs["Spec"]["Mode"]["Replicated"]["Replicas"]
                min_replicas = settings.MIN_WORKER_REPLICAS
                
                if current_replicas > min_replicas:
                    new_replicas = max(current_replicas - 1, min_replicas)
                    self.logger.info(f"Scaling down Docker service from {current_replicas} to {new_replicas} replicas")
                    
                    service.scale(new_replicas)
                    self.logger.info(f"Successfully scaled Docker service to {new_replicas} replicas")
                else:
                    self.logger.info(f"Already at minimum Docker replicas ({min_replicas}), cannot scale down further")
            except Exception as e:
                self.logger.error(f"Failed to scale down Docker service: {e}")


    