#!/bin/bash

# Script to start the job-queue Docker Stack

# Set colors for output
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

echo -e "${YELLOW}Starting job-queue Docker Stack...${NC}"

# Check if Docker is running
if ! docker info > /dev/null 2>&1; then
    echo "Error: Docker is not running. Please start Docker and try again."
    exit 1
fi

# Check if Docker Swarm is initialized
if ! docker node ls > /dev/null 2>&1; then
    echo "Initializing Docker Swarm..."
    docker swarm init > /dev/null 2>&1
    if [ $? -ne 0 ]; then
        echo "Error: Failed to initialize Docker Swarm. Please initialize manually with 'docker swarm init'."
        exit 1
    fi
    echo "Docker Swarm initialized successfully."
fi

# Check if the stack already exists
if docker stack ls | grep -q "job-queue"; then
    echo "job-queue stack is already running. Removing it first..."
    docker stack rm job-queue
    
    # Wait for the stack to be completely removed
    echo "Waiting for stack to be removed..."
    while docker service ls | grep -q "job-queue"; do
        sleep 1
    done
    echo "Previous stack removed successfully."
fi

# Deploy the stack
echo "Deploying job-queue stack..."
docker stack deploy -c docker-compose.yml job-queue

# Check if deployment was successful
if [ $? -eq 0 ]; then
    echo -e "${GREEN}job-queue stack deployed successfully!${NC}"
    echo -e "${YELLOW}Services:${NC}"
    docker stack services job-queue
    
    echo -e "\n${YELLOW}Access the application at:${NC}"
    echo -e "  - Dashboard: ${GREEN}http://localhost:8000/dashboard/${NC}"
    echo -e "  - Job Management: ${GREEN}http://localhost:8000/jobs/manage${NC}"
    echo -e "  - API Documentation: ${GREEN}http://localhost:8000/docs${NC}"
else
    echo "Error: Failed to deploy job-queue stack."
    exit 1
fi

echo -e "\n${YELLOW}To monitor the stack, run:${NC}"
echo "  docker stack ps job-queue"

exit 0