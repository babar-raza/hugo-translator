"""
Pydantic models for site profiles and configuration.

These models provide runtime validation and type safety for configuration data.
"""
from __future__ import annotations

from enum import Enum
from typing import Dict, List, Literal, Optional

from pydantic import BaseModel, Field, field_validator


class FrontmatterMode(str, Enum):
    """Modes for handling frontmatter fields."""

    TRANSLATE = "translate"  # Translate the field value
    PASSTHROUGH = "passthrough"  # Copy value as-is
    COMPUTED = "computed"  # Compute value (e.g., slug from title)
    TRANSLATE_LIST = "translate_list"  # Translate each item in a list
    IGNORE = "ignore"  # Do not include in output


class FrontmatterRule(BaseModel):
    """Rule for handling a specific frontmatter field."""

    mode: FrontmatterMode = Field(
        ..., description="How to handle this frontmatter field"
    )
    strategy: Optional[str] = Field(
        None,
        description="Optional translation strategy (e.g., preserve_case, technical_terms)",
    )

    model_config = {"use_enum_values": True}


class BodyRules(BaseModel):
    """Rules for translating markdown body content."""

    translate_markdown: bool = Field(
        ..., description="Whether to translate markdown body content"
    )
    preserve_blocks: List[str] = Field(
        default_factory=list,
        description="Block types to preserve (not translate), e.g., block_code",
    )
    preserve_patterns: List[str] = Field(
        default_factory=list,
        description="Regex patterns for content to preserve (e.g., Hugo shortcodes)",
    )
    placeholder_syntax: List[str] = Field(
        default_factory=list,
        description="Hugo shortcode/placeholder patterns to protect during translation",
    )


class OutputLayout(BaseModel):
    """Output file path layout configuration."""

    per_language_folders: bool = Field(
        ...,
        description="Whether to use per-language folder structure (e.g., /de/, /es/)",
    )
    pattern: str = Field(
        default="{lang}/{path}",
        description="Output file path pattern. Variables: {lang}, {path}, {filename}",
    )


class TMPreferences(BaseModel):
    """Translation Memory preferences."""

    use_semantic_tm: bool = Field(
        default=True, description="Enable L3 semantic translation memory"
    )
    fallback_exact_only: bool = Field(
        default=False,
        description="Fallback to exact match only if semantic fails",
    )
    min_similarity_score: float = Field(
        default=0.8,
        ge=0.0,
        le=1.0,
        description="Minimum similarity score for semantic matches",
    )


class SiteValidationConfig(BaseModel):
    """Site-specific validation configuration."""

    enabled: bool = Field(default=True, description="Enable validation for this site")
    validation_mode: Optional[Literal["strict", "normal", "lenient", "off"]] = Field(
        None, description="Override global validation mode"
    )
    validators: Optional[Dict[str, ValidatorConfig]] = Field(
        None, description="Validator-specific settings"
    )
    post_write_validation: bool = Field(
        default=True, description="Enable post-write validation"
    )


class SiteTerminologyConfig(BaseModel):
    """Site-specific terminology configuration."""

    enabled: bool = Field(default=True, description="Enable terminology preservation")
    preserve_mode: Optional[Literal["PROTECT", "VALIDATE", "BOTH", "NONE"]] = Field(
        None, description="Override global preserve mode"
    )
    inherit_global: bool = Field(
        default=True, description="Inherit global terminology rules"
    )
    custom_terms: List[TermMatch] = Field(
        default_factory=list, description="Site-specific custom terms"
    )


class SiteProfile(BaseModel):
    """Complete site profile configuration."""

    site_id: str = Field(
        ...,
        description="Unique identifier for the site (e.g., products.aspose.net)",
        pattern=r"^[a-z0-9.-]+$",
    )
    content_roots: List[str] = Field(
        ...,
        min_length=1,
        description="List of content root directories to watch/translate",
    )
    default_source_lang: str = Field(
        ...,
        description="Default source language code (e.g., en)",
        pattern=r"^[a-z]{2}(-[A-Z]{2})?$",
    )
    target_langs: List[str] = Field(
        ...,
        min_length=1,
        description="List of target language codes",
    )
    frontmatter: Dict[str, FrontmatterRule] = Field(
        default_factory=dict,
        description="Frontmatter field rules (field_name -> rule)",
    )
    body: BodyRules = Field(..., description="Body translation rules")
    output_layout: Optional[OutputLayout] = Field(
        default_factory=lambda: OutputLayout(
            per_language_folders=True, pattern="{lang}/{path}"
        ),
        description="Output file path layout",
    )
    tm_prefs: Optional[TMPreferences] = Field(
        default_factory=TMPreferences,
        description="Translation Memory preferences",
    )
    validation: Optional[SiteValidationConfig] = Field(
        None, description="Site-specific validation configuration"
    )
    terminology: Optional[SiteTerminologyConfig] = Field(
        None, description="Site-specific terminology configuration"
    )

    @field_validator("target_langs", mode="before")
    @classmethod
    def validate_target_langs(cls, v: List[str]) -> List[str]:
        """Validate target language codes."""
        import re

        pattern = re.compile(r"^[a-z]{2}(-[A-Z]{2})?$")
        for lang in v:
            if not pattern.match(lang):
                raise ValueError(
                    f"Invalid language code: {lang}. Must match pattern: xx or xx-YY"
                )
        return v

    @field_validator("frontmatter")
    @classmethod
    def validate_frontmatter_not_empty(
        cls, v: Dict[str, FrontmatterRule]
    ) -> Dict[str, FrontmatterRule]:
        """Ensure at least some frontmatter rules are defined."""
        if not v:
            # Allow empty frontmatter, but warn in logs
            pass
        return v


class ValidatorConfig(BaseModel):
    """Configuration for an individual validator."""

    enabled: bool = Field(default=True, description="Whether this validator is enabled")
    confidence_threshold: Optional[float] = Field(
        None,
        ge=0.0,
        le=1.0,
        description="Confidence threshold for validators that support it",
    )


class DecisionRules(BaseModel):
    """Decision rules for validation pipeline."""

    reject_on_error_count: int = Field(
        default=3, ge=1, description="Reject if this many errors are detected"
    )
    reject_on_placeholder_error: bool = Field(
        default=True, description="Reject if placeholder integrity fails"
    )
    reject_on_code_block_error: bool = Field(
        default=True, description="Reject if code blocks are corrupted"
    )
    reject_on_link_error: bool = Field(
        default=True, description="Reject if links are broken"
    )
    max_retry_attempts: int = Field(
        default=2, ge=0, le=5, description="Maximum number of retry attempts"
    )
    retry_on_structure_error: bool = Field(
        default=True, description="Retry if markdown structure is damaged"
    )
    retry_on_terminology_warning: bool = Field(
        default=True, description="Retry if terminology violations found"
    )
    accept_warnings: bool = Field(
        default=True, description="Accept translation with warnings"
    )
    accept_after_max_retries: bool = Field(
        default=True, description="Accept after max retries even if issues remain"
    )


class RetryStrategy(BaseModel):
    """Retry strategy configuration."""

    feedback_mode: Literal["brief", "detailed", "examples"] = Field(
        default="detailed", description="Feedback detail level"
    )
    vary_temperature: bool = Field(
        default=True, description="Vary LLM temperature on retries"
    )
    temperature_increment: float = Field(
        default=0.1, ge=0.0, le=0.5, description="Temperature increase per retry"
    )
    max_temperature: float = Field(
        default=1.0, ge=0.0, le=2.0, description="Maximum temperature to use"
    )


class ValidationMode(BaseModel):
    """Configuration for a validation mode profile."""

    accept_warnings: bool = Field(default=True, description="Accept warnings")
    reject_on_error_count: int = Field(
        default=3, ge=1, description="Error count threshold"
    )
    max_retry_attempts: int = Field(
        default=2, ge=0, le=5, description="Max retry attempts"
    )


class ValidationConfig(BaseModel):
    """Complete validation configuration."""

    version: str = Field(default="1.0", description="Configuration schema version")
    decision_rules: DecisionRules = Field(
        default_factory=DecisionRules, description="Decision rules for validation"
    )
    retry_strategy: RetryStrategy = Field(
        default_factory=RetryStrategy, description="Retry strategy configuration"
    )
    validation_modes: Dict[str, ValidationMode] = Field(
        default_factory=dict, description="Named validation mode profiles"
    )


class TermMatch(BaseModel):
    """Configuration for exact term matching."""

    term: str = Field(..., description="Exact term to match")
    category: str = Field(..., description="Term category (e.g., company_name)")
    case_sensitive: bool = Field(default=True, description="Case-sensitive matching")
    preserve_mode: Literal["protect", "validate", "both", "none"] = Field(
        default="both", description="Preservation mode"
    )
    severity: Literal["error", "warning", "info"] = Field(
        default="error", description="Violation severity"
    )


class TermPattern(BaseModel):
    """Configuration for pattern-based term matching."""

    pattern: str = Field(..., description="Regular expression pattern")
    category: str = Field(..., description="Term category")
    description: Optional[str] = Field(None, description="Pattern description")
    preserve_mode: Literal["protect", "validate", "both", "none"] = Field(
        default="both", description="Preservation mode"
    )
    severity: Literal["error", "warning", "info"] = Field(
        default="error", description="Violation severity"
    )


class GlobalTerminology(BaseModel):
    """Global terminology configuration."""

    exact_matches: List[TermMatch] = Field(
        default_factory=list, description="Exact term matches"
    )
    patterns: List[TermPattern] = Field(
        default_factory=list, description="Pattern-based matches"
    )


class SiteTerminologyOverride(BaseModel):
    """Site-specific terminology overrides."""

    inherit_global: bool = Field(
        default=True, description="Inherit global terminology rules"
    )
    patterns: List[TermPattern] = Field(
        default_factory=list, description="Site-specific patterns"
    )


class AutoDiscovery(BaseModel):
    """Auto-discovery configuration for terminology extraction."""

    enabled: bool = Field(
        default=False, description="Enable automatic terminology discovery"
    )
    min_frequency: int = Field(
        default=3, ge=1, description="Minimum occurrences to consider as terminology"
    )
    confidence_threshold: float = Field(
        default=0.8,
        ge=0.0,
        le=1.0,
        description="Minimum confidence score to auto-add term",
    )


class TerminologyConfig(BaseModel):
    """Complete terminology configuration."""

    version: str = Field(default="1.0", description="Configuration schema version")
    global_: GlobalTerminology = Field(
        default_factory=GlobalTerminology,
        alias="global",
        description="Global terminology rules",
    )
    site_overrides: Dict[str, SiteTerminologyOverride] = Field(
        default_factory=dict, description="Site-specific overrides"
    )
    auto_discovery: AutoDiscovery = Field(
        default_factory=AutoDiscovery, description="Auto-discovery settings"
    )

    model_config = {"populate_by_name": True}


class ValidationDefaults(BaseModel):
    """Validation defaults section for global config."""

    mode: Literal["strict", "normal", "lenient"] = Field(
        default="normal", description="Default validation mode"
    )
    decision_rules: DecisionRules = Field(
        default_factory=DecisionRules, description="Default decision rules"
    )
    validators: Dict[str, ValidatorConfig] = Field(
        default_factory=dict, description="Validator configurations"
    )


class ValidationSettings(BaseModel):
    """Top-level validation settings for global config."""

    enabled: bool = Field(default=True, description="Global kill switch for validation")
    config_file: str = Field(
        default="config/validation.yaml", description="Path to validation config"
    )
    mode: Literal["strict", "normal", "lenient"] = Field(
        default="normal", description="Default validation mode"
    )


class TerminologySettings(BaseModel):
    """Top-level terminology settings for global config."""

    enabled: bool = Field(
        default=True, description="Global kill switch for terminology preservation"
    )
    config_file: str = Field(
        default="config/terminology.yaml", description="Path to terminology config"
    )
    preserve_mode: Literal["PROTECT", "VALIDATE", "BOTH", "NONE"] = Field(
        default="BOTH", description="Default preservation mode"
    )


class TelemetrySettings(BaseModel):
    """Telemetry settings for global config."""

    validation_metrics: bool = Field(
        default=True, description="Track validation metrics"
    )


class GlobalConfig(BaseModel):
    """Global configuration defaults."""

    default_tm_prefs: TMPreferences = Field(
        default_factory=TMPreferences,
        description="Default TM preferences for all sites",
    )
    default_output_layout: OutputLayout = Field(
        default_factory=lambda: OutputLayout(
            per_language_folders=True, pattern="{lang}/{path}"
        ),
        description="Default output layout for all sites",
    )
    model_cache_dir: str = Field(
        default="./data/models", description="Directory for caching translation models"
    )
    tm_data_dir: str = Field(
        default="./data/tm", description="Directory for translation memory data"
    )
    validation: Optional[ValidationSettings] = Field(
        None, description="Top-level validation settings"
    )
    terminology: Optional[TerminologySettings] = Field(
        None, description="Top-level terminology settings"
    )
    telemetry: Optional[TelemetrySettings] = Field(
        None, description="Telemetry settings"
    )
    validation_defaults: Optional[ValidationDefaults] = Field(
        None, description="Validation configuration defaults"
    )


# Example usage and validation
if __name__ == "__main__":
    # Example site profile
    example_profile = SiteProfile(
        site_id="products.aspose.net",
        content_roots=["/content/products.aspose.net"],
        default_source_lang="en",
        target_langs=["de", "es", "fr", "ja"],
        frontmatter={
            "title": FrontmatterRule(mode=FrontmatterMode.TRANSLATE),
            "description": FrontmatterRule(mode=FrontmatterMode.TRANSLATE),
            "draft": FrontmatterRule(mode=FrontmatterMode.PASSTHROUGH),
        },
        body=BodyRules(
            translate_markdown=True,
            preserve_blocks=["block_code", "codespan"],
            preserve_patterns=[r"^\{\{<.*>\}\}$", r"^\{\{%.*?%\}\}$"],
            placeholder_syntax=[r"\{\{<.*>\}\}", r"\{\{%.*?%\}\}"],
        ),
    )

    print("Example profile:")
    print(example_profile.model_dump_json(indent=2))
