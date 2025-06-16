# Use NVIDIA CUDA base image
FROM nvidia/cuda:12.1.0-runtime-ubuntu22.04

# Set environment variables
ENV PYTHONUNBUFFERED=1 \
    DEBIAN_FRONTEND=noninteractive \
    PYTHON_VERSION=3.10 \
    PYTHONPATH=/app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    python3.10 \
    python3-pip \
    python3.10-venv \
    && rm -rf /var/lib/apt/lists/*

# Set working directory
WORKDIR /app

# Copy requirements first to leverage Docker cache
COPY requirements.txt .

# Install Python dependencies
RUN pip3 install --no-cache-dir -r requirements.txt

# Copy the application code
COPY . /app/

# Debug: List contents of /app directory
RUN ls -la /app

# Expose the port your application runs on
EXPOSE 8000

# Set environment variables for RunPod
ENV PORT=8000

# Command to run the application with debug logging
CMD ["sh", "-c", "ls -la /app && uvicorn api_server:app --host 0.0.0.0 --port 8000 --log-level debug"] 