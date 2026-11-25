"""bot_loop.py — bot フレンドの登録簿と、bot 同士の往復を必ず止める保険。

照合方針（元: フィオの bot_friends・2026-06-10 改定「名前と責務を一致させ続ける」）:
  - id（数値ユーザー id）が登録されていれば最優先で照合する（不変・最も確実）。
  - id が空なら name で照合する（相手の数値 id を持っていない時の退路）。
    discriminator が両方意味を持つ（旧形式 "#1234"）なら一致を要求し、
    新形式（相手側が "0"/""/None）なら name 一致のみで通す。
  - id も name も無い行は無効として飛ばす。有効な行が一つも無ければ is_friend は常に False
    ＝ 従来どおり「bot は全部弾く」になる（safe default）。

★ 無限ループの歯止めは二層:
    主層   = bot の自律判断（「もう話すことはない」と毎ターン文脈で判断して黙る）。
             普段の終わり方はこちら（「基本は自律判断でスキップして終える」）。
    保険層 = 往復カウンタのハードリミット。bot が止まれなくても構造が必ず止める
             （**意志を信じず構造に賭ける**）。bot 同士のループは暴走時の被害
             （API 費用が無限）が大きいので保険を持つ。
  このモジュールは保険層。主層は bot 本体の側に居る。

★ 保険層は一つだけ置く。元では同じ役の関数が二箇所に在り、片方は誰からも呼ばれていなかった
  ——「保険層が在るのに数えない」という赤くならない壊れ方。だから呼ばれない方を畳んだ。
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

REASON_SELF = "self"                # 自分自身の発言＝絶対に通さない（自己ループ防止）
REASON_HUMAN = "human"              # 人間の発言＝通す。往復カウンタを 0 に戻す
REASON_UNKNOWN_BOT = "unknown_bot"  # 登録簿に無い bot＝通さない
REASON_FRIEND = "friend"            # bot フレンド＝通す（カウンタ +1）
REASON_LIMIT = "limit"              # bot フレンドだが往復の上限を超えた＝構造的に止める

_NEW_FORMAT_DISCRIMINATORS = ("0", "", "None")


@dataclass(frozen=True)
class BotFriend:
    name: str            # 相手の name と照合（id が空のとき使う）
    id: str              # 数値ユーザー id。空文字なら name 照合に切り替わる
    discriminator: str   # 旧形式タグ（例 "1234"）。空なら name のみで通す
    max_exchange: int    # この子との連続往復の保険上限


class BotFriendRegistry:
    """bot フレンドの登録簿（読み取り専用）。"""

    def __init__(self, friends: Iterable[BotFriend] = ()) -> None:
        self._friends: list[BotFriend] = list(friends)

    @classmethod
    def from_list(cls, rows: Iterable[dict], default_max: int = 20) -> "BotFriendRegistry":
        """[{"id": "...", "name": "...", "discriminator": "...", "max_exchange": 20}, ...] から作る。
        id も name も無い行は無効として飛ばす。"""
        friends = []
        for row in rows or ():
            if not isinstance(row, dict):
                continue
            fid = str(row.get("id", "") or "").strip()
            name = str(row.get("name", "") or "").strip()
            disc = str(row.get("discriminator", "") or "").strip()
            if not fid and not name:
                continue
            try:
                max_ex = int(row.get("max_exchange", default_max))
            except (TypeError, ValueError):
                max_ex = int(default_max)
            friends.append(BotFriend(name=name, id=fid, discriminator=disc, max_exchange=max_ex))
        return cls(friends)

    def __len__(self) -> int:
        return len(self._friends)

    def __iter__(self):
        return iter(self._friends)

    def match(self, author_id=None, author_name: str | None = None,
              author_discriminator: str | None = None) -> BotFriend | None:
        """相手を登録簿と照合し、一致した BotFriend を返す（なければ None）。"""
        aid = str(author_id or "")
        adisc = str(author_discriminator) if author_discriminator is not None else None
        for f in self._friends:
            if f.id:
                if aid and aid == f.id:
                    return f
                continue  # id を持つ行は name では照合しない
            if f.name and author_name == f.name:
                if f.discriminator and adisc and adisc not in _NEW_FORMAT_DISCRIMINATORS:
                    if adisc == f.discriminator:
                        return f
                    continue  # 旧形式どうしで不一致＝別人
                return f  # 新形式 or discriminator 未指定＝name 一致のみで通す
        return None

    def is_friend(self, author_id=None, author_name=None, author_discriminator=None) -> bool:
        return self.match(author_id, author_name, author_discriminator) is not None

    def max_exchange_for(self, author_id=None, author_name=None, author_discriminator=None,
                         default: int = 20) -> int:
        f = self.match(author_id, author_name, author_discriminator)
        return f.max_exchange if f else int(default)


@dataclass(frozen=True)
class LoopDecision:
    """通すか（proceed）、その部屋の往復数（count）、理由コード（reason）、当たった友（friend）。"""
    proceed: bool
    count: int
    reason: str
    friend: BotFriend | None = None

    def __bool__(self) -> bool:
        return self.proceed


Decision = LoopDecision  # 名前の別綴り


class ExchangeCounter:
    """部屋ごとの往復カウンタ＝保険層。

    - 自分自身の発言は常に止める（自己無限ループの防止。登録簿に自分が居ても通さない）。
    - 人間の発言は通し、その部屋のカウンタを 0 に戻す。
    - 登録簿に無い bot は止める。
    - bot フレンドの発言はカウンタを +1 し、その友の max_exchange を超えたら止める。
    """

    def __init__(self, registry: BotFriendRegistry | None = None, default_max: int = 20) -> None:
        self.registry = registry if registry is not None else BotFriendRegistry()
        self.default_max = int(default_max)
        self._counts: dict[str, int] = {}

    def count(self, room_id) -> int:
        return self._counts.get(str(room_id), 0)

    def reset(self, room_id) -> None:
        self._counts[str(room_id)] = 0

    def on_message(self, room_id, *, author_id, author_name: str | None = None,
                   author_discriminator: str | None = None, author_is_bot: bool,
                   self_id) -> LoopDecision:
        room = str(room_id)
        if self_id is not None and str(author_id) == str(self_id):
            return LoopDecision(False, self.count(room), REASON_SELF)
        if not author_is_bot:
            self._counts[room] = 0
            return LoopDecision(True, 0, REASON_HUMAN)
        friend = self.registry.match(author_id, author_name, author_discriminator)
        if friend is None:
            return LoopDecision(False, self.count(room), REASON_UNKNOWN_BOT)
        n = self.count(room) + 1
        self._counts[room] = n
        limit = friend.max_exchange if friend.max_exchange is not None else self.default_max
        if n > limit:
            return LoopDecision(False, n, REASON_LIMIT, friend)
        return LoopDecision(True, n, REASON_FRIEND, friend)
