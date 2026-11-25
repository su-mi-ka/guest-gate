"""柵: 保留の旗の往復と、流さなかった一通の台帳。"""
import json

from guest_gate import HoldLedger


def _ledger(tmp_path):
    return HoldLedger(tmp_path / "places.json", tmp_path / "held.jsonl")


def test_set_hold_round_trip(tmp_path):
    ledger = _ledger(tmp_path)
    assert ledger.is_held("guild-a") is False
    assert ledger.set_hold("guild-a", True) is True
    assert ledger.is_held("guild-a") is True
    data = json.loads((tmp_path / "places.json").read_text(encoding="utf-8"))
    assert data == [{"id": "guild-a", "hold": True}]

    assert ledger.set_hold("guild-a", False) is True
    assert ledger.is_held("guild-a") is False
    data = json.loads((tmp_path / "places.json").read_text(encoding="utf-8"))
    assert data == [{"id": "guild-a"}]  # 解いたら旗ごと消す（偽の旗を残さない）


def test_set_hold_keeps_other_fields_and_other_places(tmp_path):
    (tmp_path / "places.json").write_text(json.dumps([
        {"id": "guild-a", "name": "server a", "note": "be polite here"},
        {"id": "guild-b", "name": "server b"},
    ]), encoding="utf-8")
    ledger = _ledger(tmp_path)
    assert ledger.set_hold("guild-a", True)
    table = ledger.table()
    assert table[0]["name"] == "server a"
    assert table[0]["hold"] is True
    assert "hold" not in table[1]
    assert ledger.note_for("guild-a") == "be polite here"
    assert ledger.note_for("guild-b") is None
    assert ledger.place_ids() == frozenset({"guild-a", "guild-b"})


def test_set_hold_returns_false_when_it_cannot_write(tmp_path):
    blocked = tmp_path / "places.json"
    blocked.mkdir()  # ディレクトリには書けない
    ledger = HoldLedger(blocked, tmp_path / "held.jsonl")
    assert ledger.set_hold("guild-a", True) is False
    assert ledger.is_held("guild-a") is False


def test_note_held_and_held_notes(tmp_path):
    ledger = _ledger(tmp_path)
    rec = ledger.note_held("guild-a", "room-1", "alice", "please answer")
    assert rec["place"] == "guild-a"
    assert rec["room"] == "room-1"
    assert rec["speaker"] == "alice"
    assert rec["text"] == "please answer"
    assert rec["t"]
    ledger.note_held("guild-b", "room-9", "bob", "x" * 600)

    notes = ledger.held_notes()
    assert [n["speaker"] for n in notes] == ["alice", "bob"]  # 書いた順
    assert len(notes[1]["text"]) == 500  # 本文は 500 字で切る
    assert [n["speaker"] for n in ledger.held_notes("guild-a")] == ["alice"]
    assert ledger.held_notes("guild-zzz") == []
    assert [n["speaker"] for n in ledger.held_notes(limit=1)] == ["bob"]  # 末尾 limit 件
    assert ledger.held_notes(limit=0) == []


def test_held_notes_tolerate_missing_file_and_broken_lines(tmp_path):
    ledger = _ledger(tmp_path)
    assert ledger.held_notes() == []
    (tmp_path / "held.jsonl").write_text(
        '{"place": "g", "speaker": "a"}\nnot json\n{"place": "g", "speaker": "b"}\n',
        encoding="utf-8")
    assert [n["speaker"] for n in ledger.held_notes()] == ["a", "b"]


def test_table_tolerates_broken_or_wrong_shape_json(tmp_path):
    ledger = _ledger(tmp_path)
    assert ledger.table() == []  # 無い
    (tmp_path / "places.json").write_text("{not json", encoding="utf-8")
    assert ledger.table() == []
    assert ledger.is_held("guild-a") is False
    (tmp_path / "places.json").write_text(json.dumps({"id": "x"}), encoding="utf-8")  # list でない
    assert ledger.table() == []
    (tmp_path / "places.json").write_text(json.dumps([{"name": "no id"}, 3, {"id": "ok"}]), encoding="utf-8")
    assert ledger.place_ids() == frozenset({"ok"})  # id の無い行・dict でない行は飛ばす
