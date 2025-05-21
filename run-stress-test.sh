#!/bin/bash

# Script to run stress tests on the job queue system

# Set colors for output
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

echo -e "${YELLOW}Job Queue System Stress Test Runner${NC}"

# Check if Python 3 is installed
if ! command -v python3 &> /dev/null; then
    echo -e "${RED}Error: Python 3 is required but not installed.${NC}"
    exit 1
fi

# Check if required Python packages are installed
echo "Checking required Python packages..."
python3 -c "import aiohttp, asyncio" 2>/dev/null
if [ $? -ne 0 ]; then
    echo -e "${YELLOW}Installing required Python packages...${NC}"
    pip install aiohttp
fi

# Check if the stress test script exists
if [ ! -f "stress-test.py" ]; then
    echo -e "${RED}Error: stress-test.py not found in the current directory.${NC}"
    exit 1
fi

# Make the script executable
chmod +x stress-test.py

# Function to run a stress test with specific parameters
run_test() {
    local test_name=$1
    local jobs=$2
    local concurrency=$3
    local priority=$4
    local dependency_prob=$5
    local monitor_interval=$6
    local timeout=$7
    local no_wait=$8
    
    echo -e "\n${BLUE}Running Test: ${test_name}${NC}"
    echo -e "${YELLOW}Parameters:${NC}"
    echo "  Jobs: $jobs"
    echo "  Concurrency: $concurrency"
    echo "  Priority Distribution: $priority"
    echo "  Dependency Probability: $dependency_prob"
    echo "  Monitor Interval: $monitor_interval seconds"
    echo "  Timeout: $timeout seconds"
    
    if [ "$no_wait" = "true" ]; then
        echo "  Wait Mode: Don't wait for job completion"
        python3 stress-test.py --jobs $jobs --concurrency $concurrency --priority $priority --dependency-prob $dependency_prob --no-wait
    else
        echo "  Wait Mode: Wait for job completion"
        python3 stress-test.py --jobs $jobs --concurrency $concurrency --priority $priority --dependency-prob $dependency_prob --monitor-interval $monitor_interval --timeout $timeout
    fi
    
    echo -e "\n${GREEN}Test Complete: ${test_name}${NC}"
    echo -e "${YELLOW}Press Enter to continue to the next test...${NC}"
    read
}

# Main menu
while true; do
    echo -e "\n${BLUE}Select a stress test to run:${NC}"
    echo "1. Light Load Test (100 jobs, low concurrency)"
    echo "2. Medium Load Test (500 jobs, medium concurrency)"
    echo "3. Heavy Load Test (1000 jobs, high concurrency)"
    echo "4. Dependency-Heavy Test (300 jobs with many dependencies)"
    echo "5. Priority Distribution Test (equal jobs of each priority)"
    echo "6. Custom Test (specify your own parameters)"
    echo "7. Exit"
    
    read -p "Enter your choice (1-7): " choice
    
    # Default monitoring parameters
    monitor_interval=5
    timeout=300
    no_wait="false"
    
    case $choice in
        1)
            run_test "Light Load Test" 100 5 "30,50,20" 0.1 $monitor_interval $timeout $no_wait
            ;;
        2)
            run_test "Medium Load Test" 500 20 "30,50,20" 0.2 $monitor_interval $timeout $no_wait
            ;;
        3)
            run_test "Heavy Load Test" 1000 50 "30,50,20" 0.2 $monitor_interval $timeout $no_wait
            ;;
        4)
            run_test "Dependency-Heavy Test" 300 10 "30,50,20" 0.8 $monitor_interval $timeout $no_wait
            ;;
        5)
            run_test "Priority Distribution Test" 300 15 "33,33,34" 0.2 $monitor_interval $timeout $no_wait
            ;;
        6)
            echo -e "\n${YELLOW}Custom Test Parameters:${NC}"
            read -p "Number of jobs: " custom_jobs
            read -p "Concurrency level: " custom_concurrency
            read -p "Priority distribution (high,normal,low): " custom_priority
            read -p "Dependency probability (0.0-1.0): " custom_dependency_prob
            read -p "Monitor interval (seconds): " custom_monitor_interval
            read -p "Timeout (seconds): " custom_timeout
            read -p "Wait for job completion? (y/n): " wait_response
            
            if [[ $wait_response =~ ^[Nn]$ ]]; then
                custom_no_wait="true"
            else
                custom_no_wait="false"
            fi
            
            run_test "Custom Test" $custom_jobs $custom_concurrency $custom_priority $custom_dependency_prob $custom_monitor_interval $custom_timeout $custom_no_wait
            ;;
        7)
            echo -e "${GREEN}Exiting stress test runner.${NC}"
            exit 0
            ;;
        *)
            echo -e "${RED}Invalid choice. Please enter a number between 1 and 7.${NC}"
            ;;
    esac
done
