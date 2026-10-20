from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts/service.py"
spec = importlib.util.spec_from_file_location("mvp_service", SCRIPT)
service = importlib.util.module_from_spec(spec)
spec.loader.exec_module(service)


def test_reused_process_id_is_never_accepted(tmp_path):
    state = tmp_path / "process.json"
    state.write_text(json.dumps({"pid": 12, "created": 100}))
    process = SimpleNamespace(create_time=lambda: 200)
    with patch.object(service, "STATE", state), patch.object(service.psutil, "Process", return_value=process):
        with pytest.raises(RuntimeError, match="identity changed"):
            service.managed_process()


def test_unrelated_executable_is_never_accepted(tmp_path):
    state = tmp_path / "process.json"
    state.write_text(json.dumps({"pid": 12, "created": 100}))
    process = SimpleNamespace(create_time=lambda: 100, exe=lambda: "C:/Windows/notepad.exe")
    with patch.object(service, "STATE", state), patch.object(service.psutil, "Process", return_value=process):
        with pytest.raises(RuntimeError, match="executable differs"):
            service.managed_process()
