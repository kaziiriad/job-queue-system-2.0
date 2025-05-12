# utils/redis_keys.py
# utils/redis_keys.py
class RedisKeyManager:
    def __init__(self, system_prefix: str = "job_queue"):
        self.system_prefix = system_prefix

    # Worker-related keys
    def worker_key(self, worker_id: str) -> str:
        return f"{self.system_prefix}:worker:{worker_id}"

    def worker_heartbeat_key(self, worker_id: str) -> str:
        return f"{self.system_prefix}:worker_heartbeat:{worker_id}"

    # Job-related keys
    def job_key(self, job_id: str) -> str:
        return f"{self.system_prefix}:job:{job_id}"

    def job_status_key(self, job_id: str) -> str:
        return f"{self.system_prefix}:job_status:{job_id}"

    # Queue keys
    def priority_queue(self, priority: str) -> str:
        return f"{self.system_prefix}:queue:{priority}"

    # Dependency tracking
    def job_dependencies_key(self, job_id: str) -> str:
        return f"{self.system_prefix}:dependencies:{job_id}"
    
    def job_dependents_key(self, job_id: str) -> str:
        return f"{self.system_prefix}:dependents:{job_id}"
    
    def dead_letter_queue_key(self) -> str:
        return f"{self.system_prefix}:dead_letter_queue"
    def processing_queue_key(self) -> str:
        return f"{self.system_prefix}:processing_queue"
    
    def active_workers_key(self) -> str:
        return f"{self.system_prefix}:active_workers"
    def worker_heartbeats(self) -> str:
        return f"{self.system_prefix}:worker_heartbeats"
    
    def job_results_key(self) -> str:
        return f"{self.system_prefix}:job_results"