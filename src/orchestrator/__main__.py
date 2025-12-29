"""
Translation Orchestrator Module Entry Point.

Enables execution via: python -m src.orchestrator

The orchestrator coordinates translation operations by managing:
- Job queue for translation jobs
- File system watcher for auto-mode translations
- Periodic content sweep scheduler
"""

import argparse
import logging
import os
import signal
import sys
import time
from pathlib import Path

from src.orchestrator.orchestrator import TranslationOrchestrator
from src.observability.graceful_shutdown import (
    setup_graceful_shutdown,
    register_shutdown_handler,
)
from src.utils.config_loader import ConfigService

logger = logging.getLogger(__name__)


def parse_args() -> argparse.Namespace:
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(
        description="Translation Orchestrator - Coordinates translation operations",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Start with default settings
  python -m src.orchestrator

  # Auto mode with file watching and sweeps
  python -m src.orchestrator --mode auto

  # Manual mode (no automatic operations)
  python -m src.orchestrator --mode manual

  # Custom configuration path
  python -m src.orchestrator --config /app/config

Environment Variables:
  CONFIG_PATH              Configuration directory path (default: ./config)
  MODE                     Orchestrator mode: auto|manual (default: auto)
  SWEEP_INTERVAL_HOURS     Hours between sweeps (default: 24)
  LOG_LEVEL                Logging level (default: INFO)
        """,
    )

    parser.add_argument(
        "--config",
        type=str,
        default=os.getenv("CONFIG_PATH", "./config"),
        help="Configuration directory path. Default: ./config (or CONFIG_PATH env var)",
    )

    parser.add_argument(
        "--mode",
        choices=["auto", "manual"],
        default=os.getenv("MODE", "auto"),
        help="Orchestrator mode. auto: file watching + sweeps, manual: on-demand only. Default: auto",
    )

    parser.add_argument(
        "--sweep-interval",
        type=int,
        default=int(os.getenv("SWEEP_INTERVAL_HOURS", "24")),
        help="Hours between automatic content sweeps. Default: 24 (or SWEEP_INTERVAL_HOURS env var)",
    )

    parser.add_argument(
        "--log-level",
        choices=["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"],
        default=os.getenv("LOG_LEVEL", "INFO"),
        help="Logging level. Default: INFO (or LOG_LEVEL env var)",
    )

    return parser.parse_args()


def configure_logging(log_level: str) -> None:
    """Configure logging system."""
    logging.basicConfig(
        level=getattr(logging, log_level),
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        stream=sys.stdout,
    )


def main() -> int:
    """Main entry point for orchestrator."""
    # Parse arguments
    args = parse_args()

    # Configure logging
    configure_logging(args.log_level)

    logger.info("=" * 70)
    logger.info("Translation Orchestrator Starting")
    logger.info("=" * 70)
    logger.info(f"Mode: {args.mode}")
    logger.info(f"Config path: {args.config}")
    logger.info(f"Sweep interval: {args.sweep_interval} hours")
    logger.info(f"Log level: {args.log_level}")

    # Verify configuration directory exists
    config_path = Path(args.config)
    if not config_path.exists():
        logger.error(f"Configuration directory not found: {config_path}")
        return 1

    # Initialize configuration service
    try:
        config_service = ConfigService(
            config_root=str(config_path)
        )
        logger.info("Configuration service initialized")
    except Exception as e:
        logger.error(f"Failed to initialize configuration: {e}")
        return 1

    # Initialize job queue based on backend configuration
    queue_backend = os.getenv("QUEUE_BACKEND", "memory").lower()
    try:
        if queue_backend == "redis":
            from src.orchestrator.redis_backend import RedisJobQueue

            redis_host = os.getenv("REDIS_HOST", "localhost")
            redis_port = int(os.getenv("REDIS_PORT", "6379"))
            redis_db = int(os.getenv("REDIS_DB", "0"))
            redis_password = os.getenv("REDIS_PASSWORD")

            queue = RedisJobQueue(
                host=redis_host,
                port=redis_port,
                db=redis_db,
                password=redis_password if redis_password else None,
            )
            logger.info(f"Using Redis queue backend at {redis_host}:{redis_port}")
        else:
            from src.orchestrator.queue import JobQueue
            queue = JobQueue()
            logger.info("Using in-memory queue backend")
    except Exception as e:
        logger.error(f"Failed to initialize queue backend: {e}")
        return 1

    # Create orchestrator
    enable_components = args.mode == "auto"
    try:
        orchestrator = TranslationOrchestrator(
            config_service=config_service,
            enable_file_watcher=enable_components,
            enable_sweep_scheduler=enable_components,
            sweep_interval_minutes=args.sweep_interval * 60,
            queue=queue,
        )
        logger.info("Orchestrator created")
    except Exception as e:
        logger.error(f"Failed to create orchestrator: {e}")
        return 1

    # Setup graceful shutdown
    def shutdown_handler() -> None:
        """Handle graceful shutdown."""
        logger.info("Shutting down orchestrator...")
        try:
            orchestrator.stop()
            logger.info("Orchestrator stopped successfully")
        except Exception as e:
            logger.error(f"Error during orchestrator shutdown: {e}")

        # Close queue connection (Redis)
        try:
            if hasattr(queue, 'close'):
                queue.close()
                logger.info("Queue connection closed")
        except Exception as e:
            logger.error(f"Error closing queue connection: {e}")

    setup_graceful_shutdown()
    register_shutdown_handler(shutdown_handler)
    logger.info("Graceful shutdown handlers registered")

    # Start orchestrator
    try:
        orchestrator.start()
    except Exception as e:
        logger.error(f"Failed to start orchestrator: {e}")
        return 1

    logger.info("=" * 70)
    logger.info("Orchestrator Running")
    logger.info("Press Ctrl+C to stop")
    logger.info("=" * 70)

    # Run until interrupted
    try:
        while orchestrator.is_running():
            time.sleep(1)
    except KeyboardInterrupt:
        logger.info("Received keyboard interrupt")
    except Exception as e:
        logger.error(f"Unexpected error in orchestrator loop: {e}")
        return 1

    # Orchestrator shutdown handled by graceful_shutdown system
    logger.info("Orchestrator exiting")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("\nOrchestrator interrupted by user", file=sys.stderr)
        sys.exit(130)  # Standard exit code for SIGINT
    except Exception as e:
        print(f"Orchestrator failed: {e}", file=sys.stderr)
        sys.exit(1)
