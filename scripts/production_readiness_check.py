#!/usr/bin/env python3
"""
Production Readiness Check

Validates that the system is ready for production deployment:
- Config files are valid
- Required directories exist
- Dependencies are installed
- TM layers are functional
- Models can be loaded (optional)
"""

import argparse
import sys
import shutil
from pathlib import Path
from typing import List, Tuple

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.tm import L1Cache, L2PersistentTM, L3SemanticTM, TranslationMemory
from src.model_runtime import ModelRegistry, HardwareDetector
from src.utils.config_loader import ConfigService


class ReadinessCheck:
    """Production readiness checker."""

    def __init__(self, project_root: Path, strict: bool = False):
        self.project_root = project_root
        self.strict = strict
        self.checks = []

    def check_directories(self) -> Tuple[bool, str]:
        """Check required directories exist."""
        required_dirs = [
            self.project_root / "config",
            self.project_root / "src",
            self.project_root / "data",
        ]

        missing = [d for d in required_dirs if not d.exists()]

        if missing:
            return False, f"Missing directories: {', '.join(str(d) for d in missing)}"
        return True, "All required directories exist"

    def check_config_files(self) -> Tuple[bool, str]:
        """Check config files are valid."""
        config_dir = self.project_root / "config"

        if not config_dir.exists():
            return False, "Config directory not found"

        # Check for model registry
        registry_file = config_dir / "model_registry.yaml"
        if not registry_file.exists():
            if self.strict:
                return False, "model_registry.yaml not found"
            return True, "model_registry.yaml not found (optional)"

        # Try to load registry
        try:
            from src.model_runtime import ModelRegistry
            registry = ModelRegistry(registry_path=str(registry_file))
            models = registry.list_models()
            return True, f"Model registry valid ({len(models)} models)"
        except Exception as e:
            return False, f"Failed to load model registry: {e}"

    def check_dependencies(self) -> Tuple[bool, str]:
        """Check critical dependencies are installed."""
        required_packages = [
            "yaml",
            "frontmatter",
            "markdown_it",
            "lmdb",
        ]

        missing = []
        for package in required_packages:
            try:
                __import__(package)
            except ImportError:
                missing.append(package)

        if missing:
            return False, f"Missing packages: {', '.join(missing)}"
        return True, "All required packages installed"

    def check_tm_functionality(self) -> Tuple[bool, str]:
        """Check TM layers are functional."""
        try:
            # Create temporary TM
            tm_dir = self.project_root / "data" / "tm" / "readiness_check"
            tm_dir.mkdir(parents=True, exist_ok=True)

            l1 = L1Cache(max_size=100)
            l2 = L2PersistentTM(db_path=str(tm_dir / "test.lmdb"), max_size_mb=10)

            # Test store and retrieve
            l1.put('test', 'en', 'es', 'hello', 'hola')
            result = l1.get('test', 'en', 'es', 'hello')

            if not result or result.translation != 'hola':
                return False, "L1 cache not working correctly"

            l2.store('test', 'en', 'es', 'world', 'mundo')
            result = l2.lookup('test', 'en', 'es', 'world')

            if not result or result.translation != 'mundo':
                l2.close()
                return False, "L2 persistent TM not working correctly"

            l2.close()
            return True, "TM layers functional (L1/L2 tested)"

        except Exception as e:
            return False, f"TM functionality check failed: {e}"

    def check_disk_space(self) -> Tuple[bool, str]:
        """Check available disk space."""
        try:
            usage = shutil.disk_usage(self.project_root)
            free_gb = usage.free / (1024**3)

            if free_gb < 1.0:
                return False, f"Low disk space: {free_gb:.1f}GB free (need >1GB)"
            elif free_gb < 10.0:
                return True, f"Disk space OK: {free_gb:.1f}GB free (warning: <10GB)"
            return True, f"Disk space OK: {free_gb:.1f}GB free"
        except Exception as e:
            return False, f"Failed to check disk space: {e}"

    def check_memory_available(self) -> Tuple[bool, str]:
        """Check available memory."""
        try:
            import psutil
            mem = psutil.virtual_memory()
            available_gb = mem.available / (1024**3)

            if available_gb < 0.5:
                return False, f"Low memory: {available_gb:.1f}GB available (need >0.5GB)"
            elif available_gb < 2.0:
                return True, f"Memory OK: {available_gb:.1f}GB available (warning: <2GB)"
            return True, f"Memory OK: {available_gb:.1f}GB available"
        except ImportError:
            return True, "Memory check skipped (psutil not installed)"
        except Exception as e:
            return False, f"Failed to check memory: {e}"

    def check_hardware(self) -> Tuple[bool, str]:
        """Check hardware configuration."""
        try:
            detector = HardwareDetector()
            hw_info = detector.detect()

            details = [
                f"Device: {hw_info.recommended_device}",
                f"CPUs: {hw_info.cpu_count}",
                f"RAM: {hw_info.total_ram_gb:.1f}GB",
            ]

            if hw_info.gpu_available:
                details.append(f"GPU: {hw_info.gpu_name}")

            return True, ", ".join(details)
        except Exception as e:
            return False, f"Hardware detection failed: {e}"

    def run_all_checks(self) -> List[dict]:
        """Run all readiness checks."""
        checks = [
            ("Directories", self.check_directories),
            ("Config Files", self.check_config_files),
            ("Dependencies", self.check_dependencies),
            ("TM Functionality", self.check_tm_functionality),
            ("Disk Space", self.check_disk_space),
            ("Memory", self.check_memory_available),
            ("Hardware", self.check_hardware),
        ]

        results = []
        for name, check_func in checks:
            try:
                passed, message = check_func()
                results.append({
                    "name": name,
                    "passed": passed,
                    "message": message,
                })
            except Exception as e:
                results.append({
                    "name": name,
                    "passed": False,
                    "message": f"Check failed with exception: {e}",
                })

        return results


def main():
    """Main execution."""
    parser = argparse.ArgumentParser(description="Production readiness check")
    parser.add_argument("--strict", action="store_true", help="Strict mode (all checks must pass)")
    parser.add_argument("--project-root", type=Path, default=Path.cwd(), help="Project root directory")

    args = parser.parse_args()

    print("=" * 60)
    print("PRODUCTION READINESS CHECK")
    print("=" * 60)
    print(f"Project root: {args.project_root}")
    print(f"Strict mode: {args.strict}")
    print()

    checker = ReadinessCheck(args.project_root, strict=args.strict)
    results = checker.run_all_checks()

    # Print results
    passed_count = sum(1 for r in results if r["passed"])
    total_count = len(results)

    for result in results:
        status = "✓" if result["passed"] else "✗"
        print(f"{status} {result['name']}: {result['message']}")

    print()
    print("=" * 60)
    print(f"RESULTS: {passed_count}/{total_count} checks passed")
    print("=" * 60)

    # Generate report
    reports_dir = args.project_root / "reports"
    reports_dir.mkdir(parents=True, exist_ok=True)
    report_file = reports_dir / "production_readiness.md"

    with open(report_file, 'w') as f:
        f.write("# Production Readiness Report\n\n")
        f.write(f"**Status:** {'READY' if passed_count == total_count else 'NOT READY'}\n")
        f.write(f"**Checks Passed:** {passed_count}/{total_count}\n\n")

        f.write("## Check Results\n\n")
        for result in results:
            status = "✓ PASS" if result["passed"] else "✗ FAIL"
            f.write(f"### {result['name']}: {status}\n\n")
            f.write(f"{result['message']}\n\n")

    print(f"\nReport saved to: {report_file}")

    # Exit code
    if passed_count == total_count:
        print("\n✓ System is READY for production")
        return 0
    else:
        print(f"\n✗ System is NOT READY: {total_count - passed_count} checks failed")
        return 1 if args.strict else 0


if __name__ == "__main__":
    sys.exit(main())
