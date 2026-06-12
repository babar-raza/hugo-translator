# Windows Worker Deployment Script (Phase 2: Dual-Run Execution Layer)
# Deploys Hugo Translator worker in windows_cuda mode (native Windows + CUDA GPU)
#
# Usage:
#   .\scripts\deploy_windows_worker.ps1 -WorkerID "windows-gpu-1" -RedisHost "localhost"
#
# Requirements:
#   - Python 3.8+ with torch installed
#   - CUDA-capable GPU (optional, will auto-detect)
#   - Redis server running
#   - NSSM (optional, for Windows service installation)

param(
    [Parameter(Mandatory=$false)]
    [string]$WorkerID = "windows-gpu-1",

    [Parameter(Mandatory=$false)]
    [string]$RedisHost = "localhost",

    [Parameter(Mandatory=$false)]
    [int]$RedisPort = 6379,

    [Parameter(Mandatory=$false)]
    [string]$ConfigPath = ".\config",

    [Parameter(Mandatory=$false)]
    [string]$TmPath = ".\data\tm",

    [Parameter(Mandatory=$false)]
    [string]$LogLevel = "INFO",

    [Parameter(Mandatory=$false)]
    [switch]$InstallService = $false,

    [Parameter(Mandatory=$false)]
    [string]$ServiceName = "HugoTranslatorWorker"
)

Write-Host "=" * 70
Write-Host "Hugo Translator - Windows Worker Deployment (Phase 2: Dual-Run)"
Write-Host "=" * 70
Write-Host ""

# Set execution mode to windows_cuda
$env:EXECUTION_MODE = "windows_cuda"
Write-Host "[1/6] Execution Mode: $env:EXECUTION_MODE"

# Set worker configuration
$env:WORKER_ID = $WorkerID
$env:REDIS_HOST = $RedisHost
$env:REDIS_PORT = $RedisPort
$env:CONFIG_PATH = $ConfigPath
$env:TM_DATA_PATH = $TmPath
$env:LOG_LEVEL = $LogLevel
$env:USE_SHARED_ENGINES = "true"
$env:PYTHONUNBUFFERED = "1"

Write-Host "[2/6] Worker Configuration:"
Write-Host "  - Worker ID: $WorkerID"
Write-Host "  - Redis: ${RedisHost}:${RedisPort}"
Write-Host "  - Config Path: $ConfigPath"
Write-Host "  - TM Path: $TmPath"
Write-Host "  - Log Level: $LogLevel"
Write-Host ""

# Check Python installation
Write-Host "[3/6] Checking Python installation..."
try {
    $pythonVersion = & python --version 2>&1
    Write-Host "  - Python found: $pythonVersion"
} catch {
    Write-Host "  - ERROR: Python not found. Please install Python 3.8+ and add to PATH."
    exit 1
}

# Check CUDA availability
Write-Host "[4/6] Checking CUDA availability..."
try {
    $cudaCheck = & python -c "import torch; print(f'CUDA available: {torch.cuda.is_available()}, Devices: {torch.cuda.device_count()}')" 2>&1
    Write-Host "  - $cudaCheck"
} catch {
    Write-Host "  - WARNING: Could not check CUDA availability. Worker will run in CPU mode."
}

# Check Redis connectivity
Write-Host "[5/6] Checking Redis connectivity..."
try {
    $redisCheck = & python -c "import redis; r = redis.Redis(host='$RedisHost', port=$RedisPort, socket_connect_timeout=2); r.ping(); print('Redis: OK')" 2>&1
    Write-Host "  - $redisCheck"
} catch {
    Write-Host "  - WARNING: Could not connect to Redis at ${RedisHost}:${RedisPort}"
    Write-Host "  - Make sure Redis is running before starting the worker"
}

Write-Host ""

# Install as Windows service or run directly
if ($InstallService) {
    Write-Host "[6/6] Installing Windows service with NSSM..."

    # Check if NSSM is available
    $nssmPath = Get-Command nssm -ErrorAction SilentlyContinue
    if (-not $nssmPath) {
        Write-Host "  - ERROR: NSSM not found. Please install NSSM from https://nssm.cc/"
        Write-Host "  - Or run without -InstallService flag to start worker directly"
        exit 1
    }

    # Get Python executable path
    $pythonExe = (Get-Command python).Source

    # Get script directory
    $scriptDir = Split-Path -Parent $PSCommandPath
    $projectRoot = Split-Path -Parent $scriptDir

    # Install service
    Write-Host "  - Installing service '$ServiceName'..."
    & nssm install $ServiceName $pythonExe "-m" "src.workers"

    # Set service parameters
    & nssm set $ServiceName AppDirectory $projectRoot
    & nssm set $ServiceName AppEnvironmentExtra `
        "EXECUTION_MODE=$env:EXECUTION_MODE" `
        "WORKER_ID=$WorkerID" `
        "REDIS_HOST=$RedisHost" `
        "REDIS_PORT=$RedisPort" `
        "CONFIG_PATH=$ConfigPath" `
        "TM_DATA_PATH=$TmPath" `
        "LOG_LEVEL=$LogLevel" `
        "USE_SHARED_ENGINES=true" `
        "PYTHONUNBUFFERED=1"

    # Set service description
    & nssm set $ServiceName Description "Hugo Translator Worker (windows_cuda mode)"

    # Set service to auto-start
    & nssm set $ServiceName Start SERVICE_AUTO_START

    Write-Host "  - Service installed successfully!"
    Write-Host "  - Start service: nssm start $ServiceName"
    Write-Host "  - Stop service: nssm stop $ServiceName"
    Write-Host "  - Remove service: nssm remove $ServiceName confirm"
    Write-Host ""

} else {
    Write-Host "[6/6] Starting worker..."
    Write-Host "  - Press Ctrl+C to stop the worker"
    Write-Host ""
    Write-Host "=" * 70
    Write-Host ""

    # Run worker directly
    & python -m src.workers
}

Write-Host ""
Write-Host "Deployment complete."
