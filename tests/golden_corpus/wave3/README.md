# Wave-3 golden corpus (TC-HT-010)

Real damaged/parent pairs extracted from the aspose.org git history (the
consuming repo), documenting the three wave-3 corruption classes this
mission (HT-PRODUCER-FIX-001) closes. Extracted read-only via `git show`
on 2026-07-14; not fetched at test time (host-path-dependent, would break
CI portability).

## description_truncation/

Multi-line YAML `description:` scalar truncated to its first physical
line with an unterminated single-quoted scalar — root cause of TC-HT-001.

```
git -C d:/onedrive/Documents/GitHub/aspose.org show 6812d020fb:content/docs.aspose.org/bg/cells/net/developer-guide/features.md
git -C d:/onedrive/Documents/GitHub/aspose.org show 6812d020fb^:content/docs.aspose.org/bg/cells/net/developer-guide/features.md
```

- `bg_cells_features_damaged.md` — `description: 'Overview of all major capabilities in Aspose.Cells FOSS for .NET: workbook` (unterminated, swallows `weight: 10`)
- `bg_cells_features_parent.md` — full Bulgarian translation, properly closed quote
- `en_cells_features_source.md` — the TRUE English source (fetched separately,
  `git show 6812d020fb:content/docs.aspose.org/en/cells/net/developer-guide/features.md`)
  confirming the exact mechanism: a genuinely 3-physical-line single-quoted
  YAML scalar. The old buggy regex (`re.search(r"^(description:\s*.+)$", en_content,
  re.MULTILINE)`) captured only line 1 — exactly what appears truncated in
  the damaged BG file.

## title_prompt_leak/

LLM system-prompt rules text leaked verbatim (translated) into
frontmatter — root cause of TC-HT-003 (wave-3 TITLE_MISMATCH).

```
git -C d:/onedrive/Documents/GitHub/aspose.org show 2ef1def182:content/reference.aspose.org/es/pdf/net/Do.md
git -C d:/onedrive/Documents/GitHub/aspose.org show 2ef1def182^:content/reference.aspose.org/es/pdf/net/Do.md
```

- `es_pdf_do_damaged.md` — `linkTitle: Do` followed by ~10 lines of translated prompt-rule bullets ("Salida SÓLO la traducción...")
- `es_pdf_do_parent.md` — **also corrupted** (`linkTitle: 'Reglas:` followed by
  the same leaked bullets) — the leak predates commit `2ef1def182`; that
  commit only changed which mangled form shipped (`'Reglas:` → `Do`). Real
  finding, kept as-is rather than re-fetched further back: demonstrates the
  leak was a persistent, repeated failure mode, not a one-off. The
  "genuinely clean" negative-control case in the tests uses synthetic
  content instead, since no clean revision of this specific file was
  captured in this corpus.

## fence_strip/

Code fences silently dropped — root cause of TC-HT-005 (Gate 26).

```
git -C d:/onedrive/Documents/GitHub/aspose.org show 2ef1def182:content/reference.aspose.org/ja/slides/java/presentation.md
git -C d:/onedrive/Documents/GitHub/aspose.org show 2ef1def182^:content/reference.aspose.org/ja/slides/java/presentation.md
```

- `ja_slides_presentation_damaged.md` — 0 code-fence lines
- `ja_slides_presentation_parent.md` — 16 code-fence lines (8 code blocks)

Identified via a diff scan of commit `2ef1def182` for reference.aspose.org
files with net fence-line loss (`git show 2ef1def182 --unified=0 -- content/reference.aspose.org/`,
counting `-\`\`\`` vs `+\`\`\`` lines per file). This was the largest loss
(16 lines) among many candidates in that commit.

## Adversarial resurrection test

`test_adversarial_resurrection.py` reconstructs the OLD, buggy
`_fix_description_hallucination` (deleted in TC-HT-001) from git history
and asserts the new Gate 26/27 (TC-HT-005) + `safe_io.save()` (TC-HT-002)
block its output on the `description_truncation` pair — proving the gates
catch this corruption class independently of the code-level fix.
