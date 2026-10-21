"""Use AstrBot's exporter/importer; restore drills never start a bot or overwrite live data."""
from __future__ import annotations

import argparse
import asyncio
from datetime import datetime
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import shutil
import sqlite3
import subprocess
import sys
from zipfile import ZipFile

from filelock import FileLock
import service

ROOT = Path(__file__).resolve().parents[1]
LATEST = ROOT / "runtime/backups/latest-native.local.json"


def validate_archive(path: Path, expected_hash: str):
    with path.open("rb") as handle:
        digest = hashlib.file_digest(handle, "sha256").hexdigest()
    if digest != expected_hash:
        raise ValueError("备份校验值不符，请勿恢复")
    with ZipFile(path) as archive:
        for info in archive.infolist():
            name = PurePosixPath(info.filename.replace("\\", "/"))
            if name.is_absolute() or ".." in name.parts or any(":" in p for p in name.parts):
                raise ValueError("备份含越界路径")
        required = {"manifest.json", "databases/main_db.json", "config/cmd_config.json"}
        if not required.issubset(archive.namelist()) or archive.testzip():
            raise ValueError("备份不完整或已损坏")
        if "cron_jobs" not in json.loads(archive.read("databases/main_db.json")):
            raise ValueError("旧备份缺少提醒任务表，不能视为本版完整备份")
        size = sum(info.file_size for info in archive.infolist())
        if shutil.disk_usage(ROOT).free < size * 2 + 1024 ** 3:
            raise OSError("恢复验证所需的磁盘空间不足")


def worker_process(action: str, app_root: Path, output: Path, archive: Path | None = None):
    env = os.environ.copy()
    env.update(ASTRBOT_ROOT=str(app_root), PYTHONUTF8="1", PYTHONIOENCODING="utf-8",
               TEMP=str(ROOT / "runtime/temp"), TMP=str(ROOT / "runtime/temp"))
    command = [sys.executable, str(Path(__file__).resolve()), action, "--output", str(output)]
    if archive:
        command += ["--archive", str(archive)]
    with (ROOT / "runtime/backup-worker.log").open("ab") as log:
        subprocess.run(command, env=env, cwd=ROOT, stdout=log, stderr=log, check=True, timeout=600)


async def native_worker(action: str, output: Path, archive: Path | None):
    app = Path(os.environ["ASTRBOT_ROOT"]).resolve()
    if action == "_restore":
        allowed = (ROOT / "runtime/restore-checks").resolve()
        if (not app.is_relative_to(allowed) or app.name != "app"
                or app.exists() or output.resolve() != app.parent):
            raise ValueError("恢复演练只允许使用全新隔离目录，拒绝覆盖现有数据")
    from astrbot.core.backup.exporter import AstrBotExporter
    from astrbot.core.backup.importer import AstrBotImporter
    from astrbot.core.backup.constants import get_backup_directories
    from astrbot.core.db.sqlite import SQLiteDatabase

    data = app / "data"
    data.mkdir(parents=True, exist_ok=True)
    database = SQLiteDatabase(str(data / "data_v4.db"))
    await database.initialize()
    try:
        if action == "_export":
            output.mkdir(parents=True, exist_ok=True)
            path = await AstrBotExporter(database, config_path=str(data / "cmd_config.json")).export_all(str(output))
            checked_source_files = 0
            with ZipFile(path) as snapshot:
                if "cron_jobs" not in json.loads(snapshot.read("databases/main_db.json")):
                    raise ValueError("备份缺少提醒任务表")
                for name, directory in get_backup_directories().items():
                    source = Path(directory)
                    for file in source.rglob("*"):
                        if not file.is_file() or "__pycache__" in file.parts or file.suffix == ".pyc":
                            continue
                        member = "directories/" + name + "/" + file.relative_to(source).as_posix()
                        if snapshot.read(member) != file.read_bytes():
                            raise ValueError("备份未完整覆盖源文件")
                        checked_source_files += 1
            result = {"archive": path, "source_files_verified": checked_source_files, "reminder_table_included": True}
        else:
            importer = AstrBotImporter(database, config_path=str(data / "cmd_config.json"), kb_root_dir=str(data / "knowledge_base"))
            precheck = importer.pre_check(str(archive))
            if not precheck.valid or not precheck.can_import:
                raise ValueError("原生备份预检查未通过")
            imported = await importer.import_all(str(archive))
            if not imported.success or imported.errors or imported.warnings:
                raise RuntimeError("原生恢复存在错误或警告，请检查本机 backup-worker.log")
            # Compare a re-export of real restored SQLModel rows, not just ZIP extraction.
            reexported = await AstrBotExporter(database, config_path=str(data / "cmd_config.json")).export_all(str(output))
            with ZipFile(archive) as source, ZipFile(reexported) as restored:
                original = json.loads(source.read("databases/main_db.json"))
                actual = json.loads(restored.read("databases/main_db.json"))
                canonical = lambda rows: sorted(json.dumps(row, sort_keys=True, ensure_ascii=False) for row in rows)
                for name, rows in original.items():
                    if canonical(rows) != canonical(actual.get(name, [])):
                        raise ValueError("恢复后数据库记录不一致: " + name)
                checked_files = 0
                for name in source.namelist():
                    if name.startswith("directories/") or name == "config/cmd_config.json":
                        if source.read(name) != restored.read(name):
                            raise ValueError("恢复文件不一致")
                        checked_files += 1
            sqlite_checks = 0
            for path in data.rglob("*.db"):
                with sqlite3.connect(path) as connection:
                    if connection.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                        raise ValueError("恢复数据库完整性检查失败")
                    sqlite_checks += 1
            result = {"native_import_succeeded": True, "reexport_rows_equal": True,
                      "tables": len(original), "rows": sum(len(rows) for rows in original.values()),
                      "files_identical": checked_files, "sqlite_integrity_checks": sqlite_checks,
                      "bots_started_in_restore_directory": False}
        output.mkdir(parents=True, exist_ok=True)
        (output / "result.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    finally:
        await database.engine.dispose()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["create", "verify", "_export", "_restore"])
    parser.add_argument("--output", type=Path)
    parser.add_argument("--archive", type=Path)
    args = parser.parse_args()
    if args.action.startswith("_"):
        asyncio.run(native_worker(args.action, args.output, args.archive))
        return
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    if args.action == "create":
        size = sum(p.stat().st_size for p in (ROOT / "runtime/app/data").rglob("*") if p.is_file())
        if shutil.disk_usage(ROOT).free < size * 2 + 1024 ** 3:
            raise OSError("备份所需磁盘空间不足")
        output = ROOT / "runtime/backups/native" / stamp
        with FileLock(str(ROOT / "runtime/service.lock"), timeout=150):
            running = service.managed_process() is not None
            if running:
                print("正在短暂停止服务以生成一致备份，完成后自动恢复运行。", flush=True)
                service.run_action("stop")
            try:
                worker_process("_export", ROOT / "runtime/app", output)
                result = json.loads((output / "result.json").read_text(encoding="utf-8"))
                archive = Path(result["archive"])
                with archive.open("rb") as handle:
                    digest = hashlib.file_digest(handle, "sha256").hexdigest()
                validate_archive(archive, digest)
                LATEST.write_text(json.dumps({"archive": str(archive), "sha256": digest, "created_at": datetime.now().isoformat(),
                                              "source_files_verified": result["source_files_verified"], "reminder_table_included": True}, indent=2), encoding="utf-8")
            finally:
                if running:
                    service.run_action("start", open_browser=False)
        print("原生数据备份已完成，保存在 runtime/backups/native；内含私人数据，请勿公开。")
    else:
        latest = json.loads(LATEST.read_text(encoding="utf-8"))
        archive = Path(latest["archive"])
        validate_archive(archive, latest["sha256"])
        destination = ROOT / "runtime/restore-checks" / stamp
        destination.mkdir(parents=True, exist_ok=False)
        worker_process("_restore", destination / "app", destination, archive)
        result = json.loads((destination / "result.json").read_text(encoding="utf-8"))
        report = ROOT / "verification/backup-restore-checks.json"
        report.parent.mkdir(parents=True, exist_ok=True)
        report.write_text(json.dumps({"checked_at": datetime.now().isoformat(), "archive_sha256": latest["sha256"],
                                      **result, "source_files_verified": latest.get("source_files_verified"),
                                      "reminder_table_included": latest.get("reminder_table_included", False),
                                      "live_data_overwritten": False}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print("备份已在全新隔离目录恢复，并逐表、逐文件核对通过。未覆盖正在使用的数据。")


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        import traceback
        with (ROOT / "runtime/backup-worker.log").open("a", encoding="utf-8") as log:
            traceback.print_exc(file=log)
        print("备份或恢复演练未完成：" + type(error).__name__ + "。请查看本机 runtime/backup-worker.log；不会用恢复演练覆盖当前数据。", file=sys.stderr)
        raise SystemExit(1)
