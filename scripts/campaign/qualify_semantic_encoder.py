"""Qualify a cross-lingual semantic encoder across the campaign locales.

Only numeric similarity scores are emitted. Generated translations remain
in memory and are never written to evidence or logs.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import torch
from transformers import M2M100ForConditionalGeneration, M2M100Tokenizer

from src.tm.l3_semantic import load_standalone_sentence_encoder
from src.translation_engine.validation.semantic_similarity_validator import (
    SemanticSimilarityValidator,
)
from src.utils.atomic_write import atomic_write

TARGET_LOCALES = (
    "ar",
    "cs",
    "de",
    "el",
    "es",
    "fa",
    "fr",
    "he",
    "hi",
    "hu",
    "id",
    "it",
    "ja",
    "ko",
    "nl",
    "pl",
    "pt",
    "ro",
    "ru",
    "sv",
    "th",
    "tr",
    "uk",
    "vi",
    "zh",
)

QUALIFICATION_SOURCE = (
    "Manage spreadsheets in Rust with Aspose.Cells. Create and rename "
    "worksheets, format cells, calculate formulas, import structured data, "
    "configure page setup, protect workbooks, and save files in common "
    "spreadsheet formats. The library supports charts, tables, filtering, "
    "sorting, validation, and reliable workbook conversion without requiring "
    "Microsoft Excel."
)


def qualify(*, encoder_model: str, translation_model: Path, device: str) -> dict:
    tokenizer = M2M100Tokenizer.from_pretrained(translation_model)
    translator = M2M100ForConditionalGeneration.from_pretrained(translation_model).to(device).eval()
    encoder = load_standalone_sentence_encoder(encoder_model, use_gpu=False)
    scores: dict[str, float] = {}

    for locale in TARGET_LOCALES:
        tokenizer.src_lang = "en"
        inputs = tokenizer(
            QUALIFICATION_SOURCE,
            return_tensors="pt",
            truncation=True,
            max_length=512,
        ).to(device)
        with torch.inference_mode():
            generated = translator.generate(
                **inputs,
                forced_bos_token_id=tokenizer.get_lang_id(locale),
                max_new_tokens=512,
            )
        translated = tokenizer.batch_decode(generated, skip_special_tokens=True)[0]
        scores[locale] = round(
            SemanticSimilarityValidator._cosine_similarity(
                encoder, QUALIFICATION_SOURCE, translated
            ),
            6,
        )

    return {
        "schema_version": 1,
        "encoder_model": encoder_model,
        "translation_model": translation_model.name,
        "locales": list(TARGET_LOCALES),
        "scores": scores,
        "minimum": min(scores.values()),
        "maximum": max(scores.values()),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--encoder-model", required=True)
    parser.add_argument("--translation-model", type=Path, required=True)
    parser.add_argument("--device", default="cuda")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    result = qualify(
        encoder_model=args.encoder_model,
        translation_model=args.translation_model.resolve(),
        device=args.device,
    )
    encoded = json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True)
    if args.output:
        atomic_write(
            path=args.output,
            content=encoded + "\n",
            encoding="utf-8",
            fsync=True,
            create_parents=True,
        )
    print(encoded)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
