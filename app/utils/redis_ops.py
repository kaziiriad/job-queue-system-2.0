from redis.asyncio import RedisCluster
from typing import Optional
import logging
from uuid import UUID

logger = logging.getLogger(__name__)

async def execute_pipeline(
    redis_client: RedisCluster, 
    pipeline_function
) -> Optional[dict]:
    pipe = redis_client.pipeline()
    try:
        result = pipeline_function(pipe)  # Define operations inside this function
        await pipe.execute()
        return result
    except Exception as e:
        await pipe.discard()
        logger.error(f"Pipeline failed: {e}")
        raise