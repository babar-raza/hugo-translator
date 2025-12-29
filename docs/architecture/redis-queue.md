# Redis Queue Architecture

## Overview

The hugo-translator system uses **Redis** as a distributed job queue to coordinate translation work between the orchestrator and multiple workers. This architecture enables:

- **Horizontal scaling**: Add workers dynamically to increase throughput
- **Job persistence**: Jobs survive orchestrator/worker restarts
- **Fault tolerance**: Workers can fail without losing jobs
- **Visibility**: Monitor queue depth, job status, processing statistics

## Architecture Diagram

```
┌─────────────────────────────────────────────────────────────────────┐
│                        Hugo Translator System                        │
└─────────────────────────────────────────────────────────────────────┘

┌──────────────────┐         ┌──────────────────┐         ┌──────────────────┐
│   Orchestrator   │         │      Redis       │         │   Worker(s)      │
│                  │         │   Job Queue      │         │                  │
│  ┌────────────┐  │         │                  │         │  ┌────────────┐  │
│  │File Watcher│  │         │  ┌────────────┐  │         │  │Job         │  │
│  │& Scheduler │  │ ENQUEUE │  │Priority    │  │ DEQUEUE │  │Processor   │  │
│  └─────┬──────┘  ├────────>│  │Queue       │  ├────────>│  └─────┬──────┘  │
│        │         │         │  │(Sorted Set)│  │         │        │         │
│        v         │         │  └────────────┘  │         │        v         │
│  ┌────────────┐  │         │                  │         │  ┌────────────┐  │
│  │Translation │  │         │  ┌────────────┐  │         │  │Translation │  │
│  │Job Creator │  │         │  │Job         │  │         │  │Engine      │  │
│  └────────────┘  │         │  │Metadata    │  │         │  └────────────┘  │
│                  │         │  │(Hash)      │  │         │                  │
│                  │         │  └────────────┘  │         │                  │
│                  │  STATUS │                  │  STATUS │                  │
│                  │ <───────┤  ┌────────────┐  ├<────────┤                  │
│                  │  UPDATE │  │Statistics  │  │  UPDATE │                  │
│                  │         │  │(Hash)      │  │         │                  │
│                  │         │  └────────────┘  │         │                  │
└──────────────────┘         └──────────────────┘         └──────────────────┘
```

## Data Structures

Redis stores queue data in three primary structures:

### 1. Priority Queue (Sorted Set)

**Key**: `hugo_translation:queue`

**Structure**: Redis Sorted Set where:
- **Member**: Job ID (string)
- **Score**: `priority * 1e10 + timestamp_ms`
  - Lower score = higher priority
  - Priority 1 jobs processed before priority 10
  - Within same priority: FIFO (first-in-first-out)

**Example**:
```
127.0.0.1:6379> ZRANGE hugo_translation:queue 0 -1 WITHSCORES
1) "job_abc123"
2) "30000001703521234567"  # Priority 3, timestamp 1703521234567
3) "job_def456"
4) "50000001703521235000"  # Priority 5, timestamp 1703521235000
```

### 2. Job Metadata (Hash)

**Key**: `hugo_translation:jobs`

**Structure**: Redis Hash where:
- **Field**: Job ID
- **Value**: JSON-serialized TranslationJob object

**Example**:
```json
{
  "job_id": "job_abc123",
  "job_type": "sweep_batch",
  "site_id": "docs.example.com",
  "target_langs": ["es", "fr", "de"],
  "input_paths": ["/content/docs/guide.md", "/content/docs/api.md"],
  "priority": 3,
  "status": "pending",
  "created_at": "2024-12-26T10:30:00",
  "metadata": {
    "sweep_id": "sweep-20241226-001",
    "batch_number": 5
  }
}
```

### 3. Statistics (Hash)

**Key**: `hugo_translation:stats`

**Structure**: Redis Hash with counters:
- `pending`: Jobs waiting in queue
- `running`: Jobs currently being processed
- `completed`: Successfully completed jobs
- `failed`: Failed jobs
- `total_enqueued`: Total jobs ever enqueued

## Job Lifecycle

### 1. Job Creation (Orchestrator)

```python
from src.orchestrator.redis_backend import RedisJobQueue
from src.orchestrator.models import TranslationJob, JobType

# Initialize queue
queue = RedisJobQueue(
    host="hugo-translator-redis",
    port=6379,
    db=0
)

# Create job
job = TranslationJob(
    job_id="unique-job-id",
    job_type=JobType.FILE,
    site_id="docs.example.com",
    target_langs=["es", "fr"],
    input_paths=[Path("/content/guide.md")],
    priority=5
)

# Enqueue
job_id = queue.enqueue(job)
```

**Redis Operations**:
1. `ZADD hugo_translation:queue <score> <job_id>` - Add to priority queue
2. `HSET hugo_translation:jobs <job_id> <json>` - Store job metadata
3. `HINCRBY hugo_translation:stats pending 1` - Increment pending count

### 2. Job Dequeue (Worker)

```python
# Worker polls queue
job = queue.dequeue()  # Returns TranslationJob or None
```

**Redis Operations** (Atomic Pipeline):
1. `ZRANGE hugo_translation:queue 0 0` - Peek highest priority job
2. `HGET hugo_translation:jobs <job_id>` - Fetch job metadata
3. `ZREM hugo_translation:queue <job_id>` - Remove from queue
4. `HSET hugo_translation:jobs <job_id> <updated_json>` - Update status=RUNNING
5. `HINCRBY hugo_translation:stats pending -1` - Decrement pending
6. `HINCRBY hugo_translation:stats running 1` - Increment running

### 3. Job Processing (Worker)

Worker processes translation using TranslationEngine:
```python
result = engine.translate_file(
    site_profile=site_profile,
    source_file=job.input_paths[0],
    target_langs=job.target_langs
)
```

### 4. Status Update (Worker)

```python
# On success
queue.update_job_status(
    job_id=job.job_id,
    status=JobStatus.COMPLETED,
    result_summary={"files_processed": 1}
)

# On failure
queue.update_job_status(
    job_id=job.job_id,
    status=JobStatus.FAILED,
    error_message="Translation failed: Model not loaded"
)
```

**Redis Operations**:
1. `HSET hugo_translation:jobs <job_id> <updated_json>` - Update status
2. `HINCRBY hugo_translation:stats running -1` - Decrement running
3. `HINCRBY hugo_translation:stats completed 1` - Increment completed (or failed)

## Deployment

### Prerequisites

- Docker and Docker Compose installed
- Redis container configured in `docker-compose.yml`
- Environment variables configured in `.env.production`

### Configuration

#### 1. Environment Variables

Add to `.env.production`:
```bash
# Redis Configuration
REDIS_HOST=hugo-translator-redis
REDIS_PORT=6379
REDIS_DB=0
REDIS_PASSWORD=

# Queue Backend
QUEUE_BACKEND=redis

# Worker Configuration
WORKER_MODE=processor
POLL_INTERVAL=5
MAX_RETRIES=3
```

#### 2. Docker Compose Services

**Redis Service**:
```yaml
redis:
  image: redis:7-alpine
  container_name: hugo-translator-redis
  command: redis-server --appendonly yes --appendfsync everysec
  ports:
    - "6379:6379"
  volumes:
    - redis_data:/data
  networks:
    - hugo-translator-network
  healthcheck:
    test: ["CMD", "redis-cli", "ping"]
    interval: 10s
    timeout: 3s
    retries: 3
```

**Orchestrator Service** (with Redis backend):
```yaml
orchestrator:
  environment:
    - QUEUE_BACKEND=redis
    - REDIS_HOST=hugo-translator-redis
    - REDIS_PORT=6379
  depends_on:
    redis:
      condition: service_healthy
```

**Worker Service** (processor mode):
```yaml
worker-cpu:
  environment:
    - WORKER_MODE=processor
    - REDIS_HOST=hugo-translator-redis
    - REDIS_PORT=6379
    - POLL_INTERVAL=5
  depends_on:
    redis:
      condition: service_healthy
    orchestrator:
      condition: service_healthy
```

### Starting the System

```bash
# Start all services
docker-compose up -d

# Verify Redis is running
docker-compose ps redis
docker exec hugo-translator-redis redis-cli ping  # Should return "PONG"

# Verify orchestrator connected
docker logs hugo-translator-orchestrator | grep "Using Redis queue backend"

# Verify worker started
docker logs hugo-translator-worker-cpu | grep "Job processor started"
```

## Monitoring

### Queue Statistics

```bash
# Get queue stats
docker exec hugo-translator-redis redis-cli HGETALL "hugo_translation:stats"

# Output:
# pending: 42
# running: 3
# completed: 158
# failed: 2
```

### Queue Depth

```bash
# Count pending jobs
docker exec hugo-translator-redis redis-cli ZCARD "hugo_translation:queue"

# Peek at next job
docker exec hugo-translator-redis redis-cli ZRANGE "hugo_translation:queue" 0 0 WITHSCORES
```

### Job Details

```bash
# Get specific job
docker exec hugo-translator-redis redis-cli HGET "hugo_translation:jobs" "job_abc123"

# List all job IDs
docker exec hugo-translator-redis redis-cli HKEYS "hugo_translation:jobs"
```

### Real-time Monitoring

```bash
# Monitor Redis commands
docker exec -it hugo-translator-redis redis-cli MONITOR

# Watch queue size
watch -n 1 'docker exec hugo-translator-redis redis-cli ZCARD "hugo_translation:queue"'
```

## Scaling

### Adding Workers

To increase translation throughput, add more workers:

```bash
# Scale CPU workers
docker-compose up -d --scale worker-cpu=3

# Workers will automatically start processing jobs from shared queue
```

**Important**: Each worker must have:
- Unique `WORKER_ID` environment variable
- Access to shared Redis queue
- Access to shared TM storage (L2/L3)

### Horizontal Scaling Considerations

1. **TM Contention**: Workers share L2 (LMDB) and L3 (FAISS) translation memory
   - L1 cache is per-worker (isolated)
   - L2/L3 use file locks for concurrent access
   - Monitor lock contention under high load

2. **Model Loading**: Each worker loads translation models independently
   - Models consume GPU/CPU memory
   - Plan worker count based on available resources

3. **I/O Bottlenecks**: Content files accessed from shared volume
   - Ensure volume supports concurrent reads/writes
   - Consider NFS/network storage for multi-node deployment

## Troubleshooting

### Jobs Stuck in Queue

**Symptom**: Queue size increases, no jobs processed

**Diagnosis**:
```bash
# Check worker logs
docker logs hugo-translator-worker-cpu --tail=100

# Verify worker is running
docker ps --filter name=worker
```

**Solutions**:
- Restart worker: `docker-compose restart worker-cpu`
- Check worker errors in logs
- Verify Redis connectivity from worker

### Redis Connection Failed

**Symptom**: `Failed to initialize queue backend` in logs

**Diagnosis**:
```bash
# Check Redis health
docker exec hugo-translator-redis redis-cli ping

# Verify network connectivity
docker exec hugo-translator-orchestrator ping hugo-translator-redis
```

**Solutions**:
- Restart Redis: `docker-compose restart redis`
- Check `REDIS_HOST` environment variable
- Verify Docker network configuration

### Jobs Marked as Failed

**Symptom**: High `failed` count in stats

**Diagnosis**:
```bash
# Get failed job details
docker exec hugo-translator-redis redis-cli HGETALL "hugo_translation:jobs" | grep -A 20 "failed"

# Check worker error logs
docker logs hugo-translator-worker-cpu | grep ERROR
```

**Common Causes**:
- Site profile not found → Check `config/site_profiles/`
- Source file not found → Verify content volume mount
- Model loading failed → Check model cache and GPU availability
- Translation engine error → Review engine logs

### Queue Growing Too Fast

**Symptom**: Pending jobs increase faster than workers can process

**Solutions**:
1. **Scale workers**: `docker-compose up -d --scale worker-cpu=5`
2. **Add GPU workers**: If available, GPU workers process faster
3. **Optimize batch size**: Reduce `MODEL_BATCH_SIZE` to process smaller batches
4. **Filter input**: Reduce sweep frequency or filter source files

### Data Persistence Issues

**Symptom**: Jobs lost after Redis restart

**Diagnosis**:
```bash
# Check Redis persistence mode
docker exec hugo-translator-redis redis-cli CONFIG GET appendonly

# Verify data directory
docker exec hugo-translator-redis ls -lh /data
```

**Solutions**:
- Enable AOF: Add `--appendonly yes` to Redis command
- Verify volume mount: `redis_data:/data`
- Check disk space: `df -h`

## Best Practices

### 1. Resource Planning

- **CPU Workers**: 1 worker per 4 CPU cores
- **GPU Workers**: 1 worker per GPU device
- **Redis Memory**: Allocate 512MB-1GB for queue metadata
- **Model Cache**: 5-10GB per worker for model storage

### 2. Queue Management

- **Priority System**: Use priorities 1-10 (1=highest) for job urgency
- **Batch Sizes**: Keep batch sizes small (10-50 files) for better parallelization
- **Monitoring**: Set up alerts for queue depth > 1000 jobs

### 3. Failure Handling

- **Retry Logic**: Implement exponential backoff for retryable errors
- **Dead Letter Queue**: Move permanently failed jobs to separate queue
- **Error Logging**: Capture full stack traces for debugging

### 4. Performance Optimization

- **Connection Pooling**: Redis client uses connection pooling by default
- **Pipeline Operations**: Atomic operations use Redis pipelines
- **Lazy Job Loading**: Workers only load job metadata when processing

## Security

### Redis Authentication

Enable password authentication:

```yaml
# docker-compose.yml
redis:
  command: redis-server --appendonly yes --requirepass YOUR_PASSWORD
```

```bash
# .env.production
REDIS_PASSWORD=YOUR_PASSWORD
```

### Network Isolation

- Redis runs on internal Docker network
- Only orchestrator and workers have access
- Port 6379 not exposed to host (remove `ports:` section for production)

### Data Encryption

For sensitive translation content:
- Use TLS for Redis connections (Redis 6+)
- Encrypt data at rest using volume encryption
- Implement job data encryption before storing in Redis

## Migration from In-Memory Queue

To migrate from in-memory queue to Redis:

1. **Deploy Redis**:
   ```bash
   docker-compose up -d redis
   ```

2. **Update Environment**:
   ```bash
   # Set QUEUE_BACKEND=redis in .env.production
   ```

3. **Rebuild Services**:
   ```bash
   docker-compose build orchestrator worker-cpu
   ```

4. **Rolling Restart**:
   ```bash
   docker-compose restart orchestrator
   docker-compose restart worker-cpu
   ```

5. **Verify**:
   ```bash
   docker logs hugo-translator-orchestrator | grep "Using Redis queue backend"
   ```

**Note**: In-memory jobs are not migrated. Finish processing before switching.

## References

- [Redis Data Structures](https://redis.io/docs/data-types/)
- [Redis Persistence](https://redis.io/docs/management/persistence/)
- [Redis Best Practices](https://redis.io/docs/management/optimization/)
- [Docker Compose Networking](https://docs.docker.com/compose/networking/)
