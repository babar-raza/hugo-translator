"""TC-APT-010 (GATE-PROMO-001): validate the 13 unvalidated write gates (plan section 12,
Gate 3) against a stratified known-good real-content sample plus a targeted adversarial
fixture per gate, three independent runs, before any registry promotion decision.

Context that makes this more than a formality: ``write_gate.py``'s ``_run_content_gates``
(the real production dispatch, confirmed by direct read) already runs gates 31-35/37-44
against their OWN independent result object under ``validation_policy: zero-defect`` and
flips the overall write to failed on ANY of them, regardless of the registry's literal
"warn" action -- unlike the non-zero-defect path, where a warn-tier gate's verdict is
run against a disposable result and can never block. **Every zero-defect campaign write
today -- including this qualification run -- is already silently gated by these 13
detectors.** A false positive here does not wait for a future registry edit to start
blocking real content; it is blocking real content right now. That is what this script
checks, not a formality before some later flip.

Two independent checks per gate:
  * **Sensitivity** (the adversarial fixture): does the gate actually fire on content
    built to trigger it? A gate that never fires would pass a false-positive check
    vacuously.
  * **Specificity** (the known-good sample + explicit negative fixtures): does the gate
    stay quiet on real, legitimate content, including the exact false-positive shapes
    each gate's own docstring calls out as a risk (".NET Framework", a correctly
    preserved brand token, a coincidental unrelated digit run)?

Run 3x and diff: these are all pure static-text checks (no LLM call, no randomness), so
byte-identical results across runs is the reproducibility bar TC-APT-023 established
generally and this taskcard names specifically for gate 36 (that one IS LLM-backed and is
evaluated separately, see gate_promotion_fidelity_shadow.py).
"""

from __future__ import annotations

import argparse
import json
import random
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from src.translation_engine.write_gate import WriteGateEvaluator  # noqa: E402
from src.utils.config_loader import ConfigService  # noqa: E402
from src.utils.content_discovery import discover_source_files, resolve_translated_path  # noqa: E402

UNVALIDATED_GATE_IDS = [31, 32, 33, 34, 35, 37, 38, 39, 40, 41, 42, 43, 44]
IN_SCOPE_SITES = [
    "blog.aspose.org",
    "docs.aspose.org",
    "kb.aspose.org",
    "products.aspose.org",
    "reference.aspose.org",
    "websites.aspose.org",
]


def build_evaluator() -> WriteGateEvaluator:
    detector = None
    try:
        from src.translation_engine.language_detection.fasttext_detector import FastTextDetector

        detector = FastTextDetector(
            cache_dir=_PROJECT_ROOT / "data" / "models" / "fasttext", auto_download=False
        )
        if detector._model is None and not detector._langdetect_available:
            detector = None
    except Exception:
        detector = None
    return WriteGateEvaluator(
        detector=detector, similarity_tracker=None, config=ConfigService(_PROJECT_ROOT / "config"),
        force_accept=True,
    )


# ---------------------------------------------------------------------------
# Adversarial + negative fixtures: one pair per gate, built directly from the
# gate's own source (read in full before writing these, not guessed).
# ---------------------------------------------------------------------------


def _page(frontmatter: dict[str, Any], body: str) -> str:
    import yaml

    fm = yaml.dump(frontmatter, sort_keys=False, allow_unicode=True, default_flow_style=False)
    return f"---\n{fm}---\n\n{body}\n"


FIXTURES: list[dict[str, Any]] = [
    # Gate 31: partial script contamination -- a Romance/Germanic function word
    # embedded in an otherwise non-Latin-script translation.
    {
        "gate_id": 31,
        "name": "adversarial",
        "locale": "he",
        "source": _page({"title": "Column Info"}, "## Overview\n\nThe ColumnInfo class exposes column width."),
        "translated": _page(
            {"title": "מידע על עמודה"},
            "## סקירה כללית\n\nהמחלקה ColumnInfo חושפת las propiedades de עמודה.",
        ),
    },
    {
        "gate_id": 31,
        "name": "known_good_dotnet_framework",
        "locale": "he",
        "source": _page({"title": "Column Info"}, "## Overview\n\nBuilt on the .NET Framework runtime."),
        "translated": _page(
            {"title": "מידע על עמודה"}, "## סקירה כללית\n\nבנוי על זמן הריצה של .NET Framework."
        ),
    },
    # Gate 32: content-hash staleness -- provenance.content_hash mismatch.
    {
        "gate_id": 32,
        "name": "adversarial",
        "locale": "de",
        "source": _page(
            {"title": "Document", "provenance": {"content_hash": "abc123newhash"}},
            "## Overview\n\n2 methods and 13 properties.",
        ),
        "translated": _page(
            {"title": "Dokument", "provenance": {"content_hash": "zzz999stalehash"}},
            "## Uebersicht\n\n3 Methoden und 1 Eigenschaft.",
        ),
    },
    {
        "gate_id": 32,
        "name": "known_good_matching_hash",
        "locale": "de",
        "source": _page(
            {"title": "Document", "provenance": {"content_hash": "abc123samehash"}},
            "## Overview\n\n2 methods and 13 properties.",
        ),
        "translated": _page(
            {"title": "Dokument", "provenance": {"content_hash": "abc123samehash"}},
            "## Uebersicht\n\n2 Methoden und 13 Eigenschaften.",
        ),
    },
    # Gate 33: brand token missing from a translated title that had it in EN.
    {
        "gate_id": 33,
        "name": "adversarial",
        "locale": "ar",
        "source": _page({"title": "Aspose.3D for Java"}, "## Overview\n\nBody text."),
        "translated": _page({"title": "أفترض ثلاثي الأبعاد لجافا"}, "## نظرة عامة\n\nنص أساسي."),
    },
    {
        "gate_id": 33,
        "name": "known_good_brand_preserved",
        "locale": "ar",
        "source": _page({"title": "Aspose.3D for Java"}, "## Overview\n\nBody text."),
        "translated": _page({"title": "Aspose.3D لجافا"}, "## نظرة عامة\n\nنص أساسي."),
    },
    # Gate 34: heading deficit -- translation has fewer ## sections than source.
    {
        "gate_id": 34,
        "name": "adversarial",
        "locale": "fr",
        "source": _page(
            {"title": "T"}, "## Intro\n\nText.\n\n## Usage\n\nText.\n\n## See Also\n\nText."
        ),
        "translated": _page({"title": "T"}, "## Intro\n\nTexte.\n\n## Utilisation\n\nTexte."),
    },
    {
        "gate_id": 34,
        "name": "known_good_same_count",
        "locale": "fr",
        "source": _page({"title": "T"}, "## Intro\n\nText.\n\n## Usage\n\nText."),
        "translated": _page({"title": "T"}, "## Intro\n\nTexte.\n\n## Utilisation\n\nTexte."),
    },
    # Gate 35: dropped trailing link -- source's last section is link-only and
    # none of its URLs survive translation.
    {
        "gate_id": 35,
        "name": "adversarial",
        "locale": "ja",
        "source": _page(
            {"title": "T"},
            "## Overview\n\nText.\n\n## See Also\n\n"
            "[Developer Guide](https://docs.aspose.org/x/) | "
            "[API Reference](https://reference.aspose.org/x/)",
        ),
        "translated": _page({"title": "T"}, "## 概要\n\nテキスト。"),
    },
    {
        "gate_id": 35,
        "name": "known_good_link_survives",
        "locale": "ja",
        "source": _page(
            {"title": "T"},
            "## Overview\n\nText.\n\n## See Also\n\n[Developer Guide](https://docs.aspose.org/x/)",
        ),
        "translated": _page(
            {"title": "T"}, "## 概要\n\nテキスト。\n\n## 関連項目\n\n[開発者ガイド](https://docs.aspose.org/x/)"
        ),
    },
    # Gate 37: TM collision -- description names a different bare identifier
    # than the file's own single-identifier title.
    {
        "gate_id": 37,
        "name": "adversarial",
        "locale": "de",
        "source": _page(
            {"title": "ColumnInfo", "description": "`ColumnInfo` exposes column width."},
            "## Overview\n\nText.",
        ),
        "translated": _page(
            {"title": "ColumnInfo", "description": "`RowInfo` stellt die Zeilenbreite dar."},
            "## Uebersicht\n\nText.",
        ),
    },
    {
        "gate_id": 37,
        "name": "known_good_matching_identifier",
        "locale": "de",
        "source": _page(
            {"title": "ColumnInfo", "description": "`ColumnInfo` exposes column width."},
            "## Overview\n\nText.",
        ),
        "translated": _page(
            {"title": "ColumnInfo", "description": "`ColumnInfo` stellt die Spaltenbreite dar."},
            "## Uebersicht\n\nText.",
        ),
    },
    # Gate 38: prose-before-code dropped -- source has a >=20-char lead-in
    # immediately before a fence; translation's lead-in for the same
    # positional fence is <5 chars. The segment "immediately before the
    # fence" includes any heading text in it too (split_fenced_segments has
    # no heading-boundary awareness) -- a heading alone is already >=5
    # chars, so the translated lead-in must have (next to) no heading text
    # either, not just a dropped paragraph.
    {
        "gate_id": 38,
        "name": "adversarial",
        "locale": "es",
        "source": _page(
            {"title": "T"},
            "## Usage\n\nCreate the document and load it as shown in the example below.\n\n"
            "```python\ndoc = Document('sample.docx')\n```\n",
        ),
        "translated": _page({"title": "T"}, "x\n\n```python\ndoc = Document('sample.docx')\n```\n"),
    },
    {
        "gate_id": 38,
        "name": "known_good_lead_in_kept",
        "locale": "es",
        "source": _page(
            {"title": "T"},
            "## Usage\n\nCreate the document and load it as shown in the example below.\n\n"
            "```python\ndoc = Document('sample.docx')\n```\n",
        ),
        "translated": _page(
            {"title": "T"},
            "## Uso\n\nCree el documento y cargelo como se muestra en el ejemplo.\n\n"
            "```python\ndoc = Document('sample.docx')\n```\n",
        ),
    },
    # Gate 39: dash-range collapse -- "18-22" becomes the fused digit run "1822".
    {
        "gate_id": 39,
        "name": "adversarial",
        "locale": "pt",
        "source": _page({"title": "T"}, "## Versions\n\nSupported in versions 18-22 of the API."),
        "translated": _page({"title": "T"}, "## Versoes\n\nSuportado nas versoes 1822 da API."),
    },
    {
        "gate_id": 39,
        "name": "known_good_unrelated_digit_run",
        "locale": "pt",
        # The range survives intact AND an unrelated coincidental "1822" (a
        # product code) also appears -- must not flag (gate's own guard).
        "source": _page(
            {"title": "T"}, "## Versions\n\nSupported in versions 18-22, product code 1822."
        ),
        "translated": _page(
            {"title": "T"}, "## Versoes\n\nSuportado nas versoes 18-22, codigo do produto 1822."
        ),
    },
    # Gate 40: SEO metadata corruption -- "<page> - <brand>" separator dropped.
    {
        "gate_id": 40,
        "name": "adversarial",
        "locale": "ru",
        "source": _page({"seoTitle": "3D Scene Management - Aspose.3D"}, "## Overview\n\nText."),
        "translated": _page({"seoTitle": "Управление 3D сценами Aspose.3D"}, "## Обзор\n\nТекст."),
    },
    {
        "gate_id": 40,
        "name": "known_good_separator_kept",
        "locale": "ru",
        "source": _page({"seoTitle": "3D Scene Management - Aspose.3D"}, "## Overview\n\nText."),
        "translated": _page(
            {"seoTitle": "Управление 3D сценами - Aspose.3D"}, "## Обзор\n\nТекст."
        ),
    },
    # Gate 41: homoglyph in code -- Cyrillic "о" inside an inline code span.
    {
        "gate_id": 41,
        "name": "adversarial",
        "locale": "ru",
        "source": _page({"title": "T"}, "## Usage\n\nCall `foo()` to load the document."),
        "translated": _page({"title": "T"}, "## Использование\n\nВызовите `fоo()` для загрузки документа."),
    },
    {
        "gate_id": 41,
        "name": "known_good_ascii_code",
        "locale": "ru",
        "source": _page({"title": "T"}, "## Usage\n\nCall `foo()` to load the document."),
        "translated": _page({"title": "T"}, "## Использование\n\nВызовите `foo()` для загрузки документа."),
    },
    # Gate 43: block-scalar key leak -- a later field's "key:" line bleeds into
    # a multi-line scalar's translated value. _is_multiline_source_field scans
    # RAW physical lines (folded '>'/plain-continuation YAML has no embedded
    # '\n' once parsed), and the leak regex needs an ACTUAL '\n' in the
    # PARSED value -- a literal block scalar ('|') is the one shape that
    # guarantees both at once, so these two are hand-authored raw YAML
    # instead of going through _page()'s generic yaml.dump (which would pick
    # double-quoted or plain-folded style depending on length, neither of
    # which reliably reproduces this exact corruption shape).
    {
        "gate_id": 43,
        "name": "adversarial",
        "locale": "fr",
        "source": (
            "---\n"
            "title: T\n"
            "description: |\n"
            "  Learn how to build 3D scenes in Java\n"
            "  using Aspose.3D FOSS.\n"
            "summary: Build node hierarchies and export to FBX.\n"
            "---\n\n## Overview\n\nText.\n"
        ),
        "translated": (
            "---\n"
            "title: T\n"
            "description: |\n"
            "  Apprenez a construire des scenes 3D en Java\n"
            "  summary: fuite de cle ici.\n"
            "summary: Construisez des hierarchies de noeuds et exportez vers FBX.\n"
            "---\n\n## Apercu\n\nTexte.\n"
        ),
    },
    {
        "gate_id": 43,
        "name": "known_good_no_leak",
        "locale": "fr",
        "source": (
            "---\n"
            "title: T\n"
            "description: |\n"
            "  Learn how to build 3D scenes in Java\n"
            "  using Aspose.3D FOSS.\n"
            "---\n\n## Overview\n\nText.\n"
        ),
        "translated": (
            "---\n"
            "title: T\n"
            "description: |\n"
            "  Apprenez a construire des scenes 3D en Java\n"
            "  avec Aspose.3D FOSS.\n"
            "---\n\n## Apercu\n\nTexte.\n"
        ),
    },
    # Gate 44: SEO length sanity -- translated head_title ballooned past 1.5x
    # AND +15 chars over the English value.
    {
        "gate_id": 44,
        "name": "adversarial",
        "locale": "de",
        "source": _page({"head_title": "3D Scene Management - Aspose"}, "## Overview\n\nText."),
        "translated": _page(
            {
                "head_title": (
                    "Verwaltung von dreidimensionalen Szenen und Objekten in Java-Anwendungen - Aspose"
                )
            },
            "## Uebersicht\n\nText.",
        ),
    },
    {
        "gate_id": 44,
        "name": "known_good_modest_growth",
        "locale": "de",
        "source": _page({"head_title": "3D Scene Management - Aspose"}, "## Overview\n\nText."),
        "translated": _page(
            {"head_title": "3D-Szenenverwaltung - Aspose"}, "## Uebersicht\n\nText."
        ),
    },
]

# Gate 42 (whole-page language mismatch) needs a real FastTextDetector and is
# handled separately below since it depends on the evaluator's detector
# instance rather than being pure content, and its own docstring notes it
# gracefully no-ops without one.


def run_fixture(evaluator: WriteGateEvaluator, fixture: dict[str, Any]) -> dict[str, Any]:
    gate_id = fixture["gate_id"]
    out_path = Path(f"content/{fixture.get('site', 'blog.aspose.org')}/{fixture['locale']}/fixture.md")
    results, _ = evaluator.run_all_content_gates(
        fixture["source"], fixture["translated"], fixture["locale"], out_path
    )
    gate_result = results.get(gate_id)
    return {
        "gate_id": gate_id,
        "name": fixture["name"],
        "fired": bool(gate_result is not None and not gate_result.passed),
        "error": gate_result.error if gate_result is not None else None,
        "other_gates_fired": sorted(
            gid for gid, res in results.items() if gid != gate_id and not res.passed
        ),
    }


def gate42_fixtures(evaluator: WriteGateEvaluator) -> list[dict[str, Any]]:
    """Gate 42 needs the shared detector instance; build its two cases here."""
    if evaluator._detector is None:
        return [
            {
                "gate_id": 42,
                "name": "adversarial",
                "fired": None,
                "error": "no FastTextDetector available in this environment -- gate self-no-ops",
                "other_gates_fired": [],
                "skipped": True,
            }
        ]
    # Body wholesale in the WRONG language relative to the declared target
    # ('de'). Needs genuinely high-confidence langid classification (gate
    # requires confidence >= 0.85) -- a short or accent-stripped fake-foreign
    # string classifies with too little confidence to fire, by design (the
    # gate's own false-positive guard), so this uses real, fluent French
    # prose, not a token salad.
    wrong_lang_body = _page(
        {"title": "T"},
        "## Apercu\n\n"
        + "Ceci est un texte entierement different, ecrit en francais avec de "
        "nombreux mots reconnaissables. " * 6,
    )
    right_lang_body = _page(
        {"title": "T"}, "## Ubersicht\n\n" + "Dies ist ein vollstaendig deutscher Beispieltext. " * 8
    )
    out = []
    for name, translated, locale in (
        ("adversarial", wrong_lang_body, "de"),
        ("known_good_correct_language", right_lang_body, "de"),
    ):
        results, _ = evaluator.run_all_content_gates(
            _page({"title": "T"}, "## Overview\n\n" + "Some English text. " * 8),
            translated,
            locale,
            Path(f"content/blog.aspose.org/{locale}/fixture.md"),
        )
        gate_result = results.get(42)
        out.append(
            {
                "gate_id": 42,
                "name": name,
                "fired": bool(gate_result is not None and not gate_result.passed),
                "error": gate_result.error if gate_result is not None else None,
                "other_gates_fired": sorted(
                    gid for gid, res in results.items() if gid != 42 and not res.passed
                ),
            }
        )
    return out


def run_all_fixtures(evaluator: WriteGateEvaluator) -> list[dict[str, Any]]:
    results = [run_fixture(evaluator, f) for f in FIXTURES]
    results.extend(gate42_fixtures(evaluator))
    return results


# ---------------------------------------------------------------------------
# Known-good sample: stratified real-content selection, existing targets only.
# ---------------------------------------------------------------------------


def build_known_good_sample(target_size: int, seed: int) -> list[dict[str, Any]]:
    """Each site profile's own ``content_roots[0]`` (env-expanded) IS the
    per-site content root -- resolving it a second time from a generic
    repo-root parameter would either duplicate or miss the ``content/`` and
    site-id path segments each site's Hugo layout actually uses.
    """
    import os

    config = ConfigService(_PROJECT_ROOT / "config")
    per_site: dict[str, list[dict[str, Any]]] = {}
    for site_id in IN_SCOPE_SITES:
        profile = config.get_site_profile(site_id)
        if profile is None or not getattr(profile, "content_roots", None):
            continue
        site_root = Path(os.path.expandvars(profile.content_roots[0]))
        target_langs = list(getattr(profile, "target_langs", None) or [])
        sources = discover_source_files(profile, site_root)
        pairs = []
        for source_path in sources:
            for locale in target_langs:
                translated_path = resolve_translated_path(profile, source_path, locale)
                if translated_path.is_file():
                    pairs.append(
                        {"site_id": site_id, "locale": locale, "source_path": source_path,
                         "translated_path": translated_path}
                    )
        per_site[site_id] = pairs

    total_existing = sum(len(v) for v in per_site.values())
    rng = random.Random(seed)
    sample: list[dict[str, Any]] = []
    for site_id, pairs in per_site.items():
        if not pairs or total_existing == 0:
            continue
        share = max(20, round(target_size * len(pairs) / total_existing))
        share = min(share, len(pairs))
        sample.extend(rng.sample(pairs, share))
    return sample


def scan_known_good(
    evaluator: WriteGateEvaluator, sample: list[dict[str, Any]]
) -> dict[int, dict[str, Any]]:
    per_gate: dict[int, dict[str, Any]] = {
        gid: {"fired": 0, "examples": []} for gid in UNVALIDATED_GATE_IDS
    }
    for pair in sample:
        try:
            en = pair["source_path"].read_text(encoding="utf-8")
            tr = pair["translated_path"].read_text(encoding="utf-8")
        except OSError as exc:
            continue
        results, _ = evaluator.run_all_content_gates(en, tr, pair["locale"], pair["translated_path"])
        for gid in UNVALIDATED_GATE_IDS:
            gres = results.get(gid)
            if gres is not None and not gres.passed:
                per_gate[gid]["fired"] += 1
                if len(per_gate[gid]["examples"]) < 15:
                    per_gate[gid]["examples"].append(
                        {
                            "path": str(pair["translated_path"]),
                            "locale": pair["locale"],
                            "error": (gres.error or "")[:300],
                        }
                    )
    return per_gate


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="TC-APT-010 GATE-PROMO-001 sample runner")
    parser.add_argument("--sample-size", type=int, default=600)
    parser.add_argument("--seed", type=int, default=20260902)
    parser.add_argument("--runs", type=int, default=3)
    parser.add_argument("--out", type=Path, default=Path("data/quality/gate_promotion_log.jsonl"))
    args = parser.parse_args(argv)

    evaluator = build_evaluator()
    print(f"detector available: {evaluator._detector is not None}")

    sample = build_known_good_sample(args.sample_size, args.seed)
    print(f"known-good sample: {len(sample)} files across "
          f"{len({p['site_id'] for p in sample})} sites")

    fixture_runs = [run_all_fixtures(evaluator) for _ in range(args.runs)]
    fixture_reproducible = all(
        json.dumps(run, sort_keys=True, default=str) == json.dumps(fixture_runs[0], sort_keys=True, default=str)
        for run in fixture_runs[1:]
    )

    known_good_runs = [scan_known_good(evaluator, sample) for _ in range(args.runs)]

    def _fired_counts(run: dict[int, dict[str, Any]]) -> dict[int, int]:
        return {gid: v["fired"] for gid, v in run.items()}

    known_good_reproducible = all(
        _fired_counts(run) == _fired_counts(known_good_runs[0]) for run in known_good_runs[1:]
    )

    fixtures_by_gate: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for f in fixture_runs[0]:
        fixtures_by_gate[f["gate_id"]].append(f)

    log_lines: list[dict[str, Any]] = []
    header = {
        "taskcard": "TC-APT-010",
        "run": "sample+adversarial (gate 36 handled separately, see gate_promotion_fidelity_shadow.py)",
        "measured_at": datetime.now(timezone.utc).isoformat(),
        "known_good_sample_size": len(sample),
        "sample_sites": sorted({p["site_id"] for p in sample}),
        "runs": args.runs,
        "fixture_reproducible_across_runs": fixture_reproducible,
        "known_good_reproducible_across_runs": known_good_reproducible,
    }
    log_lines.append(header)

    for gid in UNVALIDATED_GATE_IDS:
        gate_fixtures = fixtures_by_gate.get(gid, [])
        adversarial = next((f for f in gate_fixtures if f["name"] == "adversarial"), None)
        negatives = [f for f in gate_fixtures if f["name"] != "adversarial"]
        known_good = known_good_runs[0].get(gid, {"fired": 0, "examples": []})
        sensitivity_ok = bool(adversarial and (adversarial.get("fired") or adversarial.get("skipped")))
        specificity_ok = all(not n["fired"] for n in negatives)
        entry = {
            "gate_id": gid,
            "adversarial_fired": adversarial.get("fired") if adversarial else None,
            "adversarial_skipped": adversarial.get("skipped", False) if adversarial else None,
            "negative_fixtures_clean": specificity_ok,
            "negative_fixture_names": [n["name"] for n in negatives],
            "known_good_sample_fired_count": known_good["fired"],
            "known_good_sample_fire_rate": round(known_good["fired"] / len(sample), 5) if sample else None,
            "known_good_examples": known_good["examples"],
            "sensitivity_ok": sensitivity_ok,
            "specificity_ok_on_fixtures": specificity_ok,
        }
        log_lines.append(entry)

    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("w", encoding="utf-8") as fh:
        for line in log_lines:
            fh.write(json.dumps(line, ensure_ascii=False, default=str) + "\n")

    print(json.dumps(header, indent=2))
    for entry in log_lines[1:]:
        print(
            f"gate {entry['gate_id']:>2}: sensitivity_ok={entry['sensitivity_ok']} "
            f"specificity_ok={entry['specificity_ok_on_fixtures']} "
            f"known_good_fired={entry['known_good_sample_fired_count']}/{len(sample)}"
        )
    print(f"\nwrote {args.out}")
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
