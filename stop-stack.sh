#!/bin/bash

# Script to stop the job-queue Docker Stack

# Set colors for output
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m' # No Color

echo -e "${YELLOW}Stopping job-queue Docker Stack...${NC}"

# Check if Docker is running
if ! docker info > /dev/null 2>&1; then
    echo -e "${RED}Error: Docker is not running. Please start Docker and try again.${NC}"
    exit 1
fi

# Check if the stack exists
if ! docker stack ls | grep -q "job-queue"; then
    echo -e "${YELLOW}job-queue stack is not running.${NC}"
    exit 0
fi

# Remove the stack
echo "Removing job-queue stack..."
docker stack rm job-queue

# Wait for the stack to be completely removed
echo "Waiting for stack to be removed..."
while docker service ls | grep -q "job-queue"; do
    echo -n "."
    sleep 1
done
echo ""

echo -e "${GREEN}job-queue stack stopped successfully!${NC}"

# Ask if user wants to remove volumes
read -p "Do you want to remove persistent data volumes? (y/N): " remove_volumes
if [[ $remove_volumes =~ ^[Yy]$ ]]; then
    echo "Removing volumes..."
    # List volumes related to the stack
    volumes=$(docker volume ls --filter name=job-queue -q)
    
    if [ -z "$volumes" ]; then
        echo "No volumes found for job-queue stack."
    else
        # Remove each volume
        for volume in $volumes; do
            echo "Removing volume: $volume"
            docker volume rm $volume
        done
        echo -e "${GREEN}Volumes removed successfully!${NC}"
    fi
else
    echo "Volumes preserved. Data will be available when you restart the stack."
fi

echo -e "\n${YELLOW}To start the stack again, run:${NC}"
echo "  ./start-stack.sh"

exit 0