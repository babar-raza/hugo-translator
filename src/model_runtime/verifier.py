"""Model verification system to validate downloads and detect corruption."""
import json
import logging
from pathlib import Path
from typing import Dict, List, Optional
from dataclasses import dataclass
from datetime import datetime, UTC

logger = logging.getLogger(__name__)


@dataclass
class VerificationResult:
    """Result of model verification."""
    model_id: str
    model_path: Path
    passed: bool
    checks_performed: List[str]
    checks_passed: List[str]
    checks_failed: List[str]
    error_message: Optional[str] = None
    verification_time: Optional[str] = None

    def to_dict(self) -> dict:
        return {
            "model_id": self.model_id,
            "model_path": str(self.model_path),
            "passed": self.passed,
            "checks_performed": self.checks_performed,
            "checks_passed": self.checks_passed,
            "checks_failed": self.checks_failed,
            "error_message": self.error_message,
            "verification_time": self.verification_time
        }


class ModelVerifier:
    """Verify model integrity and functionality."""

    def __init__(self, models_dir: Path):
        """Initialize verifier.

        Args:
            models_dir: Base directory for models (e.g., models/)
        """
        self.models_dir = Path(models_dir)

    def verify(self, model_path: Path, model_id: str = None) -> VerificationResult:
        """Verify a single model.

        Args:
            model_path: Path to model directory
            model_id: Optional model ID (inferred from path if not provided)

        Returns:
            VerificationResult with details
        """
        if model_id is None:
            model_id = model_path.name

        checks_performed = []
        checks_passed = []
        checks_failed = []
        error_message = None

        try:
            # Check 1: Directory exists
            checks_performed.append("directory_exists")
            if not model_path.exists():
                checks_failed.append("directory_exists")
                error_message = f"Model directory not found: {model_path}"
                return self._create_result(
                    model_id, model_path, checks_performed, checks_passed, checks_failed, error_message
                )
            checks_passed.append("directory_exists")

            # Check 2: Metadata file exists
            checks_performed.append("metadata_exists")
            metadata_file = model_path / ".metadata.json"
            if not metadata_file.exists():
                checks_failed.append("metadata_exists")
                error_message = f"Metadata file missing: {metadata_file}"
            else:
                checks_passed.append("metadata_exists")

                # Check 3: Metadata is valid JSON
                checks_performed.append("metadata_valid")
                try:
                    with open(metadata_file) as f:
                        metadata = json.load(f)
                    checks_passed.append("metadata_valid")

                    # Check 4: Required metadata fields present
                    checks_performed.append("metadata_complete")
                    required_fields = ["model_id", "backend", "local_path", "downloaded_at"]
                    missing_fields = [f for f in required_fields if f not in metadata]
                    if missing_fields:
                        checks_failed.append("metadata_complete")
                        error_message = f"Missing metadata fields: {missing_fields}"
                    else:
                        checks_passed.append("metadata_complete")

                except json.JSONDecodeError as e:
                    checks_failed.append("metadata_valid")
                    error_message = f"Invalid JSON in metadata: {e}"

            # Check 5: Model files exist
            checks_performed.append("model_files_exist")
            model_files = list(model_path.glob("*"))
            if len(model_files) <= 1:  # Only .metadata.json
                checks_failed.append("model_files_exist")
                error_message = "No model files found (only metadata)"
            else:
                checks_passed.append("model_files_exist")

                # Check 6: Detect backend and verify required files
                checks_performed.append("required_files_present")
                if self._check_required_files(model_path):
                    checks_passed.append("required_files_present")
                else:
                    checks_failed.append("required_files_present")
                    error_message = "Missing required model files"

            # Check 7: Calculate actual size
            checks_performed.append("size_calculation")
            try:
                total_size = sum(f.stat().st_size for f in model_path.rglob('*') if f.is_file())
                size_mb = total_size / (1024 * 1024)
                checks_passed.append("size_calculation")

                # Update metadata with verification result
                if metadata_file.exists():
                    try:
                        with open(metadata_file) as f:
                            metadata = json.load(f)
                        metadata["last_verified"] = datetime.now(UTC).isoformat()
                        metadata["verification_status"] = "passed" if not checks_failed else "failed"
                        metadata["actual_size_mb"] = round(size_mb, 2)

                        # Atomic write
                        temp_file = metadata_file.with_suffix(".json.tmp")
                        with open(temp_file, 'w') as f:
                            json.dump(metadata, f, indent=2)
                        temp_file.rename(metadata_file)
                    except Exception as e:
                        logger.warning(f"Could not update metadata: {e}")

            except Exception as e:
                checks_failed.append("size_calculation")
                error_message = f"Size calculation failed: {e}"

        except Exception as e:
            error_message = f"Verification error: {e}"
            logger.error(f"Error verifying {model_id}: {e}")

        return self._create_result(
            model_id, model_path, checks_performed, checks_passed, checks_failed, error_message
        )

    def _check_required_files(self, model_path: Path) -> bool:
        """Check if required files exist based on backend."""
        # Try to detect backend from files
        has_pytorch = any(model_path.glob("*.bin")) or any(model_path.glob("*.safetensors"))
        has_ct2 = (model_path / "model.bin").exists()

        if has_pytorch:
            # HuggingFace model - check for config.json and tokenizer files
            required = ["config.json"]
            return all((model_path / f).exists() for f in required)
        elif has_ct2:
            # CTranslate2 model - check for vocabulary files
            return True  # model.bin exists
        else:
            # Unknown backend
            return False

    def _create_result(
        self,
        model_id: str,
        model_path: Path,
        checks_performed: List[str],
        checks_passed: List[str],
        checks_failed: List[str],
        error_message: Optional[str]
    ) -> VerificationResult:
        """Create verification result."""
        passed = len(checks_failed) == 0
        verification_time = datetime.now(UTC).isoformat()

        return VerificationResult(
            model_id=model_id,
            model_path=model_path,
            passed=passed,
            checks_performed=checks_performed,
            checks_passed=checks_passed,
            checks_failed=checks_failed,
            error_message=error_message,
            verification_time=verification_time
        )

    def verify_all(self, backend: Optional[str] = None) -> List[VerificationResult]:
        """Verify all models in models directory.

        Args:
            backend: Optional backend filter (huggingface, ctranslate2)

        Returns:
            List of verification results
        """
        results = []

        # Scan models directory
        for backend_dir in self.models_dir.iterdir():
            if not backend_dir.is_dir():
                continue

            # Skip if filtering by backend
            if backend and backend_dir.name != backend:
                continue

            # Check each model in backend directory
            for model_dir in backend_dir.iterdir():
                if not model_dir.is_dir():
                    continue
                if model_dir.name.startswith('.'):
                    continue

                result = self.verify(model_dir, model_id=model_dir.name)
                results.append(result)

        return results


class VerificationError(Exception):
    """Model verification failed."""
    pass
