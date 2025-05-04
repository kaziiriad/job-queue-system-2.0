from redis.asyncio import Redis
from app.core.config import settings

redis_client: Redis = None

async def get_redis_client() -> Redis:
    """
    Get a Redis client instance.
    """
    global redis_client
    if redis_client is None:
        redis_client = Redis(
            host=settings.redis_host,
            port=settings.redis_port,
            db=settings.redis_db,
            decode_responses=True,
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
