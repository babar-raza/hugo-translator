---
title: "Extraction Test Document"
description: "Test document for segment extraction"
tags:
  - tag1
  - tag2
banner:
  title: "Banner Title"
  content: "Banner content with {{< shortcode >}} embedded"
draft: false
date: 2024-01-01
---

# Introduction

This is a test document with various content types for extraction testing.

## Features

Here's a paragraph with `inline code` that should be preserved in the segment.

- List item one
- List item two with {{< figure src="image.jpg" >}}
- List item three

## Code Example

```python
def hello_world():
    print("Hello, World!")
```

This code should not be extracted as a segment.

## Mixed Content

Final paragraph with [a link](https://example.com) and more text.
