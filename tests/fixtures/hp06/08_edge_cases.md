---
title: "Edge Cases Test"
description: "Tests edge cases and special scenarios"
weight: 8
---

## Escaped Characters

This text has \*escaped asterisks\* that should not be italic.

This text has \*\*escaped bold markers\*\* that should not be bold.

This text has \`escaped backticks\` that should not be code.

This text has \[escaped brackets\](url) that should not be a link.

This text has \!\[escaped image\](image.png) that should not be an image.

## Nested Emphasis Variations

This text has ***triple asterisks*** for bold and italic.

This text has **bold *and italic* together** with proper nesting.

This text has *italic **and bold** together* with reversed nesting.

This text has ___triple underscores___ for emphasis.

This text has __bold _and italic_ together__ with underscores.

## HTML Blocks

<div class="container">
  <h2>HTML Heading</h2>
  <p>This is <strong>HTML content</strong> with tags.</p>
</div>

<table>
  <tr>
    <td>HTML Table</td>
    <td>Cell 2</td>
  </tr>
</table>

## Inline HTML

This paragraph contains <em>inline HTML</em> tags.

This paragraph has <strong>bold HTML</strong> and **markdown bold** together.

This paragraph has <code>HTML code</code> and `markdown code` together.

## Hard Line Breaks

This line ends with two spaces
and continues on the next line.

This line ends with two spaces
and this is the continuation.

## Soft Line Breaks

This line has a soft break
and continues on the next line without spaces.

## Autolinks

Visit <https://example.com> for more information.

Email us at <support@example.com> for help.

## Reference-Style Links

This text has a [reference link][ref1] in it.

This text has another [reference][ref2] link.

[ref1]: https://example.com "Title"
[ref2]: https://docs.example.com

## Empty Elements

This paragraph has ** ** empty bold.

This paragraph has * * empty italic.

This paragraph has ` ` empty code.

This paragraph has []() empty link.

This paragraph has ![]() empty image.

## Adjacent Formatting

This text has **bold***italic* adjacent.

This text has *italic*`code` adjacent.

This text has `code`**bold** adjacent.

## Formatting at Boundaries

**Bold at start** of line.

End of line **bold at end**.

*Italic at start* of line.

End of line *italic at end*.

`Code at start` of line.

End of line `code at end`.

## Special Characters

This text has unicode: é, ñ, 中文, العربية, עברית.

This text has emojis: 😀 🎉 🚀 💻.

This text has symbols: © ® ™ § ¶ †.

This text has mathematical: × ÷ ± ≈ ≠ ≤ ≥.

## Long Words and URLs

This text has a verylongwordwithoutspacesthatmightcausewrappingissues in it.

This text has a very long URL https://example.com/very/long/path/to/resource/with/many/segments/that/might/cause/issues.

## Mixed Scripts

This text mixes English with 中文 and العربية and עברית.

This sentence has Cyrillic русский and Greek ελληνικά too.

## Combining Diacritics

This text has combining diacritics: e\u0301, a\u0300, n\u0303.

## Zero-Width Characters

This text has zero-width spaces​between​words.

This text has zero-width joiners‍between‍characters.

## HTML Entities

This text has &lt;HTML entities&gt; like &amp; and &quot;.

This text has numeric entities: &#169; and &#8364;.

## Multiple Consecutive Formatting

This text has **bold** *italic* `code` [link](url) all in sequence.

This text has multiple **bold** **bold** **bold** elements.

## Unclosed Formatting (Malformed)

Note: These should be handled gracefully by the parser.

This text has **unclosed bold.

This text has *unclosed italic.

This text has `unclosed code.

This text has [unclosed link](url.

This text has ![unclosed image](image.png.

## Nested Code in Formatting

This text has **bold with `code` inside**.

This text has *italic with `code` inside*.

This text has **bold with *italic and `code`* inside**.

## Blockquotes

> This is a blockquote.
> It can span multiple lines.

> This is a blockquote with **formatting**.
> It has *italic* and `code` too.

> Nested blockquotes:
> > This is nested.
> > > This is double nested.

## Horizontal Rules

---

***

___

- - -

* * *

_ _ _

## Definition Lists (if supported)

Term 1
: Definition 1

Term 2
: Definition 2a
: Definition 2b

## Footnotes (if supported)

This text has a footnote[^1].

This text has another footnote[^2].

[^1]: This is the first footnote.
[^2]: This is the second footnote with **formatting**.

## Task Lists (if supported)

- [x] Completed task
- [ ] Incomplete task
- [x] Another completed task with **bold**
- [ ] Another incomplete task with `code`
