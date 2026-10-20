"""Exercise upstream bot-level config routing; no separate router is implemented."""
import unittest
from unittest.mock import AsyncMock

from astrbot.core.umop_config_router import UmopConfigRouter


class BotRoutingTests(unittest.IsolatedAsyncioTestCase):
    async def test_all_sessions_of_each_bot_select_its_own_profile(self):
        router = UmopConfigRouter(AsyncMock())
        await router.update_routing_data({"qq-bot-a::": "profile-a", "qq-bot-b::": "profile-b"})
        self.assertEqual("profile-a", router.get_conf_id_for_umop("qq-bot-a:FriendMessage:same-person"))
        self.assertEqual("profile-b", router.get_conf_id_for_umop("qq-bot-b:FriendMessage:same-person"))
        self.assertEqual("profile-b", router.get_conf_id_for_umop("qq-bot-b:GroupMessage:group:thread"))
        self.assertIsNone(router.get_conf_id_for_umop("unrelated-bot:FriendMessage:same-person"))
