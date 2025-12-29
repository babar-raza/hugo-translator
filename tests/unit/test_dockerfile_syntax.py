"""Test Dockerfile health check syntax."""
import re
from pathlib import Path


def test_gpu_dockerfile_health_check_syntax():
    """Verify GPU Dockerfile health check has valid Python syntax."""
    dockerfile = Path("Dockerfile.gpu").read_text()

    # Extract health check command
    match = re.search(r'CMD python -c "([^"]+)"', dockerfile)
    assert match, "Health check command not found"

    cmd = match.group(1)

    # Verify imports are present
    assert "import sys" in cmd, "Missing 'import sys'"
    assert "import torch" in cmd, "Missing 'import torch'"

    # Verify command structure
    assert "sys.exit(0)" in cmd, "Missing 'sys.exit(0)'"
    assert "torch.cuda.is_available()" in cmd, "Missing CUDA check"


if __name__ == "__main__":
    test_gpu_dockerfile_health_check_syntax()
    print("OK: GPU Dockerfile health check syntax is valid")
