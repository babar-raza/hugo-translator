# Family-Aware Translator Scope

> **Regression note:** Subdomain is not product family. Multi-family subdomains must be
> partitioned by family before translation and metrics emission.
> `product_family_token = "total"` is only valid when `family_scope: total` is explicitly
> set in the profile. Unknown family MUST resolve to `"unknown"`, not `"total"`.

---

## Background

The translator processes content across subdomains like `products`, `docs`, `kb`, `reference`,
and `blog`. Each subdomain may cover many product families (Words, Cells, Font, PDF, etc.).

Previously, when no family token was found in the content root path, `ScopeResolver`
silently fell back to `product_family_token = "total"` and emitted `product = "Aspose.Total"`.
This masked mixed-family runs as umbrella product runs.

---

## Website Structure Matrix

| website | subdomain | path convention | family location | multi-family? |
|---------|-----------|----------------|-----------------|---------------|
| aspose.org | products | `en/{family}/{platform}/` | path[1] after en/ | yes |
| aspose.org | docs | `en/{family}/` | path[1] after en/ | yes |
| aspose.org | kb | `en/{family}/` | path[1] after en/ | yes |
| aspose.org | blog | `en/{family}/` | path[1] after en/ | yes |
| aspose.org | reference | `en/{family}/` | path[1] after en/ | yes |
| aspose.net | products | `{family}/{lang}/` | path[0] at root | yes |
| aspose.net | kb | `{family}/{lang}/` | path[0] at root | yes |
| aspose.net | reference | `{family}/{lang}/` | path[0] at root | yes (when not family-split) |
| aspose.net | docs | `{family}/{lang}/` | path[0] at root | yes (when not family-split) |
| aspose.net | blog | flat filename-locale | none | no (blog-only) |

---

## Product Family Resolution Precedence

From strongest to weakest:

1. **CLI override** — `--product-family=words` wins all
2. **Per-file path** — `ScopeInput.file_path` → `extract_family_from_path()`
3. **Content root path** — scan `content_root_id` segments for known family tokens
4. **Profile filename** — scan filename parts (e.g. `docs.aspose.net.words.yaml` → `words`)
5. **`family_scope: total`** — explicit profile declaration (only legitimate path to Total)
6. **`metrics_hints.product_family`** — weak hint (cannot override to `total` without auth)
7. **None → `"unknown"`** — fail-closed; never falls back to `"total"`

---

## Profile `family_scope` Field

Add to site profile YAML:

```yaml
# Single product family — no partitioning needed
family_scope: single

# Multiple product families — triggers per-family translation batching
family_scope: multi

# Explicitly Aspose.Total umbrella scope
family_scope: total

# (omitted) — auto-detect from path
```

**Rules:**
- `family_scope: total` is the **only** way to legitimately emit `Aspose.Total`
- `family_scope: multi` triggers per-family batching in the worker
- Without `family_scope`, multi-family detection is auto via `discover_family_subdirs()`

---

## Family Extraction Module

`src/observability/family_extraction.py`

```python
# Extract family from a file path (handles both conventions)
family = extract_family_from_path("en/words/intro.md", known_families)  # → "words"
family = extract_family_from_path("words/en/intro.md", known_families)  # → "words"
family = extract_family_from_path("en/unknown/intro.md", known_families)  # → None

# Discover family subdirs in a content root
dirs = discover_family_subdirs(Path("/content/products.aspose.org"), known_families)
# → [("cells", Path(".../en/cells")), ("font", Path(".../en/font")), ...]

# Quick multi-family check
is_multi = is_multi_family(Path("/content/products.aspose.org"), known_families)
# → True
```

---

## Worker Task Partitioning

`autonomous_content_translation_worker._expand_family_content_roots()`

When a content root is multi-family, the worker expands it into per-family sub-roots
before calling `_translate_content_root()`. Each sub-root gets its own `MetricsRunContext`.

```
products.aspose.org  →  [en/cells, en/font, en/words, en/pdf, ...]
                              ↓           ↓          ↓
                     MetricsRunContext MetricsRunContext MetricsRunContext
                     (Aspose.Cells)   (Aspose.Font)   (Aspose.Words)
```

---

## Adding a New Site Profile

For a **single-family** profile:
```yaml
site_id: docs.aspose.net.words
family_scope: single  # or omit — auto-detects single family in path
content_roots:
- ${ASPOSE_NET_CONTENT}/docs.aspose.net/words
```

For a **multi-family** profile:
```yaml
site_id: products.aspose.org
family_scope: multi
content_roots:
- ${ASPOSE_ORG_CONTENT}/products.aspose.org
```

For an **explicit Total** profile (rare — only for umbrella pages):
```yaml
site_id: products.aspose.org.total
family_scope: total
content_roots:
- ${ASPOSE_ORG_CONTENT}/products.aspose.org/en/total
```

---

## What NOT to Do

- **Do not** add `metrics_hints: {product_family: total}` as a workaround — this is blocked
  and logged as a warning unless `family_scope: total` is also set.
- **Do not** hardcode family tokens in content_root without understanding path conventions.
- **Do not** assume `product_family_token == "unknown"` is an error — it is expected for
  multi-family content roots at the profile level (before runtime partitioning).

---

## Evidence Requirements for Future Changes

Any change to family extraction or scope resolution must include:
1. Updated unit tests in `tests/unit/observability/test_family_extraction.py`
2. Updated unit tests in `tests/unit/observability/test_metrics_scope.py`
3. Scope audit passing: `python -m src.observability.metrics_scope --audit`
4. Proof that `products.aspose.org` does NOT emit `Aspose.Total` for mixed-family files
5. Proof that a `family_scope: total` profile still emits `Aspose.Total` correctly
