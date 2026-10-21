from concurrent.futures import ThreadPoolExecutor
import importlib.util
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock
import unittest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("message_ledger", ROOT / "plugins/astrbot_plugin_reliability/ledger.py")
ledger = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ledger)


def test_duplicate_events_are_atomic_across_workers_and_restart(tmp_path):
    gate = ledger.MessageLedger(tmp_path / "events.db")
    with ThreadPoolExecutor(max_workers=8) as pool:
        admitted = list(pool.map(lambda _: gate.claim("bot-a:private:owner", "same-id"), range(16)))
    assert sum(admitted) == 1
    gate = ledger.MessageLedger(tmp_path / "events.db")
    assert not gate.claim("bot-a:private:owner", "same-id")
    assert gate.claim("bot-b:private:owner", "same-id")
    assert gate.claim("bot-a:private:owner", "different-id")
    assert gate.claim("bot-a:private:owner", "")


def test_deduplication_expiry_does_not_drop_later_messages(tmp_path):
    gate = ledger.MessageLedger(tmp_path / "events.db", ttl=60)
    assert gate.claim("bot", "msg", now=100)
    assert not gate.claim("bot", "msg", now=130)
    assert gate.claim("bot", "msg", now=161)


class NativeRecoveryTests(unittest.IsolatedAsyncioTestCase):
    async def test_edge_tts_honors_configured_network_timeout(self):
        import asyncio
        import time
        from unittest.mock import AsyncMock, patch
        from astrbot.core.provider.sources.edge_tts_source import ProviderEdgeTTS
        provider = ProviderEdgeTTS({"id": "timeout-test", "type": "edge_tts", "timeout": 0.02}, {})
        async def stalled_save(path):
            await asyncio.Event().wait()
        fake = SimpleNamespace(save=AsyncMock(side_effect=stalled_save))
        start = time.monotonic()
        with patch("astrbot.core.provider.sources.edge_tts_source.edge_tts.Communicate", return_value=fake):
            with self.assertRaisesRegex(RuntimeError, "音频生成失败") as error:
                await asyncio.wait_for(provider.get_audio("测试"), timeout=0.5)
        self.assertIsInstance(error.exception.__context__, asyncio.TimeoutError)
        self.assertLess(time.monotonic() - start, 0.25)

    async def test_qq_disconnect_queues_session_for_native_reconnect(self):
        from botpy.gateway import BotWebSocket
        connection = SimpleNamespace(parser=None, add=Mock())
        session = {"session_id": "session", "last_seq": 10}
        websocket = BotWebSocket(session, connection)
        await websocket.on_closed(1006, "test connection loss")
        connection.add.assert_called_once_with(session)
        self.assertEqual(session["session_id"], "session")

    async def test_native_model_request_retries_transient_failures(self):
        from astrbot.core.provider.sources.request_retry import retry_provider_request
        from unittest.mock import AsyncMock
        request = AsyncMock(side_effect=[ConnectionError("temporary"), "recovered"])
        self.assertEqual(await retry_provider_request("test", request, max_attempts=2), "recovered")
        self.assertEqual(request.await_count, 2)

    async def test_native_model_retry_is_bounded(self):
        from astrbot.core.provider.sources.request_retry import retry_provider_request
        from unittest.mock import AsyncMock
        request = AsyncMock(side_effect=ConnectionError("offline"))
        with self.assertRaises(ConnectionError):
            await retry_provider_request("test", request, max_attempts=2)
        self.assertEqual(request.await_count, 2)
