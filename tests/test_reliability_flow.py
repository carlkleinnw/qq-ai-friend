import asyncio
from types import SimpleNamespace
from plugins.astrbot_plugin_reliability.main import ReliabilityPlugin
from plugins.astrbot_plugin_reliability.ledger import MessageLedger

def test_message_hook_scopes_and_reopen(tmp_path):
    plugin=ReliabilityPlugin.__new__(ReliabilityPlugin)
    plugin.config={'bot_ids':['a','b']}
    plugin.ledger=MessageLedger(tmp_path/'received.db')
    def event(scope):
        ev=SimpleNamespace(unified_msg_origin=scope,message_obj=SimpleNamespace(message_id='audit-only'),stopped=False)
        ev.stop_event=lambda:setattr(ev,'stopped',True)
        return ev
    async def run():
        for scope in ['a:FriendMessage:one','a:FriendMessage:two','b:FriendMessage:one']:
            first=event(scope);await plugin.reject_duplicate_delivery(first);assert not first.stopped
            second=event(scope);await plugin.reject_duplicate_delivery(second);assert second.stopped
        plugin.ledger=MessageLedger(tmp_path/'received.db')
        replay=event('a:FriendMessage:one');await plugin.reject_duplicate_delivery(replay);assert replay.stopped
        ignored=event('disabled:FriendMessage:one')
        await plugin.reject_duplicate_delivery(ignored);await plugin.reject_duplicate_delivery(ignored);assert not ignored.stopped
    asyncio.run(run())
