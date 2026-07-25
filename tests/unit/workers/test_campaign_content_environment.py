import os
from types import SimpleNamespace

import pytest

from src.workers.autonomous_content_translation_worker import (
    bind_campaign_content_environment,
)


def test_campaign_binds_aspose_org_root_to_manifest_checkout(tmp_path, monkeypatch):
    content_root = tmp_path / "content"
    content_root.mkdir()
    monkeypatch.setenv("ASPOSE_ORG_CONTENT", "D:/unrelated/checkout")

    resolved = bind_campaign_content_environment(SimpleNamespace(content_repo=str(tmp_path)))

    assert resolved == content_root.resolve()
    assert os.environ["ASPOSE_ORG_CONTENT"] == str(content_root.resolve())


def test_campaign_rejects_checkout_without_content_directory(tmp_path):
    with pytest.raises(ValueError, match="content directory is missing"):
        bind_campaign_content_environment(SimpleNamespace(content_repo=str(tmp_path)))
