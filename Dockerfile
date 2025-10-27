# Dockerfile for RAG News Generation Workers
FROM python:3.12-slim

# Set working directory
WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements and install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy source code and scripts
COPY src/ ./src/
COPY run_integrated_pipeline.py .
COPY config.example.env .

# Create necessary directories
RUN mkdir -p output cache

# Set environment variables
ENV PYTHONPATH=/app
ENV PYTHONUNBUFFERED=1
ENV REDIS_HOST=localhost
ENV REDIS_PORT=6379
ENV KAFKA_BOOTSTRAP_SERVERS=localhost:19092

# Expose port (if needed for monitoring)
EXPOSE 8000

# Default command
CMD ["python", "run_integrated_pipeline.py"]

