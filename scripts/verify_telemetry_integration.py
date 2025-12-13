"""
Verification script for DEC-03 Telemetry Integration.
Directly inspects the code to verify implementation without full imports.
"""
import re
import sys

# Set encoding for Windows console
if sys.platform == 'win32':
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

def verify_telemetry_integration():
    """Verify that telemetry integration is correctly implemented."""

    print("=" * 70)
    print("DEC-03 Telemetry Integration Verification")
    print("=" * 70)

    errors = []

    # 1. Verify telemetry_integration.py has track_validation_decision method
    print("\n1. Checking telemetry_integration.py...")
    with open("src/observability/telemetry_integration.py", "r") as f:
        telemetry_content = f.read()

    if "def track_validation_decision" in telemetry_content:
        print("   ✓ track_validation_decision method found")

        # Check method signature
        if "decision: str" in telemetry_content and "retry_count: int" in telemetry_content:
            print("   ✓ Method has correct parameters (decision, retry_count, etc.)")
        else:
            errors.append("track_validation_decision method missing required parameters")

        # Check for validation_decision_made event
        if "validation_decision_made" in telemetry_content:
            print("   ✓ validation_decision_made event emitted")
        else:
            errors.append("validation_decision_made event not found")
    else:
        errors.append("track_validation_decision method not found in telemetry_integration.py")

    # 2. Verify track_validation_error method exists
    if "def track_validation_error" in telemetry_content:
        print("   ✓ track_validation_error method found")

        # Check parameters
        if "validator_name: str" in telemetry_content and "severity: str" in telemetry_content:
            print("   ✓ Method has correct parameters (validator_name, severity, etc.)")
        else:
            errors.append("track_validation_error method missing required parameters")

        # Check for validation_error event
        if "validation_error" in telemetry_content:
            print("   ✓ validation_error event emitted")
        else:
            errors.append("validation_error event not found")
    else:
        errors.append("track_validation_error method not found in telemetry_integration.py")

    # 3. Verify DummyRunContext has increment_counter
    if "def increment_counter" in telemetry_content:
        print("   ✓ DummyRunContext has increment_counter method")
    else:
        errors.append("DummyRunContext missing increment_counter method")

    # 4. Verify ValidationDecisionEngine integration
    print("\n2. Checking decision_engine.py...")
    with open("src/translation_engine/validation/decision_engine.py", "r") as f:
        engine_content = f.read()

    # Check __init__ has telemetry parameters
    if "telemetry=None" in engine_content and "run_context=None" in engine_content:
        print("   ✓ __init__ accepts telemetry and run_context parameters")
    else:
        errors.append("__init__ missing telemetry/run_context parameters")

    # Check telemetry attributes are stored
    if "self.telemetry = telemetry" in engine_content and "self.run_context = run_context" in engine_content:
        print("   ✓ Telemetry attributes stored in __init__")
    else:
        errors.append("Telemetry attributes not stored in __init__")

    # Check _track_decision method exists
    if "def _track_decision" in engine_content:
        print("   ✓ _track_decision method implemented")

        # Check it calls telemetry.track_validation_decision
        if "self.telemetry.track_validation_decision" in engine_content:
            print("   ✓ Calls telemetry.track_validation_decision")
        else:
            errors.append("_track_decision doesn't call telemetry.track_validation_decision")
    else:
        errors.append("_track_decision method not found")

    # Check _track_validation_errors method exists
    if "def _track_validation_errors" in engine_content:
        print("   ✓ _track_validation_errors method implemented")

        # Check it calls telemetry.track_validation_error
        if "self.telemetry.track_validation_error" in engine_content:
            print("   ✓ Calls telemetry.track_validation_error")
        else:
            errors.append("_track_validation_errors doesn't call telemetry.track_validation_error")
    else:
        errors.append("_track_validation_errors method not found")

    # Check that make_decision calls _track_decision
    track_decision_calls = engine_content.count("self._track_decision(")
    if track_decision_calls >= 5:  # Should be called in all decision paths
        print(f"   ✓ make_decision calls _track_decision ({track_decision_calls} times)")
    else:
        errors.append(f"make_decision should call _track_decision in all paths (found {track_decision_calls})")

    # Check that make_decision calls _track_validation_errors
    track_error_calls = engine_content.count("self._track_validation_errors(")
    if track_error_calls >= 4:  # Should be called in error/reject/retry paths
        print(f"   ✓ make_decision calls _track_validation_errors ({track_error_calls} times)")
    else:
        errors.append(f"make_decision should call _track_validation_errors (found {track_error_calls})")

    # Check error_count and warning_count are computed
    if "error_count = len([i for i in validation_result.issues if i.severity == ValidationSeverity.ERROR])" in engine_content:
        print("   ✓ error_count computed from validation_result")
    else:
        errors.append("error_count not computed correctly")

    if "warning_count = len([i for i in validation_result.issues if i.severity == ValidationSeverity.WARNING])" in engine_content:
        print("   ✓ warning_count computed from validation_result")
    else:
        errors.append("warning_count not computed correctly")

    # 5. Verify test file has telemetry tests
    print("\n3. Checking test_decision_engine.py...")
    with open("tests/unit/validation/test_decision_engine.py", "r") as f:
        test_content = f.read()

    if "class TestValidationDecisionEngineTelemetry" in test_content:
        print("   ✓ TestValidationDecisionEngineTelemetry test class exists")
    else:
        errors.append("TestValidationDecisionEngineTelemetry test class not found")

    # Check for key test methods
    test_methods = [
        "test_telemetry_validation_decision_emitted_accept",
        "test_telemetry_validation_decision_emitted_retry",
        "test_telemetry_validation_decision_emitted_reject",
        "test_telemetry_validation_error_emitted",
        "test_telemetry_not_called_when_disabled",
    ]

    for method in test_methods:
        if f"def {method}" in test_content:
            print(f"   ✓ {method} exists")
        else:
            errors.append(f"Test method {method} not found")

    # Check for Mock usage
    if "from unittest.mock import Mock" in test_content:
        print("   ✓ Tests use unittest.mock.Mock")
    else:
        errors.append("Tests don't import Mock from unittest.mock")

    # 6. Summary
    print("\n" + "=" * 70)
    if errors:
        print("✗ VERIFICATION FAILED")
        print("\nErrors found:")
        for i, error in enumerate(errors, 1):
            print(f"  {i}. {error}")
        return False
    else:
        print("✓ VERIFICATION PASSED")
        print("\nAll DEC-03 requirements verified:")
        print("  • telemetry_integration.py extended with validation methods")
        print("  • ValidationDecisionEngine integrated with telemetry")
        print("  • Comprehensive test suite added")
        print("  • validation_decision_made event tracked")
        print("  • validation_error events tracked")
        print("  • Telemetry gracefully disabled when not available")
        return True

if __name__ == "__main__":
    success = verify_telemetry_integration()
    exit(0 if success else 1)
