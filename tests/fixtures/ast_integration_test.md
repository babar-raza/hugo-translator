---
title: "AST Integration Test Document"
description: "Test fixture for AST batch translation validation"
weight: 10
---

## Introduction

This is a test document for validating the AST batch translation system. It contains multiple paragraphs with various text units to test batch translation functionality.

## Section with Code

Here is some text before the code block.

```python
def hello_world():
    print("Hello, World!")
    return True
```

And some text after the code block.

## Section with Links

This paragraph contains [a link to example.com](https://example.com) and **bold text** and *italic text*. The link should be preserved during translation while the surrounding text is translated.

## Section with Multiple Paragraphs

This is the first paragraph with enough text to be meaningful for translation testing. It should be extracted as a separate text unit.

This is the second paragraph. It also has enough content to verify that multiple paragraphs are handled correctly in batch translation.

This is the third paragraph, ensuring we have enough units to test batch processing with multiple text units.

## Section with Inline Code

The `variable_name` should not be translated, but this surrounding text should be translated properly.

## Conclusion

This final section wraps up the test document with a meaningful conclusion paragraph that provides additional text for batch translation testing.
