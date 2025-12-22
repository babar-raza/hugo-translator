"""
Language Code Mapping for Translation Models.

Different translation models use different language code formats:
- M2M100: Simple ISO 639-1 codes (en, es, de, fr, etc.)
- NLLB-200: Language_Script format (eng_Latn, spa_Latn, deu_Latn, etc.)
- OpusMT/Marian: ISO 639-1 codes

This module provides mapping between these formats.
"""

from typing import Dict, Optional


# ISO 639-1 to NLLB-200 language code mapping
# NLLB uses language_Script format where Script is usually "Latn" for Latin-based,
# "Cyrl" for Cyrillic, "Arab" for Arabic, etc.
# Reference: https://github.com/facebookresearch/flores/blob/main/flores200/README.md
ISO_TO_NLLB: Dict[str, str] = {
    # Major European languages
    "en": "eng_Latn",  # English
    "es": "spa_Latn",  # Spanish
    "fr": "fra_Latn",  # French
    "de": "deu_Latn",  # German
    "it": "ita_Latn",  # Italian
    "pt": "por_Latn",  # Portuguese
    "nl": "nld_Latn",  # Dutch
    "pl": "pol_Latn",  # Polish
    "ru": "rus_Cyrl",  # Russian (Cyrillic script)
    "uk": "ukr_Cyrl",  # Ukrainian (Cyrillic script)
    "cs": "ces_Latn",  # Czech
    "ro": "ron_Latn",  # Romanian
    "sv": "swe_Latn",  # Swedish
    "da": "dan_Latn",  # Danish
    "fi": "fin_Latn",  # Finnish
    "no": "nob_Latn",  # Norwegian (Bokmål)
    "el": "ell_Grek",  # Greek
    "tr": "tur_Latn",  # Turkish
    "hu": "hun_Latn",  # Hungarian
    "bg": "bul_Cyrl",  # Bulgarian (Cyrillic script)
    "sr": "srp_Cyrl",  # Serbian (Cyrillic script)
    "hr": "hrv_Latn",  # Croatian
    "sk": "slk_Latn",  # Slovak
    "sl": "slv_Latn",  # Slovenian
    "et": "est_Latn",  # Estonian
    "lv": "lvs_Latn",  # Latvian
    "lt": "lit_Latn",  # Lithuanian

    # Asian languages
    "zh": "zho_Hans",  # Chinese Simplified
    "ja": "jpn_Jpan",  # Japanese
    "ko": "kor_Hang",  # Korean
    "ar": "arb_Arab",  # Modern Standard Arabic
    "he": "heb_Hebr",  # Hebrew
    "hi": "hin_Deva",  # Hindi (Devanagari script)
    "th": "tha_Thai",  # Thai
    "vi": "vie_Latn",  # Vietnamese
    "id": "ind_Latn",  # Indonesian
    "ms": "zsm_Latn",  # Malay
    "tl": "tgl_Latn",  # Tagalog
    "bn": "ben_Beng",  # Bengali
    "ta": "tam_Taml",  # Tamil
    "te": "tel_Telu",  # Telugu
    "mr": "mar_Deva",  # Marathi
    "ur": "urd_Arab",  # Urdu
    "fa": "pes_Arab",  # Persian/Farsi

    # Other languages
    "af": "afr_Latn",  # Afrikaans
    "sq": "als_Latn",  # Albanian
    "am": "amh_Ethi",  # Amharic
    "hy": "hye_Armn",  # Armenian
    "az": "azj_Latn",  # Azerbaijani
    "eu": "eus_Latn",  # Basque
    "be": "bel_Cyrl",  # Belarusian
    "bs": "bos_Latn",  # Bosnian
    "ca": "cat_Latn",  # Catalan
    "eo": "epo_Latn",  # Esperanto
    "gl": "glg_Latn",  # Galician
    "ka": "kat_Geor",  # Georgian
    "is": "isl_Latn",  # Icelandic
    "ga": "gle_Latn",  # Irish
    "kk": "kaz_Cyrl",  # Kazakh
    "km": "khm_Khmr",  # Khmer
    "lo": "lao_Laoo",  # Lao
    "mk": "mkd_Cyrl",  # Macedonian
    "ml": "mal_Mlym",  # Malayalam
    "mn": "khk_Cyrl",  # Mongolian
    "my": "mya_Mymr",  # Burmese
    "ne": "npi_Deva",  # Nepali
    "ps": "pbt_Arab",  # Pashto
    "si": "sin_Sinh",  # Sinhala
    "sw": "swh_Latn",  # Swahili
    "uz": "uzn_Latn",  # Uzbek
    "cy": "cym_Latn",  # Welsh
}

# Reverse mapping: NLLB to ISO 639-1
NLLB_TO_ISO: Dict[str, str] = {v: k for k, v in ISO_TO_NLLB.items()}


def is_nllb_model(model_id: str, hf_model_id: Optional[str] = None) -> bool:
    """
    Check if a model is an NLLB model.

    Args:
        model_id: Internal model identifier
        hf_model_id: HuggingFace model identifier

    Returns:
        True if model is NLLB, False otherwise
    """
    # Check both model_id and hf_model_id for "nllb"
    check_ids = [model_id]
    if hf_model_id:
        check_ids.append(hf_model_id)

    return any("nllb" in id.lower() for id in check_ids)


def map_language_code(
    lang_code: str,
    model_id: str,
    hf_model_id: Optional[str] = None
) -> str:
    """
    Map language code to the format expected by the model.

    Args:
        lang_code: Language code (e.g., "en", "es", "spa_Latn")
        model_id: Internal model identifier
        hf_model_id: HuggingFace model identifier

    Returns:
        Mapped language code appropriate for the model
    """
    # If it's already in NLLB format, return as-is
    if "_" in lang_code:
        return lang_code

    # If it's an NLLB model, map to NLLB format
    if is_nllb_model(model_id, hf_model_id):
        nllb_code = ISO_TO_NLLB.get(lang_code)
        if nllb_code is None:
            raise ValueError(
                f"Language code '{lang_code}' not supported for NLLB models. "
                f"Supported codes: {sorted(ISO_TO_NLLB.keys())}"
            )
        return nllb_code

    # For other models (M2M100, OpusMT, etc.), use ISO 639-1
    return lang_code


def get_supported_languages(model_id: str, hf_model_id: Optional[str] = None) -> list[str]:
    """
    Get list of supported ISO 639-1 language codes for a model.

    Args:
        model_id: Internal model identifier
        hf_model_id: HuggingFace model identifier

    Returns:
        List of supported ISO 639-1 language codes
    """
    if is_nllb_model(model_id, hf_model_id):
        return sorted(ISO_TO_NLLB.keys())
    else:
        # M2M100 supports 100 languages - return common subset
        # Full list available at: https://github.com/pytorch/fairseq/tree/main/examples/m2m_100
        return sorted([
            "en", "es", "fr", "de", "it", "pt", "nl", "pl", "ru",
            "zh", "ja", "ko", "ar", "hi", "tr", "vi", "th", "cs",
            "ro", "sv", "da", "fi", "no", "el", "he", "id", "uk",
        ])
