#!/bin/bash

# Script to restart the job-queue Docker Stack

# Set colors for output
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m' # No Color

echo -e "${YELLOW}Restarting job-queue Docker Stack...${NC}"

# Check if Docker is running
if ! docker info > /dev/null 2>&1; then
    echo -e "${RED}Error: Docker is not running. Please start Docker and try again.${NC}"
    exit 1
fi

# Check if Docker Swarm is initialized
if ! docker node ls > /dev/null 2>&1; then
    echo -e "${YELLOW}Initializing Docker Swarm...${NC}"
    docker swarm init > /dev/null 2>&1
    if [ $? -ne 0 ]; then
        echo -e "${RED}Error: Failed to initialize Docker Swarm. Please initialize manually with 'docker swarm init'.${NC}"
        exit 1
    fi
    echo "Docker Swarm initialized successfully."
fi

# Check if the stack exists
if ! docker stack ls | grep -q "job-queue"; then
    echo -e "${YELLOW}job-queue stack is not running. Will deploy a new stack.${NC}"
else
    # Remove the existing stack
    echo "Removing existing job-queue stack..."
    docker stack rm job-queue
    
    # Wait for the stack to be completely removed
    echo "Waiting for stack to be removed..."
    while docker service ls | grep -q "job-queue"; do
        echo -n "."
        sleep 1
    done
    echo -e "\nPrevious stack removed successfully."
fi

# Wait a moment before redeploying
echo "Waiting 7 seconds before redeploying..."
sleep 7

# Deploy the stack
echo "Deploying job-queue stack..."
docker stack deploy -c docker-compose.yml job-queue

# Check if deployment was successful
if [ $? -eq 0 ]; then
    echo -e "${GREEN}job-queue stack redeployed successfully!${NC}"
    echo -e "${YELLOW}Services:${NC}"
    docker stack services job-queue
    
    echo -e "\n${YELLOW}Access the application at:${NC}"
    echo -e "  - Home: ${GREEN}http://localhost:8000/${NC}"
    echo -e "  - Dashboard: ${GREEN}http://localhost:8000/dashboard/${NC}"
    echo -e "  - Job Management: ${GREEN}http://localhost:8000/jobs/manage${NC}"
    echo -e "  - API Documentation: ${GREEN}http://localhost:8000/docs${NC}"
else
    echo -e "${RED}Error: Failed to deploy job-queue stack.${NC}"
    exit 1
fi

echo -e "\n${YELLOW}To monitor the stack, run:${NC}"
echo "  docker stack ps job-queue"

echo -e "\n${GREEN}Restart completed successfully!${NC}"

exit 0