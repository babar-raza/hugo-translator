# Frontmatter field ownership boundary: `evidence.*` and `provenance.*`

> HT-QUALITY-GATES-001 Phase 8 (Tier D #9). Scope note, not an implementation
> task — this documents a deliberate "will not build" decision and who
> should build it instead, so it isn't rediscovered as a surprise gap in a
> future investigation.

## The finding

The Phase 7 reconnaissance (artifact `26178f4f`) catalogued "frontmatter
structured-field corruption (`evidence.*`)" as a defect category with "no
detector anywhere, at any scale." A deep-dive into this repo's extractor and
gate code (HT-QUALITY-GATES-001 Phase 8) confirms this is **correct, and
correctly out of scope for a hugo-translator detector** — not an oversight.

## Why hugo-translator cannot detect this

`evidence.*` and `provenance.*` are nested YAML frontmatter blocks authored
by an **upstream, out-of-repo content-generation pipeline**, visible in a
real EN source fixture carried in this repo's golden corpus:
`tests/golden_corpus/wave3/description_truncation/en_cells_features_source.md`,
whose frontmatter includes a full `provenance:` block (`content_origin`,
`last_mechanism`, `content_created_at`, `content_hash: 431fa1e9...`) and an
`evidence:` block (`model_sha`, `model_version`, `claims`, `apis`). No code
in `src/` writes either block — confirmed by a repo-wide search for any
assignment into `frontmatter["evidence"]` or `frontmatter["provenance"]`.

This isn't a missing feature; it's structural. `TextUnitExtractor.
_extract_frontmatter_units()` (`src/translation_engine/extractor/
text_unit_extractor.py`) only produces a `TextUnit` for a frontmatter value
when it's a `str` or a `list[str]`. A nested **dict**-valued field like
`evidence:` or `provenance:` matches neither branch, so **no unit is ever
created for it** — the translate/reconstruct pipeline is architecturally
blind to it, and `ASTRenderer._apply_frontmatter_translations()` never
mutates a key it was never given a unit for. The field is carried through
byte-for-byte, untouched, by construction. Gate 31's own docstring in
`write_gate.py` independently confirms this is a deliberate, known
exclusion ("scanning the whole block false-positived on deliberately-
untranslated metadata... `evidence.*` fields that legitimately stay in
English by site-profile design").

`provenance.content_hash` specifically is the one exception with a reader:
`write_gate.py`'s Gate 32 (`_gate_content_hash_staleness`) reads it (source
vs. this-file's-own translation) as a diagnostic staleness signal. But
"read the value" and "own/produce the value" are different things — Gate 32
still has no writer for the field, and the gate's own comment treats a
source lacking `provenance` entirely as a normal no-op case.

## What would be needed to detect corruption here

A detector for `evidence.*`/`provenance.*` corruption needs to understand
the **semantics** of that upstream system's own schema (what `claims`/`apis`
are supposed to contain, what a "corrupted" `model_sha` looks like, what
invariants `content_hash` must satisfy relative to the content it hashes).
None of that is knowable from inside hugo-translator, which only ever sees
these fields as an opaque, passed-through blob. Building a real check
requires either:

1. A detector living in the upstream content-generation system itself
   (where the schema and its invariants are actually defined), or
2. hugo-translator being handed a formal schema/contract for these fields
   by that system, at which point a structural validator here becomes
   possible — but that's a scope expansion requiring the upstream team's
   involvement, not a unilateral addition.

## Disposition

**Not building this in hugo-translator.** Recommendation: flag to whichever
team owns the upstream content-generation pipeline that produces
`evidence:`/`provenance:` blocks, so a corruption check (if warranted) is
built where the schema is actually understood. If that team defines a
contract hugo-translator can validate against, revisit as a new taskcard —
this note is the record of why it wasn't attempted blind.

See also `scripts/quality/AUDIT_MANIFEST.md` for the full disposition of
every other Phase 7 gap category.
