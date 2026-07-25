# Adjudication Merge Report

Workflow: 36 review agents (pipeline, per locale) + 36 adversarial agents
(one per locale, since all locales had at least one top-9 core term
triggering adversarial review) = 72 agents, 0 errors, 0 empty results,
~4.1M tokens, 905 tool calls, ~37 minutes wall time.

Locales processed: 36
Raw merge stats:
```
accepted_untriggered:         660  (single-reviewer decision, not in the
                                     top-9/override/low-share/low-confidence
                                     trigger set)
accepted_adversarial_agree:   801  (triggered, adversarial pass confirmed)
disagreed_pending:             50  (triggered, adversarial pass refuted --
                                     stayed pending, logged to
                                     disagreements.md)
no_value:                       0  (no reviewer left a term fully unanswered)
```
Total decisions covered: 1511 of 1512 possible (36 locales x 42 entries);
1 entry (`ru`/`heading.inheritance`) was silently omitted from that one
locale's structured response despite `no_value` counting 0 -- a schema
gap (the array simply lacked that item) rather than an explicit null.
Caught by the completeness cross-check below, resolved directly (see
"Post-merge fixes").

## Post-merge fixes (data quality, applied after the raw merge)

1. **`rejected_variants` annotation cleanup**: 89 of 685 recorded
   `rejected_variants` strings across 13 locale files had an English
   explanatory parenthetical appended (e.g. "Свойства (Russian, wrong
   language)") instead of the bare literal wrong-form the healer/TM
   correction need for exact-string matching. Stripped via a cleanup
   pass; 10 of those, after stripping, still contained a literal `...`
   ellipsis (non-literal partial-phrase artifacts, e.g. "...con gli
   oggetti {api}..." ) and were dropped entirely rather than kept as
   unusable pseudo-strings. Net: 685 -> 675 usable rejected_variants.
2. **3 core-term disagreements arbitrated**: `hu/heading.methods`,
   `id/heading.values`, `ro/heading.description` were the only
   disagreements involving one of the 6 originally-`approved` entries,
   which would have left a real completeness gap. A third-opinion arbiter
   verified each adversarial counter-argument against that locale's OWN
   other already-written sibling headings (an independently checkable
   claim, not a coin flip) before accepting it — see
   `disagreements.md`'s "Arbitrated exceptions" section for the full
   reasoning and verification.
3. **`ru/heading.inheritance` omission resolved directly**: real corpus
   evidence showed a 100%-share, single-candidate translation
   ("Наследство") that is the SAME wrong-sense trap already caught for
   Arabic (legal/estate "inheritance" vs. the OOP-specific term) -- not
   blindly accepted; resolved to "Наследование" (the standard Russian CS
   term) with "Наследство" recorded as a rejected_variant.
4. **36 registry entries flipped `pending` -> `approved`**: coverage
   across the 36 adjudicated locales ranged 31-36/36 for every one of the
   42 scope entries (median ~35/36) -- strong evidence to promote. The
   remaining per-entry gaps (44 total, cross-referenced in
   `pending_pairs.json`) are exactly the un-arbitrated disagreements;
   `resolve()`'s designed fallback (approved+missing-locale ->
   fallthrough to TM/MT + a reported missing-key event) makes shipping
   with a documented, bounded gap set safe rather than requiring 100%
   coverage before any entry can be approved.
5. All fixes re-verified: `test_classification_resolver.py` (28 tests,
   including a new completeness-gaps-must-be-documented check
   cross-referencing `pending_pairs.json`) and the full
   `tests/unit/translation_engine` + miner + healer suites (1289 passed,
   4 skipped) are green after every change in this report.

Files written: 36

- C:\Users\prora\OneDrive\Documents\GitHub\hugo-translator\config\i18n\template_strings\ar.yaml
- C:\Users\prora\OneDrive\Documents\GitHub\hugo-translator\config\i18n\template_strings\bg.yaml
- C:\Users\prora\OneDrive\Documents\GitHub\hugo-translator\config\i18n\template_strings\ca.yaml
- C:\Users\prora\OneDrive\Documents\GitHub\hugo-translator\config\i18n\template_strings\cs.yaml
- C:\Users\prora\OneDrive\Documents\GitHub\hugo-translator\config\i18n\template_strings\da.yaml
- C:\Users\prora\OneDrive\Documents\GitHub\hugo-translator\config\i18n\template_strings\de.yaml
- C:\Users\prora\OneDrive\Documents\GitHub\hugo-translator\config\i18n\template_strings\el.yaml
- C:\Users\prora\OneDrive\Documents\GitHub\hugo-translator\config\i18n\template_strings\es.yaml
- C:\Users\prora\OneDrive\Documents\GitHub\hugo-translator\config\i18n\template_strings\fa.yaml
- C:\Users\prora\OneDrive\Documents\GitHub\hugo-translator\config\i18n\template_strings\fi.yaml
- C:\Users\prora\OneDrive\Documents\GitHub\hugo-translator\config\i18n\template_strings\fr.yaml
- C:\Users\prora\OneDrive\Documents\GitHub\hugo-translator\config\i18n\template_strings\he.yaml
- C:\Users\prora\OneDrive\Documents\GitHub\hugo-translator\config\i18n\template_strings\hi.yaml
- C:\Users\prora\OneDrive\Documents\GitHub\hugo-translator\config\i18n\template_strings\hr.yaml
- C:\Users\prora\OneDrive\Documents\GitHub\hugo-translator\config\i18n\template_strings\hu.yaml
- C:\Users\prora\OneDrive\Documents\GitHub\hugo-translator\config\i18n\template_strings\id.yaml
- C:\Users\prora\OneDrive\Documents\GitHub\hugo-translator\config\i18n\template_strings\it.yaml
- C:\Users\prora\OneDrive\Documents\GitHub\hugo-translator\config\i18n\template_strings\ja.yaml
- C:\Users\prora\OneDrive\Documents\GitHub\hugo-translator\config\i18n\template_strings\ko.yaml
- C:\Users\prora\OneDrive\Documents\GitHub\hugo-translator\config\i18n\template_strings\lt.yaml
- C:\Users\prora\OneDrive\Documents\GitHub\hugo-translator\config\i18n\template_strings\lv.yaml
- C:\Users\prora\OneDrive\Documents\GitHub\hugo-translator\config\i18n\template_strings\ms.yaml
- C:\Users\prora\OneDrive\Documents\GitHub\hugo-translator\config\i18n\template_strings\nl.yaml
- C:\Users\prora\OneDrive\Documents\GitHub\hugo-translator\config\i18n\template_strings\no.yaml
- C:\Users\prora\OneDrive\Documents\GitHub\hugo-translator\config\i18n\template_strings\pl.yaml
- C:\Users\prora\OneDrive\Documents\GitHub\hugo-translator\config\i18n\template_strings\pt.yaml
- C:\Users\prora\OneDrive\Documents\GitHub\hugo-translator\config\i18n\template_strings\ro.yaml
- C:\Users\prora\OneDrive\Documents\GitHub\hugo-translator\config\i18n\template_strings\ru.yaml
- C:\Users\prora\OneDrive\Documents\GitHub\hugo-translator\config\i18n\template_strings\sk.yaml
- C:\Users\prora\OneDrive\Documents\GitHub\hugo-translator\config\i18n\template_strings\sr.yaml
- C:\Users\prora\OneDrive\Documents\GitHub\hugo-translator\config\i18n\template_strings\sv.yaml
- C:\Users\prora\OneDrive\Documents\GitHub\hugo-translator\config\i18n\template_strings\th.yaml
- C:\Users\prora\OneDrive\Documents\GitHub\hugo-translator\config\i18n\template_strings\tr.yaml
- C:\Users\prora\OneDrive\Documents\GitHub\hugo-translator\config\i18n\template_strings\uk.yaml
- C:\Users\prora\OneDrive\Documents\GitHub\hugo-translator\config\i18n\template_strings\vi.yaml
- C:\Users\prora\OneDrive\Documents\GitHub\hugo-translator\config\i18n\template_strings\zh.yaml