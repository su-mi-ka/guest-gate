"""hold.py — 場（サーバー）ごとの保留と、流さなかった一通の台帳。

考え方（元: フィオの guest_mode・2026-11-02 の裁定「あのサーバーでは許可を出すまで
メンション付けられても推論に流すな」）:

  - 旗はファイル（JSON の札の "hold"）に置き、**毎回読む**。どの経路で書いても
    （別プロセスで書いても）次の一通から効く。プロセスの再起動は要らない。
  - 所有者の発言は保留中でも通す（判定は GuestPolicy 側）。解く言葉がその場からも届くように、
    そして所有者を止める旗を bot が持たないように。
  - 流さなかった自分宛の一通は台帳（JSON Lines・追記だけ）に残す。**黙って消さない**——
    許可が出た時にここを読んで拾い直せる。

ファイルの形:
  path_json : [{"id": "guild-a", "name": "server a", "note": "...", "hold": true}, ...]
  path_jsonl: 1 行 1 件 {"t": "...", "place": "guild-a", "room": "room-1", "speaker": "...", "text": "..."}
"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path


class HoldLedger:
    """場の札（JSON）と保留台帳（JSON Lines）を扱う。どちらも読むたびにファイルを開く。"""

    def __init__(self, path_json, path_jsonl, *, text_clip: int = 500) -> None:
        self.path_json = Path(path_json)
        self.path_jsonl = Path(path_jsonl)
        self.text_clip = int(text_clip)

    # ── 札（JSON）────────────────────────────────────────────
    def table(self) -> list[dict]:
        """札の一覧。壊れている・無い時は空（保留は何処にも掛かっていない扱い）。"""
        try:
            data = json.loads(self.path_json.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return []
        if not isinstance(data, list):
            return []
        return [g for g in data if isinstance(g, dict) and g.get("id")]

    def place_ids(self) -> frozenset[str]:
        """札に載っている場の id。GuestPolicy が「来客の場」の集合に足して使える。"""
        return frozenset(str(g["id"]).strip() for g in self.table())

    def note_for(self, place_id) -> str | None:
        """その場の札の note（この場について bot に伝える一文）。無ければ None。"""
        for g in self.table():
            if str(g.get("id")).strip() == str(place_id) and g.get("note"):
                return str(g["note"])
        return None

    def is_held(self, place_id) -> bool:
        """この場が保留中か（札の "hold"）。"""
        pid = str(place_id)
        for g in self.table():
            if str(g.get("id")).strip() == pid:
                return bool(g.get("hold"))
        return False

    def set_hold(self, place_id, hold: bool) -> bool:
        """保留の旗を札に書く。札の無い場には札を作る（＝その場は来客の場として登録される。
        それを望まないなら呼ぶ前に is_guest_place で断ること）。
        書いた後に**読み戻して**、旗が合っていれば True。書けなければ False。"""
        pid = str(place_id)
        table = self.table()
        if not any(str(g.get("id")).strip() == pid for g in table):
            table.append({"id": pid})
        for g in table:
            if str(g.get("id")).strip() == pid:
                if hold:
                    g["hold"] = True
                else:
                    g.pop("hold", None)
        try:
            self.path_json.parent.mkdir(parents=True, exist_ok=True)
            with open(self.path_json, "w", encoding="utf-8") as f:
                json.dump(table, f, ensure_ascii=False, indent=2)
                f.write("\n")
        except OSError:
            return False
        return self.is_held(pid) == bool(hold)

    # ── 台帳（JSON Lines）──────────────────────────────────────
    def note_held(self, place_id, room_id, speaker, text) -> dict | None:
        """保留で流さなかった自分宛の一通を台帳に残す。残した記録を返す（書けなければ None）。"""
        rec = {
            "t": datetime.now().isoformat(timespec="seconds"),
            "place": str(place_id),
            "room": str(room_id),
            "speaker": str(speaker),
            "text": (text or "")[: self.text_clip],
        }
        try:
            self.path_jsonl.parent.mkdir(parents=True, exist_ok=True)
            with open(self.path_jsonl, "a", encoding="utf-8") as f:
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")
        except OSError:
            return None
        return rec

    def held_notes(self, place_id=None, limit: int = 50) -> list[dict]:
        """台帳を読む（書いた順の末尾 limit 件。place_id で絞れる）。壊れた行は飛ばす。"""
        if not limit or int(limit) <= 0:
            return []
        try:
            lines = self.path_jsonl.read_text(encoding="utf-8").splitlines()
        except OSError:
            return []
        out = []
        for ln in lines:
            try:
                rec = json.loads(ln)
            except ValueError:
                continue
            if place_id is None or str(rec.get("place")) == str(place_id):
                out.append(rec)
        return out[-int(limit):]
