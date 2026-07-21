"""TC-HDN-003/H2: field_name scoping must be reachable end-to-end.

Root cause: make_tm_key_scoped() and L2PersistentTM.exact_lookup/store both
already accepted field_name, but TranslationMemory (the only layer callers
actually use) never accepted or forwarded it -- dead code one layer down.
L1Cache wasn't field-scoped at all, so even a fixed TranslationMemory would
have served a cross-field-collided L1 hit before L2 was ever consulted.

This complements (not replaces) TC-HT-TMKEY-001's tm_key_text fix: that fix
prevents two different DOCUMENTS sharing a template from colliding within
the SAME field (e.g. two classes' `description`); this fix prevents two
different FIELDS on the same or different documents from colliding when
they happen to contain identical text (e.g. `title` vs `description`).
"""

from src.tm.l1_cache import L1Cache
from src.tm.l2_persistent import L2PersistentTM
from src.tm.models import LookupRequest
from src.tm.translation_memory import TranslationMemory


class TestL1CacheFieldScoping:
    def test_same_text_different_field_name_does_not_collide(self):
        cache = L1Cache(max_size=100)
        cache.put("site", "en", "uk", "Alignment", "Вирівнювання", field_name="title")
        cache.put("site", "en", "uk", "Alignment", "Вирівнювання класу", field_name="description")

        assert cache.get("site", "en", "uk", "Alignment", field_name="title") == "Вирівнювання"
        assert cache.get("site", "en", "uk", "Alignment", field_name="description") == "Вирівнювання класу"

    def test_unscoped_lookup_after_scoped_store_misses(self):
        """A field-scoped entry must not leak into an unscoped lookup."""
        cache = L1Cache(max_size=100)
        cache.put("site", "en", "uk", "Alignment", "Вирівнювання", field_name="title")
        assert cache.get("site", "en", "uk", "Alignment") is None

    def test_default_field_name_backward_compatible(self):
        """Omitting field_name entirely must behave exactly as before."""
        cache = L1Cache(max_size=100)
        cache.put("site", "en", "uk", "hello", "Привіт")
        assert cache.get("site", "en", "uk", "hello") == "Привіт"


class TestTranslationMemoryFieldScoping:
    def _make_tm(self, tmp_path):
        l1 = L1Cache(max_size=100)
        l2 = L2PersistentTM(db_path=tmp_path / "l2.lmdb")
        return TranslationMemory(l1_cache=l1, l2_persistent=l2, l3_semantic=None)

    def test_store_and_lookup_round_trip_with_field_name(self, tmp_path):
        tm = self._make_tm(tmp_path)
        tm.store(
            site_id="reference.aspose.org", src_lang="en", tgt_lang="uk",
            text="Alignment", translation="Вирівнювання", field_name="title",
        )
        result = tm.lookup(
            site_id="reference.aspose.org", src_lang="en", tgt_lang="uk",
            text="Alignment", field_name="title", use_semantic=False,
        )
        assert result.hit is True
        assert result.translation == "Вирівнювання"

    def test_different_field_name_is_a_genuine_miss_not_a_collision(self, tmp_path):
        """The core H2 guarantee: identical source text under a different
        field_name must not return the wrong field's cached translation."""
        tm = self._make_tm(tmp_path)
        tm.store(
            site_id="reference.aspose.org", src_lang="en", tgt_lang="uk",
            text="Alignment", translation="Вирівнювання (title)", field_name="title",
        )
        result = tm.lookup(
            site_id="reference.aspose.org", src_lang="en", tgt_lang="uk",
            text="Alignment", field_name="description", use_semantic=False,
        )
        assert result.hit is False

    def test_batch_lookup_respects_field_name(self, tmp_path):
        tm = self._make_tm(tmp_path)
        tm.store(
            site_id="site", src_lang="en", tgt_lang="uk",
            text="Alignment", translation="Title translation", field_name="title",
        )
        tm.store(
            site_id="site", src_lang="en", tgt_lang="uk",
            text="Alignment", translation="Description translation", field_name="description",
        )
        results = tm.batch_lookup(
            [
                LookupRequest(site_id="site", src_lang="en", tgt_lang="uk", text="Alignment", field_name="title"),
                LookupRequest(site_id="site", src_lang="en", tgt_lang="uk", text="Alignment", field_name="description"),
            ],
            use_semantic=False,
        )
        assert results[0].translation == "Title translation"
        assert results[1].translation == "Description translation"

    def test_omitting_field_name_is_backward_compatible(self, tmp_path):
        tm = self._make_tm(tmp_path)
        tm.store(site_id="site", src_lang="en", tgt_lang="fr", text="hello", translation="bonjour")
        result = tm.lookup(site_id="site", src_lang="en", tgt_lang="fr", text="hello", use_semantic=False)
        assert result.hit is True
        assert result.translation == "bonjour"
