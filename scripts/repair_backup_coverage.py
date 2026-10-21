"""Include native CronJob rows in the existing shared export/import model map."""
import hashlib
from pathlib import Path
from service import PYTHON

ROOT = Path(__file__).resolve().parents[1]
TARGET = PYTHON.parent / "Lib/site-packages/astrbot/core/backup/constants.py"
ORIGINAL = "4678bfc50a7d1af3794aeacf0c3411d7eeac8355716bc86d95206a189e3a972e"
CHANGES = [
    ("    ConversationV2,\n", "    ConversationV2,\n    CronJob,\n"),
    ('    "conversations": ConversationV2,\n', '    "conversations": ConversationV2,\n    "cron_jobs": CronJob,\n'),
]


def repair():
    data = TARGET.read_bytes()
    source = data.decode("utf-8")
    base = source
    for old, new in reversed(CHANGES):
        if new in base:
            base = base.replace(new, old, 1)
    if hashlib.sha256(base.encode()).hexdigest() != ORIGINAL:
        raise ValueError("Backup model map changed; refusing to overwrite other code")
    corrected = base
    for old, new in CHANGES:
        if corrected.count(old) != 1:
            raise ValueError("Backup source contract changed")
        corrected = corrected.replace(old, new, 1)
    if corrected == source:
        return
    backup = ROOT / "runtime/backups/backup_constants.py.before-cron-coverage"
    if not backup.exists():
        backup.write_bytes(data)
    TARGET.write_text(corrected, encoding="utf-8", newline="")


if __name__ == "__main__":
    repair()
    print("Native backup export/import now includes reminder tasks.")
