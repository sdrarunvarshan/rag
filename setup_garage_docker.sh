#!/bin/bash
# Setup script for Garage with Docker (Linux/macOS)
# This script sets up Garage for image storage using Docker

echo "Setting up Garage with Docker for RAG system..."
echo ""

# Check if Docker is running
if ! docker ps > /dev/null 2>&1; then
    echo "ERROR: Docker is not running or not installed."
    echo "Please install Docker Desktop from https://www.docker.com/products/docker-desktop"
    exit 1
fi

echo "Docker is running."
echo ""

# Start Garage with Docker Compose
echo "Starting Garage with Docker Compose..."
docker-compose up -d

if [ $? -ne 0 ]; then
    echo "ERROR: Failed to start Garage."
    exit 1
fi

echo ""
echo "Garage started successfully!"
echo ""
echo "Garage services:"
echo "- S3 API: http://localhost:3900"
echo "- Web UI: http://localhost:3902"
echo ""
echo "Next steps:"
echo "1. Access Garage Web UI at http://localhost:3902"
echo "2. Create a bucket named 'rag-documents'"
echo "3. Create an access key"
echo "4. Update .env with your Garage credentials"
echo ""
echo "Default credentials (change these in production):"
echo "- Endpoint: http://localhost:3900"
echo "- Access Key: garage-key"
echo "- Secret Key: garage-secret"
echo "- Region: garage"
