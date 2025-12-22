#!/usr/bin/env python
"""Test the fixed language consistency validator with corrupted content"""

import sys
sys.path.insert(0, r'C:\Users\prora\AppData\Roaming\Python\Python313\site-packages')

from src.translation_engine.validation.language_consistency_validator import LanguageConsistencyValidator

# Sample corrupted German text with mixed English
corrupted_text = """
und die **Aspose.Slides Plugins for .NET** bietet eine robuste Reihe von Tools, die PowerPoint-Präsentationsverarbeitung innerhalb von .NET-Anwendungen erleichtern sollen.
Ob Sie Präsentierungen zwischen Formaten konvertieren, mehrere Decks miteinander vereinen, Text für die Indexierung extrahieren oder Slides in PDF, Bilder oder Web-Formate exportieren müssen, diese Plugins bieten die Flexibilität und Strom, den Sie benötigen.

Presentation Format Konvertierung is a common requirement.

Mit der Aspose.Slides Presentation Converter Plugin Entwickler können Präsentationen zwischen verschiedenen Formaten in ihren .NET-Anwendungen leicht konvertieren.
"""

# Sample clean German text
clean_text = """
Die Aspose.Slides Plugins für .NET bieten eine robuste Sammlung von Werkzeugen zur Verarbeitung von PowerPoint-Präsentationen in .NET-Anwendungen.
Egal ob Sie Präsentationen zwischen Formaten konvertieren, mehrere Decks zusammenführen, Text zur Indizierung extrahieren oder Folien in PDF-, Bild- oder Web-Formate exportieren müssen, diese Plugins bieten die Flexibilität und Leistung, die Sie benötigen.
"""

validator = LanguageConsistencyValidator(confidence_threshold=0.85)

print("=" * 80)
print("Testing CORRUPTED text (mixed German/English):")
print("=" * 80)
result1 = validator.validate(
    source="",
    translation=corrupted_text,
    context={"target_lang": "de"}
)

print(f"Success: {result1.success}")
print(f"Issues: {len(result1.issues)}")
for issue in result1.issues:
    print(f"  - [{issue.severity.value}] {issue.message}")
if result1.metadata:
    print(f"Metadata: {result1.metadata}")

print("\n" + "=" * 80)
print("Testing CLEAN text (pure German):")
print("=" * 80)
result2 = validator.validate(
    source="",
    translation=clean_text,
    context={"target_lang": "de"}
)

print(f"Success: {result2.success}")
print(f"Issues: {len(result2.issues)}")
for issue in result2.issues:
    print(f"  - [{issue.severity.value}] {issue.message}")
if result2.metadata:
    print(f"Metadata: {result2.metadata}")

print("\n" + "=" * 80)
print("RESULT:")
print("=" * 80)
if not result1.success and result2.success:
    print("✓ Validator correctly REJECTS corrupted text")
    print("✓ Validator correctly ACCEPTS clean text")
    print("\nValidator is working correctly!")
    sys.exit(0)
else:
    print("✗ Validator failed to detect correctly")
    print(f"  Corrupted text success={result1.success} (should be False)")
    print(f"  Clean text success={result2.success} (should be True)")
    sys.exit(1)
