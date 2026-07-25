# Site Locale Allowlist Policy

**Version:** 1.0
**Last Updated:** 2026-07-25
**Scope:** Every Hugo Translator site profile

## The mechanism

Every site profile already declares its own `target_langs:` list. A
profile can additionally set:

```yaml
strict_locale_allowlist: true
```

When set, `target_langs` (plus the site's `default_source_lang`) becomes
that site's **exact, enforced locale allowlist** everywhere a target
locale can be determined — CLI overrides, the translation engine, the
orchestrator job queue, and quality-script directory auto-discovery all
reject or filter out any locale not in that set. Sites that leave the flag
unset (the default, `false`) keep today's lenient behavior unchanged: any
format-valid locale may be requested regardless of `target_langs`.

**This mechanism has zero knowledge of any specific site or brand.** The
single source of truth,
[`src/utils/locale_policy.py`](../../src/utils/locale_policy.py), operates
purely on whatever profile object it's given:

```python
def validate_requested_locales(site_profile, requested) -> None: ...  # raises on violation
def filter_to_allowed_locales(site_profile, candidates) -> list[str]: ...  # silently drops
```

Onboarding a new site to strict enforcement is a **pure config change** —
edit that site's profile YAML, nothing else:

```yaml
site_id: newsite.example.org
target_langs: [de, fr, ja]
strict_locale_allowlist: true
```

No code in `locale_policy.py`, `models.py`, `engine.py`, `cli.py`, or any
quality script needs to change for this to take effect.

## Enforcement layers

| Layer | File | Gated by the flag? |
|---|---|---|
| Translation engine | `src/translation_engine/engine.py` (`translate_file`), `src/translation_engine/directory_orchestrator.py` (`translate_directory`) | Yes — no-op for non-strict sites. This is the last-line safety net that also protects ad-hoc scripts and out-of-tree tooling that call the engine directly. |
| CLI | `src/cli.py` (`translate_site`) | Yes — `--target-langs` naming a disallowed locale for a strict site fails fast with a clear error and non-zero exit, before any work starts. |
| Quality scripts' directory auto-discovery | `scripts/quality/heal_english_headings.py`, `surgical_retranslate.py`, `delete_for_retranslate.py`, `backfill_frontmatter_ids.py` | Yes — each fetches the site's live profile via `ConfigService` and calls the generic functions; behavior is a no-op unless that site's profile has the flag set. |
| Orchestrator job queue | `src/workers/job_processor.py` (`process_job`) | **No — universal.** A job's `target_langs` snapshot (possibly frozen before the site's profile changed) is always re-filtered to the *live* `target_langs`, for every site. This isn't a new restriction: the main automated pipeline already only ever iterates whatever `target_langs` it was given — this just stops a stale snapshot from disagreeing with the current profile. |
| Contamination-scan queuing | `src/workers/autonomous_content_translation_worker.py` (`_run_post_contamination_scan`) | **No — universal**, same reasoning as above: never queue retranslation work for a locale a site doesn't currently declare. |

## Adding or removing a locale for any site

1. Edit `target_langs:` in that site's profile YAML
   (`config/site_profiles/<site_id>.yaml`).
2. If turning strict enforcement on/off, add or remove
   `strict_locale_allowlist: true`.
3. If retiring a locale with an active retry queue, run
   `scripts/ops/archive_retired_locale_queue_entries.py --apply` — it's
   site-agnostic: it archives any queue entry whose locale isn't in its
   site's *current* `target_langs`, for any site, automatically.
4. Run `pytest tests/unit/config/test_strict_locale_allowlist_policy.py` —
   the generic-mechanism test suite (uses synthetic, non-Aspose profiles,
   so it stays valid regardless of which real site you changed).

## Validators that prove the mechanism is generic

- `tests/unit/config/test_strict_locale_allowlist_policy.py` — the core
  proof: entirely synthetic, non-Aspose site profiles exercising every
  behavior (strict accepts/rejects, lenient no-op, two independent strict
  sites not interfering with each other, default-flag lenience). Also
  asserts `src/utils/locale_policy.py`'s source contains zero references
  to "aspose" anywhere.
- `tests/integration/test_cli_aspose_org_locale_rejection.py` — despite
  the filename, its fixtures are two from-scratch synthetic sites (one
  strict, one lenient, neither Aspose-named) proving CLI rejection
  activates purely via the config flag.

## Aspose.org's own policy

Aspose.org is simply the first adopter of this mechanism — its exact
25-target-locale contract is *data*, not special-cased logic. See
[`ASPOSE_ORG_LOCALE_POLICY.md`](ASPOSE_ORG_LOCALE_POLICY.md) for that data
and the business context behind it.

## Relationship to the global language catalog

Hugo Translator's underlying language/model catalog
([`config/target_languages.yaml`](../../config/target_languages.yaml),
documented in [`SUPPORTED_LANGUAGES.md`](SUPPORTED_LANGUAGES.md)) describes
what the system is *capable* of — which MT models exist, what's been
benchmarked. It remains unrestricted and is unaffected by any site's
`strict_locale_allowlist` setting. A site's `target_langs` is always a
subset of that catalog; `strict_locale_allowlist` only controls whether
that subset is enforced as a hard boundary for that specific site.
