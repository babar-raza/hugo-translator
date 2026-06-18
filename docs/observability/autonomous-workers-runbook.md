# Autonomous Workers Runbook

Operations guide for deploying and managing autonomous translation workers.

## Quick Start

### Available Workers

This guide covers two autonomous workers:

1. **Autonomous Content Translation Worker** (`autonomous_content_translation_worker`)
   - Translates content files on a schedule
   - Supports oneshot and daemon modes
   - Handles VRAM budgeting and git commits

2. **TM Improvement Worker** (`tm_improvement_worker`)
   - Improves translation memory quality
   - Runs periodic optimization and cleanup
   - Manages TM database maintenance

Both workers can be invoked via:
- Direct module execution: `python -m src.workers.{worker_name}`
- WORKER_MODE environment variable: `WORKER_MODE=autonomous_translate python -m src.workers`
- WORKER_MODE environment variable: `WORKER_MODE=tm_improve python -m src.workers`

---

### Windows Task Scheduler Deployment

**Goal**: Run translations 5 times/day between 10:00-22:00 Pacific Time

**Steps**:

1. **Open Task Scheduler**
   - Press `Win+R`, type `taskschd.msc`, press Enter

2. **Create Task for 10:00 AM Run**
   - Click "Create Task" (not "Create Basic Task")
   - **General Tab**:
     - Name: `Hugo Translation - 10AM`
     - Description: `Autonomous translation worker (10:00 AM Pacific)`
     - Run whether user is logged on or not: ✓
     - Run with highest privileges: ✓
   - **Triggers Tab**:
     - New → Daily
     - Start: Select date, time `10:00:00 AM`
     - Synchronize across time zones: ✓ (set to Pacific Time)
     - Enabled: ✓
   - **Actions Tab**:
     - New → Start a program
     - Program: `C:\Python311\python.exe` (adjust to your Python path)
     - Arguments: `-m src.workers.autonomous_content_translation_worker --mode oneshot --log-level INFO`
     - Start in: `C:\Users\YourName\repos\hugo-translator` (adjust to your repo path)
   - **Conditions Tab**:
     - Start only if computer is on AC power: ✓ (recommended)
     - Wake computer to run: ✓ (optional)
   - **Settings Tab**:
     - Allow task to run on demand: ✓
     - Stop task if it runs longer than: `4 hours` (adjust based on your content size)
     - If task fails, restart every: `15 minutes`, attempt 3 times

3. **Repeat for Other Times**
   - Create 4 more tasks with names:
     - `Hugo Translation - 1PM` (1:00 PM)
     - `Hugo Translation - 4PM` (4:00 PM)
     - `Hugo Translation - 7PM` (7:00 PM)
     - `Hugo Translation - 10PM` (10:00 PM)

4. **Test First Run**
   - Right-click task → Run
   - Check last run status after completion
   - Review logs in output directory

**Expected Output**:
```
Task Scheduler → Task History:
✓ Hugo Translation - 10AM   Completed   2025-01-16 10:00:05
✓ Hugo Translation - 1PM    Completed   2025-01-16 13:00:03
✓ Hugo Translation - 4PM    Completed   2025-01-16 16:00:07
```

---

### Windows Task Scheduler - TM Improvement Worker

**Goal**: Run TM optimization weekly on Sunday at 2:00 AM

**Steps**:

1. **Create Task**
   - Name: `TM Improvement Worker - Weekly`
   - Description: `Translation memory improvement and optimization`
   - Run whether user is logged on or not: ✓
   - Run with highest privileges: ✓

2. **Trigger**:
   - Weekly → Sunday → 2:00 AM

3. **Action**:
   - Program: `C:\Python311\python.exe`
   - Arguments: `-m src.workers.tm_improvement_worker --mode oneshot --log-level INFO`
   - Start in: `C:\Users\YourName\repos\hugo-translator`

4. **Settings**:
   - Stop if runs longer than: `2 hours`
   - Restart on failure: ✓ (3 attempts, 15 min intervals)

**Alternative: Using WORKER_MODE Environment Variable**

You can also use the unified worker entry point:

- **Set Environment Variable**: In Task Scheduler → Actions → New Environment Variable
  - Name: `WORKER_MODE`
  - Value: `tm_improve`

- **Arguments**: `-m src.workers --log-level INFO`

This approach is useful if you want to switch worker types without modifying the command.

---

### Docker Compose Deployment (Recommended)

**Goal**: Single container that self-schedules 5 runs/day

**Files**:

`docker-compose.yml`:
```yaml
version: '3.8'

services:
  translation-worker:
    build:
      context: .
      dockerfile: Dockerfile
    container_name: hugo-translation-worker
    restart: unless-stopped
    environment:
      - TZ=America/Los_Angeles
      - EXECUTION_MODE=docker_gpu
      - DEVICE=cuda
      - LOG_LEVEL=INFO
    volumes:
      # Config (read-only)
      - ./config:/app/config:ro
      # Content directories (read-write for translations)
      - ./content:/app/content
      # Data (TM, telemetry, logs)
      - ./data:/app/data
      # Git credentials (if auto-push enabled)
      - ~/.gitconfig:/root/.gitconfig:ro
      - ~/.ssh:/root/.ssh:ro
    command: >
      python -m src.workers.autonomous_content_translation_worker
      --mode daemon
      --runs-per-day 5
      --window-start 10:00
      --window-end 22:00
      --timezone America/Los_Angeles
      --device cuda
      --max-gpu-memory-percent 60
      --log-level INFO
    deploy:
      resources:
        reservations:
          devices:
            - driver: nvidia
              count: 1
              capabilities: [gpu]
        limits:
          memory: 16G
```

`Dockerfile`:
```dockerfile
FROM nvidia/cuda:11.8.0-base-ubuntu22.04

# Install Python 3.11
RUN apt-get update && apt-get install -y \
    python3.11 \
    python3.11-venv \
    python3-pip \
    git \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy requirements first (for caching)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . .

# Install package in development mode
RUN pip install -e .

# Set timezone (for logging)
ENV TZ=America/Los_Angeles

CMD ["python", "-m", "src.workers.autonomous_content_translation_worker", "--mode", "daemon"]
```

**TM Improvement Worker (docker-compose.yml addition)**:

```yaml
  tm-improvement-worker:
    build:
      context: .
      dockerfile: Dockerfile
    container_name: hugo-tm-improvement-worker
    restart: unless-stopped
    environment:
      - TZ=America/Los_Angeles
      - EXECUTION_MODE=docker_gpu
      - DEVICE=cuda
      - LOG_LEVEL=INFO
      - WORKER_MODE=tm_improve
    volumes:
      - ./config:/app/config:ro
      - ./data:/app/data
    command: >
      python -m src.workers.tm_improvement_worker
      --mode daemon
      --check-interval-hours 168
      --log-level INFO
```

**Alternative: Using WORKER_MODE**

Instead of specifying the worker module directly, you can use the `WORKER_MODE` environment variable:

```yaml
services:
  translation-worker:
    environment:
      - WORKER_MODE=autonomous_translate
    command: python -m src.workers --mode daemon --runs-per-day 5 ...

  tm-worker:
    environment:
      - WORKER_MODE=tm_improve
    command: python -m src.workers --mode daemon --check-interval-hours 168 ...
```

This approach provides a unified entry point and makes worker type switching easier.

**Deployment Steps**:

1. **Build and Start**:
   ```bash
   docker-compose up -d
   ```

2. **Verify Running**:
   ```bash
   docker-compose ps
   # Should show: hugo-translation-worker   Up
   ```

3. **Check Logs**:
   ```bash
   docker-compose logs -f translation-worker
   ```

   Expected output:
   ```
   INFO - ================================================================================
   INFO - DAEMON MODE: Starting continuous scheduler
   INFO - Schedule: 5 runs/day
   INFO - Window: 10:00-22:00 America/Los_Angeles
   INFO - ================================================================================
   INFO - Sleeping until 2025-01-16 13:07:42 PST (9234 seconds)
   ```

4. **Test Immediate Run** (optional):
   ```bash
   docker-compose exec translation-worker python -m src.workers.autonomous_content_translation_worker \
     --mode oneshot \
     --log-level DEBUG
   ```

5. **Stop Worker**:
   ```bash
   docker-compose down
   ```

**Production Monitoring**:

Add health check to `docker-compose.yml`:
```yaml
healthcheck:
  test: ["CMD", "python", "-c", "import sys; sys.exit(0)"]
  interval: 5m
  timeout: 10s
  retries: 3
  start_period: 30s
```

---

## Configuration

### Site Profile Setup

Each site needs a profile in `config/site_profiles/{site_id}.yaml`:

```yaml
site_id: docs.aspose.net
content_roots:
  - /app/content/docs/en
  - /app/content/tutorials/en
target_langs:
  - es
  - fr
  - de
default_source_lang: en
# ... other fields ...
```

**Key Fields**:
- `content_roots`: List of directories to translate (worker processes each one)
- `target_langs`: Languages to translate into
- `default_source_lang`: Source language code

### Git Commit Configuration

Enable auto-commit in `config/global.yaml` or site profile:

```yaml
git_commit:
  enabled: true
  auto_push: true
  commit_template: "chore: translate {file_count} {site_id} files to {languages}"
  co_author_name: "Translation Worker"
  co_author_email: "worker@example.com"
  block_signals: true  # Prevent Ctrl+C during commit
```

### VRAM Configuration

Set in `config/global.yaml` under execution mode:

```yaml
execution:
  modes:
    docker_gpu:
      device: cuda
      max_gpu_memory_percent: 60
      enable_gpu: true
    windows_cuda:
      device: cuda
      max_gpu_memory_percent: 60
      enable_gpu: true
    docker_cpu:
      device: cpu
      enable_gpu: false
```

---

## Monitoring

### Verify Worker is Running

**Docker**:
```bash
docker-compose ps
# Expected: hugo-translation-worker   Up

docker-compose logs --tail=50 translation-worker
# Expected: Recent log entries with timestamps
```

**Windows Task Scheduler**:
1. Open Task Scheduler
2. Check "Last Run Time" and "Last Run Result" columns
3. View task history: Right-click task → View History

### Check Last Translation Run

**Via Git**:
```bash
git log -1 --grep="translate.*files"
```

Expected output:
```
commit a1b2c3d4e5f6...
Author: Translation Worker <worker@example.com>
Date:   Wed Jan 16 13:07:45 2025 -0800

    chore: translate 15 docs.aspose.net files to es,fr,de

    - Translated: 15 files
    - Model: m2m100_1.2b
    - TM hits: 67.3% (152/226 segments)
    ...
```

**Via Telemetry**:
```bash
sqlite3 data/benchmarks/benchmarks.db
```

Query recent scheduled runs:
```sql
SELECT
  run_id,
  site_id,
  trigger_type,
  datetime(created_at / 1000, 'unixepoch') AS run_time,
  status
FROM translation_runs
WHERE trigger_type = 'scheduled'
ORDER BY created_at DESC
LIMIT 10;
```

### View Logs

**Docker**:
```bash
# Live tail
docker-compose logs -f translation-worker

# Last hour
docker-compose logs --since 1h translation-worker

# Save to file
docker-compose logs --no-color translation-worker > worker-logs.txt
```

**Windows**:
Check Task Scheduler history or redirect output to file:

Update task arguments:
```
-m src.workers.autonomous_content_translation_worker --mode oneshot >> C:\logs\translation-worker.log 2>&1
```

---

## Troubleshooting

### Issue: Worker not starting

**Symptoms**: Container exits immediately or task fails to start

**Check**:
1. **Docker**: View logs for error message
   ```bash
   docker-compose logs translation-worker
   ```

2. **Windows**: Check Task Scheduler "Last Run Result" (error code)

**Common Causes**:
- Missing config directory: Verify `config/` path in volume mount
- Invalid Python path: Check `python` command exists
- Missing dependencies: Run `pip install -r requirements.txt`

**Solution**:
```bash
# Docker: Test command manually
docker-compose run --rm translation-worker python -m src.workers.autonomous_content_translation_worker --mode oneshot

# Windows: Test in terminal
cd C:\repos\hugo-translator
python -m src.workers.autonomous_content_translation_worker --mode oneshot
```

---

### Issue: No translations happening (all skipped)

**Symptoms**: Logs show "Skipped 10/10 files (content unchanged)"

**Cause**: Content hash tracking detected no changes since last translation

**Solution**:
1. **Verify content actually changed**: Check source files for modifications
2. **Force retranslation** (if needed): Requires code change to add `force=True`

**Workaround**: Clear content hash metadata
```bash
rm content/.translation_metadata.json
# Next run will translate all files
```

---

### Issue: CUDA out of memory

**Symptoms**: Logs show "RuntimeError: CUDA out of memory"

**Cause**: GPU memory limit too high or model too large

**Solution**:
1. **Lower GPU limit**:
   ```bash
   # Reduce from 60% to 40%
   --max-gpu-memory-percent 40
   ```

2. **Use smaller model**: Edit site profile
   ```yaml
   default_model: m2m100_418m  # Instead of 1.2b
   ```

3. **Use CPU**: Slower but avoids GPU issues
   ```bash
   --device cpu
   ```

---

### Issue: Git commit fails

**Symptoms**: Logs show "Git commit failed: ..."

**Common Causes**:
1. **Not a git repo**: Ensure content directory is a git repository
   ```bash
   cd content && git status
   ```

2. **No git credentials**: Configure git user
   ```bash
   git config --global user.name "Translation Worker"
   git config --global user.email "worker@example.com"
   ```

3. **No changes to commit**: Normal if no files were modified

**Solution**:
Check git status:
```bash
cd content
git status
# Should show modified files
```

Enable git commit debugging:
```bash
--log-level DEBUG
# Will show detailed git command output
```

---

### Issue: Worker stops scheduling (daemon mode)

**Symptoms**: No more runs after the first one

**Check Logs**:
```bash
docker-compose logs translation-worker | grep -i "error\|exception"
```

**Common Causes**:
1. **Unhandled exception**: Check for stack traces in logs
2. **Container restart**: Verify restart policy is set
   ```yaml
   restart: unless-stopped
   ```

**Solution**:
Restart worker:
```bash
docker-compose restart translation-worker
```

Check for exceptions and file a bug if reproducible.

---

### Issue: Wrong timezone

**Symptoms**: Runs happening at unexpected times

**Cause**: Timezone mismatch

**Verify Current Timezone**:
```bash
# Docker
docker-compose exec translation-worker python -c "from zoneinfo import ZoneInfo; from datetime import datetime; print(datetime.now(ZoneInfo('America/Los_Angeles')))"

# Windows
python -c "from zoneinfo import ZoneInfo; from datetime import datetime; print(datetime.now(ZoneInfo('America/Los_Angeles')))"
```

**Solution**:
Ensure `--timezone` argument matches desired timezone:
```bash
--timezone America/Los_Angeles  # Not America/New_York
```

---

## Performance Tuning

### Adjust Run Frequency

**More Frequent** (8 runs/day):
```bash
--runs-per-day 8
--window-start 08:00
--window-end 23:00
```

**Less Frequent** (3 runs/day):
```bash
--runs-per-day 3
--window-start 10:00
--window-end 22:00
```

### Limit Sites Per Run

Process only 3 sites per run (useful for large repos):
```bash
--max-sites-per-run 3
```

### Adjust GPU Memory

**High-Memory GPU** (80% usage):
```bash
--max-gpu-memory-percent 80
```

**Shared GPU** (40% usage):
```bash
--max-gpu-memory-percent 40
```

---

## Maintenance

### Update Worker Code

**Docker**:
```bash
git pull
docker-compose build
docker-compose down
docker-compose up -d
```

**Windows**:
1. Stop scheduled tasks (disable in Task Scheduler)
2. Pull latest code: `git pull`
3. Update dependencies: `pip install -r requirements.txt`
4. Re-enable tasks

### View Translation Statistics

```bash
sqlite3 data/benchmarks/benchmarks.db

# Total scheduled translations
SELECT COUNT(*) FROM translation_runs WHERE trigger_type = 'scheduled';

# Average translation time by site
SELECT
  site_id,
  COUNT(*) AS total_runs,
  AVG(duration_ms) / 1000.0 AS avg_seconds,
  SUM(items_completed) AS total_files
FROM translation_runs
WHERE trigger_type = 'scheduled'
GROUP BY site_id
ORDER BY total_runs DESC;

# Recent runs with commit hashes
SELECT
  r.site_id,
  datetime(r.created_at / 1000, 'unixepoch') AS run_time,
  r.status,
  c.commit_hash
FROM translation_runs r
LEFT JOIN git_commits c ON r.run_id = c.run_id
WHERE r.trigger_type = 'scheduled'
ORDER BY r.created_at DESC
LIMIT 20;
```

### Clean Up Old Telemetry

```bash
# Keep only last 90 days
sqlite3 data/benchmarks/benchmarks.db << EOF
DELETE FROM translation_runs
WHERE created_at < (strftime('%s', 'now') - 90 * 86400) * 1000;
DELETE FROM git_commits
WHERE created_at < (strftime('%s', 'now') - 90 * 86400) * 1000;
VACUUM;
EOF
```

---

## Alerts and Notifications

### Email on Failure (Windows)

Update task to send email on failure:
1. Task Properties → Actions → New
2. Action: Send an e-mail (requires SMTP configuration)
3. Or use PowerShell script:

```powershell
# alert_on_failure.ps1
param($TaskName, $ExitCode)

if ($ExitCode -ne 0) {
    Send-MailMessage `
        -To "ops@example.com" `
        -From "worker@example.com" `
        -Subject "Translation Worker Failed: $TaskName" `
        -Body "Task $TaskName exited with code $ExitCode" `
        -SmtpServer "smtp.example.com"
}
```

### Slack Notifications (Docker)

Add webhook to worker:

1. Set environment variable:
   ```yaml
   environment:
     - SLACK_WEBHOOK_URL=https://hooks.slack.com/services/YOUR/WEBHOOK/URL
   ```

2. Update worker to send notifications on completion

---

## Security Considerations

### Git Credentials

**SSH Keys** (recommended for auto-push):
```bash
# Generate SSH key (no passphrase for automation)
ssh-keygen -t ed25519 -f ~/.ssh/translation_worker -N ""

# Add to GitHub/GitLab
cat ~/.ssh/translation_worker.pub
# Copy to GitHub Settings → SSH Keys

# Configure git to use key
git config core.sshCommand "ssh -i ~/.ssh/translation_worker"
```

**Personal Access Token** (alternative):
```bash
# Create PAT with repo scope
# Store in environment variable
export GIT_TOKEN=ghp_xxxxxxxxxxxxx

# Configure git credential helper
git config credential.helper store
echo "https://$GIT_TOKEN@github.com" > ~/.git-credentials
```

### File Permissions

Ensure worker has write access to content directories:
```bash
# Docker
docker-compose exec translation-worker ls -la /app/content

# Windows
icacls C:\repos\content /grant Everyone:(OI)(CI)F
```

### API Keys

If using external translation services, store keys securely:
```yaml
# docker-compose.yml
environment:
  - TRANSLATION_API_KEY=${TRANSLATION_API_KEY}  # From host environment
```

---

## Backup and Recovery

### Backup Critical Data

```bash
# Backup configuration
tar -czf config-backup-$(date +%Y%m%d).tar.gz config/

# Backup telemetry database
cp data/benchmarks/benchmarks.db data/benchmarks/benchmarks-backup-$(date +%Y%m%d).db

# Backup translation memory
tar -czf tm-backup-$(date +%Y%m%d).tar.gz data/tm/
```

### Restore from Backup

```bash
# Restore config
tar -xzf config-backup-20250116.tar.gz

# Restore database
cp data/benchmarks/benchmarks-backup-20250116.db data/benchmarks/benchmarks.db

# Restore TM
tar -xzf tm-backup-20250116.tar.gz -C data/
```

---

## Scaling

### Multiple Workers (Parallel Sites)

Run multiple containers with different site filters:

```yaml
# docker-compose.yml
services:
  worker-docs:
    <<: *worker-template
    container_name: worker-docs
    command: ... --site docs.aspose.net

  worker-kb:
    <<: *worker-template
    container_name: worker-kb
    command: ... --site kb.aspose.net

  worker-products:
    <<: *worker-template
    container_name: worker-products
    command: ... --site products.aspose.net
```

**Note**: Ensure each worker uses different GPU (set `CUDA_VISIBLE_DEVICES`)

### Load Balancing

Use Kubernetes with multiple replicas:
```yaml
spec:
  replicas: 3
  strategy:
    type: RollingUpdate
```

---

## Support

For issues or questions:
1. Check this runbook first
2. Review worker logs with `--log-level DEBUG`
3. Search existing issues: https://github.com/your-org/hugo-translator/issues
4. Create new issue with:
   - Deployment method (Docker/Windows/K8s)
   - Full error logs
   - Configuration (sanitized)
   - Steps to reproduce

---

## Appendix: Full Example Configurations

### Minimal Windows Setup

```powershell
# Single run at 2 PM daily
# Task Scheduler → Create Task
Name: Hugo Translation Worker
Trigger: Daily at 2:00 PM
Action: Start program
  Program: python
  Arguments: -m src.workers.autonomous_content_translation_worker --mode oneshot --device cpu
  Start in: C:\repos\hugo-translator
```

### Production Docker Setup

See [docker-compose.yml](#docker-compose-deployment-recommended) above.

### Kubernetes Production Setup

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: translation-worker
spec:
  replicas: 1
  selector:
    matchLabels:
      app: translation-worker
  template:
    metadata:
      labels:
        app: translation-worker
    spec:
      containers:
      - name: worker
        image: your-registry/hugo-translator:latest
        args:
          - python
          - -m
          - src.workers.autonomous_content_translation_worker
          - --mode
          - daemon
          - --runs-per-day
          - "5"
          - --window-start
          - "10:00"
          - --window-end
          - "22:00"
          - --timezone
          - America/Los_Angeles
        resources:
          requests:
            memory: "8Gi"
            nvidia.com/gpu: 1
          limits:
            memory: "16Gi"
            nvidia.com/gpu: 1
        volumeMounts:
          - name: config
            mountPath: /app/config
          - name: content
            mountPath: /app/content
          - name: data
            mountPath: /app/data
      volumes:
        - name: config
          configMap:
            name: translation-config
        - name: content
          persistentVolumeClaim:
            claimName: content-pvc
        - name: data
          persistentVolumeClaim:
            claimName: data-pvc
```
