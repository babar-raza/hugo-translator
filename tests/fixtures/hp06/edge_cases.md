---
title: Edge Cases Test
description: Tests edge cases and special scenarios
---

## Escaped Characters

This is \*not italic\* because it is escaped.

This is \[not a link\](url) because it is escaped.

Use \`not code\` for literal backticks.

## Hard Line Breaks

This line has two trailing spaces
for a hard line break.

This line also has hard break
continuation.

## HTML Blocks

<div class="note">
This is an HTML block that should be preserved exactly.
</div>

<table>
  <tr>
    <td>HTML Table Cell</td>
  </tr>
</table>

## Inline HTML

This has <strong>inline HTML</strong> that differs from markdown.

Use <code>inline code HTML</code> for comparison.

## Empty Paragraphs and Whitespace

Paragraph before blank lines.



Paragraph after blank lines with extra spacing.

## Special Unicode

This has special characters: em—dash, en–dash, ellipsis…

Smart quotes: "quoted" and 'quoted'.

## Very Long Paragraph

This is a very long paragraph that contains many words and phrases to test how the system handles longer text segments. It includes various punctuation marks, numbers like 123 and 456.78, and continues for multiple sentences. The purpose is to ensure that long text blocks are handled correctly without truncation or corruption. We also test that formatting within long paragraphs works: **bold text** and *italic text* and `code spans` and [links](https://example.com) all preserve their structure correctly even when surrounded by lots of other content.
