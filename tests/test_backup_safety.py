import hashlib
from pathlib import Path
import sys
from zipfile import ZipFile

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from native_backup import validate_archive, native_worker, ROOT


def test_restore_rejects_tampered_archive_before_import(tmp_path):
    archive = tmp_path / "backup.zip"
    archive.write_bytes(b"changed")
    with pytest.raises(ValueError, match="校验值"):
        validate_archive(archive, "0" * 64)


def test_old_backup_without_reminders_is_not_reported_as_complete(tmp_path):
    archive = tmp_path / "old-backup.zip"
    with ZipFile(archive, "w") as zipped:
        zipped.writestr("manifest.json", "{}")
        zipped.writestr("databases/main_db.json", '{"personas": []}')
        zipped.writestr("config/cmd_config.json", "{}")
    with pytest.raises(ValueError, match="缺少提醒"):
        validate_archive(archive, hashlib.sha256(archive.read_bytes()).hexdigest())


@pytest.mark.parametrize("name", ["../outside.txt", "directories/config/../../outside.txt", "C:/outside.txt", "\\outside.txt"])
def test_restore_rejects_escaping_paths(tmp_path, name):
    archive = tmp_path / "backup.zip"
    with ZipFile(archive, "w") as zipped:
        zipped.writestr(name, "fixture")
    with pytest.raises(ValueError, match="越界"):
        validate_archive(archive, hashlib.sha256(archive.read_bytes()).hexdigest())


def test_internal_restore_worker_refuses_live_or_existing_directories(tmp_path, monkeypatch):
    import asyncio
    monkeypatch.setenv("ASTRBOT_ROOT", str(ROOT / "runtime/app"))
    with pytest.raises(ValueError, match="拒绝覆盖"):
        asyncio.run(native_worker("_restore", tmp_path, None))


def test_native_backup_round_trip_restores_reminder_identity_and_state(tmp_path, monkeypatch):
    import asyncio
    import json
    from astrbot.core.backup.exporter import AstrBotExporter
    from astrbot.core.backup.importer import AstrBotImporter
    from astrbot.core.db.sqlite import SQLiteDatabase

    async def exercise():
        source = tmp_path / "source"
        destination = tmp_path / "destination"
        for root in [source, destination]:
            (root / "data").mkdir(parents=True)
        monkeypatch.setenv("ASTRBOT_ROOT", str(source))
        config = source / "data/cmd_config.json"
        config.write_text(json.dumps({"fixture_only": True}), encoding="utf-8")
        original = SQLiteDatabase(str(source / "data/data_v4.db"))
        restored = SQLiteDatabase(str(destination / "data/data_v4.db"))
        try:
            await original.initialize()
            job = await original.create_cron_job(
                name="reminder-backup-fixture", job_type="active_agent", cron_expression=None,
                run_once=True, enabled=False, persistent=True, status="failed",
                payload={"session": "fixture-bot:FriendMessage:fixture-user", "run_at": "2027-01-01T00:00:00+08:00"},
            )
            await original.update_cron_job(job.job_id, last_error="fixture delivery unknown")
            archive = await AstrBotExporter(original, config_path=str(config)).export_all(str(tmp_path / "archives"))
            monkeypatch.setenv("ASTRBOT_ROOT", str(destination))
            await restored.initialize()
            imported = await AstrBotImporter(restored, config_path=str(destination / "data/cmd_config.json")).import_all(archive)
            assert imported.success and not imported.errors and not imported.warnings
            actual = await restored.get_cron_job(job.job_id)
            assert actual is not None
            assert actual.payload == job.payload
            assert actual.status == "failed" and not actual.enabled and actual.run_once
            assert actual.last_error == "fixture delivery unknown"
        finally:
            await original.engine.dispose()
            await restored.engine.dispose()
    asyncio.run(exercise())
