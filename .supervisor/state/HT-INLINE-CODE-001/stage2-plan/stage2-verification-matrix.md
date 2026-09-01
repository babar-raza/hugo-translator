# Stage 2 — Verification Matrix (HT-INLINE-CODE-001), updated with real results

| Taskcard | Verification performed | Result |
|---|---|---|
| TC-ICR-001 | `pytest tests/unit/quality/test_inline_code_repair.py -v` | 13 passed |
| TC-ICR-002 | `pytest tests/unit/translation_engine/extractor/test_segment_extractor_global_preserve_baseline.py -v` | 10 passed (real config/global.yaml load, all 5 real site profiles) |
| TC-ICR-004 | `pytest tests/unit/quality/test_audit_all_content_inline_code.py` + 3 existing audit_all_content suites + `test_unit_quality_scorer.py` + unit_heal suites | 22 + 38 + 14 passed |
| TC-ICR-005 | `pytest tests/unit/translation_engine/test_write_gate_22_inline_code_tm_buffer.py` + full write_gate/registry-invariant suite (139 total) | 139 passed |
| TC-ICR-006 | **Real live GPU translation** via installed `translate-hugo` CLI, `kb.aspose.org/en/pdf/_index.md` -> fr, `--force-retranslate --validation-mode strict` | SUCCESS — all 13 real EN inline-code identifiers confirmed byte-identical in the translated output on disk |
| TC-ICR-007 | `pytest tests/unit/translation_engine/test_segment_translator.py` | 13 passed (no behavior change, new log line added) |
| TC-ICR-008 | `pytest tests/unit/quality/test_unit_heal_inline_code_dispatch.py` + existing unit_heal suites | 14 passed |
| TC-ICR-011 (code) | `pytest tests/unit/scripts/test_tm_surgical_cleanup_rule5_inline_code.py` + existing Rule-4 suite | 11 passed |
| TC-ICR-011 (backup) | `scripts/tm/backup_tm.py --output data/tm/backups/backup_pre_inline_code_repair.tar.gz --rotate 5` against the real 8.1GB `data/tm/l2.lmdb` | SUCCESS — 1.48GB backup + sha256 checksum on disk |
| TC-ICR-012 (dry-run) | `tm_surgical_cleanup.py --site products.aspose.org --dry-run --verbose` | 7 real `inline_code_span_translated` hits found among 49,786 scanned entries; 1 deep-verified (`Scene`/`Mesh`/`Camera` -> Hindi Devanagari script) by direct TM inspection |
| TC-ICR-012 (apply) | `tm_surgical_cleanup.py --site products.aspose.org --apply --max-changes 500` | 7/7 patches applied, 0 errors (plus 183 pre-existing Rule-1 identifier_translated fixes as a side effect of the same script) |
| TC-ICR-012 (post-apply re-scan) | Same dry-run re-run | 0 remaining hits, all 4 rules; entry count reconciled exactly (49,786 -> 49,786, no deletes occurred) |
| TC-ICR-012 (round-trip) | Direct TM query for all 7 patched entries by `metadata.remediation == "inline_code_repair_v1"` | 7/7 found, each showing the corrupted span replaced, surrounding text intact, original model metadata preserved alongside the new provenance stamp |
| TC-ICR-012 (integrity) | `scripts/tm/verify_tm_integrity.py --tm-dir data/tm` (explicit path — default resolves 2 directories too shallow, a pre-existing bug, disclosed below) | L2: ok, 1,150,560 entries |
| TC-ICR-012 (L3 health) | `scripts/tm/quick_validate_l3.py --index_path ./data/tm/l3_faiss` (`verify_tm_integrity.py`'s own L3 path default is also stale — looks for `l3_index`, real dir is `l3_faiss`, pre-existing, disclosed below) | 764,510 entries loaded successfully, correct structure |
| TC-ICR-012 (L3 rebuild) | `scripts/tm/build_l3_index.py --force --use_gpu` | IN PROGRESS at time of writing — full re-embed needed since L2's key is a source-text hash, unaffected by a patch, so L3's cached target-text metadata needs a real rebuild to reflect the 7 corrected translations |

## Pre-existing tooling bugs found and disclosed (not fixed — out of this mission's scope, flagged as follow-up)

- `scripts/tm/verify_tm_integrity.py`: `PROJECT_ROOT = Path(__file__).parent.parent` resolves to `scripts/`, not the repo root — its default `--tm-dir` is silently wrong. Worked around by passing `--tm-dir data/tm` explicitly.
- Same script's `_get_l3_stats()` looks for `tm_dir / "l3_index"`; the real, live directory is `l3_faiss` (confirmed via `quick_validate_l3.py` and the live canary translation's own startup log: "L3 index initialized: 764510 entries"). L3 health verified via `quick_validate_l3.py` instead.
