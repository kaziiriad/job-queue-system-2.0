from redis.asyncio import Redis
from typing import Optional
import logging
from uuid import UUID

logger = logging.getLogger(__name__)

async def execute_pipeline(
    redis_client: Redis, 
    pipeline_function
) -> Optional[dict]:
    pipe = redis_client.pipeline()
    try:
        result = pipeline_function(pipe)  # Define operations inside this function
        await pipe.execute()
        return result
    except Exception as e:
        # ClusterPipeline doesn't have a discard() method
        logger.error(f"Pipeline failed: {e}")
        raise
