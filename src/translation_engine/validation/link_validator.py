"""
Link validity validator.

Ensures that links in translations are valid and properly formed.
"""

import re
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urlparse

from .base import Validator, ValidationResult, ValidationSeverity


class LinkValidator(Validator):
    """
    Validates link integrity and format in translations.

    Checks:
    - Link URLs are preserved or properly translated
    - Link syntax is valid
    - Internal links maintained
    - Anchor links preserved
    """

    def __init__(
        self, check_url_changes: bool = True, allow_url_translation: bool = False, name: Optional[str] = None
    ):
        """
        Initialize link validator.

        Args:
            check_url_changes: Whether to flag changed URLs
            allow_url_translation: Whether URL changes are acceptable (for localized links)
            name: Optional custom name
        """
        super().__init__(name)
        self.check_url_changes = check_url_changes
        self.allow_url_translation = allow_url_translation

    def validate(
        self,
        source: str,
        translation: str,
        context: Optional[Dict[str, Any]] = None,
    ) -> ValidationResult:
        """
        Validate link integrity.

        Args:
            source: Source markdown text
            translation: Translated markdown text
            context: Optional context

        Returns:
            ValidationResult with any link issues
        """
        result = ValidationResult(success=True)

        # Extract links
        source_links = self._extract_links(source)
        translation_links = self._extract_links(translation)

        # Check link count
        if len(source_links) != len(translation_links):
            result.issues.append(
                self.create_issue(
                    ValidationSeverity.WARNING,
                    f"Link count mismatch: source has {len(source_links)}, translation has {len(translation_links)}",
                    location="links",
                    details={
                        "source_count": len(source_links),
                        "translation_count": len(translation_links),
                    },
                )
            )

        # Check each translation link
        for text, url in translation_links:
            self._check_link_syntax(url, result)

        # Check URL preservation if required
        if self.check_url_changes:
            self._check_url_preservation(source_links, translation_links, result)

        return result

    def _extract_links(self, text: str) -> List[Tuple[str, str]]:
        """
        Extract markdown links and images.

        Args:
            text: Markdown text

        Returns:
            List of (link_text, url) tuples
        """
        # Pattern for [text](url) and ![alt](url) - Allow empty URLs with *
        pattern = r"!?\[([^\]]*)\]\(([^)]*)\)"
        matches = re.findall(pattern, text)
        return [(text.strip(), url.strip()) for text, url in matches]

    def _check_link_syntax(self, url: str, result: ValidationResult) -> None:
        """
        Check if link URL is valid.

        Args:
            url: URL to validate
            result: ValidationResult to add issues to
        """
        # Check for empty URLs
        if not url:
            result.issues.append(
                self.create_issue(
                    ValidationSeverity.ERROR,
                    "Empty URL found in link",
                    location="links",
                )
            )
            result.success = False
            return

        # Check for spaces in URLs (should be %20)
        if " " in url and not url.startswith("#"):
            result.issues.append(
                self.create_issue(
                    ValidationSeverity.WARNING,
                    f"URL contains unencoded spaces: {url}",
                    location="links",
                    details={"url": url},
                )
            )

        # For absolute URLs, check basic structure
        if url.startswith(("http://", "https://")):
            try:
                parsed = urlparse(url)
                if not parsed.netloc:
                    result.issues.append(
                        self.create_issue(
                            ValidationSeverity.ERROR,
                            f"Invalid absolute URL: {url}",
                            location="links",
                            details={"url": url},
                        )
                    )
                    result.success = False
            except Exception as e:
                result.issues.append(
                    self.create_issue(
                        ValidationSeverity.ERROR,
                        f"Malformed URL: {url} ({str(e)})",
                        location="links",
                        details={"url": url, "error": str(e)},
                    )
                )
                result.success = False

    def _check_url_preservation(
        self,
        source_links: List[Tuple[str, str]],
        translation_links: List[Tuple[str, str]],
        result: ValidationResult,
    ) -> None:
        """
        Check that URLs are preserved from source to translation.

        Args:
            source_links: Source (text, url) tuples
            translation_links: Translation (text, url) tuples
            result: ValidationResult to add issues to
        """
        # Extract just URLs
        source_urls = {url for _, url in source_links}
        translation_urls = {url for _, url in translation_links}

        # Check for missing URLs
        missing_urls = source_urls - translation_urls
        if missing_urls:
            result.issues.append(
                self.create_issue(
                    ValidationSeverity.WARNING,
                    f"URLs from source not found in translation: {', '.join(list(missing_urls)[:3])}{'...' if len(missing_urls) > 3 else ''}",
                    location="links",
                    details={"missing_urls": list(missing_urls)},
                )
            )

        # Check for new URLs
        extra_urls = translation_urls - source_urls
        if extra_urls:
            # If URL translation is allowed, it's just info; otherwise it's a warning
            severity = ValidationSeverity.INFO if self.allow_url_translation else ValidationSeverity.WARNING
            result.issues.append(
                self.create_issue(
                    severity,
                    f"New URLs in translation: {', '.join(list(extra_urls)[:3])}{'...' if len(extra_urls) > 3 else ''}",
                    location="links",
                    details={"extra_urls": list(extra_urls)},
                )
            )
