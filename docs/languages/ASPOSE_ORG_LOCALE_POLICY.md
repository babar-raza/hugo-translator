# Aspose.org Locale Policy

**Version:** 2.0
**Last Updated:** 2026-07-25
**Scope:** Aspose.org site profiles only

This document is Aspose.org's own locale-set decision — *data* fed into
the generic, site-agnostic enforcement mechanism described in
[`SITE_LOCALE_ALLOWLIST_POLICY.md`](SITE_LOCALE_ALLOWLIST_POLICY.md). Read
that doc first for how the mechanism itself works; this doc only states
what Aspose.org has configured.

## The contract

Every Aspose.org site profile resolves to exactly **26 locales**: the
`en` source language plus these 25 target languages:

```
ar cs de el es fa fr he hi hu id it ja ko nl pl pt ro ru sv th tr uk vi zh
```

This is the *only* locale set Hugo Translator actively translates,
retranslates, refreshes, or otherwise maintains for an Aspose.org site.
Each of the 7 Aspose.org profiles declares this exact `target_langs:` list
plus `strict_locale_allowlist: true`:

```
config/site_profiles/docs.aspose.org.yaml
config/site_profiles/kb.aspose.org.yaml
config/site_profiles/products.aspose.org.yaml
config/site_profiles/reference.aspose.org.yaml
config/site_profiles/blog.aspose.org.yaml
config/site_profiles/websites.aspose.org.yaml
config/site_profiles/www.aspose.org.yaml
```

There is nothing Aspose.org-specific in the code that enforces this — the
same generic mechanism applies to any site with the flag set. See the
enforcement-layers table in
[`SITE_LOCALE_ALLOWLIST_POLICY.md`](SITE_LOCALE_ALLOWLIST_POLICY.md).

## Retired locales

11 locales were previously active for Aspose.org and are now retired:
`bg, ca, da, fi, hr, lt, lv, ms, no, sk, sr`.

**Existing translated content in these locales is preserved on disk and
in the deployed site.** Nothing was deleted. Hugo Translator simply stops
generating, retranslating, refreshing, or repairing content in these
locales for Aspose.org going forward. Old retry-queue entries for these
locales were archived (not deleted) to
`data/retranslate_queue_archive_stale_locales.jsonl` — see
`scripts/ops/archive_retired_locale_queue_entries.py` (a site-agnostic
tool: it archives whatever a site currently no longer lists in
`target_langs`, not a hardcoded Aspose.org list).

## Changing Aspose.org's locale set

1. Edit `target_langs:` in all 7 `config/site_profiles/*.aspose.org.yaml`
   files to match — this repo has no inheritance mechanism, so each file
   is edited independently.
2. If retiring a locale with an active retry queue, run
   `scripts/ops/archive_retired_locale_queue_entries.py --apply`.
3. Run `pytest tests/unit/config/test_aspose_org_locale_contract.py` — a
   thin snapshot test asserting the exact 25-code set and
   `strict_locale_allowlist: true` on all 7 profiles; it fails loudly on
   drift.

## Tests

- `tests/unit/config/test_aspose_org_locale_contract.py` — Aspose.org's
  own data snapshot (this file's content, effectively).
- `tests/unit/config/test_strict_locale_allowlist_policy.py` — the
  generic mechanism, proven with synthetic non-Aspose profiles (see the
  other doc).
- `tests/unit/quality/test_aspose_org_locale_discovery_filters.py` —
  proves the 4 Aspose.org quality scripts' directory auto-discovery never
  picks up a retired locale, and that `delete_for_retranslate.py` never
  deletes retired-locale content.
- `tests/integration/test_cli_aspose_org_locale_rejection.py` — CLI
  rejection, via synthetic (non-Aspose) strict/lenient fixtures.
- `tests/unit/workers/test_job_processor_stale_target_langs.py` — proves
  a stale/resumed job can't resurrect a locale outside a site's current
  `target_langs` (generic, applies to any site).
