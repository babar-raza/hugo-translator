# Stage 2 — Evidence Contract (HT-INLINE-CODE-001)

Every taskcard's CLOSED status traces to one of:
1. Real pytest output captured verbatim (not paraphrased).
2. A real before/after file diff (content or TM entry).
3. Direct filesystem/TM/git inspection with the inspected paths/keys recorded.

## Evidence recorded so far this execution pass

- TC-ICR-001: `stage3-execution/evidence/TC-ICR-001-pytest.txt` — 13 passed.
- TC-ICR-002: 7 passed (real config/global.yaml + monkeypatched throwaway-pattern proofs), all 5 site profiles confirmed via `ConfigService.get_site_profile()` + real `SegmentExtractor` construction — no mocked config.
- TC-ICR-003: 10 passed, including a parametrized test loading the REAL `config/` tree for all 5 site profiles (reference/docs/kb/products/blog) and asserting each resolves the shared inline-code pattern.
- TC-ICR-004: 22 (audit_all_content) + 38 (UnitQualityScorer) + 110 (write_gate full suite) passed.
- TC-ICR-005: 5 new tests + 139 full write_gate/registry-invariant suite passed.
- TC-ICR-006: **real, live GPU-model translation** of `kb.aspose.org/en/pdf/_index.md` -> `fr` via the installed `translate-hugo` CLI entry point, `--force-retranslate`, `--validation-mode strict`. All 13 real EN inline-code identifiers (`Document`, `Page`, `EncryptionOptions`, `Form`, `TextBoxField`, `CheckboxField`, `RadioButtonField`, `Table`, `Row`, `Cell`, `BorderInfo`, `OutlineItemCollection`, `DestinationXYZ`) confirmed present verbatim in the real translated output on disk post-translation. Full CLI log saved at `stage3-execution/evidence/TC-ICR-006-kb-canary-translate.log`.
- TC-ICR-007: 13 passed (segment_translator full suite, unchanged behavior + new log line).
- TC-ICR-008: 14 passed (dispatch tests + existing unit_heal regression suites).
- TC-ICR-011 (code): 11 passed (Rule 5 detection + fake-TM apply proving span-only patch + metadata provenance stamping, dry-run no-op proof).
- TC-ICR-011 (backup): real `scripts/tm/backup_tm.py` run against the actual 8.1GB production `data/tm/l2.lmdb` — `data/tm/backups/backup_pre_inline_code_repair.tar.gz` (1.48GB) + sha256 checksum, both on disk, checksum copied to `stage3-execution/evidence/TC-ICR-011-tm-backup.sha256`.

## Known limitations disclosed, not hidden

- The full 5-site content-remediation rollout (TC-ICR-009 Stage 2/3) and full-TM apply across all sites (TC-ICR-012) are staged, long-running operations against tens of thousands of real files / an 8.1GB TM — this execution pass proves the mechanism end-to-end on real production data at canary scale and documents the exact commands to continue the staged rollout; it does not claim the full corpus is healed within this session's wall-clock budget.
- 3 pre-existing test failures were found unrelated to this mission (confirmed via `git stash` bisection before any of this session's changes existed): `test_kb_verify_allows_translated_keyword_list_items`, `test_verify_pair_rejects_material_evidence_drift`, `test_code_block_repair_restores_source_blocks_inside_translatable_fields`. Not claimed as fixed; not caused by this mission.
- `tests/unit/test_audit_script.py` has a pre-existing collection error (`ModuleNotFoundError: scripts.audit_codebase`) unrelated to this mission.
