from enum import Enum

class PriorityLevel(str, Enum):
    low = 'low'
    normal = 'normal'
    high = 'high'

class JobStatus(str, Enum):
    pending = 'pending'
    processing = 'processing'
    processed = 'processed'
    failed = 'failed'
    retrying = 'retrying'  # Used for tracking retries
    cancelled = 'cancelled'
    completed = 'completed'

