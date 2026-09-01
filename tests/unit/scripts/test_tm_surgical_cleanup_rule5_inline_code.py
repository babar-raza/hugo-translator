"""HT-INLINE-CODE-001 TC-ICR-011: tm_surgical_cleanup.py's Rule 5 --
patching TM entries whose cached translation has an embedded inline-code
span translated instead of preserved verbatim.

Unlike Rule 1 (identifier_translated -> full identity overwrite of the
whole segment), this rule only patches the specific corrupted span(s)
within a larger cached segment, leaving correctly-translated surrounding
prose untouched -- the TM-side counterpart to TC-ICR-004/008's
content-side fix, both built on the same shared, count-guarded
inline_code_repair primitive.
"""
from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO_ROOT / "scripts" / "quality"))
sys.path.insert(0, str(REPO_ROOT))

from src.tm.l2_persistent import TranslationEntry
from scripts.quality.tm_surgical_cleanup import is_corrupt_entry, run


def _entry(source_text, translation, tgt_lang="fr", metadata=None):
    return TranslationEntry(
        source_text=source_text,
        translation=translation,
        site_id="reference.aspose.org",
        src_lang="en",
        tgt_lang=tgt_lang,
        metadata=metadata,
    )


class TestRule5Detection:
    def test_embedded_span_corruption_flagged_for_patch(self) -> None:
        entry = _entry(
            "Use `equals`, `close`, and `create` here.",
            "Utilisez `identité`, `close`, et `create` ici.",
        )
        corrupt, reason, action = is_corrupt_entry(entry)
        assert corrupt is True
        assert reason == "inline_code_span_translated"
        assert action == "patch"

    def test_clean_segment_not_flagged(self) -> None:
        entry = _entry(
            "Use `equals`, `close`, and `create` here.",
            "Utilisez `equals`, `close`, et `create` ici.",
        )
        corrupt, _, _ = is_corrupt_entry(entry)
        assert corrupt is False

    def test_span_count_mismatch_not_flagged(self) -> None:
        entry = _entry(
            "Use `create`, `close`, and `equals` here.",
            "Utilisez `create`, `equals`, et `extra` ici.",
        )
        corrupt, _, _ = is_corrupt_entry(entry)
        assert corrupt is False

    def test_below_three_span_threshold_not_flagged(self) -> None:
        entry = _entry("Call `Save` then `Close`.", "Appelez `Enregistrer` puis `Fermer`.")
        corrupt, _, _ = is_corrupt_entry(entry)
        assert corrupt is False


class _FakeL2TM:
    """Minimal in-memory stand-in for L2PersistentTM, just enough surface
    for tm_surgical_cleanup.run() to scan and apply a patch."""

    def __init__(self, entries: list[TranslationEntry]) -> None:
        self._entries = entries
        self.stored: list[dict] = []

    def export_iter(self, site_id=None):
        for e in self._entries:
            if site_id is None or e.site_id == site_id:
                yield e

    def store(self, **kwargs):
        self.stored.append(kwargs)
        return True

    def delete(self, **kwargs):
        return True


class TestRule5ApplyPatchesOnlyTheSpanAndStampsProvenance:
    def test_apply_patches_span_leaves_prose_untouched_and_stamps_metadata(self) -> None:
        entry = _entry(
            "Before text. Use `equals`, `close`, and `create` here. After text.",
            "Avant le texte. Utilisez `identité`, `close`, et `create` ici. Après le texte.",
            metadata={"existing_key": "existing_value"},
        )
        tm = _FakeL2TM([entry])

        stats = run(
            tm=tm,
            site=None,
            only_locales=None,
            apply=True,
            max_changes=1000,
            verbose=False,
        )

        assert stats["patched"] == 1
        assert stats.get("patch_errors", 0) == 0
        assert len(tm.stored) == 1
        stored = tm.stored[0]
        assert stored["translation"] == (
            "Avant le texte. Utilisez `equals`, `close`, et `create` ici. Après le texte."
        )
        assert stored["overwrite"] is True
        # Existing metadata preserved, provenance marker added -- not clobbered.
        assert stored["metadata"]["existing_key"] == "existing_value"
        assert stored["metadata"]["remediation"] == "inline_code_repair_v1"

    def test_dry_run_does_not_call_store(self) -> None:
        entry = _entry(
            "Use `equals`, `close`, and `create` here.",
            "Utilisez `identité`, `close`, et `create` ici.",
        )
        tm = _FakeL2TM([entry])

        stats = run(
            tm=tm,
            site=None,
            only_locales=None,
            apply=False,
            max_changes=1000,
            verbose=False,
        )

        assert stats["to_patch"] == 1
        assert stats["patched"] == 0
        assert len(tm.stored) == 0
