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

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
    
settings = Settings()