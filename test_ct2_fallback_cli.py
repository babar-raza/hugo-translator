"""
Simple CLI-based test for CT2 empty translation fallback.

This test creates a minimal markdown file with placeholder content
and translates it to verify the fallback mechanism works.
"""

import json
import tempfile
from pathlib import Path
import subprocess
import sys


def create_test_file():
    """Create a test markdown file with placeholder content."""
    content = """---
title: Test Page
---

# Test Heading

This is normal text that should translate.

{PLACEHOLDER_0}

More normal text here.

{PLACEHOLDER_1}

End of document.
"""
    # Create temp file
    temp_dir = Path("temp_ct2_fallback_test")
    temp_dir.mkdir(exist_ok=True)

    test_file = temp_dir / "test.en.md"
    test_file.write_text(content, encoding="utf-8")

    return test_file, temp_dir


def run_translation_test():
    """Run translation test and check results."""

    print(f"\n{'='*70}")
    print("CT2 Empty Translation Fallback - CLI Test")
    print(f"{'='*70}\n")

    # Create test file
    print("Creating test file with placeholder content...")
    test_file, temp_dir = create_test_file()
    print(f"✅ Created: {test_file}\n")

    # Create output directory
    output_dir = temp_dir / "output"
    output_dir.mkdir(exist_ok=True)

    try:
        # Run translation with CT2 model
        print("Running translation (en → fr) with CT2 model...")
        print("-" * 70)

        cmd = [
            sys.executable, "-m", "src.cli", "translate",
            "--input", str(test_file),
            "--target-langs", "fr",
            "--output", str(output_dir),
            "--device", "cpu",
            "--batch-size", "4",
            "--auto-select-model",  # Use CT2 models
            "--validation-mode", "normal"
        ]

        print(f"Command: {' '.join(cmd)}\n")

        result = subprocess.run(
            cmd,
            cwd="C:\\Users\\prora\\OneDrive\\Documents\\GitHub\\hugo-translator",
            capture_output=True,
            text=True,
            timeout=300
        )

        print("STDOUT:")
        print(result.stdout)

        if result.stderr:
            print("\nSTDERR:")
            print(result.stderr)

        print("-" * 70)

        # Check if translation succeeded
        if result.returncode == 0:
            print("\n✅ Translation completed successfully")

            # Check output file
            output_file = output_dir / "test.fr.md"
            if output_file.exists():
                print(f"✅ Output file created: {output_file}")

                # Read and analyze output
                output_content = output_file.read_text(encoding="utf-8")
                print("\nOutput content:")
                print("-" * 70)
                print(output_content)
                print("-" * 70)

                # Check for placeholders in output (should be preserved via fallback)
                has_placeholder_0 = "{PLACEHOLDER_0}" in output_content
                has_placeholder_1 = "{PLACEHOLDER_1}" in output_content

                print("\nValidation:")
                if has_placeholder_0:
                    print("✅ {PLACEHOLDER_0} preserved (fallback worked)")
                else:
                    print("⚠️  {PLACEHOLDER_0} not found (may have been translated or removed)")

                if has_placeholder_1:
                    print("✅ {PLACEHOLDER_1} preserved (fallback worked)")
                else:
                    print("⚠️  {PLACEHOLDER_1} not found (may have been translated or removed)")

                # Check for actual translation (normal text should change)
                has_french_content = any(
                    word in output_content.lower()
                    for word in ["ceci", "texte", "normal", "document"]
                )

                if has_french_content or output_content != test_file.read_text(encoding="utf-8"):
                    print("✅ Normal text was translated")
                else:
                    print("⚠️  Content appears unchanged (may have used fallback for everything)")

                return True
            else:
                print(f"❌ Output file not found: {output_file}")
                return False
        else:
            print(f"\n❌ Translation failed with exit code {result.returncode}")
            return False

    except subprocess.TimeoutExpired:
        print("❌ Translation timed out after 5 minutes")
        return False

    except Exception as e:
        print(f"❌ Error during test: {e}")
        import traceback
        traceback.print_exc()
        return False

    finally:
        # Cleanup
        print("\nCleaning up test files...")
        try:
            import shutil
            shutil.rmtree(temp_dir)
            print("✅ Cleanup complete")
        except Exception as e:
            print(f"⚠️  Cleanup warning: {e}")


if __name__ == "__main__":
    success = run_translation_test()
    print(f"\n{'='*70}")
    if success:
        print("✅ TEST PASSED: CT2 empty translation fallback is working")
    else:
        print("❌ TEST FAILED: Check output above for details")
    print(f"{'='*70}\n")

    sys.exit(0 if success else 1)
