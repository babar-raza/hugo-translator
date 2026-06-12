#!/usr/bin/env python
# ARCHIVED: 2026-06-11. Replacement: python -m src.cli <args>
"""Wrapper script to run translation with proper sys.path"""

import sys

from src.cli import main

if __name__ == "__main__":
    sys.exit(main())
