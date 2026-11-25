"""柵: 登録簿の照合（id 優先・name 退路・discriminator）と、往復カウンタの保険。"""
from guest_gate import (
    REASON_FRIEND,
    REASON_HUMAN,
    REASON_LIMIT,
    REASON_SELF,
    REASON_UNKNOWN_BOT,
    BotFriendRegistry,
    ExchangeCounter,
    LoopDecision,
)

ROWS = [
    {"id": "bot-b", "name": "beta", "discriminator": "", "max_exchange": 3},
    {"name": "gamma", "discriminator": "1234", "max_exchange": 5},  # id 無し・旧形式
    {"name": "delta"},                                              # id 無し・discriminator 無し
    {"discriminator": "9999"},                                      # id も name も無い → 無効
    "garbage",                                                      # dict でない → 無効
]


def _registry(default_max=20):
    return BotFriendRegistry.from_list(ROWS, default_max=default_max)


# ── 登録簿 ───────────────────────────────────────────────────────
def test_from_list_skips_invalid_rows_and_fills_default_max():
    reg = _registry(default_max=7)
    assert len(reg) == 3
    assert [f.max_exchange for f in reg] == [3, 5, 7]
    assert BotFriendRegistry.from_list([{"id": "x", "max_exchange": "abc"}], default_max=4).match("x").max_exchange == 4


def test_match_prefers_id_and_never_falls_back_to_name_for_id_rows():
    reg = _registry()
    assert reg.match("bot-b", "someone-else").id == "bot-b"
    assert reg.match("bot-x", "beta") is None  # id を持つ行は name では照合しない
    assert reg.match(None, "beta") is None


def test_match_old_format_requires_discriminator_new_format_name_only():
    reg = _registry()
    assert reg.match("bot-g", "gamma", "1234").name == "gamma"
    assert reg.match("bot-g", "gamma", "4321") is None  # 旧形式どうしで不一致＝別人
    assert reg.match("bot-g", "gamma", "0").name == "gamma"  # 新形式は name のみ
    assert reg.match("bot-g", "gamma", "").name == "gamma"
    assert reg.match("bot-g", "gamma", None).name == "gamma"


def test_match_name_only_when_registry_has_no_discriminator():
    reg = _registry()
    assert reg.match("bot-d", "delta", "5555").name == "delta"
    assert reg.match("bot-d", "DELTA") is None  # 完全一致
    assert reg.is_friend("bot-d", "delta") is True
    assert reg.max_exchange_for("bot-d", "delta") == 20
    assert reg.max_exchange_for("nobody", default=9) == 9


def test_empty_registry_blocks_every_bot():
    reg = BotFriendRegistry.from_list([{"discriminator": "1"}])
    assert len(reg) == 0
    assert reg.is_friend("bot-b", "beta") is False
    counter = ExchangeCounter(reg)
    d = counter.on_message("r", author_id="bot-b", author_name="beta", author_is_bot=True, self_id="me")
    assert d.proceed is False
    assert d.reason == REASON_UNKNOWN_BOT
    # registry を渡さなくても同じ（safe default）
    d2 = ExchangeCounter().on_message("r", author_id="bot-b", author_is_bot=True, self_id="me")
    assert d2.proceed is False


# ── 往復カウンタ ─────────────────────────────────────────────────
def test_counter_increments_and_stops_past_limit():
    counter = ExchangeCounter(_registry())
    decisions = [counter.on_message("r", author_id="bot-b", author_is_bot=True, self_id="me")
                 for _ in range(5)]
    assert [d.proceed for d in decisions] == [True, True, True, False, False]
    assert [d.count for d in decisions] == [1, 2, 3, 4, 5]
    assert decisions[0].reason == REASON_FRIEND
    assert decisions[0].friend.name == "beta"
    assert decisions[3].reason == REASON_LIMIT
    assert bool(decisions[0]) is True
    assert bool(decisions[3]) is False
    # 部屋ごとに独立
    assert counter.on_message("r2", author_id="bot-b", author_is_bot=True, self_id="me").count == 1


def test_human_resets_counter():
    counter = ExchangeCounter(_registry())
    for _ in range(3):
        counter.on_message("r", author_id="bot-b", author_is_bot=True, self_id="me")
    assert counter.count("r") == 3
    d = counter.on_message("r", author_id="u1", author_name="alice", author_is_bot=False, self_id="me")
    assert d.proceed is True
    assert d.count == 0
    assert d.reason == REASON_HUMAN
    assert counter.count("r") == 0
    d2 = counter.on_message("r", author_id="bot-b", author_is_bot=True, self_id="me")
    assert d2.proceed is True
    assert d2.count == 1


def test_self_is_always_blocked_even_if_registered():
    reg = BotFriendRegistry.from_list([{"id": "me", "max_exchange": 99}])
    counter = ExchangeCounter(reg)
    d = counter.on_message("r", author_id="me", author_is_bot=True, self_id="me")
    assert d.proceed is False
    assert d.reason == REASON_SELF
    assert d.count == 0  # 数えもしない
    d2 = counter.on_message("r", author_id="me", author_is_bot=False, self_id="me")  # bot の旗が偽でも
    assert d2.proceed is False
    assert d2.reason == REASON_SELF


def test_unknown_bot_is_blocked_without_touching_the_count():
    counter = ExchangeCounter(_registry())
    counter.on_message("r", author_id="bot-b", author_is_bot=True, self_id="me")
    d = counter.on_message("r", author_id="bot-z", author_name="zeta", author_is_bot=True, self_id="me")
    assert d.proceed is False
    assert d.reason == REASON_UNKNOWN_BOT
    assert d.count == 1
    assert counter.count("r") == 1


def test_reset_and_decision_bool():
    counter = ExchangeCounter(_registry())
    counter.on_message("r", author_id="bot-b", author_is_bot=True, self_id="me")
    counter.reset("r")
    assert counter.count("r") == 0
    assert bool(LoopDecision(True, 1, "friend")) is True
    assert bool(LoopDecision(False, 0, "self")) is False
