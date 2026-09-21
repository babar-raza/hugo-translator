"""
Link validity validator.

Ensures that links in translations are valid and properly formed.
"""

from collections import Counter
from typing import Any
from urllib.parse import urlparse

from .base import ValidationResult, ValidationSeverity, Validator
from .link_utils import extract_markdown_links


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
        self, check_url_changes: bool = True, allow_url_translation: bool = False, name: str | None = None
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
        context: dict[str, Any] | None = None,
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

        # VA-04 (TC-APT-105): a URL appearing MORE times in the translation
        # than in the source is unambiguously a defect -- unlike a
        # missing/added link (which has documented false-positive history
        # elsewhere in this codebase and correctly stays a WARNING), there is
        # no legitimate reason a correct translation would introduce EXTRA
        # copies of a URL the source didn't repeat that many times. Keyed on
        # URL alone, not (text, url): keying on the full pair would flag
        # every ordinarily-translated anchor text (e.g. "Link" -> "Lien",
        # same URL) as a false "duplicate", since the translated-text pair
        # never existed in source at all -- that is the overwhelmingly
        # common, correct case, not a defect. Escalated to ERROR so it drives
        # decision_engine's critical-failure path on its own, without
        # depending on the generic count-mismatch WARNING above (which the
        # live TC-APT-105 incident showed can be silently defeated by a
        # retry-budget/policy interaction -- see VA-01).
        source_url_counts = Counter(url for _, url in source_links)
        translation_url_counts = Counter(url for _, url in translation_links)
        for url, translation_count in translation_url_counts.items():
            source_count = source_url_counts.get(url, 0)
            # A URL with ZERO source occurrences is a NEW link, not a
            # duplicate of an existing one -- that is the softer, deliberately
            # non-ERROR `extra_urls` case _check_url_preservation already
            # handles (localization can legitimately introduce a new URL).
            # Only escalate when the source already had this URL and the
            # translation has strictly more copies of it.
            if source_count == 0 or translation_count <= source_count:
                continue
            extra_count = translation_count - source_count
            result.issues.append(
                self.create_issue(
                    ValidationSeverity.ERROR,
                    f"URL {url!r} appears {extra_count} extra time(s) in the "
                    f"translation beyond its {source_count} source occurrence(s)",
                    location="links",
                    details={
                        "duplicated_url": url,
                        "source_occurrences": source_count,
                        "translation_occurrences": translation_count,
                        "extra_occurrences": extra_count,
                    },
                )
            )
            result.success = False

        # Check each translation link
        for text, url in translation_links:
            self._check_link_syntax(url, result)

        # Check URL preservation if required
        if self.check_url_changes:
            self._check_url_preservation(source_links, translation_links, result)

        return result

    def _extract_links(self, text: str) -> list[tuple[str, str]]:
        """
        Extract markdown links and images.

        Args:
            text: Markdown text

        Returns:
            List of (link_text, url) tuples
        """
        return extract_markdown_links(text)

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
        source_links: list[tuple[str, str]],
        translation_links: list[tuple[str, str]],
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
