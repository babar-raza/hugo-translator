#!/usr/bin/env python3
"""Verify all downloaded models are valid and loadable."""
import argparse
import json
import sys
from pathlib import Path
import importlib.util


def load_module_directly(module_name, module_path):
    """Load a module directly from file path."""
    spec = importlib.util.spec_from_file_location(module_name, module_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def main():
    parser = argparse.ArgumentParser(description="Verify model integrity")
    parser.add_argument("--model", type=str, help="Verify specific model by ID")
    parser.add_argument("--backend", type=str, help="Filter by backend (huggingface, ctranslate2)")
    parser.add_argument("--json", action="store_true", help="Output JSON report")
    parser.add_argument("--models-dir", type=str, default="models", help="Models directory")
    args = parser.parse_args()

    # Load verifier module directly
    project_root = Path(__file__).parent.parent
    verifier_path = project_root / "src" / "model_runtime" / "verifier.py"
    verifier_module = load_module_directly("verifier", verifier_path)
    ModelVerifier = verifier_module.ModelVerifier

    verifier = ModelVerifier(args.models_dir)

    # Verify specific model or all models
    if args.model:
        # Find model in any backend
        models_dir = Path(args.models_dir)
        model_path = None

        for backend_dir in models_dir.iterdir():
            if backend_dir.is_dir():
                candidate = backend_dir / args.model
                if candidate.exists():
                    model_path = candidate
                    break

        if not model_path:
            print(f"✗ Model not found: {args.model}")
            return 1

        results = [verifier.verify(model_path, args.model)]
    else:
        results = verifier.verify_all(backend=args.backend)

    if not results:
        print("No models found to verify")
        return 0

    # Output results
    if args.json:
        report = {
            "total": len(results),
            "passed": sum(1 for r in results if r.passed),
            "failed": sum(1 for r in results if not r.passed),
            "results": [r.to_dict() for r in results]
        }
        print(json.dumps(report, indent=2))
    else:
        # Text output
        print("Model Verification Report")
        print("=" * 60)

        passed_count = 0
        failed_count = 0

        for result in results:
            status = "✓ PASS" if result.passed else "✗ FAIL"
            print(f"\n{status}: {result.model_id}")

            if result.passed:
                passed_count += 1
                print(f"  Checks passed: {len(result.checks_passed)}/{len(result.checks_performed)}")
            else:
                failed_count += 1
                print(f"  Failed checks: {', '.join(result.checks_failed)}")
                if result.error_message:
                    print(f"  Error: {result.error_message}")

        print()
        print("=" * 60)
        print(f"Total: {len(results)} | Passed: {passed_count} | Failed: {failed_count}")

        if failed_count > 0:
            print()
            print("Failed models:")
            for result in results:
                if not result.passed:
                    print(f"  - {result.model_id}: {result.error_message or 'Unknown error'}")

    # Exit code
    return 0 if all(r.passed for r in results) else 1


if __name__ == "__main__":
    sys.exit(main())
