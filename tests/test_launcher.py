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


def test_installed_environment_and_port_are_local_and_validated(tmp_path):
    config = tmp_path / 'installation.local.json'
    config.write_text(json.dumps({'environment': 'envs/locked', 'port': 6191}))
    assert service.installation_settings(tmp_path) == (tmp_path / 'envs/locked/python.exe', 6191)
    config.write_text(json.dumps({'environment': '../elsewhere', 'port': 6191}))
    with pytest.raises(ValueError, match='inside'):
        service.installation_settings(tmp_path)
    config.write_text(json.dumps({'port': True}))
    with pytest.raises(ValueError, match='port'):
        service.installation_settings(tmp_path)


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


def test_occupied_port_never_starts_a_second_process():
    with patch.object(service, "managed_process", return_value=None), \
         patch.object(service.socket, "socket") as socket, \
         patch.object(service.subprocess, "Popen") as launch:
        socket.return_value.__enter__.return_value.connect_ex.return_value = 0
        with pytest.raises(RuntimeError, match="another instance"):
            service.start(False)
        launch.assert_not_called()


def test_concurrent_launchers_share_a_process_lock(tmp_path):
    import subprocess
    import sys
    import time
    worker = tmp_path / "launcher_worker.py"
    worker.write_text("""
import importlib.util, pathlib, sys, time
spec=importlib.util.spec_from_file_location('service', sys.argv[1])
service=importlib.util.module_from_spec(spec);spec.loader.exec_module(service)
root=pathlib.Path(sys.argv[2]);name=sys.argv[3];service.RUNTIME=root
(root / ('ready-'+name)).touch()
while not (root / 'go').exists():time.sleep(.01)
def start(open_browser):
    with (root / 'trace').open('a') as f:f.write('start\\n')
    time.sleep(.2)
    with (root / 'trace').open('a') as f:f.write('end\\n')
service.start=start;sys.argv=['service.py','start','--no-browser'];service.main()
""", encoding="utf-8")
    processes = [subprocess.Popen([sys.executable, str(worker), str(SCRIPT), str(tmp_path), str(i)]) for i in range(2)]
    try:
        deadline = time.monotonic() + 10
        while len(list(tmp_path.glob("ready-*"))) < 2 and time.monotonic() < deadline:
            time.sleep(.02)
        assert len(list(tmp_path.glob("ready-*"))) == 2
        (tmp_path / "go").touch()
        for process in processes:
            assert process.wait(timeout=10) == 0
        assert (tmp_path / "trace").read_text().splitlines() == ["start", "end", "start", "end"]
    finally:
        for process in processes:
            if process.poll() is None:
                process.terminate()
                process.wait(timeout=5)
