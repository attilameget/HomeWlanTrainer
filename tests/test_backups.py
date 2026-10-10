"""Local settings backups omit secrets and do not replace the Claude key."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from kickr_pi.config import Settings, apply_persisted_settings, persisted_settings
from kickr_pi.storage.backups import create_backup, list_backups, read_backup, resolve_backup
from kickr_pi.storage.repository import Repository


@pytest.fixture(autouse=True)
def _clear_trainer_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("KICKR_TRAINER_MODE", raising=False)
    monkeypatch.delenv("KICKR_ALLOW_SIMULATED", raising=False)


def test_backup_file_omits_claude_key_and_garmin_tokens(tmp_path) -> None:
    data = tmp_path / "data"
    data.mkdir()
    token = tmp_path / "garmin_tokens.json"
    token.write_text('{"token":"secret-garmin"}', encoding="utf-8")

    settings = Settings()
    settings.ftp_w = 250
    settings.anthropic_api_key = "sk-ant-test"
    settings.plan_notes = "keep me"
    created = create_backup(
        data,
        persisted_settings(settings),
        None,
        now=datetime(2026, 10, 10, 10, 53, tzinfo=timezone.utc),
    )

    raw = (data / "backups" / created["id"]).read_text(encoding="utf-8")
    assert "sk-ant-test" not in raw
    assert "anthropic_api_key" not in raw
    assert "secret-garmin" not in raw
    assert token.read_text(encoding="utf-8") == '{"token":"secret-garmin"}'
    assert created["label"].startswith("10 Oct 2026,")


def test_restore_keeps_claude_key_already_on_disk(tmp_path) -> None:
    data = tmp_path / "data"
    data.mkdir()
    settings = Settings()
    settings.ftp_w = 250
    settings.anthropic_api_key = "sk-ant-test"
    settings.plan_notes = "keep me"
    repo = Repository(data / "kickr_pi.db")
    repo.save_settings(persisted_settings(settings))
    created = create_backup(data, persisted_settings(settings), None)

    settings.ftp_w = 180
    settings.plan_notes = "changed"
    settings.anthropic_api_key = "sk-ant-test"
    payload = read_backup(resolve_backup(data, created["id"]))
    kept = settings.anthropic_api_key
    apply_persisted_settings(settings, payload["settings"])
    settings.anthropic_api_key = kept
    repo.save_settings(persisted_settings(settings))

    saved = repo.get_settings()
    assert settings.ftp_w == 250
    assert settings.plan_notes == "keep me"
    assert settings.anthropic_api_key == "sk-ant-test"
    assert saved["ftp_w"] == 250
    assert saved["anthropic_api_key"] == "sk-ant-test"


def test_second_backup_in_the_same_second_is_a_new_file(tmp_path) -> None:
    data = tmp_path / "data"
    data.mkdir()
    moment = datetime(2026, 10, 10, 10, 53, tzinfo=timezone.utc)
    first = create_backup(data, {"ftp_w": 200}, None, now=moment)
    second = create_backup(data, {"ftp_w": 210}, None, now=moment)
    assert first["id"] != second["id"]
    assert second["id"].endswith("-2.json")
    listed = list_backups(data)
    assert [item["id"] for item in listed] == [second["id"], first["id"]]
    assert read_backup(resolve_backup(data, second["id"]))["settings"]["ftp_w"] == 210
