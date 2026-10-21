"""Verify upstream reminder persistence, cancellation and ownership boundaries."""
import asyncio
from datetime import datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock

from astrbot.core.cron.manager import CronJobManager, CronJobSchedulingError
from astrbot.core.db.sqlite import SQLiteDatabase
from astrbot.core.tools.cron_tools import FutureTaskTool

ROOT = Path(__file__).resolve().parents[1]


class ReminderStoreTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.directory = TemporaryDirectory(dir=ROOT / "runtime/temp")
        self.db = SQLiteDatabase(str(Path(self.directory.name) / "reminders.db"))
        await self.db.initialize()
        self.manager = CronJobManager(self.db)
        await self.manager.start(SimpleNamespace())

    async def asyncTearDown(self):
        await self.manager.shutdown()
        # Upstream schedules next-run DB writes in background tasks. Finish
        # this fixture's writes before disposing its engine on Windows.
        pending = [
            task for task in asyncio.all_tasks()
            if task is not asyncio.current_task()
            and task.get_coro().__qualname__ == "SQLiteDatabase.update_cron_job"
        ]
        if pending:
            await asyncio.gather(*pending)
        await self.db.engine.dispose()
        self.directory.cleanup()

    async def test_once_survives_manager_restart_and_cancel_removes_db_and_schedule(self):
        due = datetime.now(timezone.utc) + timedelta(days=1)
        job = await self.manager.add_active_job(
            name="isolated-test", cron_expression=None, run_once=True, run_at=due,
            timezone="Asia/Shanghai", payload={"session": "bot-a:FriendMessage:user-a"},
        )
        await self.manager.shutdown()
        self.manager = CronJobManager(self.db)
        await self.manager.start(SimpleNamespace())
        self.assertEqual(due, self.manager.get_next_run_time(job.job_id))
        await self.manager.delete_job(job.job_id)
        self.assertIsNone(self.manager.get_next_run_time(job.job_id))
        self.assertIsNone(await self.db.get_cron_job(job.job_id))

    async def test_invalid_edit_preserves_recurring_schedule_and_timezone(self):
        job = await self.manager.add_active_job(
            name="weekday-test", cron_expression="0 8 * * mon-fri", payload={}, timezone="Asia/Shanghai",
        )
        original = self.manager.get_next_run_time(job.job_id)
        self.assertIsNotNone(original)
        with self.assertRaises(CronJobSchedulingError):
            await self.manager.update_job(job.job_id, cron_expression="invalid")
        self.assertEqual(original, self.manager.get_next_run_time(job.job_id))
        persisted = await self.db.get_cron_job(job.job_id)
        self.assertEqual("0 8 * * mon-fri", persisted.cron_expression)
        trigger = self.manager._build_trigger(persisted)
        self.assertEqual("Asia/Shanghai", str(trigger.timezone))

    async def test_failed_once_is_retained_disabled_after_restart_without_resending(self):
        job = await self.manager.add_active_job(
            name="failure-fixture", cron_expression=None, run_once=True,
            run_at=datetime.now(timezone.utc) + timedelta(days=1),
            payload={"session": "bot-a:FriendMessage:user-a"},
        )
        self.manager._run_active_agent_job = AsyncMock(side_effect=ConnectionError("fixture delivery failed"))
        await self.manager._run_job(job.job_id)
        failed = await self.db.get_cron_job(job.job_id)
        self.assertIsNotNone(failed)
        self.assertEqual(failed.status, "failed")
        self.assertIn("fixture delivery failed", failed.last_error)
        self.assertFalse(failed.enabled)
        self.assertIsNone(self.manager.get_next_run_time(job.job_id))
        await self.manager.shutdown()
        self.manager = CronJobManager(self.db)
        await self.manager.start(SimpleNamespace())
        self.manager._run_active_agent_job = AsyncMock()
        await self.manager._run_job(job.job_id)
        self.manager._run_active_agent_job.assert_not_awaited()
        self.assertFalse((await self.db.get_cron_job(job.job_id)).enabled)
        await self.manager.delete_job(job.job_id)

    async def test_successful_once_still_removed_after_execution(self):
        job = await self.manager.add_active_job(
            name="success-fixture", cron_expression=None, run_once=True,
            run_at=datetime.now(timezone.utc) + timedelta(days=1), payload={},
        )
        self.manager._run_active_agent_job = AsyncMock()
        await self.manager._run_job(job.job_id)
        self.manager._run_active_agent_job.assert_awaited_once()
        self.assertIsNone(await self.db.get_cron_job(job.job_id))

    async def test_cancelled_execution_is_not_recorded_as_success(self):
        job = await self.manager.add_active_job(
            name="cancel-fixture", cron_expression=None, run_once=True,
            run_at=datetime.now(timezone.utc) + timedelta(days=1), payload={},
        )
        entered = asyncio.Event()
        async def wait_until_cancelled(*args, **kwargs):
            entered.set()
            await asyncio.Event().wait()
        self.manager._run_active_agent_job = wait_until_cancelled
        task = asyncio.create_task(self.manager._run_job(job.job_id))
        await asyncio.wait_for(entered.wait(), timeout=2)
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task
        stored = await self.db.get_cron_job(job.job_id)
        self.assertEqual(stored.status, "failed")
        self.assertFalse(stored.enabled)

    async def test_restart_does_not_replay_an_interrupted_once(self):
        job = await self.manager.add_active_job(
            name="interrupted-fixture", cron_expression=None, run_once=True,
            run_at=datetime.now(timezone.utc) + timedelta(days=1), payload={},
        )
        await self.db.update_cron_job(job.job_id, status="running")
        await self.manager.shutdown()
        self.manager = CronJobManager(self.db)
        await self.manager.start(SimpleNamespace())
        stored = await self.db.get_cron_job(job.job_id)
        self.assertEqual(stored.status, "failed")
        self.assertFalse(stored.enabled)
        self.assertIsNone(self.manager.get_next_run_time(job.job_id))

    async def test_offline_missed_once_is_visible_as_failure_after_grace(self):
        job = await self.manager.add_active_job(
            name="missed-fixture", cron_expression=None, run_once=True, enabled=False,
            run_at=datetime.now(timezone.utc) - timedelta(minutes=10), payload={},
        )
        await self.db.update_cron_job(job.job_id, enabled=True)
        await self.manager.shutdown()
        self.manager = CronJobManager(self.db)
        await self.manager.start(SimpleNamespace())
        stored = await self.db.get_cron_job(job.job_id)
        self.assertEqual(stored.status, "failed")
        self.assertFalse(stored.enabled)
        self.assertIn("Missed while offline", stored.last_error)

    async def test_malformed_legacy_once_does_not_block_other_jobs_at_startup(self):
        valid = await self.manager.add_active_job(
            name="valid-after-malformed", cron_expression=None, run_once=True,
            run_at=datetime.now(timezone.utc) + timedelta(days=1), payload={},
        )
        malformed = await self.db.create_cron_job(
            name="malformed", job_type="active_agent", cron_expression=None,
            run_once=True, payload={"run_at": "not-a-date"}, enabled=True, persistent=True,
        )
        await self.manager.shutdown()
        self.manager = CronJobManager(self.db)
        await self.manager.start(SimpleNamespace())
        self.assertIsNotNone(self.manager.get_next_run_time(valid.job_id))
        self.assertIsNone(self.manager.get_next_run_time(malformed.job_id))


class ReminderOwnershipTests(unittest.IsolatedAsyncioTestCase):
    async def test_chat_cannot_cancel_another_bot_or_another_members_reminder(self):
        for owner_session, owner_sender in (("bot-b:FriendMessage:user", "user"), ("bot-a:FriendMessage:user", "other")):
            manager = SimpleNamespace(
                db=SimpleNamespace(get_cron_job=AsyncMock(return_value=SimpleNamespace(payload={"session": owner_session, "sender_id": owner_sender}))),
                delete_job=AsyncMock(),
            )
            event = SimpleNamespace(unified_msg_origin="bot-a:FriendMessage:user", get_sender_id=lambda: "user", get_message_type=lambda: None)
            wrapper = SimpleNamespace(context=SimpleNamespace(event=event, context=SimpleNamespace(cron_manager=manager)))
            result = await FutureTaskTool().call(wrapper, action="delete", job_id="protected")
            self.assertIn("error:", result)
            manager.delete_job.assert_not_awaited()
