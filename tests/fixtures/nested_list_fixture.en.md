---
title: Nested List Test Fixture
description: Fixture to reproduce nested list concatenation bug
type: docs
---

# Nested List Preservation Test

This fixture tests that nested list structures are preserved during translation.

## Test Section 1: Standard Nested List

* **Primary Item One**
  Description of the first item:
    - Nested bullet A
    - Nested bullet B
    - Nested bullet C

* **Primary Item Two**
  Description of the second item:
    - Nested bullet X
    - Nested bullet Y
    - Nested bullet Z

## Test Section 2: Checklist with Icons

✔ First checklist item with icon
✔ Second checklist item with icon
✔ Third checklist item with icon
✔ Fourth checklist item with icon
✔ Fifth checklist item with icon

## Test Section 3: Mixed Content

Regular paragraph before list.

* **Feature Conversion**
  Convert documents to multiple formats:
    - PDF (print-ready)
    - HTML (browser-ready)
    - PNG (image output)

Regular paragraph after list.

## Test Section 4: Deep Nesting

* Level 1 Item A
  * Level 2 Item A1
    * Level 3 Item A1a
    * Level 3 Item A1b
  * Level 2 Item A2
* Level 1 Item B
  * Level 2 Item B1
    * Level 3 Item B1a

End of fixture.
