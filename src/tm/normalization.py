"""
Text normalization utilities for translation memory.
"""
import hashlib
import re
import unicodedata


def normalize_text(text: str) -> str:
    """
    Normalize text for TM matching.

    Applies:
    - Unicode NFC normalization
    - Whitespace collapsing
    - Trimming

    Args:
        text: Text to normalize

    Returns:
        Normalized text
    """
    # Unicode normalization (NFC - composed form)
    text = unicodedata.normalize("NFC", text)

    # Collapse multiple whitespace to single space
    text = re.sub(r"\s+", " ", text)

    # Trim leading/trailing whitespace
    text = text.strip()

    return text


def hash_text(text: str) -> str:
    """
    Create hash of normalized text for keying.

    Args:
        text: Text to hash

    Returns:
        MD5 hash (hex string)
    """
    normalized = normalize_text(text)
    return hashlib.md5(normalized.encode("utf-8"), usedforsecurity=False).hexdigest()


def make_tm_key(
    site_id: str, src_lang: str, tgt_lang: str, text: str
) -> str:
    """
    Create composite TM key.

    Format: {site_id}:{src_lang}:{tgt_lang}:{hash}

    Args:
        site_id: Site identifier
        src_lang: Source language code
        tgt_lang: Target language code
        text: Source text

    Returns:
        Composite key string
    """
    text_hash = hash_text(text)
    return f"{site_id}:{src_lang}:{tgt_lang}:{text_hash}"


def make_tm_key_scoped(
    site_id: str, src_lang: str, tgt_lang: str, text: str, field_name: str = ""
) -> str:
    """
    Create a scoped composite TM key that includes an optional field dimension.

    Prevents cross-field TM contamination (e.g. description: field returning
    a cached translation that was stored for a different field).

    Format when field_name given: {site_id}:{field_name}:{src_lang}:{tgt_lang}:{hash}
    Format when field_name empty: {site_id}:{src_lang}:{tgt_lang}:{hash}  (backward compat)

    Args:
        site_id: Site identifier
        src_lang: Source language code
        tgt_lang: Target language code
        text: Source text
        field_name: Optional field context (e.g. "description", "title"). Empty = unscoped.

    Returns:
        Composite key string
    """
    text_hash = hash_text(text)
    if field_name:
        return f"{site_id}:{field_name}:{src_lang}:{tgt_lang}:{text_hash}"
    return f"{site_id}:{src_lang}:{tgt_lang}:{text_hash}"
