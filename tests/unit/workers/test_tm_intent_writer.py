import json
from pathlib import Path

from src.tm.intent_spool import TMIntentSpool
from src.tm.l2_persistent import L2PersistentTM
from src.tm.lmdb_registry import set_project_root
from src.workers import tm_intent_writer


def test_writer_cli_applies_one_spooled_intent_to_canonical_l2(tmp_path: Path, capsys):
    spool_path = tmp_path / "intents.sqlite"
    spool = TMIntentSpool(spool_path)
    spool.enqueue({
        "site_id": "docs.aspose.org", "src_lang": "en", "tgt_lang": "de",
        "text": "source", "translation": "ziel",
    })

    assert tm_intent_writer.main([
        "--repository-root", str(tmp_path), "--spool-path", str(spool_path), "--owner", "test", "--no-l3",
    ]) == 0
    assert json.loads(capsys.readouterr().out)["applied"] == 1
    set_project_root(tmp_path)
    l2 = L2PersistentTM(tmp_path / "data" / "tm" / "l2.lmdb")
    try:
        assert l2.exact_lookup("docs.aspose.org", "en", "de", "source").translation == "ziel"
    finally:
        l2.close()


def test_writer_cli_uses_configured_spool_limit_lease_and_l3_policy(tmp_path: Path, capsys):
    config_root = tmp_path / "config"
    config_root.mkdir()
    spool_path = tmp_path / "custom" / "intents.sqlite"
    (config_root / "global.yaml").write_text(
        "tm_writer:\n"
        "  intent_spool_path: " + json.dumps(str(spool_path)) + "\n"
        "  l3_enabled: false\n"
        "  batch_limit: 1\n"
        "  lease_seconds: 7\n",
        encoding="utf-8",
    )
    spool = TMIntentSpool(spool_path)
    for text in ("first", "second"):
        spool.enqueue({"site_id": "docs.aspose.org", "src_lang": "en", "tgt_lang": "de", "text": text, "translation": text})

    assert tm_intent_writer.main([
        "--repository-root", str(tmp_path), "--config-root", str(config_root), "--owner", "test",
    ]) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["applied"] == 1
    assert spool.stats()["PENDING"] == 1


def test_writer_config_rejects_invalid_lifecycle_values(tmp_path: Path):
    config_root = tmp_path / "config"
    config_root.mkdir()
    (config_root / "global.yaml").write_text(
        "tm_writer:\n  l3_enabled: nope\n", encoding="utf-8"
    )
    try:
        tm_intent_writer.load_tm_writer_config(config_root)
    except ValueError as exc:
        assert "l3_enabled" in str(exc)
    else:
        raise AssertionError("invalid writer config must fail closed")
