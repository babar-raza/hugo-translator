# Controlled full-corpus comparison

Method: for each translated file, read the body once, execute the historical
`check_purity` and `check_duplicate_content` functions extracted directly from
`git show HEAD:scripts/quality/audit_all_content.py`, then execute the current
working-tree functions on that same in-memory body. The machine-readable
per-site/per-locale result and every delta path are in
`corpus-comparison.json`.

| Check | Historical | Current | Old-only | New-only |
| --- | ---: | ---: | ---: | ---: |
| duplicate_content | 62 | 52 | 10 | 0 |
| purity_issue | 3,313 | 3,284 | 36 | 7 |

The 10 duplicate old-only findings are resolved false positives in code
regions (no new duplicate finding). The 36 purity old-only findings are
resolved code-region false positives. The seven purity new-only findings are
all confirmed dropped/misplaced-fence defects, documented in
`manual-purity-dispositions.md`.

The run covered 136,689 translated files in 524.9 seconds. It used the live
resolved config hash `05e97236319b884ab096bdd28339accd20cd69402b17dd8d199da99c7b341d63`.
The content roots and Git SHAs (where available) are in the JSON artifact.
Dirty status is explicitly `not_collected`: two bounded attempts to run a
full `git status --porcelain` across the live content checkout failed to
complete promptly. This limits rerun provenance only; it does not affect the
same-read old-vs-new comparison.
