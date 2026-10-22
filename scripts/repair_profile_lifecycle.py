"""Expose the pinned native profile lifecycle operation to packaged plugins."""
import hashlib
from pathlib import Path
from service import PYTHON

ROOT = Path(__file__).resolve().parents[1]
TARGET = PYTHON.parent / 'Lib/site-packages/astrbot/core/core_lifecycle.py'
ORIGINAL = '89ea4fe8e39713603c4434429fb90e79328b1ba430e1fa7717b73b5bdb13ca93'
OLD = b'        self.star_context.html_renderer = html_renderer\n'
NEW = OLD + b'        self.star_context.reload_pipeline_scheduler = self.reload_pipeline_scheduler\n'


def repair(target=TARGET):
    data = target.read_bytes()
    if data.count(NEW) == 1 and hashlib.sha256(data.replace(NEW, OLD, 1)).hexdigest() == ORIGINAL:
        return
    if hashlib.sha256(data).hexdigest() != ORIGINAL or data.count(OLD) != 1:
        raise ValueError('Native lifecycle version changed; refusing to overwrite other code')
    backup = ROOT / 'runtime/backups/core_lifecycle.py.before-profile-bridge'
    backup.parent.mkdir(parents=True, exist_ok=True)
    if not backup.exists():
        backup.write_bytes(data)
    target.write_bytes(data.replace(OLD, NEW, 1))


if __name__ == '__main__':
    repair()
    print('Native profile scheduler callback verified; message pipeline remains upstream.')
