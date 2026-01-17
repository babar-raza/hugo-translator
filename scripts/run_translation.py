#!/usr/bin/env python
"""Wrapper script to run translation with proper sys.path"""
import sys

from src.cli import main

if __name__ == "__main__":
    sys.exit(main())
