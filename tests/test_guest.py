"""柵: 来客の場の三つの規則・保留・部屋バッファ・ターン局所状態。"""
import contextvars

import pytest

from guest_gate import (
    REASON_ADDRESSED,
    REASON_HELD,
    REASON_HOME,
    REASON_NOT_ADDRESSED,
    REASON_OWNER_WHILE_HELD,
    ROLE_GUEST,
    ROLE_OWNER,
    GuestPolicy,
    GuestTurn,
    HoldLedger,
    RoomBuffer,
    addressed,
    strip_mention,
)

GUEST = "guild-a"
HOME = "guild-home"
OWNER = "u-owner"
VISITOR = "u1"


@pytest.fixture
def policy():
    return GuestPolicy(guest_place_ids={GUEST}, owner_id=OWNER)


# ── 規則一: 来客の場では宛名が付いた時だけ ────────────────────────
def test_guest_place_unmentioned_is_ignored(policy):
    d = policy.should_respond(GUEST, mentioned=False, author_id=VISITOR)
    assert d.respond is False
    assert d.reason == REASON_NOT_ADDRESSED
    assert not d  # bool() は respond


def test_guest_place_unmentioned_owner_is_also_ignored(policy):
    # 宛名の無い一通には答えない。所有者でも例外ではない（既読の気配も出さない）
    assert policy.should_respond(GUEST, mentioned=False, author_id=OWNER).respond is False


def test_guest_place_mentioned_passes(policy):
    d = policy.should_respond(GUEST, mentioned=True, author_id=VISITOR)
    assert d.respond is True
    assert d.reason == REASON_ADDRESSED


def test_home_always_passes(policy):
    for mentioned in (True, False):
        for who in (OWNER, VISITOR):
            d = policy.should_respond(HOME, mentioned=mentioned, author_id=who)
            assert d.respond is True
            assert d.reason == REASON_HOME
    # 場が無い（DM など）のもホーム
    assert policy.should_respond(None, mentioned=False, author_id=VISITOR).reason == REASON_HOME


def test_is_guest_place_and_speaker_role(policy):
    assert policy.is_guest_place(GUEST)
    assert not policy.is_guest_place(HOME)
    assert not policy.is_guest_place(None)
    assert policy.speaker_role(OWNER) == ROLE_OWNER
    assert policy.speaker_role(VISITOR) == ROLE_GUEST
    # owner 未設定なら誰も所有者ではない
    assert GuestPolicy({GUEST}).speaker_role(OWNER) == ROLE_GUEST


# ── 保留: 所有者だけ通す ──────────────────────────────────────────
def test_hold_lets_only_owner_through(tmp_path):
    ledger = HoldLedger(tmp_path / "places.json", tmp_path / "held.jsonl")
    pol = GuestPolicy({GUEST}, owner_id=OWNER, holds=ledger)
    assert ledger.set_hold(GUEST, True)

    d_guest = pol.should_respond(GUEST, mentioned=True, author_id=VISITOR)
    assert d_guest.respond is False
    assert d_guest.reason == REASON_HELD

    d_owner = pol.should_respond(GUEST, mentioned=True, author_id=OWNER)
    assert d_owner.respond is True
    assert d_owner.reason == REASON_OWNER_WHILE_HELD

    # 解けば次の判定から通る（毎回読む＝再起動なし）
    assert ledger.set_hold(GUEST, False)
    assert pol.should_respond(GUEST, mentioned=True, author_id=VISITOR).reason == REASON_ADDRESSED


def test_hold_does_not_relax_rule_one(tmp_path):
    ledger = HoldLedger(tmp_path / "places.json", tmp_path / "held.jsonl")
    pol = GuestPolicy({GUEST}, owner_id=OWNER, holds=ledger)
    ledger.set_hold(GUEST, True)
    # 保留中でも、宛名の無い所有者の一通は規則一で止まる
    assert pol.should_respond(GUEST, mentioned=False, author_id=OWNER).reason == REASON_NOT_ADDRESSED


def test_held_message_is_kept_in_ledger_and_readable(tmp_path):
    ledger = HoldLedger(tmp_path / "places.json", tmp_path / "held.jsonl")
    pol = GuestPolicy({GUEST}, owner_id=OWNER, holds=ledger)
    ledger.set_hold(GUEST, True)
    d = pol.should_respond(GUEST, mentioned=True, author_id=VISITOR)
    assert d.reason == REASON_HELD
    # 流さなかった一通は黙って消さない——台帳へ
    ledger.note_held(GUEST, "room-1", "alice", "could you look at this?")
    notes = ledger.held_notes(GUEST)
    assert len(notes) == 1
    assert notes[0]["speaker"] == "alice"
    assert notes[0]["text"] == "could you look at this?"
    assert notes[0]["room"] == "room-1"


def test_ledger_places_count_as_guest_places(tmp_path):
    ledger = HoldLedger(tmp_path / "places.json", tmp_path / "held.jsonl")
    pol = GuestPolicy((), holds=ledger)
    assert not pol.is_guest_place("guild-b")
    ledger.set_hold("guild-b", True)  # 札の無い場に札を作る＝来客の場として登録される
    assert pol.is_guest_place("guild-b")
    assert pol.guest_place_ids() == frozenset({"guild-b"})


# ── 宛名の三つの形 ───────────────────────────────────────────────
def test_addressed_three_ways():
    assert addressed(self_id="bot", mention_ids=["bot"])
    assert addressed(self_id="bot", role_mention_ids=["r1"], self_role_ids=["r1"])
    assert not addressed(self_id="bot", role_mention_ids=["r2"], self_role_ids=["r1"])
    assert not addressed(self_id="bot", role_mention_ids=["r1"])  # 自分のロールを知らなければ通さない
    assert addressed(self_id="bot", replied_author_id="bot")
    assert not addressed(self_id="bot", mention_ids=["u1"], replied_author_id="u1")
    assert not addressed(self_id="bot")


def test_strip_mention():
    assert strip_mention("<@bot> hello", "bot") == "hello"
    assert strip_mention("<@!bot> hello", "bot") == "hello"
    assert strip_mention("<@&r1> hello", "bot", role_ids=["r1"]) == "hello"
    assert strip_mention("<@&r2> hello", "bot", role_ids=["r1"]) == "<@&r2> hello"
    assert strip_mention("<@other> hello", "bot") == "<@other> hello"
    assert strip_mention("", "bot") == ""


# ── 部屋バッファ ─────────────────────────────────────────────────
def test_room_buffer_limit_and_clip():
    rooms = RoomBuffer(max_items=3, clip=10)
    for i in range(5):
        rooms.push("r", "a", f"m{i}")
    assert rooms.recent("r") == ["a: m2", "a: m3", "a: m4"]  # 古い方から落ちる
    line = rooms.push("r", "b", "x" * 25)
    assert line == "b: " + "x" * 10 + "…"
    assert rooms.recent("other") == []


def test_room_buffer_owner_mark_whitespace_and_attachments():
    rooms = RoomBuffer(clip=5)
    line = rooms.push("r", "boss", "hello world", is_owner=True, attachments="[image: a.png]")
    assert line == "[owner] boss: hello… [image: a.png]"  # 添付の札は切り詰めを受けない
    assert rooms.push("r", "c", "a   b\n c") == "c: a b c"
    assert rooms.push("r", "d", "", attachments="[file: x.txt]") == "d: [file: x.txt]"


def test_room_buffer_render_empty_and_clear():
    rooms = RoomBuffer()
    assert rooms.render("r") == ""  # 空なら何も足さない
    rooms.push("r", "a", "hi")
    assert rooms.render("r", title="recent") == "recent\n- a: hi"
    assert rooms.render("r", title="") == "- a: hi"
    rooms.clear("r")
    assert rooms.render("r") == ""


# ── ターン局所状態 ────────────────────────────────────────────────
def test_guest_turn_block_is_empty_outside_guest_turn():
    rooms = RoomBuffer()
    rooms.push("r", "a", "hi")
    turn = GuestTurn(rooms)
    assert turn.current() is None
    assert turn.current_block() == ""  # 非ゲスト＝部屋にログが在っても 1 bit も足さない
    with turn.open("r", "alice", False, place="server-a / #general", note="a quiet place"):
        block = turn.current_block()
        assert "alice" in block
        assert "server-a / #general" in block
        assert "a quiet place" in block
        assert "- a: hi" in block
        assert "current speaker: guest" in block
    assert turn.current() is None
    assert turn.current_block() == ""


def test_guest_turn_owner_and_context_isolation():
    turn = GuestTurn()
    turn.set("r", "boss", True)
    assert "current speaker: owner" in turn.current_block()
    turn.clear()
    assert turn.current_block() == ""

    turn.set("r", "alice", False)
    ctx = contextvars.copy_context()
    ctx.run(turn.set, "r2", "bob", False)
    assert turn.current()["name"] == "alice"  # 別の流れの set は混ざらない
    assert ctx.run(turn.current)["name"] == "bob"
    turn.clear()
