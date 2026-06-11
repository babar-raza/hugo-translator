# Open Questions

1. **Was the shortcode regex bug causing production translation failures?**
   The `{{< >}}` shortcode type is the most common in Hugo. With the regex never matching them, the shortcode preservation validator was always reporting 0 source shortcodes for `{{< >}}` content, meaning validation silently passed even when shortcodes were missing from translations. Actual production impact depends on whether `{{% %}}` shortcodes (which did work) were the primary type in translated content.

2. **Should extra shortcodes in translation remain as WARNING or be promoted back to ERROR?**
   The tests expected WARNING, and this is the more pragmatic choice (LLM hallucination of an extra shortcode is less harmful than missing one). However, in strict validation mode, it might be desirable to treat extras as errors. Consider adding a config option.

3. **Are there other validators with similar regex or API drift bugs?**
   Only the shortcode_preservation_validator was affected. Other validators in the validation suite use different patterns and all 461 validation tests pass.
