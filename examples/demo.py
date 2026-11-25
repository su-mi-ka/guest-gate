"""demo.py — guest_gate の四つの場面を標準出力へ流す。

    python examples/demo.py

  1. 2 体の bot が往復し、上限で保険（構造）が止める
  2. 来客の場での宛名あり／なし、ホームでは常に答える
  3. 保留: 所有者だけ通す・流さなかった一通は台帳に残る
  4. 部屋バッファ（場の共有文脈）の描画と、ホームでは空になること
"""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from guest_gate import (  # noqa: E402
    BotFriendRegistry,
    ExchangeCounter,
    GuestPolicy,
    GuestTurn,
    HoldLedger,
    RoomBuffer,
)

ME = "bot-a"        # 自分
FRIEND = "bot-b"    # 友の bot（往復の上限 3）
OWNER = "u-owner"   # 所有者
VISITOR = "u1"      # 来客
GUEST_PLACE = "guild-a"
HOME_PLACE = "guild-home"
ROOM = "room-1"


def scene_bot_loop() -> None:
    print("== 1. bot-to-bot exchanges: structure stops them, not will ==")
    registry = BotFriendRegistry.from_list([{"id": FRIEND, "name": FRIEND, "max_exchange": 3}])
    counter = ExchangeCounter(registry)
    for i in range(1, 6):
        d = counter.on_message(ROOM, author_id=FRIEND, author_name=FRIEND, author_is_bot=True, self_id=ME)
        tail = "-> reply" if d.proceed else "-> structural stop"
        print(f"  {FRIEND} speaks #{i}: proceed={d.proceed} count={d.count} reason={d.reason} {tail}")
    d = counter.on_message(ROOM, author_id=VISITOR, author_is_bot=False, self_id=ME)
    print(f"  a human speaks: proceed={d.proceed} count={d.count} reason={d.reason} (counter reset)")
    d = counter.on_message(ROOM, author_id=ME, author_is_bot=True, self_id=ME)
    print(f"  {ME} hears itself: proceed={d.proceed} reason={d.reason} (self is never let through)")
    d = counter.on_message(ROOM, author_id="bot-z", author_name="bot-z", author_is_bot=True, self_id=ME)
    print(f"  an unregistered bot: proceed={d.proceed} reason={d.reason}")
    print()


def scene_guest_place() -> None:
    print("== 2. guest place: only when addressed. home: always ==")
    policy = GuestPolicy(guest_place_ids={GUEST_PLACE}, owner_id=OWNER)
    cases = [
        (GUEST_PLACE, False, VISITOR),
        (GUEST_PLACE, True, VISITOR),
        (GUEST_PLACE, False, OWNER),
        (HOME_PLACE, False, VISITOR),
    ]
    for place, mentioned, who in cases:
        d = policy.should_respond(place, mentioned=mentioned, author_id=who)
        print(f"  place={place:<10} mentioned={str(mentioned):<5} speaker={policy.speaker_role(who):<5}"
              f" -> respond={d.respond} ({d.reason})")
    print()


def scene_hold(tmp: Path) -> None:
    print("== 3. hold: only the owner gets through; what is not forwarded goes to the ledger ==")
    ledger = HoldLedger(tmp / "places.json", tmp / "held.jsonl")
    policy = GuestPolicy(guest_place_ids={GUEST_PLACE}, owner_id=OWNER, holds=ledger)
    print(f"  set_hold({GUEST_PLACE}, True) -> {ledger.set_hold(GUEST_PLACE, True)} (written, read back, matched)")
    for who, text in ((VISITOR, "hey, can you summarize this thread?"), (OWNER, "you may answer here now")):
        d = policy.should_respond(GUEST_PLACE, mentioned=True, author_id=who)
        print(f"  {policy.speaker_role(who):<5} mentions me -> respond={d.respond} ({d.reason})")
        if not d.respond:
            ledger.note_held(GUEST_PLACE, ROOM, who, text)
            print("        not forwarded, but not dropped: written to the ledger")
    print(f"  set_hold({GUEST_PLACE}, False) -> {ledger.set_hold(GUEST_PLACE, False)}")
    for rec in ledger.held_notes(GUEST_PLACE):
        print(f"  ledger: room={rec['room']} speaker={rec['speaker']} text={rec['text']!r}")
    print()


def scene_room_buffer() -> None:
    print("== 4. room buffer: shared context of the room; empty at home ==")
    rooms = RoomBuffer(max_items=40, clip=40)
    rooms.push(ROOM, "alice", "did anyone try the new build?")
    rooms.push(ROOM, "bob", "yes, " + "it works " * 12, attachments="[image: screenshot.png]")
    rooms.push(ROOM, "owner", "bot-a, what do you think?", is_owner=True)
    turn = GuestTurn(rooms)
    print("  outside a guest turn, current_block() is:", repr(turn.current_block()))
    with turn.open(ROOM, "alice", speaker_is_owner=False, place="server-a / #general",
                   note="a friend's place; answer briefly"):
        print("  inside a guest turn:")
        for line in turn.current_block().splitlines():
            print("   |", line)
    print()


def main() -> None:
    scene_bot_loop()
    scene_guest_place()
    with tempfile.TemporaryDirectory() as tmp:
        scene_hold(Path(tmp))
    scene_room_buffer()


if __name__ == "__main__":
    main()
