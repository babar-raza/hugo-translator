#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Simple validation script to test configuration loading without pytest.
This script validates that all configuration files are valid and loadable.
"""
import sys
import os
from pathlib import Path

# Set UTF-8 encoding for Windows console
if sys.platform == 'win32':
    import codecs
    sys.stdout = codecs.getwriter('utf-8')(sys.stdout.buffer, 'strict')
    sys.stderr = codecs.getwriter('utf-8')(sys.stderr.buffer, 'strict')

# Add src to path
sys.path.insert(0, str(Path(__file__).parent))

try:
    from src.utils.config_loader import ConfigService, ConfigLoadError, ConfigValidationError
    from src.utils.models import ValidationConfig, TerminologyConfig, GlobalConfig

    print("=" * 70)
    print("Configuration Validation Script")
    print("=" * 70)
    print()

    # Initialize config service
    print("1. Initializing ConfigService...")
    config_root = Path(__file__).parent / "config"
    service = ConfigService(config_root)
    print("   ✓ ConfigService initialized successfully")
    print()

    # Test validation config
    print("2. Loading validation.yaml...")
    try:
        validation_config = service.get_validation_config()
        print(f"   ✓ Version: {validation_config.version}")
        print(f"   ✓ Decision rules loaded")
        print(f"     - reject_on_error_count: {validation_config.decision_rules.reject_on_error_count}")
        print(f"     - max_retry_attempts: {validation_config.decision_rules.max_retry_attempts}")
        print(f"   ✓ Retry strategy loaded")
        print(f"     - feedback_mode: {validation_config.retry_strategy.feedback_mode}")
        print(f"     - vary_temperature: {validation_config.retry_strategy.vary_temperature}")
        print(f"   ✓ Validation modes loaded: {', '.join(validation_config.validation_modes.keys())}")
    except Exception as e:
        print(f"   ✗ FAILED: {e}")
        sys.exit(1)
    print()

    # Test terminology config
    print("3. Loading terminology.yaml...")
    try:
        terminology_config = service.get_terminology_config()
        print(f"   ✓ Version: {terminology_config.version}")
        print(f"   ✓ Global exact matches: {len(terminology_config.global_.exact_matches)}")

        # Check for required terms
        terms = [t.term for t in terminology_config.global_.exact_matches]
        required_terms = ["Aspose", ".NET", "Java", "Python"]
        for term in required_terms:
            if term in terms:
                print(f"     - '{term}' found")
            else:
                print(f"     ✗ '{term}' NOT FOUND")
                sys.exit(1)

        print(f"   ✓ Global patterns: {len(terminology_config.global_.patterns)}")
        for pattern in terminology_config.global_.patterns:
            print(f"     - {pattern.category}: {pattern.description or pattern.pattern}")

        print(f"   ✓ Site overrides: {len(terminology_config.site_overrides)}")
        for site in terminology_config.site_overrides.keys():
            print(f"     - {site}")

        print(f"   ✓ Auto-discovery: enabled={terminology_config.auto_discovery.enabled}")
    except Exception as e:
        print(f"   ✗ FAILED: {e}")
        sys.exit(1)
    print()

    # Test global config with validation defaults
    print("4. Loading global.yaml (validation_defaults section)...")
    try:
        global_config = service.global_config
        if global_config.validation_defaults is None:
            print("   ✗ FAILED: validation_defaults section not found")
            sys.exit(1)

        print(f"   ✓ Validation defaults loaded")
        print(f"     - mode: {global_config.validation_defaults.mode}")
        print(f"     - reject_on_error_count: {global_config.validation_defaults.decision_rules.reject_on_error_count}")
        print(f"     - max_retry_attempts: {global_config.validation_defaults.decision_rules.max_retry_attempts}")
        print(f"   ✓ Validators configured: {len(global_config.validation_defaults.validators)}")

        # Check required validators
        required_validators = [
            "completeness",
            "language_consistency",
            "shortcode_preservation",
            "frontmatter_protection",
            "terminology_preservation",
            "file_placement"
        ]
        for validator_name in required_validators:
            if validator_name in global_config.validation_defaults.validators:
                validator = global_config.validation_defaults.validators[validator_name]
                status = "enabled" if validator.enabled else "disabled"
                print(f"     - {validator_name}: {status}")
            else:
                print(f"     ✗ {validator_name}: NOT FOUND")
                sys.exit(1)
    except Exception as e:
        print(f"   ✗ FAILED: {e}")
        sys.exit(1)
    print()

    # Test caching
    print("5. Testing configuration caching...")
    try:
        validation_config2 = service.get_validation_config()
        if validation_config is validation_config2:
            print("   ✓ Validation config caching works")
        else:
            print("   ✗ Validation config caching failed")
            sys.exit(1)

        terminology_config2 = service.get_terminology_config()
        if terminology_config is terminology_config2:
            print("   ✓ Terminology config caching works")
        else:
            print("   ✗ Terminology config caching failed")
            sys.exit(1)
    except Exception as e:
        print(f"   ✗ FAILED: {e}")
        sys.exit(1)
    print()

    # Test reload
    print("6. Testing configuration reload...")
    try:
        validation_config3 = service.reload_validation_config()
        if validation_config3 is not validation_config:
            print("   ✓ Validation config reload works (new instance)")
        else:
            print("   ✗ Validation config reload failed (same instance)")
            sys.exit(1)

        if validation_config3.version == validation_config.version:
            print("   ✓ Validation config reload preserves data")
        else:
            print("   ✗ Validation config reload corrupted data")
            sys.exit(1)
    except Exception as e:
        print(f"   ✗ FAILED: {e}")
        sys.exit(1)
    print()

    print("=" * 70)
    print("✓ ALL CONFIGURATION VALIDATION TESTS PASSED")
    print("=" * 70)
    print()
    print("Summary:")
    print("  - config/validation.yaml: ✓ Valid")
    print("  - config/terminology.yaml: ✓ Valid")
    print("  - config/global.yaml (validation_defaults): ✓ Valid")
    print("  - Schema validation: ✓ Working")
    print("  - Configuration caching: ✓ Working")
    print("  - Configuration reload: ✓ Working")
    print()

except ImportError as e:
    print(f"✗ Import error: {e}")
    print("\nNote: This script requires PyYAML and pydantic to be installed.")
    print("To install: pip install pyyaml pydantic")
    sys.exit(1)
except Exception as e:
    print(f"✗ Unexpected error: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)
