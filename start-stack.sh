#!/bin/bash

# Script to start the job-queue Docker Stack

# Set colors for output
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

echo -e "${YELLOW}Starting job-queue Docker Stack...${NC}"

# Check if Docker is running
if ! docker info > /dev/null 2>&1; then
    echo "Error: Docker is not running. Please start Docker and try again."
    exit 1
fi

# Check if local registry is running, if not start it
if ! docker ps | grep -q "registry:2"; then
    echo -e "${BLUE}Starting local Docker registry...${NC}"
    docker run -d -p 5000:5000 --restart=always --name registry registry:2
    echo "Local registry started at localhost:5000"
else
    echo "Local registry is already running"
fi

# Build and push images to local registry
echo -e "${BLUE}Building and pushing images to local registry...${NC}"

# Build job-queue-api image
echo "Building job-queue-api image..."
docker build -t localhost:5000/job-queue-api:latest -f Dockerfile.job_queue .
if [ $? -ne 0 ]; then
    echo "Error: Failed to build job-queue-api image."
    exit 1
fi

# Build job-queue-worker image
echo "Building job-queue-worker image..."
docker build -t localhost:5000/job-queue-worker:latest -f Dockerfile.worker .
if [ $? -ne 0 ]; then
    echo "Error: Failed to build job-queue-worker image."
    exit 1
fi

# Build job-queue-monitor image
echo "Building job-queue-monitor image..."
docker build -t localhost:5000/job-queue-monitor:latest -f Dockerfile.monitor .
if [ $? -ne 0 ]; then
    echo "Error: Failed to build job-queue-monitor image."
    exit 1
fi

# Push images to local registry
echo "Pushing images to local registry..."
docker push localhost:5000/job-queue-api:latest
docker push localhost:5000/job-queue-worker:latest
docker push localhost:5000/job-queue-monitor:latest

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

# Update docker-compose.yml to use local registry images
echo "Updating docker-compose.yml to use local registry images..."
sed -i.bak 's|image: job-queue-api:latest|image: localhost:5000/job-queue-api:latest|g' docker-compose.yml
sed -i.bak 's|image: job-queue-worker:latest|image: localhost:5000/job-queue-worker:latest|g' docker-compose.yml
sed -i.bak 's|image: job-queue-monitor:latest|image: localhost:5000/job-queue-monitor:latest|g' docker-compose.yml

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
echo "waiting for stack to be removed..."
sleep 15
# Deploy the stack
echo "Deploying job-queue stack..."
docker stack deploy -c docker-compose.yml job-queue

# Check if deployment was successful
if [ $? -eq 0 ]; then
    echo -e "${GREEN}job-queue stack deployed successfully!${NC}"
    echo -e "${YELLOW}Services:${NC}"
    docker stack services job-queue
    
    echo -e "\n${YELLOW}Access the application at:${NC}"
    echo -e "  - Home: ${GREEN}http://localhost:8000/${NC}"
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