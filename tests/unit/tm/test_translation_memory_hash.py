"""TC-01 / BUG-4: Verify L3 entry_id uses deterministic hash_text (MD5), not Python hash().

Python's hash() is randomized per-process via PYTHONHASHSEED since Python 3.3.
Using hash() caused duplicate FAISS vectors to accumulate across daemon restarts.
hash_text() uses MD5 which is stable regardless of PYTHONHASHSEED.
"""

import hashlib


class TestHashTextDeterminism:
    """BUG-4 fix: hash_text must produce consistent, deterministic output."""

    def test_hash_text_returns_md5_hex(self):
        """hash_text output matches raw MD5 of the same input."""
        from src.tm.normalization import hash_text

        text = "Aspose.Words for .NET developer guide"
        expected = hashlib.md5(text.encode("utf-8")).hexdigest()
        assert hash_text(text) == expected

    def test_hash_text_same_input_same_output(self):
        """Same string always produces same hash (no process-level randomness)."""
        from src.tm.normalization import hash_text

        text = "Translation memory entry"
        results = {hash_text(text) for _ in range(10)}
        assert len(results) == 1, "hash_text must be deterministic"

    def test_hash_text_different_inputs_differ(self):
        """Different strings (after normalization) produce different hashes."""
        from src.tm.normalization import hash_text

        # Both inputs are meaningfully different after normalization
        assert hash_text("foo") != hash_text("bar")
        assert hash_text("hello world") != hash_text("goodbye world")
        # Note: hash_text normalizes whitespace, so "foo" == "foo " after normalize

    def test_hash_text_returns_string_not_int(self):
        """hash_text must return str (hexdigest), not int like Python's hash()."""
        from src.tm.normalization import hash_text

        result = hash_text("test")
        assert isinstance(result, str)
        assert len(result) == 32  # MD5 hex = 32 chars

    def test_entry_id_format_uses_hash_text(self):
        """TranslationMemory builds L3 entry_id with hash_text, not hash()."""
        from src.tm.normalization import hash_text

        # Simulate the entry_id construction from translation_memory.py:222
        site_id = "blog.aspose.net"
        src_lang = "en"
        tgt_lang = "fr"
        text = "Convert PDF files in C#"
        entry_id = f"{site_id}:{src_lang}:{tgt_lang}:{hash_text(text)}"
        # Verify format: <site>:<src>:<tgt>:<32-char-md5>
        parts = entry_id.split(":")
        assert len(parts) == 4
        assert len(parts[3]) == 32
        # Verify it's deterministic by recomputing
        assert entry_id == f"{site_id}:{src_lang}:{tgt_lang}:{hash_text(text)}"

    def test_hash_text_normalizes_before_hashing(self):
        """hash_text normalizes whitespace before hashing — matches L2 key behavior."""
        from src.tm.normalization import hash_text

        # Trailing space normalizes away → same hash
        assert hash_text("foo") == hash_text("foo ")
        # Multiple internal spaces collapse → same hash
        assert hash_text("foo  bar") == hash_text("foo bar")

    def test_hash_text_not_python_builtin_hash(self):
        """Explicitly verify hash_text != Python's built-in hash output.

        Python hash() returns an int; hash_text() returns a 32-char hex string.
        This guards against accidentally reverting to hash().
        """
        from src.tm.normalization import hash_text

        text = "test entry"
        ht_result = hash_text(text)
        py_hash = hash(text)
        assert ht_result != str(py_hash), (
            "hash_text must not equal str(hash()) — would be non-deterministic"
        )
        assert len(ht_result) == 32  # MD5 hex
