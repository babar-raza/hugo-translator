"""Package entry point for `python -m src`."""

import sys

from .cli import main

if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "translate":
        del sys.argv[1]
    sys.exit(main())

