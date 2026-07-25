# Audit & healing script manifest

HT-QUALITY-GATES-001 Phase 8 (F6). One place enumerating every quality-audit
and healing script in this directory, what it checks, its scope, and whether
its output feeds the `merge_audit_queues.py` → `data/audit/master_heal_queue.jsonl`
→ `unit_heal.py` remediation loop.

**Why this file exists**: the Phase 7 reconnaissance sweep (artifact
`26178f4f`) concluded several defect categories had "no detector anywhere at
any scale" — but two of them (cross-context metadata contamination,
cross-locale template duplication) already had working, tested detector
scripts sitting in this directory, simply never discovered or wired in
(root cause RC5: no registry of what already exists). Check this file before
writing a new detector — the check you need may already exist, possibly
scoped more narrowly than you'd write it from scratch.

## Full-corpus structural sweeps (feed the merge queue)

| Script | Covers | Feeds `merge_audit_queues.py`? |
|---|---|---|
| `audit_all_content.py` | Primary structural sweep, all sites (registry-driven site list). ~23 hand-rolled checks (gates 9-28's concepts, kept separate for historical output continuity) + every `GATE_REGISTRY` gate 29+ auto-swept via `WriteGateEvaluator.run_all_content_gates()` (Phase 8 F1). Absorbed the former `audit_blog_bundle.py` (retired — blog.aspose.org is now covered via registry-driven discovery). | Yes — `audit_structural.jsonl` (Tier 1), auto-discovered. |
| `audit_linguistic.py` | Tier 2 linguistic checks. | Yes — `audit_linguistic.jsonl` (Tier 2), auto-discovered. |
| `audit_completeness.py` | Tier 3: prose-line-count ratio completeness heuristic — a **separate, independent reimplementation** of the same concept as `CompletenessValidator` (pipeline) and `audit_translation_quality.py::score_completeness`. See "Known duplication" below. | Yes — `audit_completeness.jsonl` (Tier 3), auto-discovered. |
| `audit_semantic.py` | Tier 4 (optional): LLM-scored semantic check for short API description cells / frontmatter descriptions that passed T1/T2 but may still hallucinate (e.g. "psychiatrist" for "shrink to fit"). Costs real LLM calls — sampled, not full-corpus. | Yes — `audit_semantic.jsonl` (Tier 4), auto-discovered if present. |
| `build_unit_heal_queue.py` | Runs the real `UnitQualityScorer` (genuine AST/TextUnit extraction) per file — the only tool in this directory that produces REAL per-unit indices, not `[]`. 10-type fixed vocabulary: `mojibake_detector`, `shortcode_leak_detector`, `inline_code_integrity_detector`, `empty_unit_detector`, `hallucination_length_detector`, `short_api_desc_detector`, `language_purity_detector`, `duplicate_run_detector`, `link_path_detector`, `newline_ratio_detector`. | Yes (Phase 8 F4) — `unit_heal_queue.jsonl`, auto-discovered as a 5th tier. Previously a disconnected pipeline (RC2). |

## Narrow / targeted structural scans (NOT auto-fed into the merge queue)

These are real, working, targeted detectors for specific confirmed bugs.
Their output stays in its own JSONL and is **not** picked up by
`merge_audit_queues.py`'s auto-discovery — read them directly, or wire a
specific one in if you need its findings in the main remediation loop.

| Script | Covers | Scope |
|---|---|---|
| `audit_tm_collision.py` | Translated `description`/`summary` names a DIFFERENT class/identifier than the file's own title (TM-key-collision signature). **This is the working detector for the Phase 7 report's "cross-context metadata contamination" gap category (#12)** — see the Phase 8 plan's Tier C. | `reference.aspose.org`-style single-identifier API pages only. |
| `audit_cross_locale_duplication.py` | 2+ locales share a byte-identical non-trivial value for the same frontmatter field on the same source page (shared-batch/template corruption signature). **Working detector for the Phase 7 report's gap category #6** — but frontmatter-field-only; body-paragraph duplication is a Phase 8 Tier B extension. | `title`/`description`/`head_title`/`subtitle`/`head_description`/`summary` frontmatter fields, filtered to fields actually configured `mode: translate` per site profile. |
| `audit_bare_brace_placeholder_leak.py` | The bare-brace-wrapped-correct-value placeholder leak (`` `{ColumnInfo}` `` instead of `` `ColumnInfo` ``) fixed 2026-07-22 in `PlaceholderManager.restore()` — a DIFFERENT shape from Gate 30's literal `PLACEHOLDER_N` token leak. | `reference.aspose.org` only (the only site whose frontmatter `preserve_patterns` lack a backtick-specific rule). |
| `audit_brand_duplication.py` | "Aspose.\<Product\> FOSS" template mangled into a doubled-FOSS string in title/head_title/linkTitle/FAQ fields. | All sites, FOSS-template pages. |
| `audit_code_duplication.py` | `single.block[].content` frontmatter field's fenced code sample duplicated in place with a stray reopened (often unclosed) fence. **Related to but distinct from Phase 8 Tier A #7** (Gate 26's reopened-fence extension) — this script targets a frontmatter-embedded YAML code string specific to products.aspose.org landing pages; Gate 26 targets general markdown-body fenced code blocks on any site. Complementary, not redundant. | `products.aspose.org` only, `single.block[].content` field only. |
| `audit_digit_headings.py` | Non-Latin-locale heading starting with a digit, left untranslated in English (old "version number" regex had no end anchor). | Non-Latin locales only (script mismatch makes English-vs-translated unambiguous without an EN comparison). |
| `audit_sr_script_mixing.py` | Cyrillic/Latin script-mixing within a single Serbian bullet list (some `-`/`*` items translated to Cyrillic, adjacent ones stay Latin). | `sr` locale only, all sites. |
| `audit_llm_artifacts.py` | Standalone full-corpus scan reusing `quality/refusal_patterns.py`'s `REFUSAL_RE`/`LEADING_DASH_RE`/`ASPOSE_TOKEN_RE` (same pattern source as Gate 29, different consumer). | All sites; frontmatter fields + heading/link text. |
| `scripts/audit_translation_quality.py` (repo root, not `scripts/quality/`) | Sampling-based (stratified by site/lang/content-type) 5-dimension quality score: completeness, purity, terminology, structural fidelity, shortcode preservation, optional LLM naturalness/fidelity. The documented CI/incident-response gate (see `docs/operations/incident-response.md`). | Sample, not full corpus. Separate tool from everything above — do not confuse with `scripts/quality/audit_completeness.py`. |

## Healing / remediation

| Script | Role |
|---|---|
| `merge_audit_queues.py` | Merges the auto-fed tiers above into `data/audit/master_heal_queue.jsonl`, deduplicated by `(file_path, locale)`. |
| `unit_heal.py` | The healer. Default input: `master_heal_queue.jsonl`. Two repair paths (Phase 8 F3): (1) gate-registry-derived issue types (e.g. `refusal_artifact_gate29`, or any `gate{id}_...` name) are healed by re-running the real `WriteGateEvaluator` via `run_all_content_gates()` — auto_clean gates fix mechanically, others correctly report `needs_retranslation` rather than being silently marked clean; (2) `UnitQualityScorer`-vocabulary issue types are re-scored fresh via a live `scorer.score()` call (does NOT trust the queue's `unit_indices` field — always re-derives). **Must use `run_all_content_gates()`, never `evaluate()`, for path (1)'s still-failing check**: `evaluate()` discards every "warn"-tier gate's verdict against a disposable result (by design, for the production write path), so checking its `result.passed` always reads `True` for a warn-tier gate regardless of the real content — silently reproducing RC2. This exact bug was introduced, then caught by independent verification and fixed, in the same session that added this healing path. |

**Gate 36 (fidelity judge) is a special case, not covered by the row above**:
both `audit_all_content.py` and `unit_heal.py` construct their `WriteGateEvaluator`
with `config=None`, and gate 36's own guard (`if not _cfg.get("enabled", False): return
translated_content`) makes it an unconditional no-op whenever config is absent —
so it is a guaranteed no-op in *every* offline tool regardless of what
`config/global.yaml` says. In production, though, `engine_builder.py` wires a
real `ConfigService` in, and `config/global.yaml`'s `fidelity_judge.enabled: true`
/ `enforce: false` means gate 36 actually runs in shadow mode on live writes
(computes a verdict, writes `translation_fidelity` frontmatter, never blocks).
Net effect: gate 36 findings can only ever be inspected on files already
written by the live pipeline — neither the audit sweep nor the healer will
ever surface or re-check them. This is intentional (prevents runaway offline
LLM calls) and safe, just worth knowing before assuming the audit sweep's
"every gate is auto-swept" claim above covers gate 36 too.
| `surgical_retranslate.py` | A fifth, independent full-disk scanner + repairer — does **not** consume any JSONL queue (scans disk directly). `--apply` performs CPU-only mechanical repairs for a subset of issue types; anything needing real retranslation is detected and reported in a `model_needed_*` bucket, not auto-fixed (a prior regex "fix" here caused real corruption — see TC-HT-001). |
| `heal_english_headings.py` | GPU-based retranslation for 5 specific defect categories (API/section headings left in English, table Access-column values, body-identical-to-EN, empty-body). Queue-driven; hardcodes `<site>/en/<rel>` source resolution — does not support blog.aspose.org's page-bundle scheme. |
| `heal_llm_refusal_blogscheme.py` | One-off remediation for blog.aspose.org's page-bundle + filename-suffix scheme specifically (the case `heal_english_headings.py` can't handle), using `TranslationEngine.translate_file()`'s own `output_layout`-aware path resolution. |
| `heal_missing_indexes.py` | Translates missing `_index.md` files for `reference.aspose.org`, by locale. |

## Explicitly out of scope

`evidence.*`/`provenance.*` nested frontmatter fields (Phase 7 gap category
"frontmatter structured-field corruption") are deliberately NOT detected
here — they're authored by an upstream, out-of-repo content-generation
system and structurally invisible to this repo's extractor (no `TextUnit`
is ever created for a dict-valued frontmatter field). See
`docs/architecture/frontmatter-field-ownership-boundary.md` for the full
reasoning and the upstream-team recommendation.

## Known duplication (not yet consolidated — read before adding a 6th copy)

"Completeness" is independently implemented **five times** with no shared
code: `src/translation_engine/validation/completeness_validator.py`
(pipeline, segment-map + length-ratio + trailing-URL),
`scripts/audit_translation_quality.py::score_completeness` (paragraph-count
ratio), `scripts/quality/audit_completeness.py` (prose-line-count ratio),
`scripts/quality/audit_all_content.py`'s overlapping checks
(`empty_body`/`table_row_corruption`/`code_fence_dropped`), and
`scripts/quality/surgical_retranslate.py::detect_all_corruption`. Language-ID
/ purity similarly exists as three independent detector implementations
(`FastTextDetector` — real ML, production; `LanguageConsistencyValidator` —
langdetect; VA-03's `LanguageDetectionCheck` — also langdetect) plus a
fourth, non-ML ASCII-ratio proxy inside `audit_all_content.py`'s
`check_purity()`. Consolidating these is out of scope for Phase 8 — noted
here so it isn't rediscovered as a surprise later.

**Dead frontmatter/SEO validators — not live, do not treat as coverage.**
`src/translation_engine/validation/frontmatter_protection_validator.py`
(`FrontmatterProtectionValidator`) and `frontmatter_integrity_validator.py`
(`FrontmatterIntegrityValidator`, the only code anywhere aware of a
`canonical` field) are fully implemented and unit-tested in isolation, but
**neither is ever instantiated in the live pipeline**.
`FrontmatterProtectionValidator` is only built by `ValidationSuite.from_config()`,
which the real pipeline never calls (`engine_builder.py` builds the suite via
the bare `ValidationSuite()` → `_create_default_validators()`, a hardcoded
list that excludes it); `FrontmatterIntegrityValidator(` has zero live call
sites at all. The actual live frontmatter-language check is a third,
independent implementation — `engine.py`'s `_check_frontmatter_language()`
(checks `title`/`description`/`seoTitle`/`summary` via langdetect, called
from `file_pipeline.py` and feeding `decision_engine.make_decision()`, which
genuinely can reject a write) — plus the relevant `GATE_REGISTRY` gates
(10, 11, 18, 24, 28, 33, 37, 40). `docs/plans/hugo-translator-shipping-gates.md`
previously listed `FrontmatterProtectionValidator` as "Enabled" based on it
existing in the codebase, not on it being wired in — corrected 2026-07-24.
Do not re-wire these two classes in without first confirming they wouldn't
just duplicate the coverage `_check_frontmatter_language`/the gates above
already provide live.
