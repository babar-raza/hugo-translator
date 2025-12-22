"""
Verification Agent for post-translation quality checks.

Orchestrates pluggable verification checks to detect:
- Mixed-language content in output
- Untranslated segments
- Truncated content
- Other quality issues

The agent runs after translation but before writing output files.
"""
import logging
from typing import Any, Dict, List, Optional

from .checks.base import VerificationCheck, VerificationIssue, VerificationResult

logger = logging.getLogger(__name__)


class VerificationAgent:
    """
    Orchestrates verification checks on translated documents.

    The agent manages a collection of pluggable checks and runs them
    against translated content to detect quality issues.

    Example:
        from src.verification import VerificationAgent
        from src.verification.checks import LanguageDetectionCheck

        agent = VerificationAgent([
            LanguageDetectionCheck(confidence_threshold=0.85),
        ])

        result = agent.verify(
            source_doc=source_data,
            translated_doc=translated_data,
            target_lang="de"
        )

        if not result.passed:
            for issue in result.issues:
                print(f"{issue.severity}: {issue.message}")
    """

    def __init__(
        self,
        checks: Optional[List[VerificationCheck]] = None,
        fail_fast: bool = False,
    ):
        """
        Initialize verification agent.

        Args:
            checks: List of verification checks to run
            fail_fast: If True, stop on first error; if False, run all checks
        """
        self.checks = checks or []
        self.fail_fast = fail_fast

    def add_check(self, check: VerificationCheck) -> None:
        """
        Add a verification check.

        Args:
            check: Verification check to add
        """
        self.checks.append(check)

    def remove_check(self, check_name: str) -> bool:
        """
        Remove a check by name.

        Args:
            check_name: Name of the check to remove

        Returns:
            True if check was found and removed, False otherwise
        """
        for i, check in enumerate(self.checks):
            if check.name == check_name:
                del self.checks[i]
                return True
        return False

    def verify(
        self,
        source_doc: Dict[str, Any],
        translated_doc: Dict[str, Any],
        target_lang: str,
        context: Optional[Dict[str, Any]] = None,
    ) -> VerificationResult:
        """
        Run all verification checks on translated document.

        Args:
            source_doc: Source document data (frontmatter + body)
            translated_doc: Translated document data
            target_lang: Target language code
            context: Optional context (site profile, config, etc.)

        Returns:
            VerificationResult containing all issues found
        """
        result = VerificationResult(
            metadata={
                "target_lang": target_lang,
                "checks_run": [],
                "checks_skipped": [],
            }
        )

        context = context or {}

        for check in self.checks:
            check_name = check.name

            # Check if this verification is enabled
            if not check.is_enabled(context):
                result.metadata["checks_skipped"].append(check_name)
                logger.debug(f"Skipping disabled check: {check_name}")
                continue

            logger.debug(f"Running verification check: {check_name}")

            try:
                issues = check.run(
                    source=source_doc,
                    translated=translated_doc,
                    target_lang=target_lang,
                    context=context,
                )

                # Record check result
                result.check_results[check_name] = {
                    "passed": len([i for i in issues if i.severity == "error"]) == 0,
                    "issue_count": len(issues),
                    "error_count": len([i for i in issues if i.severity == "error"]),
                    "warning_count": len([i for i in issues if i.severity == "warning"]),
                }

                # Add issues to result
                result.issues.extend(issues)
                result.metadata["checks_run"].append(check_name)

                # Fail fast if enabled and errors found
                if self.fail_fast and any(i.severity == "error" for i in issues):
                    logger.info(f"Fail-fast triggered by check: {check_name}")
                    break

            except Exception as e:
                logger.error(f"Verification check {check_name} failed: {e}")
                result.issues.append(
                    VerificationIssue(
                        severity="error",
                        check_name=check_name,
                        location="<check_execution>",
                        message=f"Check execution failed: {str(e)}",
                        metadata={"exception_type": type(e).__name__},
                    )
                )
                result.check_results[check_name] = {
                    "passed": False,
                    "error": str(e),
                }

        # Log summary
        logger.info(
            f"Verification complete: {result.error_count} errors, "
            f"{result.warning_count} warnings, {result.info_count} info"
        )

        return result

    def get_check_names(self) -> List[str]:
        """Get names of all registered checks."""
        return [check.name for check in self.checks]

    def __len__(self) -> int:
        """Return number of registered checks."""
        return len(self.checks)

    def __repr__(self) -> str:
        """String representation."""
        check_names = ", ".join(self.get_check_names())
        return f"VerificationAgent(checks=[{check_names}])"
