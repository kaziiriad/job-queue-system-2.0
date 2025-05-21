#!/usr/bin/env python3
import asyncio
import aiohttp
import argparse
import time
import random
import json
import logging
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Default settings
DEFAULT_API_URL = "http://localhost:8000"
DEFAULT_JOBS = 100
DEFAULT_CONCURRENCY = 10
DEFAULT_PRIORITY_DISTRIBUTION = "30,50,20"  # high,normal,low in percentages
DEFAULT_DEPENDENCY_PROBABILITY = 0.2  # 20% chance of having dependencies
DEFAULT_MAX_DEPENDENCIES = 3
DEFAULT_JOB_TITLE_PREFIX = "Stress Test Job"

class JobQueueStressTester:
    def __init__(self, api_url, total_jobs, concurrency, priority_distribution, 
                 dependency_probability, max_dependencies, job_title_prefix):
        self.api_url = api_url
        self.total_jobs = total_jobs
        self.concurrency = concurrency
        self.priority_distribution = self._parse_priority_distribution(priority_distribution)
        self.dependency_probability = dependency_probability
        self.max_dependencies = max_dependencies
        self.job_title_prefix = job_title_prefix
        
        self.created_jobs = []
        self.start_time = None
        self.end_time = None
        
        # Statistics
        self.successful_jobs = 0
        self.failed_jobs = 0
        self.job_statuses = {}
        
    def _parse_priority_distribution(self, distribution_str):
        """Parse the priority distribution string into a dictionary."""
        try:
            high, normal, low = map(int, distribution_str.split(','))
            if high + normal + low != 100:
                logger.warning("Priority distribution doesn't sum to 100%. Normalizing...")
                total = high + normal + low
                high = int(high * 100 / total)
                normal = int(normal * 100 / total)
                low = 100 - high - normal
            
            return {"high": high, "normal": normal, "low": low}
        except ValueError:
            logger.error(f"Invalid priority distribution: {distribution_str}. Using default.")
            return {"high": 30, "normal": 50, "low": 20}
    
    def _select_priority(self):
        """Select a priority based on the configured distribution."""
        rand = random.randint(1, 100)
        if rand <= self.priority_distribution["high"]:
            return "high"
        elif rand <= self.priority_distribution["high"] + self.priority_distribution["normal"]:
            return "normal"
        else:
            return "low"
    
    def _select_dependencies(self):
        """Randomly select dependencies from already created jobs."""
        if not self.created_jobs or random.random() > self.dependency_probability:
            return None
        
        num_deps = random.randint(1, min(self.max_dependencies, len(self.created_jobs)))
        return random.sample(self.created_jobs, num_deps)
    
    async def create_job(self, session, job_id):
        """Create a single job with the API."""
        priority = self._select_priority()
        dependencies = self._select_dependencies()
        
        job_data = {
            "job_title": f"{self.job_title_prefix} {job_id}",
            "priority": priority,
            "status": "pending",  # Explicitly set the status
            "max_retries": random.randint(1, 5)
        }
        
        if dependencies:
            job_data["dependencies"] = dependencies
        
        try:
            logger.debug(f"Creating job with data: {job_data}")
            async with session.post(f"{self.api_url}/jobs/create", json=job_data) as response:
                if response.status == 200:
                    result = await response.json()
                    self.created_jobs.append(result["job_id"])
                    self.successful_jobs += 1
                    logger.debug(f"Created job {job_id} with ID {result['job_id']}")
                    return result["job_id"]
                else:
                    self.failed_jobs += 1
                    error_text = await response.text()
                    logger.error(f"Failed to create job {job_id}: {response.status} - {error_text}")
                    return None
        except Exception as e:
            self.failed_jobs += 1
            logger.error(f"Exception creating job {job_id}: {str(e)}")
            return None
    
    async def check_job_status(self, session, job_id):
        """Check the status of a job."""
        try:
            async with session.get(f"{self.api_url}/jobs/{job_id}") as response:
                if response.status == 200:
                    result = await response.json()
                    status = result.get("status", "unknown")
                    
                    # Update status counts
                    if status not in self.job_statuses:
                        self.job_statuses[status] = 0
                    self.job_statuses[status] += 1
                    
                    return status
                else:
                    logger.error(f"Failed to check job {job_id}: {response.status}")
                    return "error"
        except Exception as e:
            logger.error(f"Exception checking job {job_id}: {str(e)}")
            return "error"
    
    async def monitor_queue_metrics(self, session):
        """Monitor queue metrics during the test."""
        try:
            async with session.get(f"{self.api_url}/dashboard/metrics/queue") as response:
                if response.status == 200:
                    return await response.json()
                else:
                    logger.error(f"Failed to get queue metrics: {response.status}")
                    return None
        except Exception as e:
            logger.error(f"Exception getting queue metrics: {str(e)}")
            return None
    
    async def monitor_worker_metrics(self, session):
        """Monitor worker metrics during the test."""
        try:
            async with session.get(f"{self.api_url}/dashboard/metrics/workers") as response:
                if response.status == 200:
                    return await response.json()
                else:
                    logger.error(f"Failed to get worker metrics: {response.status}")
                    return None
        except Exception as e:
            logger.error(f"Exception getting worker metrics: {str(e)}")
            return None
    
    async def run_monitoring(self, session):
        """Run continuous monitoring of the system during the test."""
        while not self.end_time:
            queue_metrics = await self.monitor_queue_metrics(session)
            worker_metrics = await self.monitor_worker_metrics(session)
            
            if queue_metrics and worker_metrics:
                logger.info(f"Queue Metrics: High={queue_metrics.get('pending_high', 0)}, "
                           f"Normal={queue_metrics.get('pending_normal', 0)}, "
                           f"Low={queue_metrics.get('pending_low', 0)}, "
                           f"Processing={queue_metrics.get('processing', 0)}, "
                           f"DLQ={queue_metrics.get('dead_letters', 0)}")
                
                logger.info(f"Worker Metrics: Active={worker_metrics.get('active_workers', 0)}, "
                           f"Stale={worker_metrics.get('stale_workers', 0)}")
            
            # Check job statuses
            statuses = {}
            for job_id in random.sample(self.created_jobs, min(10, len(self.created_jobs))):
                status = await self.check_job_status(session, job_id)
                if status not in statuses:
                    statuses[status] = 0
                statuses[status] += 1
            
            logger.info(f"Sample Job Statuses: {statuses}")
            
            await asyncio.sleep(5)  # Check every 5 seconds
    
    async def create_jobs(self):
        """Create all jobs with the specified concurrency."""
        self.start_time = time.time()
        logger.info(f"Starting stress test with {self.total_jobs} jobs, concurrency={self.concurrency}")
        logger.info(f"Priority distribution: {self.priority_distribution}")
        
        async with aiohttp.ClientSession() as session:
            # Start monitoring in a separate task
            monitoring_task = asyncio.create_task(self.run_monitoring(session))
            
            # Create jobs with the specified concurrency
            tasks = set()
            for i in range(1, self.total_jobs + 1):
                if len(tasks) >= self.concurrency:
                    # Wait for some tasks to complete before adding more
                    done, tasks = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
                
                tasks.add(asyncio.create_task(self.create_job(session, i)))
                
                # Small delay to avoid overwhelming the API
                await asyncio.sleep(0.05)
            
            # Wait for all remaining tasks to complete
            if tasks:
                await asyncio.wait(tasks)
            
            self.end_time = time.time()
            
            # Wait a bit for monitoring to catch up
            await asyncio.sleep(2)
            monitoring_task.cancel()
            
            # Final check of all jobs
            logger.info("Checking final status of all jobs...")
            final_statuses = {}
            for job_id in self.created_jobs:
                status = await self.check_job_status(session, job_id)
                if status not in final_statuses:
                    final_statuses[status] = 0
                final_statuses[status] += 1
            
            # Get final metrics
            final_queue_metrics = await self.monitor_queue_metrics(session)
            final_worker_metrics = await self.monitor_worker_metrics(session)
            
            return final_statuses, final_queue_metrics, final_worker_metrics
    
    def print_results(self, final_statuses, final_queue_metrics, final_worker_metrics):
        """Print the results of the stress test."""
        duration = self.end_time - self.start_time
        jobs_per_second = self.successful_jobs / duration
        
        print("\n" + "="*50)
        print(f"STRESS TEST RESULTS")
        print("="*50)
        print(f"Total jobs created: {self.successful_jobs}")
        print(f"Failed job creations: {self.failed_jobs}")
        print(f"Test duration: {duration:.2f} seconds")
        print(f"Jobs per second: {jobs_per_second:.2f}")
        print("\nFinal Job Statuses:")
        for status, count in final_statuses.items():
            print(f"  {status}: {count} ({count/len(self.created_jobs)*100:.1f}%)")
        
        print("\nFinal Queue Metrics:")
        if final_queue_metrics:
            for key, value in final_queue_metrics.items():
                print(f"  {key}: {value}")
        
        print("\nFinal Worker Metrics:")
        if final_worker_metrics:
            for key, value in final_worker_metrics.items():
                print(f"  {key}: {value}")
        
        print("="*50)
        
        # Determine if the test was successful
        if final_statuses.get("completed", 0) > 0.8 * len(self.created_jobs):
            print("✅ STRESS TEST PASSED: Most jobs completed successfully")
        elif final_statuses.get("processing", 0) + final_statuses.get("completed", 0) > 0.8 * len(self.created_jobs):
            print("⚠️ STRESS TEST PARTIALLY PASSED: Most jobs are processing or completed")
        else:
            print("❌ STRESS TEST FAILED: Too many jobs in error or pending state")
        
        # Check if worker scaling worked
        if final_worker_metrics and final_worker_metrics.get("active_workers", 0) > 1:
            print("✅ WORKER SCALING: Workers scaled up successfully")
        else:
            print("⚠️ WORKER SCALING: No evidence of worker scaling")

async def main():
    parser = argparse.ArgumentParser(description="Stress test the job queue system")
    parser.add_argument("--api-url", default=DEFAULT_API_URL, help=f"API URL (default: {DEFAULT_API_URL})")
    parser.add_argument("--jobs", type=int, default=DEFAULT_JOBS, help=f"Number of jobs to create (default: {DEFAULT_JOBS})")
    parser.add_argument("--concurrency", type=int, default=DEFAULT_CONCURRENCY, 
                        help=f"Number of concurrent job creations (default: {DEFAULT_CONCURRENCY})")
    parser.add_argument("--priority", default=DEFAULT_PRIORITY_DISTRIBUTION, 
                        help=f"Priority distribution as high,normal,low percentages (default: {DEFAULT_PRIORITY_DISTRIBUTION})")
    parser.add_argument("--dependency-prob", type=float, default=DEFAULT_DEPENDENCY_PROBABILITY, 
                        help=f"Probability of a job having dependencies (default: {DEFAULT_DEPENDENCY_PROBABILITY})")
    parser.add_argument("--max-dependencies", type=int, default=DEFAULT_MAX_DEPENDENCIES, 
                        help=f"Maximum number of dependencies per job (default: {DEFAULT_MAX_DEPENDENCIES})")
    parser.add_argument("--job-prefix", default=DEFAULT_JOB_TITLE_PREFIX, 
                        help=f"Prefix for job titles (default: {DEFAULT_JOB_TITLE_PREFIX})")
    
    args = parser.parse_args()
    
    tester = JobQueueStressTester(
        api_url=args.api_url,
        total_jobs=args.jobs,
        concurrency=args.concurrency,
        priority_distribution=args.priority,
        dependency_probability=args.dependency_prob,
        max_dependencies=args.max_dependencies,
        job_title_prefix=args.job_prefix
    )
    
    final_statuses, final_queue_metrics, final_worker_metrics = await tester.create_jobs()
    tester.print_results(final_statuses, final_queue_metrics, final_worker_metrics)

if __name__ == "__main__":
    asyncio.run(main())
