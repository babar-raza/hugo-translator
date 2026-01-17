"""
Translation Worker Module Entry Point.

Enables execution via: python -m src.workers

This module supports multiple modes:
- MCP mode (default): Runs as MCP server exposing translation tools
- Processor mode: Polls Redis queue and processes translation jobs
- Autonomous Translate mode: Scheduled content translation worker
- TM Improve mode: Translation memory improvement worker

Mode selection via WORKER_MODE environment variable.
"""

import asyncio
import os
import sys


def run_mcp_mode():
    """Run worker in MCP server mode."""
    from src.workers.translation_worker import main

    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nMCP server interrupted by user", file=sys.stderr)
        sys.exit(130)  # Standard exit code for SIGINT
    except Exception as e:
        print(f"MCP server failed: {e}", file=sys.stderr)
        sys.exit(1)


def run_processor_mode():
    """Run worker in job processor mode."""
    from src.workers.job_processor import main

    try:
        exit_code = main()
        sys.exit(exit_code)
    except KeyboardInterrupt:
        print("\nJob processor interrupted by user", file=sys.stderr)
        sys.exit(130)  # Standard exit code for SIGINT
    except Exception as e:
        print(f"Job processor failed: {e}", file=sys.stderr)
        sys.exit(1)


def run_autonomous_translate_mode():
    """Run autonomous content translation worker."""
    from src.workers.autonomous_content_translation_worker import main

    try:
        main()
    except KeyboardInterrupt:
        print("\nAutonomous translation worker interrupted by user", file=sys.stderr)
        sys.exit(130)  # Standard exit code for SIGINT
    except Exception as e:
        print(f"Autonomous translation worker failed: {e}", file=sys.stderr)
        sys.exit(1)


def run_tm_improve_mode():
    """Run TM improvement worker."""
    from src.workers.tm_improvement_worker import main

    try:
        main()
    except KeyboardInterrupt:
        print("\nTM improvement worker interrupted by user", file=sys.stderr)
        sys.exit(130)  # Standard exit code for SIGINT
    except Exception as e:
        print(f"TM improvement worker failed: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    # Get worker mode from environment
    worker_mode = os.getenv("WORKER_MODE", "mcp").lower()

    if worker_mode == "processor":
        print(f"Starting worker in PROCESSOR mode", file=sys.stderr)
        run_processor_mode()
    elif worker_mode == "autonomous_translate":
        print(f"Starting worker in AUTONOMOUS TRANSLATE mode", file=sys.stderr)
        run_autonomous_translate_mode()
    elif worker_mode == "tm_improve":
        print(f"Starting worker in TM IMPROVE mode", file=sys.stderr)
        run_tm_improve_mode()
    else:
        print(f"Starting worker in MCP mode", file=sys.stderr)
        run_mcp_mode()
