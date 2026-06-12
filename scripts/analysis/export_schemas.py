"""
Export Pydantic models as JSON Schema files.

Generates schema files in config/schemas/ from the contracts defined
in src/model_runtime/contracts.py. Run after modifying contracts.

Usage:
    python scripts/export_schemas.py
"""

import json
import sys
from pathlib import Path

# Add project root to path
project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(project_root))

from src.model_runtime.contracts import (
    LLMProviderConfig,
    TokenUsage,
    TranslationRequest,
    TranslationResponse,
)


def main():
    schemas_dir = project_root / "config" / "schemas"
    schemas_dir.mkdir(parents=True, exist_ok=True)

    models = [LLMProviderConfig, TranslationRequest, TranslationResponse, TokenUsage]

    for model_cls in models:
        schema = model_cls.model_json_schema()
        output_path = schemas_dir / f"{model_cls.__name__}.schema.json"
        output_path.write_text(json.dumps(schema, indent=2) + "\n", encoding="utf-8")
        print(f"Exported: {output_path}")

    print(f"\nDone. {len(models)} schemas exported to {schemas_dir}")


if __name__ == "__main__":
    main()
