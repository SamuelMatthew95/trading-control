# Multi-stage build for production
FROM python:3.14-alpine as builder

# Install build dependencies
RUN apk add --no-cache \
    gcc \
    musl-dev \
    postgresql-dev \
    redis-dev \
    libffi-dev \
    openssl-dev

WORKDIR /app

# Copy and install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Production stage
FROM python:3.14-alpine

# Install runtime dependencies
RUN apk add --no-cache \
    postgresql-client \
    redis

# Create non-root user for security
RUN addgroup -g 1000 trading && \
    adduser -D -s /bin/sh -u 1000 -G trading trading

WORKDIR /app

# Copy installed packages from builder
COPY --from=builder /usr/local/lib/python3.14/site-packages /usr/local/lib/python3.14/site-packages
COPY --from=builder /usr/local/bin /usr/local/bin

# Copy application code
COPY . .

# Create logs directory
RUN mkdir -p logs && chown trading:trading logs

# Set permissions
RUN chown -R trading:trading /app

# Switch to non-root user
USER trading

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD python -c "import asyncio; from api.redis_client import get_redis; asyncio.run(get_redis().ping())" || exit 1

# Expose port
EXPOSE 8000

# Start command (optimized for containers)
CMD ["python", "api/v3_container_system.py"]
