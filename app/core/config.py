from pydantic_settings import BaseSettings, Field
import os
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()
class Settings(BaseSettings):

    # Redis
    redis_host: str = Field(default=os.getenv("REDIS_HOST", "localhost"))
    redis_port: int = Field(default=os.getenv("REDIS_PORT", 6379))
    redis_db: int = Field(default=os.getenv("REDIS_DB", 0))
    redis_url: str = Field(default=os.getenv("REDIS_URL", "redis://localhost:6379/0"))
    BASE_URL: str = Field(default=os.getenv("BASE_URL", "http://localhost:8000"))
    QUEUE_NAME: str = Field(default=os.getenv("QUEUE_NAME", "jobs_queue"))
    RUNNING_IN_CLOUD: bool = Field(default=os.getenv("RUNNING_IN_CLOUD", False))
    AWS_ACCESS_KEY_ID: str = Field(default=os.getenv("AWS_ACCESS_KEY_ID", ""))
    AWS_SECRET_ACCESS_KEY: str = Field(default=os.getenv("AWS_SECRET_ACCESS_KEY", ""))
    AWS_REGION: str = Field(default=os.getenv("AWS_REGION", "ap-southeast-1"))
    # MIN_AWS_REPLICAS: int = Field(default=os.getenv("MIN_AWS_REPLICAS", 1))
    AWS_ASG_NAME: str = Field(default=os.getenv("AWS_ASG_NAME", ""))
    DOCKER_SERVICE_NAME: str = Field(default=os.getenv("DOCKER_SERVICE_NAME", "worker"))
    MAX_WORKER_REPLICAS: int = Field(default=os.getenv("MAX_WORKER_REPLICAS", 5))
    MIN_WORKER_REPLICAS: int = Field(default=os.getenv("MIN_WORKER_REPLICAS", 1))
    
    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
    
settings = Settings()