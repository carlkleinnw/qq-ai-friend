"""Exercise the actual upstream memory store with QQ Official session identities.

These tests do not log into QQ or call a model service.
"""
from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock

ROOT = Path(__file__).resolve().parents[1]
PLUGIN = ROOT / "runtime/vendor/memory_companion"
sys.path.insert(0, str(PLUGIN / "tests"))
from package_bootstrap import bootstrap_package

bootstrap_package(PLUGIN)
from astrbot_plugin_memory_companion.core.models import SessionContext
from astrbot_plugin_memory_companion.core.service import MemoryCompanionService


class MemoryIntegrationTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(dir=ROOT / "runtime/temp")
        self.addCleanup(self.directory.cleanup)
        self.services = []

    def make_service(self):
        service = MemoryCompanionService(
            context=None,
            config={
                "retrieval": {"mode": "basic"},
                "memory_summary": {"enabled": False},
                "maintenance": {"auto_schedule_enabled": False},
                "memory_injection": {"enable_injection_logs": False},
            },
            plugin_root=PLUGIN,
            data_dir=Path(self.directory.name),
        )
        self.addCleanup(service.close)
        return service

    @staticmethod
    def context(user="owner-openid", scope="private", bot="bot-001", persona=""):
        kind = "FriendMessage" if scope == "private" else "GroupMessage"
        return SessionContext(
            session_id=f"qq-official-main:{kind}:{user}",
            scope=scope, platform="qq_official", user_id=user,
            user_name="验收用户", bot_id=bot, persona_id=persona,
            group_id="group-001" if scope == "group" else "",
            message_text="我喜欢哪家面馆？",
        )

    async def remember(self, service):
        service.identity.resolve_event_context = AsyncMock(return_value=self.context())
        result = await service.tool_remember(
            object(), "验收用户喜欢的面馆是云杉面馆。", note_type="preference"
        )
        self.assertTrue(result.get("ok"), result)
        return result

    async def recall(self, service, context):
        return await service._compose_memory_injection(context, max_chars=3200, write_log=False)

    async def test_qq_official_memory_survives_service_restart(self):
        first = self.make_service()
        await self.remember(first)
        self.assertIn("云杉面馆", await self.recall(first, self.context()))
        first.close()
        second = self.make_service()
        self.assertIn("云杉面馆", await self.recall(second, self.context()))

    async def test_private_memory_is_not_exposed_to_other_people_or_groups(self):
        service = self.make_service()
        await self.remember(service)
        self.assertNotIn("云杉面馆", await self.recall(service, self.context("other-openid")))
        self.assertNotIn("云杉面馆", await self.recall(service, self.context(scope="group")))
        self.assertNotIn("云杉面馆", await self.recall(service, self.context(bot="other-bot")))

    async def test_two_bot_persona_memories_remain_separate_after_restart(self):
        service = self.make_service()
        first = self.context(bot="qq-bot-a", persona="qq-friend")
        second = self.context(bot="qq-bot-b", persona="gpt-lord")
        for ctx, marker in ((first, "银杉馆"), (second, "蓝鹭馆")):
            service.identity.resolve_event_context = AsyncMock(return_value=ctx)
            result = await service.tool_remember(object(), f"验收用户最喜欢的面馆是{marker}。", note_type="preference")
            self.assertTrue(result.get("ok"), result)
        service.close()
        service = self.make_service()
        first_recall = await self.recall(service, first)
        second_recall = await self.recall(service, second)
        self.assertIn("银杉馆", first_recall)
        self.assertNotIn("蓝鹭馆", first_recall)
        self.assertIn("蓝鹭馆", second_recall)
        self.assertNotIn("银杉馆", second_recall)

    async def test_corrected_memory_replaces_old_recall_and_deleted_memory_stays_absent(self):
        service = self.make_service()
        created = await self.remember(service)
        memory_id = created["memory_id"]
        self.assertIn("云杉面馆", await self.recall(service, self.context()))
        self.assertTrue(await service.store.update_memory_payload(
            memory_id, content="验收用户喜欢的面馆是蓝鹭面馆。",
        ))
        corrected = await self.recall(service, self.context())
        self.assertIn("蓝鹭面馆", corrected)
        self.assertNotIn("云杉面馆", corrected)
        service.close()
        service = self.make_service()
        self.assertIn("蓝鹭面馆", await self.recall(service, self.context()))
        self.assertTrue(await service.store.delete_memory(memory_id))
        self.assertIsNone(await service.store.get_memory(memory_id))
        service.close()
        service = self.make_service()
        deleted = await self.recall(service, self.context())
        self.assertNotIn("蓝鹭面馆", deleted)
        self.assertNotIn("云杉面馆", deleted)


if __name__ == "__main__":
    unittest.main()
