"""guest_gate — チャット bot を他人の場へ「出張」させる時の作法と、bot 同士の無限ループを
構造で止める保険。チャットライブラリに依存しない純粋判定。

    from guest_gate import GuestPolicy, RoomBuffer, GuestTurn, HoldLedger
    from guest_gate import BotFriendRegistry, ExchangeCounter
"""
from .bot_loop import (
    REASON_FRIEND,
    REASON_HUMAN,
    REASON_LIMIT,
    REASON_SELF,
    REASON_UNKNOWN_BOT,
    BotFriend,
    BotFriendRegistry,
    ExchangeCounter,
    LoopDecision,
)
from .guest import (
    REASON_ADDRESSED,
    REASON_HELD,
    REASON_HOME,
    REASON_NOT_ADDRESSED,
    REASON_OWNER_WHILE_HELD,
    ROLE_GUEST,
    ROLE_OWNER,
    Decision,
    GuestPolicy,
    GuestTurn,
    RoomBuffer,
    addressed,
    speaker_label,
    strip_mention,
)
from .hold import HoldLedger

__all__ = [
    "BotFriend", "BotFriendRegistry", "ExchangeCounter", "LoopDecision",
    "REASON_FRIEND", "REASON_HUMAN", "REASON_LIMIT", "REASON_SELF", "REASON_UNKNOWN_BOT",
    "Decision", "GuestPolicy", "GuestTurn", "RoomBuffer", "addressed", "speaker_label", "strip_mention",
    "REASON_ADDRESSED", "REASON_HELD", "REASON_HOME", "REASON_NOT_ADDRESSED", "REASON_OWNER_WHILE_HELD",
    "ROLE_GUEST", "ROLE_OWNER",
    "HoldLedger",
]
