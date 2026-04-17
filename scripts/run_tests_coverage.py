"""Test runner with specific coverage for decision engine."""
import sys

sys.path.insert(0, r'C:\Users\prora\AppData\Roaming\Python\Python313\site-packages')

import pytest

if __name__ == "__main__":
    sys.exit(pytest.main([
        "tests/unit/validation/test_decision_engine.py",
        "-v",
        "--cov=src/translation_engine/validation/decision_engine",
        "--cov-report=term-missing",
        "--cov-report=html",
        "--tb=short"
    ]))
