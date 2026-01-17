# Data and State

## Overview

The Hugo Translation System manages various types of data and state throughout the translation process. This document describes the data structures, storage mechanisms, and state management approaches used in the system.

## Data Types

### Translation Memory (TM)

The system uses a three-tiered translation memory architecture:

1. **L1 Cache**: In-memory cache for fast access to recent translations
   - **Storage**: In-memory dictionary
   - **Lifetime**: Process lifetime
   - **Evidence**: [`src/tm/l1_cache.py`](src/tm/l1_cache.py)

2. **L2 Persistent**: Persistent storage for translations
   - **Storage**: LMDB database
   - **Location**: `data/tm/l2_lmdb/`
   - **Evidence**: [`src/tm/l2_persistent.py`](src/tm/l2_persistent.py)

3. **L3 Semantic**: Semantic search for similar translations
   - **Storage**: FAISS index
   - **Location**: `data/tm/l3_faiss/`
   - **Evidence**: [`src/tm/l3_semantic.py`](src/tm/l3_semantic.py)

### Translation Metadata

- **File**: `.translation_metadata.json`
- **Location**: Output directory
- **Contents**:
  - Content hashes
  - Translation timestamps
  - Model information
  - Validation results
- **Evidence**: [`src/translation_engine/engine.py`](src/translation_engine/engine.py)

### Progress Tracking

- **Directory**: `.translation_progress/`
- **Files**: `progress_*.json`
- **Contents**:
  - Files processed
  - Translations completed
  - Errors encountered
  - Timestamps
- **Evidence**: [`src/translation_engine/progress.py`](src/translation_engine/progress.py)

### Benchmarking Data

- **Directory**: `data/benchmarks/`
- **Files**:
  - `benchmarks.db`: Benchmarking database
  - `production.db`: Production metrics database
- **Evidence**: [`src/benchmarking/storage.py`](src/benchmarking/storage.py)

### Logs

- **Directory**: `data/logs/`
- **Files**:
  - `hugo-translator.ndjson`: Structured logs
  - `hugo-translator.log`: Text logs
- **Evidence**: [`src/observability/logger.py`](src/observability/logger.py)

## State Management

### File Locks

- **Purpose**: Prevent concurrent translation of the same site
- **Implementation**: File-based locks
- **Location**: `.translation_progress/locks/`
- **Evidence**: [`src/utils/file_lock.py`](src/utils/file_lock.py)

### Progress Tracking

- **Purpose**: Track translation progress for crash recovery
- **Implementation**: JSON files with atomic writes
- **Location**: `.translation_progress/`
- **Evidence**: [`src/translation_engine/progress.py`](src/translation_engine/progress.py)

### Content Hash Tracking

- **Purpose**: Detect content changes and avoid unnecessary retranslation
- **Implementation**: SHA-256 hashes of file content
- **Location**: `.translation_metadata.json`
- **Evidence**: [`src/translation_engine/engine.py`](src/translation_engine/engine.py)

## Data Flow

### Translation Process

1. **Input**: Source markdown files
2. **Processing**:
   - Content extraction
   - Translation memory lookup
   - Machine translation
   - Validation
   - Terminology preservation
3. **Output**: Translated markdown files
4. **Metadata**: Translation metadata and progress tracking

### Benchmarking Process

1. **Input**: Translation results and metrics
2. **Processing**:
   - Metrics collection
   - Performance analysis
   - Quality assessment
3. **Output**: Benchmarking reports and databases

## Data Retention

### Translation Memory
- **L1 Cache**: Cleared on process exit
- **L2 Persistent**: Retained indefinitely
- **L3 Semantic**: Retained indefinitely

### Logs
- **Retention**: Configurable via `max_file_size_mb` and `backup_count`
- **Default**: 100MB per file, 10 backups

### Benchmarking Data
- **Retention**: Configurable via database settings
- **Default**: 30 days for production metrics

## Data Security

### Sensitive Data
- **Redis Password**: Stored in environment variables
- **Grafana Password**: Stored in environment variables
- **API Keys**: Not currently used in the system

### Data Protection
- **File Permissions**: Configurable via `chmod`
- **Encryption**: Not currently implemented
- **Backup**: Recommended to backup `data/` directory regularly

## Best Practices

1. **Regular Backups**: Backup the `data/` directory regularly
2. **Monitor Disk Space**: Monitor disk space usage for LMDB and FAISS databases
3. **Cleanup Old Data**: Regularly cleanup old logs and benchmarking data
4. **Secure Configuration**: Use environment variables for sensitive configuration
5. **Atomic Writes**: Use atomic writes for critical files to prevent corruption
