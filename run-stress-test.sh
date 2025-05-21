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
    
    echo -e "\n${BLUE}Running Test: ${test_name}${NC}"
    echo -e "${YELLOW}Parameters:${NC}"
    echo "  Jobs: $jobs"
    echo "  Concurrency: $concurrency"
    echo "  Priority Distribution: $priority"
    echo "  Dependency Probability: $dependency_prob"
    
    python3 stress-test.py --jobs $jobs --concurrency $concurrency --priority $priority --dependency-prob $dependency_prob
    
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
    
    case $choice in
        1)
            run_test "Light Load Test" 100 5 "30,50,20" 0.1
            ;;
        2)
            run_test "Medium Load Test" 500 20 "30,50,20" 0.2
            ;;
        3)
            run_test "Heavy Load Test" 1000 50 "30,50,20" 0.2
            ;;
        4)
            run_test "Dependency-Heavy Test" 300 10 "30,50,20" 0.8
            ;;
        5)
            run_test "Priority Distribution Test" 300 15 "33,33,34" 0.2
            ;;
        6)
            echo -e "\n${YELLOW}Custom Test Parameters:${NC}"
            read -p "Number of jobs: " custom_jobs
            read -p "Concurrency level: " custom_concurrency
            read -p "Priority distribution (high,normal,low): " custom_priority
            read -p "Dependency probability (0.0-1.0): " custom_dependency_prob
            
            run_test "Custom Test" $custom_jobs $custom_concurrency $custom_priority $custom_dependency_prob
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