"""
Model Runtime CLI Entry Point.

Allows running: python -m src.model_runtime.model_cli <command>
"""
from .model_cli import main

if __name__ == "__main__":
    raise SystemExit(main())
