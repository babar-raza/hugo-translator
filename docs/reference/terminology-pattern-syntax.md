# Terminology Pattern Syntax Reference

**Status**: Core system feature - terminology protection and validation

## Overview

The Hugo Translation System uses regular expressions (regex) to identify and protect critical terminology during translation. This reference document provides comprehensive guidance on the regex pattern syntax used in `config/terminology.yaml` for terminology protection.

## Pattern Syntax Basics

Terminology patterns use Python's `re` module regex syntax. All patterns are case-sensitive unless explicitly configured otherwise.

### Word Boundaries

Word boundaries (`\b`) ensure patterns match complete words only:

```yaml
# Matches "API" but not "APIs" or "SOAP"
pattern: "\\bAPI\\b"

# Matches "class" but not "classes" or "classify"
pattern: "\\bclass\\b"
```

### Character Classes

Common character classes for matching specific character types:

```yaml
# Any uppercase letter
[A-Z]

# Any lowercase letter
[a-z]

# Any letter (uppercase or lowercase)
[A-Za-z]

# Any digit
\d

# Any alphanumeric character or underscore
\w

# Any character except newline
.
```

### Quantifiers

Control how many times a pattern element repeats:

```yaml
# Zero or more
*

# One or more
+

# Zero or one (optional)
?

# Exactly n times
{n}

# Between n and m times
{n,m}
```

## Pattern Categories

### Product and Brand Names

Patterns for identifying product families and brand terminology:

```yaml
# Aspose product families (Aspose.Words, Aspose.Cells, etc.)
pattern: "Aspose\\.[A-Z][a-z]+"
category: product_family
description: "Aspose product families"

# Examples:
# ✓ Aspose.Words
# ✓ Aspose.Cells
# ✓ Aspose.PDF
# ✗ aspose.words (case sensitive)
# ✗ Aspose.words (mixed case)
```

### Platform and Technology Names

Patterns for technology platforms and frameworks:

```yaml
# .NET platform variants
patterns:
  - pattern: "\\.NET Framework"
    category: platform
    description: ".NET Framework platform"

  - pattern: "\\.NET Core"
    category: platform
    description: ".NET Core platform"

  - pattern: "\\.NET Standard"
    category: platform
    description: ".NET Standard platform"

  - pattern: "\\.NET \\d+\\.\\d+"
    category: platform
    description: ".NET version numbers (e.g., .NET 6.0, .NET 7.1)"

# Examples:
# ✓ .NET Framework
# ✓ .NET Core
# ✓ .NET Standard
# ✓ .NET 6.0
# ✓ .NET 7.1
```

### Programming Identifiers

Patterns for code constructs and identifiers:

```yaml
# PascalCase identifiers (C# class/method names)
pattern: "\\b[A-Z][a-z]+(?:[A-Z][a-z]+)+\\b"
category: pascal_case_identifier
description: "PascalCase API identifiers"

# UPPER_CASE constants
pattern: "\\b[A-Z_]+\\b"
category: constant_name
description: "UPPER_CASE constants"

# Code constructs with dot notation
pattern: "SaveFormat\\.[A-Za-z]+"
category: code
description: "SaveFormat enum values"

# Examples:
# ✓ DocumentBuilder (PascalCase)
# ✓ MAX_LENGTH (UPPER_CASE)
# ✓ SaveFormat.Pdf (dot notation)
# ✗ documentBuilder (lowercase start)
# ✗ max_length (lowercase with underscore)
```

### Version Numbers

Patterns for semantic versioning and version strings:

```yaml
# Semantic versioning (major.minor.patch)
pattern: "\\d+\\.\\d+\\.\\d+"
category: version
description: "Semantic version numbers"

# Version ranges with plus (e.g., 6.0+)
pattern: "\\d+\\.\\d+\\+"
category: version
description: "Version ranges with plus suffix"

# Examples:
# ✓ 1.2.3
# ✓ 21.4.0
# ✓ 6.0+
# ✓ 7.1+
```

### Technical Terms

Patterns for technical terminology and API references:

```yaml
# Technical terms (case-insensitive word boundaries)
patterns:
  - pattern: "\\bAPI Reference\\b"
    category: technical
    description: "API Reference documentation"

  - pattern: "\\bLowCode API\\b"
    category: technical
    description: "LowCode API terminology"

  - pattern: "\\bLINQ Engine\\b"
    category: plugin_name
    description: "LINQ Engine plugin"

# Examples:
# ✓ API Reference
# ✓ LowCode API
# ✓ LINQ Engine
```

### Class and Type Names

Patterns for object-oriented programming constructs:

```yaml
# Class names with "class" keyword
pattern: "Presentation class"
category: code
description: "Presentation class references"

# Generic patterns for class-like constructs
pattern: "\\b[A-Z][a-zA-Z0-9]*\\b"
category: type_name
description: "Type and class names"

# Examples:
# ✓ Presentation class
# ✓ DocumentBuilder
# ✓ String
```

## Advanced Pattern Techniques

### Non-Capturing Groups

Use non-capturing groups `(?:...)` for logical grouping without capturing:

```yaml
# PascalCase: Capital + lowercase, repeated
pattern: "\\b[A-Z][a-z]+(?:[A-Z][a-z]+)+\\b"

# This matches: DocumentBuilder, HtmlDocument, XmlParser
# Without capturing the repeated groups
```

### Alternation

Use `|` for matching alternatives:

```yaml
# Match either "class" or "interface"
pattern: "\\b(?:class|interface)\\b"

# Match different file extensions
pattern: "\\.(?:pdf|doc|docx|xlsx)\\b"
```

### Lookahead and Lookbehind

Advanced patterns using lookahead/lookbehind (rarely needed):

```yaml
# Match "API" only when followed by "Reference"
pattern: "\\bAPI(?= Reference)\\b"

# Match "class" only when preceded by a type name
pattern: "(?<=\\b[A-Z][a-z]+\\s)class\\b"
```

## Pattern Testing and Validation

### Testing Patterns

Use Python's `re` module to test patterns:

```python
import re

# Test a pattern
pattern = r"\b[A-Z][a-z]+(?:[A-Z][a-z]+)+\b"
text = "Use DocumentBuilder to create documents"

matches = re.findall(pattern, text)
print(matches)  # ['DocumentBuilder']
```

### Common Pattern Issues

**Over-matching**: Patterns that match too broadly
```yaml
# Too broad - matches any word
pattern: "\\w+"  # AVOID

# Better - specific to PascalCase
pattern: "\\b[A-Z][a-z]+(?:[A-Z][a-z]+)+\b"
```

**Under-matching**: Patterns that are too restrictive
```yaml
# Too restrictive - misses valid cases
pattern: "\\bAspose\\.Words\\b"  # Only exact match

# Better - matches product family pattern
pattern: "Aspose\\.[A-Z][a-z]+"
```

**Performance**: Complex patterns can slow down processing
```yaml
# Complex pattern with nested quantifiers
pattern: "(?:\\w+\\s+)*\\w*"  # Can be slow

# Simpler alternative
pattern: "\\b\\w+(?:\\s+\\w+)*\\b"
```

## Configuration Examples

### Complete Terminology Configuration

```yaml
version: "1.0"

global:
  exact_matches:
    - term: "Aspose"
      category: company_name
      case_sensitive: true
      preserve_mode: both
      severity: error

  patterns:
    # Product families
    - pattern: "Aspose\\.[A-Z][a-z]+"
      category: product_family
      description: "Aspose product families"
      preserve_mode: protect
      severity: error

    # Platform terms
    - pattern: "\\.NET Framework"
      category: platform
      preserve_mode: both
      severity: error

    # API identifiers
    - pattern: "\\b[A-Z][a-z]+(?:[A-Z][a-z]+)+\\b"
      category: pascal_case_identifier
      description: "PascalCase API identifiers"
      preserve_mode: protect
      severity: error

site_overrides:
  reference.aspose.net:
    inherit_global: true
    patterns:
      # Additional API patterns for reference docs
      - pattern: "\\b[A-Z_]+\\b"
        category: constant_name
        description: "UPPER_CASE constants"
        preserve_mode: protect
        severity: warning
```

## Best Practices

### Pattern Design

1. **Use word boundaries** (`\b`) to prevent partial matches
2. **Be specific** - prefer targeted patterns over broad ones
3. **Test thoroughly** - validate against real content
4. **Document intent** - use descriptions for complex patterns
5. **Consider performance** - avoid overly complex regex

### Category Organization

1. **company_name**: Brand and company terms
2. **product_family**: Product line identifiers
3. **platform**: Technology platforms and frameworks
4. **pascal_case_identifier**: API class/method names
5. **constant_name**: UPPER_CASE constants
6. **technical**: Technical terminology
7. **version**: Version numbers and ranges
8. **code**: Code constructs and examples

### Maintenance

- **Regular review**: Audit patterns against new content
- **Performance monitoring**: Watch for slow pattern matching
- **False positives**: Adjust patterns that block valid translations
- **Coverage gaps**: Add patterns for newly discovered terminology

## Troubleshooting

### Pattern Not Matching

**Check case sensitivity**:
```yaml
# If pattern doesn't match "Aspose.Words"
pattern: "Aspose\\.[A-Z][a-z]+"  # Requires exact case
```

**Verify word boundaries**:
```yaml
# If matching "class" in "classes"
pattern: "\\bclass\\b"  # Requires word boundaries
```

### Pattern Matching Too Broadly

**Add constraints**:
```yaml
# Instead of matching any word
pattern: "\\w+"  # AVOID

# Match specific pattern
pattern: "\\b[A-Z][a-z]+\\b"  # Better
```

### Performance Issues

**Simplify complex patterns**:
```yaml
# Complex nested quantifiers
pattern: "(?:\\w+\\s+)*\\w*"  # Slow

# Simpler alternative
pattern: "\\b\\w+(?:\\s+\\w+)*\\b"  # Faster
```

## Related Documentation

- [Terminology Configuration](../reference/config.md#terminologyyaml) - Complete config reference
- [Quality Improvement Guide](../guides/quality-improvement.md#11-implement-terminology-protection-system) - Usage and setup
- [Validation Guide](../guides/validation-guide.md) - Validation system overview
