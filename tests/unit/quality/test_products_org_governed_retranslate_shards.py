from pathlib import Path

import pytest

from scripts.quality.products_org_governed_retranslate import (
    VERIFIER_POLICY_VERSION,
    baseline_file,
    build_translate_cmd,
    checkpoint_file,
    current_file,
    merge_shard_checkpoints,
    overlay_main_checkpoint_for_items,
    parse_locale_filter,
    reverify_accepted_items,
    repair_target_code_blocks,
    repair_extra_code_blocks_with_source_order,
    repair_known_scalar_translations,
    repair_target_material_copy_fields,
    repair_target_product_identities,
    safe_shard_id,
    sha256_file,
    summary_file,
    verify_pair,
    WorkItem,
    write_json,
)
from src.translation_engine.parser.hugo_parser import HugoParser
from src.utils.config_loader import ConfigService


def products_profile():
    return ConfigService(config_root=Path("config")).get_site_profile("products.aspose.org")


def write_page(path: Path, body: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body.strip() + "\n", encoding="utf-8")


def test_parse_locale_filter_preserves_profile_order():
    assert parse_locale_filter("zh,ar", ["ar", "bg", "zh"]) == ["ar", "zh"]


def test_parse_locale_filter_rejects_unknown_locale():
    with pytest.raises(ValueError, match="Unknown locale"):
        parse_locale_filter("ar,xx", ["ar", "bg"])


def test_shard_file_paths_are_isolated():
    root = Path("evidence")

    assert checkpoint_file(root / "checkpoints", None) == root / "checkpoints" / "checkpoint.json"
    assert checkpoint_file(root / "checkpoints", "gpu0") == root / "checkpoints" / "checkpoint.gpu0.json"
    assert current_file(root / "checkpoints", "gpu0") == root / "checkpoints" / "current.gpu0.json"
    assert summary_file(root / "final", "gpu0") == root / "final" / "summary.gpu0.json"
    assert baseline_file(root / "baseline", "inventory", "gpu0") == root / "baseline" / "inventory.gpu0.json"


def test_safe_shard_id_sanitizes_path_unsafe_text():
    assert safe_shard_id("gpu 0/ar,bg") == "gpu_0_ar_bg"


def test_overlay_main_checkpoint_only_imports_shard_items():
    checkpoint = {"accepted": {}, "failed": {}}
    main = {
        "accepted": {"a": {"receipt": 1}, "outside": {"receipt": 2}},
        "failed": {"b": {"failure": 1}, "outside_failed": {"failure": 2}},
    }

    overlay_main_checkpoint_for_items(checkpoint, main, {"a", "b"})

    assert checkpoint["accepted"] == {"a": {"receipt": 1}}
    assert checkpoint["failed"] == {"b": {"failure": 1}}


def test_merge_shard_checkpoints_updates_main_and_drops_accepted_failures(tmp_path):
    evidence = tmp_path / "evidence"
    checkpoints = evidence / "checkpoints"
    write_json(
        checkpoints / "checkpoint.json",
        {"accepted": {"old": {"receipt": "old"}}, "failed": {"a": {"failure": "old"}}},
    )
    write_json(
        checkpoints / "checkpoint.gpu0.json",
        {"accepted": {"a": {"receipt": "new"}}, "failed": {"b": {"failure": "b"}}},
    )
    write_json(
        checkpoints / "checkpoint.gpu1.json",
        {"accepted": {"c": {"receipt": "c"}}, "failed": {"a": {"failure": "stale"}}},
    )

    result = merge_shard_checkpoints(evidence)

    assert result["merged_shard_count"] == 2
    merged = __import__("json").loads((checkpoints / "checkpoint.json").read_text(encoding="utf-8"))
    assert set(merged["accepted"]) == {"old", "a", "c"}
    assert set(merged["failed"]) == {"b"}


def test_merge_shard_checkpoints_normalizes_null_failed(tmp_path):
    evidence = tmp_path / "evidence"
    checkpoints = evidence / "checkpoints"
    write_json(checkpoints / "checkpoint.json", {"accepted": {}, "failed": None})
    write_json(checkpoints / "checkpoint.gpu0.json", {"accepted": {"a": {"receipt": 1}}, "failed": {}})

    result = merge_shard_checkpoints(evidence)

    merged = __import__("json").loads((checkpoints / "checkpoint.json").read_text(encoding="utf-8"))
    assert result["accepted"] == 1
    assert result["failed"] == 0
    assert merged["failed"] == {}


def test_translate_cmd_forces_configured_device(tmp_path):
    args = type(
        "Args",
        (),
        {
            "python": Path("python.exe"),
            "model": "m2m100_418m",
            "device": "cuda",
        },
    )()
    item = WorkItem(
        work_item_id="wid",
        source_path="source.md",
        target_path="target.md",
        locale="pt",
        relative_path="cells/cpp/_index.md",
        source_hash="hash",
    )

    cmd = build_translate_cmd(args, item, tmp_path / "translate.log")

    assert "--device" in cmd
    assert cmd[cmd.index("--device") + 1] == "cuda"


def test_extra_code_block_repair_restores_source_order_and_drops_duplicate():
    source = """Intro prose.

```shell
dotnet add package Aspose.Slides.Foss
```

More prose.

```csharp
using Aspose.Slides.Foss;
```
"""
    target = """Texte traduit.

```csharp
using Aspose.Slides.Foss;
```

Plus de texte.

```shell
dotnet add package Aspose.Slides.Foss
```

```csharp
using Aspose.Slides.Foss;
```
"""

    repaired = repair_extra_code_blocks_with_source_order(source, target)

    assert repaired.count("```shell") == 1
    assert repaired.count("```csharp") == 1
    assert repaired.index("```shell") < repaired.index("```csharp")


def test_known_scalar_repair_fixes_thai_words_python_title(tmp_path):
    source = tmp_path / "en" / "words" / "python" / "_index.md"
    target = tmp_path / "th" / "words" / "python" / "_index.md"
    write_page(
        source,
        """
---
layout: product
family_name: words
overview:
  title: Open-Source Python Library for Word Document Conversion
---
""",
    )
    write_page(
        target,
        """
---
layout: product
family_name: words
overview:
  title: ฟรีสํารองข้อมูล Python Library for Word Document Conversion
---
""",
    )

    result = repair_known_scalar_translations(products_profile(), HugoParser(), source, target, "th")

    assert result["changed"] is True
    assert "Library for Word Document Conversion" not in target.read_text(encoding="utf-8")


def test_verify_pair_rejects_code_fence_count_mismatch(tmp_path):
    source = tmp_path / "en" / "cells" / "cpp" / "_index.md"
    target = tmp_path / "fr" / "cells" / "cpp" / "_index.md"
    write_page(
        source,
        """
---
layout: product
family_name: Aspose.Cells
title: Aspose.Cells FOSS for C++
description: Build spreadsheet apps with Aspose.Cells for C++.
---
```cpp
auto workbook = Workbook("book.xlsx");
```
""",
    )
    write_page(
        target,
        """
---
layout: product
family_name: Aspose.Cells
title: Aspose.Cells FOSS pour C++
description: Creez des applications de feuille de calcul avec Aspose.Cells pour C++.
---
""",
    )

    comparison = verify_pair(products_profile(), HugoParser(), source, target, "fr")

    assert comparison["verdict"] == "REJECT_CODE_FENCE_MISMATCH"
    assert comparison["code_fence_differences"][0]["source_count"] == 1
    assert comparison["code_fence_differences"][0]["target_count"] == 0
    assert comparison["code_fence_differences"][0]["source_paths"] == ["$body"]


def test_verify_pair_rejects_mutated_code_block(tmp_path):
    source = tmp_path / "en" / "cells" / "cpp" / "_index.md"
    target = tmp_path / "de" / "cells" / "cpp" / "_index.md"
    write_page(
        source,
        """
---
layout: product
family_name: Aspose.Cells
title: Aspose.Cells FOSS for C++
description: Build spreadsheet apps with Aspose.Cells for C++.
---
```cpp
auto workbook = Workbook("book.xlsx");
```
""",
    )
    write_page(
        target,
        """
---
layout: product
family_name: Aspose.Cells
title: Aspose.Cells FOSS fur C++
description: Erstellen Sie Tabellenkalkulationsanwendungen mit Aspose.Cells fur C++.
---
```cpp
auto arbeitsmappe = Workbook("book.xlsx");
```
""",
    )

    comparison = verify_pair(products_profile(), HugoParser(), source, target, "de")

    assert comparison["verdict"] == "REJECT_CODE_BLOCK_MUTATED"
    assert comparison["code_block_differences"][0]["index"] == 0


def test_verify_pair_rejects_product_identity_corruption(tmp_path):
    source = tmp_path / "en" / "email" / "_index.md"
    target = tmp_path / "hi" / "email" / "_index.md"
    body = """
---
layout: product
family_name: Aspose.Email
title: Aspose.Email FOSS for Java
description: Build email processing apps with Aspose.Email for Java.
---
"""
    write_page(source, body)
    write_page(
        target,
        """
---
layout: product
family_name: Aspose.Email
title: Email Java
description: Java ke liye email apps banayen.
---
""",
    )

    comparison = verify_pair(products_profile(), HugoParser(), source, target, "hi")

    assert comparison["verdict"] == "REJECT_PRODUCT_IDENTITY_CHANGED"
    assert comparison["product_identity_differences"][0]["missing"] == ["Aspose.Email FOSS"]


def test_verify_pair_rejects_material_evidence_drift(tmp_path):
    source = tmp_path / "en" / "cells" / "_index.md"
    target = tmp_path / "pt" / "cells" / "_index.md"
    write_page(
        source,
        """
---
layout: product
family_name: Aspose.Cells
title: Aspose.Cells
description: Build spreadsheet apps with Aspose.Cells.
evidence:
  formats:
  - XLSX
  - CSV
---
""",
    )
    write_page(
        target,
        """
---
layout: product
family_name: Aspose.Cells
title: Aspose.Cells
description: Crie aplicativos de planilha com Aspose.Cells.
evidence:
  formats:
  - XLSX
---
""",
    )

    comparison = verify_pair(products_profile(), HugoParser(), source, target, "pt")

    assert comparison["verdict"] == "REJECT_STRUCTURAL_MISMATCH"
    assert comparison["list_length_differences"] == [{"path": "evidence.formats", "source_len": 2, "target_len": 1}]


def test_reverify_accepted_quarantines_failed_receipt(tmp_path):
    evidence = tmp_path / "evidence"
    checkpoint_path = evidence / "checkpoints" / "checkpoint.json"
    source = tmp_path / "en" / "email" / "_index.md"
    target = tmp_path / "sv" / "email" / "_index.md"
    write_page(
        source,
        """
---
layout: product
family_name: Aspose.Email
title: Aspose.Email FOSS for Java
description: Build email processing apps with Aspose.Email for Java.
---
""",
    )
    write_page(
        target,
        """
---
layout: product
family_name: Aspose.Email
title: Email - Email - Email - Email - Email - Email
description: Skapa e-postappar med Aspose.Email for Java.
---
""",
    )
    item = WorkItem(
        work_item_id="accepted_bad",
        source_path=str(source),
        target_path=str(target),
        locale="sv",
        relative_path="email/_index.md",
        source_hash=sha256_file(source),
    )
    checkpoint = {
        "run_id": "test_run",
        "accepted": {
            item.work_item_id: {
                "work_item_id": item.work_item_id,
                "target_hash": sha256_file(target),
                "config_hash": "old",
            }
        },
        "failed": {},
    }
    write_json(evidence / "per-file" / item.locale / f"{item.work_item_id}.receipt.json", checkpoint["accepted"][item.work_item_id])

    report = reverify_accepted_items(
        evidence_root=evidence,
        checkpoint_path=checkpoint_path,
        checkpoint=checkpoint,
        items=[item],
        profile=products_profile(),
        parser_obj=HugoParser(),
        policy_hash="new-policy",
        dry_run=False,
    )

    assert report["quarantined_accepts"] == 1
    assert checkpoint["accepted"] == {}
    assert checkpoint["failed"][item.work_item_id]["failure_type"] == "REJECT_PRODUCT_IDENTITY_CHANGED"
    assert (evidence / "quarantined-accepted" / "sv" / "accepted_bad.receipt.json").exists()
    assert (evidence / "accepted-reverification-failures" / "accepted_bad.json").exists()


def test_reverify_accepted_refreshes_stale_passing_receipt(tmp_path):
    evidence = tmp_path / "evidence"
    checkpoint_path = evidence / "checkpoints" / "checkpoint.json"
    source = tmp_path / "en" / "cells" / "_index.md"
    target = tmp_path / "fr" / "cells" / "_index.md"
    write_page(
        source,
        """
---
layout: product
family_name: Aspose.Cells
title: Aspose.Cells
description: Build spreadsheet apps with Aspose.Cells.
---
""",
    )
    write_page(
        target,
        """
---
layout: product
family_name: Aspose.Cells
title: Aspose.Cells
description: Creez des applications de feuille de calcul avec Aspose.Cells.
---
""",
    )
    item = WorkItem(
        work_item_id="accepted_good",
        source_path=str(source),
        target_path=str(target),
        locale="fr",
        relative_path="cells/_index.md",
        source_hash=sha256_file(source),
    )
    checkpoint = {
        "run_id": "test_run",
        "accepted": {
            item.work_item_id: {
                "work_item_id": item.work_item_id,
                "target_hash": sha256_file(target),
                "config_hash": "old",
            }
        },
        "failed": {},
    }

    report = reverify_accepted_items(
        evidence_root=evidence,
        checkpoint_path=checkpoint_path,
        checkpoint=checkpoint,
        items=[item],
        profile=products_profile(),
        parser_obj=HugoParser(),
        policy_hash="new-policy",
        dry_run=False,
    )

    assert report["refreshed_receipts"] == 1
    receipt = checkpoint["accepted"][item.work_item_id]
    assert receipt["config_hash"] == "new-policy"
    assert receipt["verifier_policy_version"] == VERIFIER_POLICY_VERSION


def test_product_identity_repair_restores_canonical_brand_before_verify(tmp_path):
    source = tmp_path / "en" / "3d" / "_index.md"
    target = tmp_path / "bg" / "3d" / "_index.md"
    write_page(
        source,
        """
---
layout: family
type: _default
head_title: Aspose.3D FOSS | Open-Source 3D File Processing Library
title: Aspose.3D FOSS
description: Load, create, transform, and export 3D scenes.
---
""",
    )
    write_page(
        target,
        """
---
layout: family
type: _default
head_title: 3D biblioteka za obrabotka na faylove
title: Apsos 3D FOSS
description: Zarezhdane, sazdavane i eksport na 3D stseny.
---
""",
    )

    repair = repair_target_product_identities(HugoParser(), source, target)
    comparison = verify_pair(products_profile(), HugoParser(), source, target, "bg")

    assert repair["changed"] is True
    assert {entry["path"] for entry in repair["repairs"]} == {"head_title", "title"}
    assert comparison["verdict"] == "VERIFIED_ACCEPT"
    repaired_text = target.read_text(encoding="utf-8")
    assert "head_title: Aspose.3D FOSS -" in repaired_text
    assert "title: Aspose.3D FOSS" in repaired_text


def test_material_copy_repair_restores_evidence_block(tmp_path):
    source = tmp_path / "en" / "3d" / "net" / "_index.md"
    target = tmp_path / "cs" / "3d" / "net" / "_index.md"
    write_page(
        source,
        """
---
layout: product
family_name: Aspose.3D
title: Aspose.3D FOSS for .NET
description: Build 3D apps with Aspose.3D for .NET.
evidence:
  formats:
  - ext: OBJ
    support: read-write
  claims:
  - MIT licensed
---
""",
    )
    write_page(
        target,
        """
---
layout: product
family_name: Aspose.3D
title: Aspose.3D FOSS pro .NET
description: Vytvarejte 3D aplikace s Aspose.3D pro .NET.
evidence:
  formats: []
  claims: []
---
""",
    )

    repair = repair_target_material_copy_fields(products_profile(), HugoParser(), source, target)
    comparison = verify_pair(products_profile(), HugoParser(), source, target, "cs")

    assert repair["changed"] is True
    assert comparison["verdict"] == "VERIFIED_ACCEPT"
    assert "ext: OBJ" in target.read_text(encoding="utf-8")


def test_code_block_repair_restores_source_blocks_inside_translatable_fields(tmp_path):
    source = tmp_path / "en" / "3d" / "net" / "_index.md"
    target = tmp_path / "cs" / "3d" / "net" / "_index.md"
    write_page(
        source,
        """
---
layout: product
family_name: Aspose.3D
title: Aspose.3D FOSS for .NET
description: Build 3D apps with Aspose.3D for .NET.
single:
  enable: true
  block:
  - title: Example
    content: |
      ```csharp
      using Aspose.ThreeD;
      // Load OBJ
      scene.Open("model.obj");
      ```
---
""",
    )
    write_page(
        target,
        """
---
layout: product
family_name: Aspose.3D
title: Aspose.3D FOSS pro .NET
description: Vytvarejte 3D aplikace s Aspose.3D pro .NET.
single:
  enable: true
  block:
  - title: Priklad
    content: |
      ```csharp
      using Aspose.ThreeD;
      // Nacist OBJ
      scene.Open("model.obj");
      ```
---
""",
    )

    before = verify_pair(products_profile(), HugoParser(), source, target, "cs")
    repair = repair_target_code_blocks(products_profile(), HugoParser(), source, target)
    after = verify_pair(products_profile(), HugoParser(), source, target, "cs")

    assert before["verdict"] == "REJECT_CODE_BLOCK_MUTATED"
    assert repair["changed"] is True
    assert after["verdict"] == "VERIFIED_ACCEPT"
    assert "// Load OBJ" in target.read_text(encoding="utf-8")
