"""
Regression test for Phase 5 Fix U1: Untranslated Ratio Metric Correction.

Tests that the untranslated ratio check correctly uses AST-based character-level
analysis instead of flawed word-based overlap.

Key test cases:
1. Technical terms that SHOULD remain identical (file formats, product names)
   are NOT counted as "untranslated"
2. Actual untranslated prose IS detected
3. Code blocks are handled correctly
"""

import sys
from pathlib import Path

import pytest

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from scripts.e2e_verify_single_file import (
    check_excessive_untranslated,
    generate_untranslated_breakdown,
)


@pytest.fixture
def source_with_technical_terms():
    """
    Source content with technical terms that should stay identical.

    This represents real documentation with:
    - File formats: PPTX, PPT, DOCX
    - Product names: Aspose.Slides, .NET Framework
    - Platform names: DevOps pipelines
    - Technical abbreviations: FAQ, API, SDK
    """
    return """---
title: Presentation Converter
---

# Overview

Aspose.Slides **Presentation Converter for .NET** provides conversion capabilities.

## Supported Formats

| Format | Description |
|--------|-------------|
| PPTX   | PowerPoint 2007+ |
| PPT    | PowerPoint 97-2003 |
| ODP    | OpenDocument Presentation |

## Requirements

**OS:** Windows, Linux, macOS

**Frameworks:** .NET 8.0+, .NET Framework, .NET Core, Mono

## Features

- Convert **single files** or **batch processing**
- Integrate with **DevOps pipelines** and documentation services
- Export to PDF, HTML, images

## FAQ

**Q: Is the API free?**

A: Yes, the API is free for basic usage.

## Code Example

```csharp
using Aspose.Slides;

var presentation = new Presentation("input.pptx");
presentation.Save("output.pdf", SaveFormat.Pdf);
```

**Note:** This example uses the Aspose.Slides SDK.
"""


@pytest.fixture
def correct_french_translation():
    """
    Correct French translation where technical terms stay identical.

    Technical terms like PPTX, .NET Framework, Aspose.Slides, DevOps
    remain unchanged (as they should).
    """
    return """---
title: Convertisseur de présentation
---

# Aperçu

Aspose.Slides **Convertisseur de présentation pour .NET** fournit des capacités de conversion.

## Formats pris en charge

| Format | Description |
|--------|-------------|
| PPTX   | PowerPoint 2007+ |
| PPT    | PowerPoint 97-2003 |
| ODP    | Présentation OpenDocument |

## Exigences

**OS:** Windows, Linux, macOS

**Frameworks:** .NET 8.0+, .NET Framework, .NET Core, Mono

## Fonctionnalités

- Convertir **fichiers uniques** ou **traitement par lots**
- Intégrer avec **DevOps pipelines** et les services de documentation
- Exporter vers PDF, HTML, images

## FAQ

**Q: L'API est-elle gratuite?**

R: Oui, l'API est gratuite pour une utilisation de base.

## Exemple de code

```csharp
using Aspose.Slides;

var presentation = new Presentation("input.pptx");
presentation.Save("output.pdf", SaveFormat.Pdf);
```

**Note:** Cet exemple utilise le SDK Aspose.Slides.
"""


@pytest.fixture
def untranslated_prose():
    """
    Translation where actual prose paragraphs are left untranslated.

    This should FAIL the untranslated check.
    """
    return """---
title: Convertisseur de présentation
---

# Overview

Aspose.Slides **Presentation Converter for .NET** provides conversion capabilities.

## Supported Formats

| Format | Description |
|--------|-------------|
| PPTX   | PowerPoint 2007+ |
| PPT    | PowerPoint 97-2003 |
| ODP    | OpenDocument Presentation |

## Requirements

**OS:** Windows, Linux, macOS

**Frameworks:** .NET 8.0+, .NET Framework, .NET Core, Mono

## Features

- Convert **single files** or **batch processing**
- Integrate with **DevOps pipelines** and documentation services
- Export to PDF, HTML, images

## FAQ

**Q: Is the API free?**

A: Yes, the API is free for basic usage.

## Code Example

```csharp
using Aspose.Slides;

var presentation = new Presentation("input.pptx");
presentation.Save("output.pdf", SaveFormat.Pdf);
```

**Note:** This example uses the Aspose.Slides SDK.
"""


def test_technical_terms_not_counted_as_untranslated(
    source_with_technical_terms,
    correct_french_translation
):
    """
    Test that properly translated content PASSES even with technical terms.

    This is the core of Fix U1: technical terms like PPTX, .NET Framework,
    Aspose.Slides, DevOps pipelines SHOULD remain identical in translations.

    The check should PASS as long as:
    1. Prose is properly translated
    2. Total identity match ratio stays under 35% threshold
    """
    has_issue, ratio = check_excessive_untranslated(
        source_with_technical_terms,
        correct_french_translation,
        'fr'
    )

    # Should PASS - properly translated content with technical terms is acceptable
    assert not has_issue, \
        f"Translation with correct technical terms should PASS. Ratio: {ratio:.1%}"

    # Ratio might be non-zero (technical terms), but should be under threshold
    assert ratio < 0.35, \
        f"Ratio should be under 35% threshold: {ratio:.1%}"


def test_actual_untranslated_prose_is_detected(
    source_with_technical_terms,
    untranslated_prose
):
    """
    Test that actual untranslated prose IS still detected.

    This proves Fix U1 doesn't weaken the check - it still catches
    real translation failures where prose remains in English.
    """
    has_issue, ratio = check_excessive_untranslated(
        source_with_technical_terms,
        untranslated_prose,
        'fr'
    )

    # The ratio should be HIGH (> 35%) because most content is untranslated
    assert ratio > 0.35, \
        f"Untranslated prose should be detected. Ratio: {ratio:.1%}"

    # Should FAIL (have an issue)
    assert has_issue, \
        f"Translation with untranslated prose should FAIL. Ratio: {ratio:.1%}"


def test_breakdown_categorizes_technical_terms():
    """
    Test that breakdown function works and identifies identity matches.

    The breakdown should correctly identify text spans that are identical
    in source and target, including technical terms.
    """
    source = """---
title: Test
---

**API:** Aspose.Slides for .NET

Supported formats: PPTX, PPT, ODP
"""

    target = """---
title: Test
---

**API:** Aspose.Slides for .NET

Formats pris en charge: PPTX, PPT, ODP
"""

    breakdown = generate_untranslated_breakdown(source, target, 'fr', output_path=None)

    assert breakdown.get('available'), "Breakdown should be available"
    assert 'total_source_chars' in breakdown, "Should have char counts"
    assert 'untranslated_ratio' in breakdown, "Should have ratio"
    assert 'contributors' in breakdown, "Should have contributors list"

    # Should have some identity matches (technical terms)
    assert len(breakdown['contributors']) > 0, "Should identify some identity matches"


def test_code_blocks_excluded_from_ratio():
    """
    Test that code blocks are properly handled in untranslated ratio.

    Code blocks should NOT be translated, so they should either:
    1. Be excluded from the ratio calculation, OR
    2. Not count as "untranslated" since they're correctly preserved
    """
    source = """---
title: Test
---

## Code Example

```csharp
using System;
Console.WriteLine("Hello World");
```

This is translated text.
"""

    target = """---
title: Test
---

## Exemple de code

```csharp
using System;
Console.WriteLine("Hello World");
```

Ceci est un texte traduit.
"""

    has_issue, ratio = check_excessive_untranslated(source, target, 'fr')

    # Code staying identical should NOT cause high untranslated ratio
    assert ratio < 0.20, \
        f"Code blocks staying identical should not inflate ratio: {ratio:.1%}"

    assert not has_issue, \
        f"Translation with preserved code blocks should PASS. Ratio: {ratio:.1%}"


def test_word_based_vs_ast_based_comparison():
    """
    Direct comparison showing word-based check is flawed.

    This test documents the specific improvement of Fix U1.
    """
    # Minimal example with technical terms
    source = "Aspose.Slides PPTX PPT ODP API SDK"
    target = "Aspose.Slides PPTX PPT ODP API SDK"  # Correctly preserved

    # Word-based would show 100% overlap (all words match)
    # AST-based shows 100% untranslated (identity match)
    # BUT with context (paragraph, proper translation around it), should pass

    source_full = f"""---
title: Test
---

Supported formats: {source}

The converter handles all formats efficiently.
"""

    target_full = f"""---
title: Test
---

Formats pris en charge: {source}

Le convertisseur gère tous les formats efficacement.
"""

    has_issue, ratio = check_excessive_untranslated(source_full, target_full, 'fr')

    # With AST-based check and context, should have LOW ratio
    assert ratio < 0.25, \
        f"Technical terms in context should have low ratio: {ratio:.1%}"


def test_regression_frozen_file_case():
    """
    Regression test for the frozen file case from Phase 5.

    The real frozen file had:
    - Old word-based check: 35.6% (FAIL)
    - New AST-based check: 3.0% (PASS)

    This demonstrates the pattern: more prose dilutes the technical terms.
    """
    source = """---
title: Presentation Converter
---

# Overview

Aspose.Slides **Presentation Converter for .NET** is a powerful library that enables developers to convert presentation files between different formats. The library supports a wide range of input and output formats, making it an essential tool for document processing workflows.

## Supported Formats

| Format | Description |
|--------|-------------|
| PPTX   | PowerPoint 2007+ presentations with modern formatting |
| PPT    | Legacy PowerPoint 97-2003 format for compatibility |
| ODP    | OpenDocument Presentation format for open standards |

## System Requirements

**OS:** Windows, Linux, macOS - works on all major operating systems

**Frameworks:** .NET 8.0+, .NET Framework, .NET Core, Mono - flexible framework support

## Key Features

The converter provides comprehensive capabilities for enterprise document workflows:

- Convert **single files** interactively or enable **batch processing** for automation
- Integrate seamlessly with **DevOps pipelines** and continuous documentation services
- Export to multiple formats including PDF, HTML, and image files
- Preserve document formatting and layout during conversion
- Handle large presentations efficiently with optimized memory usage

## Getting Started

To begin using the converter, install the package and initialize the conversion engine. The API provides intuitive methods for loading presentations and saving them in your desired output format.

## FAQ

**Q: What file formats are supported?**

A: The converter supports all major presentation formats including PowerPoint and OpenDocument standards.
"""

    target = """---
title: Convertisseur de présentation
---

# Aperçu

Aspose.Slides **Convertisseur de présentation pour .NET** est une bibliothèque puissante qui permet aux développeurs de convertir des fichiers de présentation entre différents formats. La bibliothèque prend en charge une large gamme de formats d'entrée et de sortie, ce qui en fait un outil essentiel pour les flux de travail de traitement de documents.

## Formats pris en charge

| Format | Description |
|--------|-------------|
| PPTX   | Présentations PowerPoint 2007+ avec formatage moderne |
| PPT    | Format PowerPoint 97-2003 hérité pour la compatibilité |
| ODP    | Format de présentation OpenDocument pour les normes ouvertes |

## Configuration système requise

**OS:** Windows, Linux, macOS - fonctionne sur tous les principaux systèmes d'exploitation

**Frameworks:** .NET 8.0+, .NET Framework, .NET Core, Mono - support de framework flexible

## Fonctionnalités clés

Le convertisseur offre des capacités complètes pour les flux de travail documentaires d'entreprise:

- Convertir **fichiers uniques** de manière interactive ou activer **traitement par lots** pour l'automatisation
- Intégrer de manière transparente avec **DevOps pipelines** et les services de documentation continue
- Exporter vers plusieurs formats, y compris les fichiers PDF, HTML et image
- Préserver le formatage et la mise en page du document pendant la conversion
- Gérer efficacement les grandes présentations avec une utilisation optimisée de la mémoire

## Commencer

Pour commencer à utiliser le convertisseur, installez le package et initialisez le moteur de conversion. L'API fournit des méthodes intuitives pour charger des présentations et les enregistrer dans le format de sortie souhaité.

## FAQ

**Q: Quels formats de fichiers sont pris en charge?**

R: Le convertisseur prend en charge tous les principaux formats de présentation, y compris PowerPoint et les normes OpenDocument.
"""

    has_issue, ratio = check_excessive_untranslated(source, target, 'fr')

    # Should PASS - more prose content dilutes the technical terms
    assert not has_issue, \
        f"Frozen file pattern with adequate prose should PASS. Ratio: {ratio:.1%}"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
