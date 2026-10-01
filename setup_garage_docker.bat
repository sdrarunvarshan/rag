@echo off
REM Setup script for Garage with Docker (Windows)
REM This script sets up Garage for image storage using Docker

echo Setting up Garage with Docker for RAG system...
echo.

REM Check if Docker is running
docker ps >nul 2>&1
if %errorlevel% neq 0 (
    echo ERROR: Docker is not running or not installed.
    echo Please install Docker Desktop from https://www.docker.com/products/docker-desktop
    pause
    exit /b 1
)

echo Docker is running.
echo.

REM Start Garage with Docker Compose
echo Starting Garage with Docker Compose...
docker-compose up -d

if %errorlevel% neq 0 (
    echo ERROR: Failed to start Garage.
    pause
    exit /b 1
)

echo.
echo Garage started successfully!
echo.
echo Garage services:
echo - S3 API: http://localhost:3900
echo - Web UI: http://localhost:3902
echo.
echo Next steps:
echo 1. Access Garage Web UI at http://localhost:3902
echo 2. Create a bucket named 'rag-documents'
echo 3. Create an access key
echo 4. Update .env with your Garage credentials
echo.
echo Default credentials (change these in production):
echo - Endpoint: http://localhost:3900
echo - Access Key: garage-key
echo - Secret Key: garage-secret
echo - Region: garage
echo.
pause
