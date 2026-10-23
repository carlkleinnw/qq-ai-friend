"""Patch the pinned upstream legacy editor without changing memory data."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil

ROOT = Path(__file__).resolve().parents[1]
RELATIVE = Path("pages/记忆面板/app.js")
ORIGINAL_SHA256 = "58b60bb7dcdec230b18e2f3e8c879dd055e6e35cc48bbb37f2f0c1ab786c5c6c"
LABELS = {
    "VISIBILITY_LABEL": {
        "private_pair": "仅当前私聊", "group_public": "群内共享",
        "bot_self": "仅 Bot 自身", "shareable": "允许共享", "internal": "内部记录",
    },
    "LIFECYCLE_LABEL": {
        "raw_event": "原始事件", "short_term_candidate": "短期候选",
        "stable_memory": "稳定记忆", "planned_projection": "计划预测", "archived": "归档",
    },
}
HELPER = '''
function memorySelectOptions(labels, current) {
  const value = compact(current);
  const choices = Object.assign({}, labels);
  if (!Object.prototype.hasOwnProperty.call(choices, value)) choices[value] = value || "保持空值";
  return Object.keys(choices).map((key) => '<option value="' + esc(key) + '"' +
    (value === key ? " selected" : "") + ">" + esc(choices[key]) + "</option>").join("");
}
'''


def patched_source(source: str, *, preserve_initial_navigation=True) -> str:
    for name, labels in LABELS.items():
        source, count = re.subn(
            rf"const {name} = \{{.*?\n\}};",
            "const " + name + " = " + json.dumps(labels, ensure_ascii=False, indent=2) + ";",
            source, count=1, flags=re.S,
        )
        if count != 1:
            raise ValueError(f"Missing upstream editor labels: {name}")
        field = "visibility" if name == "VISIBILITY_LABEL" else "lifecycle"
        source, count = re.subn(
            rf'Object.keys\({name}\)\.map\(.*?\.join\(""\)',
            f"memorySelectOptions({name}, memory.{field})", source, count=1,
        )
        if count != 1:
            raise ValueError(f"Missing upstream editor options: {name}")
    source = source.replace('const VALIDITY_LABEL = {', HELPER + '\nconst VALIDITY_LABEL = {', 1)
    source = source.replace('["", "public", "private", "group_shared", "bot_self", "restricted"]',
                            '["", ...Object.keys(VISIBILITY_LABEL)]', 1)
    source = source.replace('["", "active", "stable", "fading", "archived", "expired"]',
                            '["", ...Object.keys(LIFECYCLE_LABEL)]', 1)
    if preserve_initial_navigation:
        if source.count('  await go(target);') != 1:
            raise ValueError('Memory page boot navigation changed')
        source=source.replace('  await go(target);','  await go(renderToken > 0 ? state.view : target);',1)
    return source


def repair_panel(target: Path, original: bytes, backup: Path, *, check=False) -> bool:
    if hashlib.sha256(original).hexdigest() != ORIGINAL_SHA256:
        raise ValueError("Upstream version changed; review compatibility before applying this repair")
    replacement = patched_source(original.decode("utf-8")).encode("utf-8")
    current = target.read_bytes()
    if current == replacement:
        return True
    previous=patched_source(original.decode('utf-8'),preserve_initial_navigation=False).encode('utf-8')
    if current not in (original,previous):
        raise ValueError("Installed editor has other changes; refusing to overwrite them")
    if check:
        return False
    if shutil.disk_usage(target.parent).free < len(current) + len(replacement) + 1024 * 1024:
        raise OSError("Insufficient space for editor backup and replacement")
    backup.parent.mkdir(parents=True, exist_ok=True)
    if current==previous:
        navigation_backup=backup.with_name('app.js.before-navigation-guard')
        if not navigation_backup.exists():navigation_backup.write_bytes(current)
    if not backup.exists():
        backup.write_bytes(current)
    temporary = target.with_suffix(".js.tmp")
    temporary.write_bytes(replacement)
    os.replace(temporary, target)
    return True


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    fixed = repair_panel(
        ROOT / "runtime/app/data/plugins/astrbot_plugin_memory_companion" / RELATIVE,
        (ROOT / "runtime/vendor/memory_companion" / RELATIVE).read_bytes(),
        ROOT / "runtime/backups/memory-panel/app.js.before-repair", check=args.check,
    )
    print(json.dumps({"legacy_editor_repaired": fixed, "memory_data_changed": False}))
    if not fixed:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
