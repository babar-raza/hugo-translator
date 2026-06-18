# ADR-004: Translation Engine God-Class Decomposition

**Status:** Accepted  
**Date:** 2026-06-17 (documented retroactively; change implemented in commit `0a684b8`)  
**Last Updated:** 2026-06-17

---

## Context

The `TranslationEngine` class in `src/translation_engine/engine.py` accumulated all translation orchestration logic into a single monolithic class (~3000+ lines). This created:

- High coupling between construction, file processing, segment translation, and output gating
- Difficulty testing individual responsibilities in isolation
- Long method chains that were hard to follow and debug
- No clean interfaces between the main pipeline stages

## Decision

Decompose `TranslationEngine` into five collaborating components with single responsibilities:

| Component | File | Responsibility |
|-----------|------|---------------|
| `TranslationEngine` | `engine.py` | Entry point; delegates to specialists |
| `EngineBuilder` | `engine_builder.py` | Engine construction: TM, models, validators, config |
| `FileTranslationPipeline` | `file_pipeline.py` | Per-file retry, pipeline, language context |
| `SegmentTranslator` | `segment_translator.py` | Segment-level translation: TM lookup, model call, validation |
| `WriteGateEvaluator` | `write_gate.py` | Output safety gate: accept/reject/reroute |

## Consequences

**Positive:**
- Each component is independently testable
- Construction logic is isolated from runtime logic
- Segment-level decisions are encapsulated in one place
- Output safety decisions have a single authority

**Negative:**
- Existing integration tests required updates to mock at component boundaries
- Pre-existing callers of `TranslationEngine` were unchanged (public API preserved)

## Implementation Reference

- Commit: `0a684b8` — `refactor(engine): decompose TranslationEngine god-class into 5 components`
- Files: `src/translation_engine/{engine,engine_builder,file_pipeline,segment_translator,write_gate}.py`

## Related

- [Translation Engine Architecture](../architecture/translation-engine.md)
