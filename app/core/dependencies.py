from redis.asyncio import Redis
from .config import settings

redis_client = None

async def get_redis_client():
    """
    Get a Redis client instance.
    """
    global redis_client
    if not redis_client:
        redis_client = Redis(
            host=settings.redis_host,
            port=settings.redis_port,
            db=settings.redis_db,  # Standard Redis client supports db selection
            decode_responses=True
        )
    return redis_client

    
async def close_redis_client() -> None:
    """
    Close the Redis client connection.
    """
    global redis_client
    if redis_client:
        await redis_client.close()
        redis_client = None