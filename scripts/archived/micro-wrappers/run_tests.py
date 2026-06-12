# ARCHIVED: 2026-06-11. Has hardcoded site-packages path. Replacement: python -m pytest tests/ -v
"""Simple test runner to run decision engine tests."""

import sys

sys.path.insert(0, r"C:\Users\prora\AppData\Roaming\Python\Python313\site-packages")

import pytest

if __name__ == "__main__":
    sys.exit(pytest.main(["tests/unit/validation/test_decision_engine.py", "-v", "--tb=short"]))
