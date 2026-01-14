"""
Shared Engines - Unified interfaces for autonomous workers.

This package provides 8 shared engines that enable both manual CLI execution
and autonomous worker orchestration with consistent APIs:

1. TranslationEngine - Unified translation with pluggable backends (MT, LLM)
2. TelemetryEngine - Event logging and metrics collection
3. JobEngine - Job queue abstraction (memory, Redis)
4. ProfileEngine - Site profile and configuration resolution
5. LoggingEngine - Structured NDJSON logging
6. CommitEngine - Automated git commit workflow
7. LimitingEngine - Resource constraint enforcement (CPU, RAM, GPU)
8. HealingEngine - Retry and recovery logic

Usage:
    from shared_engines.composition_root import CompositionRoot

    # Create all engines from config
    engines = CompositionRoot.create_from_config("config/global.yaml")

    # Use engines
    result = engines.translation.translate_file(...)
    engines.telemetry.emit("translation_complete", {...})
    engines.commit.commit_if_enabled(...)

Architecture:
    - Composition Root pattern for dependency injection
    - Backend abstraction for swappable implementations
    - Configuration-driven instantiation
    - Graceful fallbacks for optional dependencies
"""

# Version will be populated as engines are implemented
__all__ = [
    # Core engines (populated in later tasks)
]
