"""Run the installed editor's actual option expressions in a browser."""
import importlib.util
from pathlib import Path
import re

import pytest
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("memory_panel_repair", ROOT / "scripts/repair_memory_panel.py")
repair = importlib.util.module_from_spec(spec)
spec.loader.exec_module(repair)


@pytest.fixture(scope="module")
def browser_page():
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(channel="msedge", headless=True)
        yield browser.new_page()
        browser.close()


@pytest.mark.parametrize("visibility,lifecycle", [
    ("private_pair", "stable_memory"), ("group_public", "short_term_candidate"),
    ("future_private<value>", "future_lifecycle"),
])
def test_editor_preserves_existing_access_and_lifecycle(browser_page, visibility, lifecycle):
    source = (ROOT / "runtime/app/data/plugins/astrbot_plugin_memory_companion" / repair.RELATIVE).read_text(encoding="utf-8")
    definitions = "\n".join(re.search(rf"const {name} = \{{.*?\n\}};", source, re.S)[0] for name in repair.LABELS)
    helper = re.search(r"function memorySelectOptions\(.*?\n\}", source, re.S)
    if helper:
        definitions += "\n" + helper[0]
    for field, value in (("Visibility", visibility), ("Lifecycle", lifecycle)):
        expression = re.search(rf'<select id="edit{field}">\'\s*\+\s*(.*?)\s*\+\s*"</select>', source, re.S)[1]
        html = browser_page.evaluate("""({definitions,expression,memory}) => {
          const compact = s => String(s ?? '').trim();
          const esc = s => String(s).replaceAll('&','&amp;').replaceAll('<','&lt;').replaceAll('"','&quot;');
          return new Function('memory','compact','esc', definitions+'; return '+expression)(memory,compact,esc);
        }""", {"definitions": definitions, "expression": expression, "memory": {"visibility": visibility, "lifecycle": lifecycle}})
        browser_page.set_content('<select id="actualEditor">' + html + '</select>')
        assert browser_page.locator("#actualEditor").input_value() == value
        assert browser_page.locator("select").count() == 1


def test_repair_is_idempotent_and_refuses_unrelated_changes(tmp_path):
    original = (ROOT / "runtime/vendor/memory_companion" / repair.RELATIVE).read_bytes()
    target = tmp_path / "app.js"
    backup = tmp_path / "backup.js"
    target.write_bytes(original)
    assert not repair.repair_panel(target, original, backup, check=True)
    assert repair.repair_panel(target, original, backup)
    assert repair.repair_panel(target, original, backup)
    assert backup.read_bytes() == original
    target.write_bytes(b"unrelated user changes")
    with pytest.raises(ValueError, match="other changes"):
        repair.repair_panel(target, original, backup)
    assert target.read_bytes() == b"unrelated user changes"
