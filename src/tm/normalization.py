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
    site_id: str,
    src_lang: str,
    tgt_lang: str,
    text: str,
    field_name: str = "",
    context: str = "",
) -> str:
    """
    Create a scoped composite TM key that includes optional field/context dimensions.

    Prevents cross-field TM contamination (e.g. description: field returning
    a cached translation that was stored for a different field), and, when
    context is given, cross-context contamination within the same field (e.g.
    a frontmatter.title occurrence of "Title" colliding with an unrelated
    body.heading occurrence of the same literal text).

    field_name changes the key's *shape* (an extra colon-delimited segment,
    for backward compatibility with pre-existing unscoped keys). context does
    not change the shape -- it's folded into the hash input instead, since
    context values (AST paths, frontmatter keys) can contain arbitrary
    delimiter-like characters. Passing context="" reproduces the exact
    pre-existing hash for that (site_id, field_name) combination, so this is
    backward compatible by construction, not just by convention.

    Format when field_name given: {site_id}:{field_name}:{src_lang}:{tgt_lang}:{hash}
    Format when field_name empty: {site_id}:{src_lang}:{tgt_lang}:{hash}  (backward compat)

    Args:
        site_id: Site identifier
        src_lang: Source language code
        tgt_lang: Target language code
        text: Source text
        field_name: Optional field context (e.g. "description", "title"). Empty = unscoped.
        context: Optional finer-grained context (e.g. "frontmatter.title", an AST
            node path). Empty = not context-scoped (legacy hash).

    Returns:
        Composite key string
    """
    text_hash = hash_text(f"{context}\x00{text}") if context else hash_text(text)
    if field_name:
        return f"{site_id}:{field_name}:{src_lang}:{tgt_lang}:{text_hash}"
    return f"{site_id}:{src_lang}:{tgt_lang}:{text_hash}"
