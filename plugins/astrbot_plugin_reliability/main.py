"""Use native event hooks; do not replace chat, retry, or platform engines."""
import asyncio

from astrbot.api import logger
from astrbot.api.event import filter, AstrMessageEvent
from astrbot.api.star import Star, Context, StarTools

from .ledger import MessageLedger


class ReliabilityPlugin(Star):
    def __init__(self, context: Context, config):
        super().__init__(context)
        self.config = config
        self.ledger = MessageLedger(StarTools.get_data_dir("astrbot_plugin_reliability") / "received.db")

    @filter.event_message_type(filter.EventMessageType.ALL, priority=200000)
    async def reject_duplicate_delivery(self, event: AstrMessageEvent):
        scope = event.unified_msg_origin
        if scope.split(":", 1)[0] not in self.config.get("bot_ids", []):
            return
        message_id = str(getattr(event.message_obj, "message_id", "") or "")
        if not await asyncio.to_thread(self.ledger.claim, scope, message_id):
            logger.info("[AI好友] 已忽略重复投递的消息事件")
            event.stop_event()
