# guest-gate

## Summary (English)

- Manners for a chat bot that "visits" someone else's server, plus a structural brake that always stops bot-to-bot loops.
- Pure decisions: no Discord / discord.py dependency, standard library only, Python 3.11+. Your transport (whatever receives messages) calls the decisions.
- Rule one: in a guest place, answer only when addressed (user mention, mention of a role the bot holds, or a reply to the bot). Unaddressed messages are ignored completely, owner included.
- Tells the owner from guests (`speaker_role`); home places are untouched: `should_respond` is always True and the prompt block is always `""` there, so not one bit of home behaviour changes.
- A per-room buffer (40 items, 200 chars each by default) supplies the shared context of the room that per-speaker histories lack.
- A hold flag per place, re-read from a JSON file on every decision (no restart needed), lets the owner mute a server until permission is given; only the owner gets through while held.
- Whatever is held back is written to an append-only JSON Lines ledger: never dropped silently, can be picked up later.
- Bot friends are matched by id first and by name as a fallback (old-style discriminator must match; new-style is name only); rows with neither id nor name are invalid, so an empty registry blocks every bot (safe default).
- `ExchangeCounter` is the insurance layer: count friend-bot messages per room, stop past `max_exchange`, reset on any human message, never let the bot itself through. "Bet on structure, not on will."
- 32 pytest tests, a runnable example in `examples/demo.py`, licence not decided yet.

## 何か

チャット bot を自分のサーバー（ホーム）の外、他人のサーバー（来客の場）へ「出張」させる時の作法を、
チャットライブラリに依存しない純粋判定として切り出したもの。合わせて、bot と bot が延々と
返事をし合う無限ループを**構造で**止める保険（往復カウンタ）を同梱する。

三つの部品:

| モジュール | 中身 |
|---|---|
| `guest_gate.guest` | `GuestPolicy`（答えるか・話し手の役）、`RoomBuffer`（部屋ごとの直近発言）、`GuestTurn`（ターン局所の状態と注入文）、`addressed` / `strip_mention`（宛名の判定と除去） |
| `guest_gate.hold` | `HoldLedger`（場ごとの保留の旗と、流さなかった一通の台帳） |
| `guest_gate.bot_loop` | `BotFriendRegistry`（bot フレンドの登録簿と照合）、`ExchangeCounter`（往復の保険） |

依存は標準ライブラリだけ。Discord の型は一つも出てこない。`fio` も import しない。

## なぜ注目に値するか

- **ホームの挙動は 1 bit も変えない。** 来客の場でない所では `should_respond` が常に True、注入文が常に `""`。
  出張の仕組みを足しても、家での振る舞いが変わらないことを設計で保証する。
- **返信が先、承認が後。** 来客に頼まれて迷ったら、まず来客に丁寧に返し、それから所有者の承認を取る。
  来客を待たせて所有者に伺いを立てる順ではない（承認の輸送はこの切り出しでは落とした。順序の思想だけ残す）。
- **黙って消さない。** 保留中の場で流さなかった自分宛の一通は、台帳（追記だけの JSON Lines）に残る。
  許可が出た日にそこから拾い直せる。「無視した」と「捨てた」は違う。
- **意志を信じず構造に賭ける。** bot 同士の往復を止める歯止めは二層。主層は bot 自身の自律判断
  （「もう話すことはない」と黙る）。保険層がこの `ExchangeCounter` で、bot が止まれなくても
  構造が必ず止める。bot 同士のループは暴走時の被害（API 費用が無限）が大きい。
- **保険層は一つだけ置く。** 元のコードでは同じ役の関数が二箇所に在り、片方は誰からも呼ばれていなかった。
  「保険層が在るのに数えない」は赤くならない壊れ方なので、呼ばれない方を畳み、一つにした。
- **場の共有文脈。** 会話履歴を話し手ごとに持つ bot は「友人の直前の発言を知らない」会話をする。
  部屋単位の直近発言バッファが、その穴を注入で補う。

## どう動くか（仕組み・名前の付いた考え方）

### 三つの規則（来客の場）

1. **宛名が付いた時だけ答える。** 未メンションは完全に無視（既読の気配も出さない）。所有者でも例外ではない。
2. 音声チャンネルの出入りは所有者の命令でだけ。自動追従しない。（この切り出しでは落とした）
3. **話し手を見分ける**（所有者／来客）。答えるか・道具を使うかは bot の自律判断。迷ったら返信が先・承認が後。

`GuestPolicy.should_respond(place_id, mentioned, author_id)` は `Decision(respond, reason)` を返す。
`reason` は理由コードで、呼び手が分岐やログに使える:

| reason | 意味 |
|---|---|
| `home` | 来客の場ではない＝常に答える |
| `guest_not_addressed` | 来客の場・宛名なし＝無視 |
| `guest_addressed` | 来客の場・宛名あり＝答える |
| `held` | 来客の場・宛名あり・保留中・来客＝流さない（呼び手は台帳へ） |
| `owner_while_held` | 保留中でも所有者は通す |

### 宛名の三つの形（`addressed`）

ユーザーメンションだけを見ると取りこぼす。元の実測では、bot 用の同名ロール宛に送られた三通が
「メンション欄が空」なので未メンションとして捨てられていた。宛名と見るのは
(1) 自分へのユーザーメンション (2) **自分が持つ**ロールへのメンション (3) 自分の発言への返信。
ロールは自分が持つものに限るので、everyone や無関係のロールでは起きない。

### 保留（`HoldLedger`）

- 旗は JSON の札（`{"id": "guild-a", "hold": true}`）に置き、**毎回読む**。別プロセスから書いても次の一通から効く。再起動は要らない。
- 所有者の発言は保留中でも通す。解く言葉がその場からも届くように、そして所有者を止める旗を bot が持たないように。
- `set_hold` は書いた後に**読み戻して**旗が合っているかを確かめ、合っていれば True。
- `set_hold` は札の無い場に札を作る＝その場を来客の場として登録してしまう。望まないなら先に `is_guest_place` で断る。
- 流さなかった一通は `note_held` で台帳へ。`held_notes(place_id, limit)` で末尾から読む。本文は 500 字で切る。

### 部屋バッファ（`RoomBuffer`）と注入文（`GuestTurn`）

- 1 部屋 40 件・1 発言 200 字（既定）。超えた分は古い方から落ち、長い発言は `…` で切る。
- 所有者の発言には印（既定 `[owner]`）を頭に付け、来客と一目で見分ける。
- 添付の札（例 `[image: a.png]`）は本文の切り詰めを受けずに後ろへ付く。
- `GuestTurn` は **contextvars** に置く。複数の話し手の流れが並走しても、話し手の名前が奪い合いにならない
  （元はプロセス全体のグローバルだったものを、タスク局所へ移した）。
- `GuestTurn.current_block()` は来客のターン中だけ「今の話し手・今いる場・場の一文・部屋の直近の会話」を返す。
  行動指針の文は載せない——**残すのは事実だけ**。来客のターンでなければ `""`。

### 登録簿と保険（`BotFriendRegistry` / `ExchangeCounter`）

- 照合は **id が最優先**（不変・最も確実）。id が空の行だけ name で照合する（相手の数値 id を持っていない時の退路）。
  discriminator が両方意味を持つ（旧形式）なら一致を要求し、新形式（相手側が `"0"` / `""` / None）なら name 一致のみで通す。
  id を持つ行は name では照合しない。id も name も無い行は無効。
- `ExchangeCounter.on_message(...)` は `LoopDecision(proceed, count, reason, friend)` を返す:

| reason | 動き |
|---|---|
| `self` | 自分自身の発言。**常に止める**（登録簿に自分が居ても、bot の旗が偽でも） |
| `human` | 人間の発言。通して、その部屋のカウンタを 0 に戻す |
| `unknown_bot` | 登録簿に無い bot。止める（カウンタは触らない） |
| `friend` | bot フレンド。カウンタ +1 で通す |
| `limit` | bot フレンドだが `max_exchange` を超えた。構造的に止める |

## 使い方

```python
import contextlib
from guest_gate import GuestPolicy, HoldLedger, RoomBuffer, GuestTurn
from guest_gate import BotFriendRegistry, ExchangeCounter

MY_ID = "bot-a"
ledger = HoldLedger("data/places.json", "data/held.jsonl")
policy = GuestPolicy(guest_place_ids={"guild-a"}, owner_id="u-owner", holds=ledger)
rooms = RoomBuffer()
turn = GuestTurn(rooms)
counter = ExchangeCounter(BotFriendRegistry.from_list([{"id": "bot-b", "max_exchange": 20}]))

def on_message(msg):  # msg はあなたのチャットライブラリの型。必要な値だけ取り出して渡す
    loop = counter.on_message(msg.room_id, author_id=msg.author_id, author_name=msg.author_name,
                              author_is_bot=msg.author_is_bot, self_id=MY_ID)
    if not loop:                      # 自分・知らない bot・上限超え
        return
    is_owner = policy.speaker_role(msg.author_id) == "owner"
    rooms.push(msg.room_id, msg.author_name, msg.text, is_owner=is_owner)   # 答えなくても刻む
    d = policy.should_respond(msg.place_id, mentioned=msg.mentions_me, author_id=msg.author_id)
    if d.reason == "held":
        ledger.note_held(msg.place_id, msg.room_id, msg.author_name, msg.text)  # 黙って消さない
    if not d:
        return
    opened = (turn.open(msg.room_id, msg.author_name, is_owner, place=msg.place_name)
              if policy.is_guest_place(msg.place_id) else contextlib.nullcontext())
    with opened:
        extra = turn.current_block()  # ホームでは ""
        reply = think(extra, msg.text)
    rooms.push(msg.room_id, "me", reply)
```

所有者が「あのサーバーでは許可を出すまで答えるな」と言ったら `ledger.set_hold("guild-a", True)`。
解いたら `ledger.held_notes("guild-a")` で、その間に来た自分宛を読める。

動く例:

```
cd <このフォルダ>
python examples/demo.py
```

四つの場面（bot 同士の往復が上限で止まる／来客の場での宛名あり・なし／保留と台帳／部屋バッファの描画）を標準出力に流す。

## 出所

フィオ本体の次の箇所を読み、単体で動く形へ書き直した（丸写しではない）。

| 本体 | 中身 | ここでの対応 |
|---|---|---|
| `fio/guest_mode.py:1-17` | 三つの規則と構造（discord に依存しない・transport が判定を呼ぶ・非ゲストでは空文字） | モジュール docstring・`GuestPolicy`・`GuestTurn` |
| `fio/guest_mode.py:26-27` | 部屋バッファの既定（40 件・200 字） | `RoomBuffer(max_items=40, clip=200)` |
| `fio/guest_mode.py:36-77` | 鯖の札（JSON と env の両方・毎回読む）・`is_guest_guild`・札の note | `HoldLedger.table/place_ids/note_for`・`GuestPolicy.is_guest_place` |
| `fio/guest_mode.py:80-161` | 保留（`is_held`・`hold_blocks`・`set_hold` の読み戻し・`note_held`・`held_notes`） | `HoldLedger`・`should_respond` の `held` / `owner_while_held` |
| `fio/guest_mode.py:164-201` | `strip_bot_mention`・`addressed`（宛名の三つの形） | `strip_mention`・`addressed` |
| `fio/guest_mode.py:248-262`, `303-323` | 部屋バッファ（`_clip`・所有者の印・`note_utterance`・`room_lines`） | `RoomBuffer` |
| `fio/guest_mode.py:336-355` | ターン局所状態（contextvars へ移した経緯） | `GuestTurn.set/clear/open` |
| `fio/guest_mode.py:396-418` | `current_guest_block`（事実だけ・非ゲストは `""`） | `GuestTurn.current_block` |
| `fio/core/bot_friends.py:2-38` | 照合方針・二層の歯止め・保険層を一つに畳んだ記録 | `bot_loop` の docstring |
| `fio/core/bot_friends.py:52-124` | `BotFriend`・`BotFriendRegistry`（`load`・`_match`） | `BotFriend`・`BotFriendRegistry.from_list/match` |
| `fio/discord_bot/events.py:52-55` | `_bot_exchange_count`（channel → int）の定義と役割 | `ExchangeCounter._counts` |
| `fio/discord_bot/events.py:849-859` | 自分自身は絶対に通さない・登録簿に無い bot は弾く | `reason` の `self` / `unknown_bot` |
| `fio/discord_bot/events.py:871-884` | 来客の場の関所（場か → 宛名か → 保留か） | `should_respond` の順序 |
| `fio/discord_bot/events.py:904-913` | friend bot で +1・上限超えで return | `reason` の `friend` / `limit` |
| `fio/discord_bot/events.py:941-942` | 人間の発言で 0 に戻す | `reason` の `human` |
| `fio/discord_bot/events.py:1526-1534` | 保留で流さなかった一通を台帳へ | `HoldLedger.note_held` |
| `fio/discord_bot/events.py:1117-1121`, `1179`・`fio/voice/sink.py:858-870` | transport が部屋に刻み、ターンを set/clear する配線 | 「使い方」の流れ |

## フィオ本体との違い

落としたもの:

- Discord の型を受ける皮（`is_addressed(message, bot_user)`・`bot_role_ids_of`・`attachment_notes`）。ここでは id や旗を取り出して渡す。
- 音声チャンネルの出入り（規則二・`match_vc_command`・join/leave）。
- 所有者の承認を取る輸送（承認ダイアログ）。「返信が先・承認が後」の順序だけ思想として残した。
- env による場の登録（カンマ区切りの環境変数）。登録は引数か札の JSON で。
- 呼ばれたターンが開いている間だけ、未メンションの発言を割り込みとして渡す仕組み（部屋→持ち主の表）。
- 相手（bot フレンド）のターンに往復数と上限を文脈へ載せる「相手の門」。
- 起動時に一度読むシングルトンの登録簿（`get_registry`）とログ出力。ここでは `from_list` で作り、保持は呼び手に任せる。

単純化・置き換え:

- 判定の結果を bool ではなく `Decision(respond, reason)` / `LoopDecision(proceed, count, reason, friend)` で返す（`bool()` は従来どおり）。
- モジュール変数だった部屋バッファ・ターン局所状態・往復カウンタを、インスタンス（`RoomBuffer` / `GuestTurn` / `ExchangeCounter`）に持たせた。bot を複数動かしても混ざらない。
- 台帳のキー `guild` → `place`、所有者の印を `[owner]` に、注入文の見出しを英語に。
- 登録簿の照合メソッドは author オブジェクトではなく `(author_id, author_name, author_discriminator)` を受ける。
- 「ゲストでないなら空」の責務は `GuestTurn.current_block()`（ターンが開いていなければ `""`）に置いた。`RoomBuffer.render` は部屋が空なら `""`。

変えていないもの: 三つの規則の順序、宛名の三つの形、保留中に所有者だけ通すこと、流さなかった一通を台帳に残すこと、id 優先・name 退路・discriminator の扱い、無効行の飛ばし方、往復カウンタの数え方（friend で +1・上限超えで止める・人間で 0・自分は常に止める）、既定値（40 件・200 字・500 字・max_exchange 20）。

## 柵

`tests/` に 32 本（`test_guest.py` 16・`test_hold.py` 6・`test_bot_loop.py` 10）。

```
cd <このフォルダ>
python -m pytest tests -q -p no:cacheprovider
```

結果の行（2026-11-19・Python 3.13・pytest 9）:

```
32 passed in 0.16s
```

縛っている崖: 来客の場で未メンションは無視・メンションは通る・ホームは常に通る／保留は所有者だけ通す／
流さなかった一通が台帳に残り読める／`set_hold` の往復（書いて読み戻す・解いたら旗ごと消す・書けなければ False）／
部屋バッファの上限と切り詰めと描画（空なら `""`・非ゲストのターンでは注入が `""`）／
登録簿の id・name・discriminator の照合（旧形式の不一致は None・新形式は name のみ・無効行は飛ばす）／
カウンタの増減と上限・人間で 0 に戻る・自分自身は常に止める・登録簿に無い bot は止める。

## 未了

- 呼ばれたターンの間だけ未メンションを割り込みとして渡す仕組みは移していない（上の「落としたもの」）。
- 添付の札は `push(attachments="...")` に文字列で渡す形だけ。添付の型から札を作る関数は無い。
- `HoldLedger` の書き込みは原子的ではない（読み戻して確かめる形で代えている）。複数プロセスから同時に書く用途ならロックが要る。
- 実際のチャットライブラリへの配線は例（純粋判定だけ）に留まり、実運用では未検証。

ライセンス: [MIT](LICENSE)
