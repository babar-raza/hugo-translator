# Segment Extraction Context Rules

This guide explains how the Hugo Translation System segments content for translation based on frontmatter, body text, and different context types.

## Overview

When translating Hugo content, the system breaks down documents into smaller, translatable units called **segments**. Each segment represents a piece of content that should be translated as a whole, such as a title, a paragraph, or a list item.

Segmentation is controlled by:
- **Site profiles** - Define what content to translate and how
- **Context types** - Categorize segments (frontmatter, body text, headings, etc.)
- **Protection rules** - Preserve non-translatable content like code and shortcodes

## Content Segmentation Types

### Frontmatter Segmentation

Frontmatter (the YAML header at the top of Hugo files) is segmented based on field rules defined in your site profile.

#### Translation Modes

- **Translate**: Extract the field value as a single segment
- **Translate List**: Extract each list item as a separate segment
- **Passthrough**: Copy the field unchanged (no translation)
- **Ignore**: Skip the field entirely

#### Example Frontmatter Rules

```yaml
frontmatter:
  title:
    mode: translate
  tags:
    mode: translate_list
  draft:
    mode: passthrough
  date:
    mode: ignore
```

#### Input Document
```yaml
---
title: "Getting Started with Hugo"
tags:
  - tutorial
  - hugo
  - static-site
draft: false
date: 2024-01-15
---

Welcome to Hugo!
```

#### Extracted Segments
- 1 segment: "Getting Started with Hugo" (title)
- 3 segments: "tutorial", "hugo", "static-site" (tags)
- No segments for draft/date (passthrough/ignore)

### Body Text Segmentation

Body content is segmented by parsing the Markdown AST (Abstract Syntax Tree) and extracting text from different node types.

#### Supported Node Types

- **Headings** (`# ## ###`): Each heading becomes a segment
- **Paragraphs**: Each paragraph becomes a segment
- **List items**: Each list item becomes a segment
- **Blockquotes**: Content within blockquotes

#### Preserved Content

Some content is not translated but preserved with placeholders:

- **Code blocks** (```code```): Protected entirely
- **Inline code** (`code`): Protected
- **Hugo shortcodes** ({{< shortcode >}}): Protected
- **Custom patterns**: URLs, dates, etc. (defined in site profile)

#### Example Body Segmentation

**Input Markdown:**
```markdown
# Welcome to Hugo

This is a paragraph with `inline code` and {{< shortcode >}}.

- List item 1
- List item 2

```
Code block here
```
```

**Extracted Segments:**
- Heading: "Welcome to Hugo"
- Paragraph: "This is a paragraph with {PLACEHOLDER_0} and {PLACEHOLDER_1}."
- List item: "List item 1"
- List item: "List item 2"
- (Code block preserved, not segmented)

## Context Types

Each segment is tagged with a context type that indicates where it came from and how it should be handled.

### Frontmatter Context
- **Type**: `frontmatter`
- **Key Path**: Dot-notation path (e.g., `banner.title`)
- **Metadata**: Field type, nesting level

### Body Text Context
- **Type**: `body_text`
- **Node ID**: AST node identifier
- **Parent Type**: Container node type (paragraph, list, etc.)
- **Depth**: Nesting level in document structure

### Heading Context
- **Type**: `heading`
- **Level**: Heading level (1-6)
- **Node ID**: AST node identifier

### List Item Context
- **Type**: `list_item`
- **List Type**: Ordered (`1.`) or unordered (`-`)
- **Node ID**: AST node identifier

## Placeholder Protection

Non-translatable content is replaced with placeholders during extraction and restored after translation.

### Built-in Protections

- **Hugo Shortcodes**: `{{< shortcode >}}`, `{{% shortcode %}}`
- **Code Blocks**: Triple backticks
- **Inline Code**: Single backticks
- **HTML Tags**: `<tag>` (if configured)

### Custom Patterns

Define additional patterns in your site profile:

```yaml
body:
  preserve_patterns:
    - "https?://[^\\s]+"     # URLs
    - "\\d{4}-\\d{2}-\\d{2}" # ISO dates
    - "[A-Z]{2,}"           # Acronyms
```

### Placeholder Format

- **Pattern**: `{PLACEHOLDER_N}` where N is a sequential number
- **Mapping**: Stored separately for restoration
- **Stability**: Same content always gets same placeholder ID

## Complete Segmentation Example

**Input Document:**
```yaml
---
title: "Hugo Tutorial"
tags:
  - beginner
  - tutorial
description: "Learn Hugo with {{< relref \"quickstart\" >}}"
---

# Getting Started

Welcome! This guide covers `hugo new site`.

## Installation

Install Hugo from [hugo site](https://gohugo.io).

- Download the binary
- Add to PATH
- Verify with `hugo version`

```
hugo new site my-site
cd my-site
```
```

**Site Profile Rules:**
```yaml
frontmatter:
  title: {mode: translate}
  tags: {mode: translate_list}
  description: {mode: translate}

body:
  preserve_blocks: [block_code, inline_code]
  placeholder_syntax: ["\\{\\{<.*?>\\}\\}", "\\{\\{%.*?%\\}\\}"]
  preserve_patterns: ["https?://[^\\s]+"]  # URLs
```

**Extracted Segments:**

1. **Frontmatter Segments:**
   - Context: `frontmatter`, Key: `title`
     Text: "Hugo Tutorial"
   - Context: `frontmatter`, Key: `tags[0]`
     Text: "beginner"
   - Context: `frontmatter`, Key: `tags[1]`
     Text: "tutorial"
   - Context: `frontmatter`, Key: `description`
     Text: "Learn Hugo with {PLACEHOLDER_0}"

2. **Body Segments:**
   - Context: `heading`, Level: 1
     Text: "Getting Started"
   - Context: `body_text`
     Text: "Welcome! This guide covers {PLACEHOLDER_1}."
   - Context: `heading`, Level: 2
     Text: "Installation"
   - Context: `body_text`
     Text: "Install Hugo from {PLACEHOLDER_2}."
   - Context: `list_item`
     Text: "Download the binary"
   - Context: `list_item`
     Text: "Add to PATH"
   - Context: `list_item`
     Text: "Verify with `hugo version`"

**Placeholder Map:**
- `{PLACEHOLDER_0}`: `{{< relref "quickstart" >}}`
- `{PLACEHOLDER_1}`: `` `hugo new site` ``
- `{PLACEHOLDER_2}`: `https://gohugo.io`

## Best Practices

### Site Profile Configuration

1. **Be Specific**: Define rules for all frontmatter fields you want to control
2. **Use Passthrough**: For metadata that shouldn't be translated (dates, slugs, booleans)
3. **Protect Code**: Always preserve code blocks and inline code
4. **Pattern Testing**: Test regex patterns with sample content

### Content Authoring

1. **Short Segments**: Keep paragraphs concise for better translation quality
2. **Consistent Structure**: Use consistent heading levels and list formats
3. **Avoid Mixed Content**: Don't mix translatable text with code in the same segment

### Translation Workflow

1. **Preserve Placeholders**: Always restore placeholders after translation
2. **Maintain Context**: Use context information for translation memory lookups
3. **Validate Restoration**: Check that protected content is correctly restored

## Troubleshooting

### Common Issues

**Segments Too Long**: Break up long paragraphs or use more headings

**Missing Translations**: Check that context types are properly configured in site profile

**Broken Placeholders**: Verify regex patterns don't conflict with each other

**Inconsistent IDs**: Segment IDs change if content or context changes - this is expected

### Debugging Segmentation

Use debug logging to see segmentation details:

```bash
translate-hugo --input content/post.md --log-level DEBUG --dry-run
```

This will show:
- All extracted segments with their context
- Placeholder mappings
- Applied rules and filters

## Related Documentation

- [Site Profile Configuration](../reference/config.md)
- [Architecture: Segment Extractor](../architecture/segment-extractor.md)
- [Terminology Pattern Syntax](../reference/terminology-pattern-syntax.md)
- [Validation Guide](validation-guide.md)
