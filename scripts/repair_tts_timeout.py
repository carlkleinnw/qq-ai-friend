"""Apply a pinned one-line timeout correction to the existing Edge TTS adapter."""
import hashlib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TARGET = ROOT / "runtime/conda/Lib/site-packages/astrbot/core/provider/sources/edge_tts_source.py"
ORIGINAL = "4efb2c13406e6458219eeb68b1eafe56e90a20c34c4946c4ce2b8807f48a3e24"
OLD = "await communicate.save(mp3_path)"
NEW = "await asyncio.wait_for(communicate.save(mp3_path), timeout=self.timeout)"


def repair(target=TARGET):
    data = target.read_bytes()
    if NEW.encode() in data:
        candidate = data.replace(NEW.encode(), OLD.encode(), 1)
        if hashlib.sha256(candidate).hexdigest() == ORIGINAL:
            return
    if hashlib.sha256(data).hexdigest() != ORIGINAL or data.count(OLD.encode()) != 1:
        raise ValueError("Adapter version changed; refusing to overwrite other code")
    backup = ROOT / "runtime/backups/edge_tts_source.py.before-timeout"
    backup.parent.mkdir(parents=True, exist_ok=True)
    if not backup.exists():
        backup.write_bytes(data)
    target.write_bytes(data.replace(OLD.encode(), NEW.encode(), 1))


if __name__ == "__main__":
    repair()
    print("Edge TTS network timeout verified; voice settings preserved.")
