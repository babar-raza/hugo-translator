# Hugo Translation System - Orchestrator
FROM python:3.10-slim

# Set working directory
WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    build-essential \
    git \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements
COPY requirements/base.txt requirements/base.txt
COPY requirements/cpu.txt requirements/cpu.txt

# Install Python dependencies
RUN pip install --no-cache-dir -r requirements/cpu.txt

# Copy application code
COPY src/ src/
COPY config/ config/

# Create data directories
RUN mkdir -p data logs artifacts models

# Set environment variables
ENV PYTHONPATH=/app
ENV PYTHONUNBUFFERED=1

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=40s --retries=3 \
  CMD python -c "import sys; sys.exit(0)"

# Default command
CMD ["python", "-m", "src.orchestrator.orchestrator"]
