"""guest.py — 来客の場（他人のサーバー）での作法。純粋判定・部屋バッファ・ターン局所状態。

三つの規則（元: フィオの guest_mode・2026-08-13 の裁定）:
  第一: 来客の場では宛名（メンション）が付いた時だけ答える。未メンションは完全に無視する
        （既読の気配も出さない）。
  第二: 音声チャンネルの出入りは所有者の命令でだけ。自動追従しない（この切り出しでは落とした）。
  第三: 話し手を見分け（所有者／来客）、答えるか・道具を使うかは bot の自律判断。
        迷ったら、まず来客に丁寧に返してから所有者の承認を取る——**返信が先、承認が後**。

構造:
  - チャットライブラリに依存しない。transport（受信側）が判定を呼び、ターンの前後で
    GuestTurn を set/clear し、プロンプトを組む側が current_block() を毎ターン呼ぶ。
  - ホーム（来客の場でない所）では should_respond が常に True、current_block が空文字
    ＝ **ホームの挙動は 1 bit も変わらない**。
  - 会話履歴が話し手ごとに分かれている bot では「友人の直前の発言を知らない」会話になる。
    部屋バッファ（部屋単位の直近発言）が場の共有文脈を補う。
"""
from __future__ import annotations

import contextvars
import re
from collections import deque
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Iterable, Iterator

from .hold import HoldLedger

# should_respond の理由コード（呼び手が分岐に使える・ログに刻める）
REASON_HOME = "home"                          # 来客の場ではない＝常に答える
REASON_NOT_ADDRESSED = "guest_not_addressed"  # 来客の場・宛名なし＝無視
REASON_HELD = "held"                          # 来客の場・宛名あり・保留中・来客＝流さない（台帳へ）
REASON_OWNER_WHILE_HELD = "owner_while_held"  # 来客の場・保留中でも所有者は通す
REASON_ADDRESSED = "guest_addressed"          # 来客の場・宛名あり＝答える

ROLE_OWNER = "owner"
ROLE_GUEST = "guest"


@dataclass(frozen=True)
class Decision:
    """答えるか（respond）と、その理由コード（reason）。bool() は respond と同じ。"""
    respond: bool
    reason: str

    def __bool__(self) -> bool:
        return self.respond


class GuestPolicy:
    """来客の場の判定。

    guest_place_ids : 来客の場（サーバー）の id の集まり。
    owner_id        : 所有者の id（None なら誰も所有者ではない）。
    holds           : HoldLedger。渡すと、札に載っている場も来客の場に数え、保留の旗を見る。
    """

    def __init__(self, guest_place_ids: Iterable[str] = (), owner_id: str | None = None,
                 holds: HoldLedger | None = None) -> None:
        self._places = frozenset(str(p).strip() for p in guest_place_ids if str(p).strip())
        self._owner_id = str(owner_id) if owner_id is not None else None
        self._holds = holds

    @property
    def owner_id(self) -> str | None:
        return self._owner_id

    @property
    def holds(self) -> HoldLedger | None:
        return self._holds

    def guest_place_ids(self) -> frozenset[str]:
        """来客の場の id（固定の集合 ＋ 札に載っている場）。札は毎回読む。"""
        ids = self._places
        if self._holds is not None:
            ids = ids | self._holds.place_ids()
        return ids

    def is_guest_place(self, place_id) -> bool:
        if place_id is None:
            return False
        return str(place_id) in self.guest_place_ids()

    def speaker_role(self, author_id) -> str:
        """話し手の役: "owner" か "guest"。"""
        if self._owner_id is not None and author_id is not None and str(author_id) == self._owner_id:
            return ROLE_OWNER
        return ROLE_GUEST

    def should_respond(self, place_id, mentioned: bool, author_id) -> Decision:
        """この一通に答えてよいか。

        - ホーム（来客の場でない）: 常に True。
        - 来客の場・宛名なし: False（所有者でも。宛名の無い一通には答えない）。
        - 来客の場・宛名あり・保留中: 所有者だけ True。来客は False（呼び手は台帳へ残す）。
        - 来客の場・宛名あり: True。答え方・道具の使い方は bot の自律判断。
        """
        if not self.is_guest_place(place_id):
            return Decision(True, REASON_HOME)
        if not mentioned:
            return Decision(False, REASON_NOT_ADDRESSED)
        if self._holds is not None and self._holds.is_held(place_id):
            if self.speaker_role(author_id) == ROLE_OWNER:
                return Decision(True, REASON_OWNER_WHILE_HELD)
            return Decision(False, REASON_HELD)
        return Decision(True, REASON_ADDRESSED)


def addressed(*, self_id, mention_ids: Iterable = (), role_mention_ids: Iterable = (),
              self_role_ids: Iterable = (), replied_author_id=None) -> bool:
    """この一通は自分宛か（純粋判定）。宛名と見る三つ:

      1. 自分へのユーザーメンション
      2. 自分が持つロールへのメンション（bot 用の同名ロール。補完で選ぶとこちらが入ることがある）
      3. 自分の発言への「返信」

    元の実測（2026-10-28）: ロール宛の三通が「メンション欄が空」なので未メンションとして
    捨てられていた。ユーザーメンションだけを見てはいけない。ロールは自分が持つものに限る
    ＝ everyone や無関係のロールでは起きない。
    """
    me = str(self_id)
    if any(str(m) == me for m in mention_ids or ()):
        return True
    mine = {str(r) for r in self_role_ids or ()}
    if mine and any(str(r) in mine for r in role_mention_ids or ()):
        return True
    if replied_author_id is not None and str(replied_author_id) == me:
        return True
    return False


def strip_mention(content: str, self_id, role_ids: Iterable = ()) -> str:
    """本文から自分宛のメンション（<@id> / <@!id> と、自分のロール <@&rid>）を除いた残り。"""
    if not content:
        return ""
    out = re.sub(r"<@!?" + re.escape(str(self_id)) + r">", "", content)
    for rid in role_ids or ():
        out = re.sub(r"<@&" + re.escape(str(rid)) + r">", "", out)
    return out.strip()


def speaker_label(name: str, is_owner: bool, owner_mark: str = "[owner]") -> str:
    """部屋バッファに刻む話し手の札。所有者の発言は印を頭に付け、来客と一目で見分ける。"""
    return f"{owner_mark} {name}" if is_owner else str(name)


class RoomBuffer:
    """部屋ごとの直近発言（場の共有文脈）。

    max_items : 1 部屋あたり保持する件数（元の既定 40）
    clip      : 1 発言の注入上限文字数（元の既定 200。超えた分は「…」）
    """

    def __init__(self, max_items: int = 40, clip: int = 200, owner_mark: str = "[owner]") -> None:
        self.max_items = int(max_items)
        self.clip = int(clip)
        self.owner_mark = owner_mark
        self._logs: dict[str, deque] = {}

    def _clip(self, text: str) -> str:
        text = " ".join((text or "").split())
        return text if len(text) <= self.clip else text[: self.clip] + "…"

    def push(self, room_id, speaker: str, text: str, *, is_owner: bool = False,
             attachments: str = "") -> str:
        """一発言を刻む。attachments（例 "[image: a.png]"）は本文の切り詰めを受けず後ろに付く。
        刻んだ一行を返す。"""
        log = self._logs.setdefault(str(room_id), deque(maxlen=self.max_items))
        body = self._clip(text)
        if attachments:
            body = f"{body} {attachments}" if body else attachments
        line = f"{speaker_label(speaker, is_owner, self.owner_mark)}: {body}"
        log.append(line)
        return line

    def recent(self, room_id) -> list[str]:
        return list(self._logs.get(str(room_id), ()))

    def clear(self, room_id) -> None:
        """部屋バッファを空にする（再起動後の埋め直しの前に使う）。"""
        self._logs.pop(str(room_id), None)

    def render(self, room_id, title: str = "recent in this room") -> str:
        """注入用の文。空の部屋なら ""（何も足さない）。"""
        lines = self.recent(room_id)
        if not lines:
            return ""
        out = [title] if title else []
        out.extend(f"- {ln}" for ln in lines)
        return "\n".join(out)


class GuestTurn:
    """ターン局所の状態（transport が set/clear、プロンプトを組む側が current_block を読む）。

    contextvars に置くので、複数の話し手の流れが並走しても話し手の名前が奪い合いにならない
    （元は 2026-08-25 に「プロセス全体のグローバル」から「タスク局所」へ移した）。
    来客のターンでない時、current_block() は ""——ホームの挙動は 1 bit も変わらない。
    """

    def __init__(self, rooms: RoomBuffer | None = None) -> None:
        self.rooms = rooms
        self._var: contextvars.ContextVar = contextvars.ContextVar("guest_gate_turn", default=None)

    def set(self, room_id, speaker_name: str, speaker_is_owner: bool,
            place: str | None = None, note: str | None = None) -> None:
        """place はこの場の名（例 "server-a / #general"）。bot が「自分がどのサーバーに
        居るのか」を探し回らないように注入へ載せる。note はその場についての一文。"""
        self._var.set({
            "room": str(room_id),
            "name": str(speaker_name),
            "is_owner": bool(speaker_is_owner),
            "place": place or None,
            "note": note or None,
        })

    def clear(self) -> None:
        self._var.set(None)

    def current(self) -> dict | None:
        return self._var.get()

    @contextmanager
    def open(self, room_id, speaker_name: str, speaker_is_owner: bool,
             place: str | None = None, note: str | None = None) -> Iterator[dict]:
        """with 文で set/clear を対にする。"""
        self.set(room_id, speaker_name, speaker_is_owner, place, note)
        try:
            yield self.current()
        finally:
            self.clear()

    def current_block(self, heading: str = "## Guest mode (a place where other people are; refreshed every turn)",
                      room_title: str = "(recent conversation in this room: the shared context of the room, "
                                        "separate from per-speaker history)") -> str:
        """来客のターン中だけ、話し手の役＋場の名＋場の共有文脈を返す。来客でなければ ""。
        行動指針の文は載せない——残すのは事実だけ（元の 2026-10-28 の裁定）。"""
        t = self._var.get()
        if t is None:
            return ""
        speaker = "owner" if t["is_owner"] else "guest " + repr(t["name"])
        lines = [heading, f"- current speaker: {speaker}"]
        if t.get("place"):
            lines.append(f"- current place: {t['place']}")
        if t.get("note"):
            lines.append(f"- about this place: {t['note']}")
        if self.rooms is not None:
            room = self.rooms.render(t["room"], title=room_title)
            if room:
                lines.append("")
                lines.append(room)
        return "\n".join(lines)
