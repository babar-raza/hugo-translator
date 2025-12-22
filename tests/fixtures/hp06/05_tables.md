---
title: "Tables Test"
description: "Tests tables with various formatting"
weight: 5
---

## Simple Table

| Column 1 | Column 2 | Column 3 |
|----------|----------|----------|
| Cell 1   | Cell 2   | Cell 3   |
| Cell 4   | Cell 5   | Cell 6   |

## Table with Formatting

| Feature | Description | Status |
|---------|-------------|--------|
| **Bold feature** | This feature is *important* | ✓ |
| `Code feature` | Uses **bold** and `code` | ✓ |
| Regular feature | No formatting | ✗ |

## Table with Links

| Resource | URL | Type |
|----------|-----|------|
| Website | [example.com](https://example.com) | Official |
| Documentation | [docs.example.com](https://docs.example.com) | Guides |
| API Reference | [api.example.com](https://api.example.com) | Technical |

## Table with Aligned Columns

| Left Aligned | Center Aligned | Right Aligned |
|:-------------|:--------------:|--------------:|
| Left | Center | Right |
| **Bold** | *Italic* | `Code` |
| [Link](https://example.com) | Text | 123 |

## Complex Table

| Method | Parameters | Returns | Description |
|--------|-----------|---------|-------------|
| `Save()` | **string** path | **void** | Saves presentation to **`PPTX`** format |
| `Load()` | **string** path | **Presentation** | Loads *existing* presentation |
| `Export()` | **`SaveFormat`** format | **byte[]** | Exports to [various formats](https://docs.example.com) |

## Table with Long Content

| Feature | Description |
|---------|-------------|
| **File Size Reduction** | PPTX files are typically smaller than PPT files, making them easier to share and store. |
| **Preserve Layout** | Convert between formats while preserving layout, formatting, animations, and embedded media. |
| **Batch Conversion** | Process multiple files simultaneously, saving time in large-scale migration projects. |
