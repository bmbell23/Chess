"""Insights v1: records & streaks, tilt detector, performance rating, terminations.

All computed from the games table. Conventions:
- rating-based metrics (upsets, peaks, performance) use RATED games only
- tilt/session metrics use LIVE modes only (rapid/blitz/bullet) — daily games
  run asynchronously and say nothing about a play session
"""
import re
from collections import defaultdict

from fastapi import APIRouter
from sqlalchemy import select

from ..database import SessionLocal
from ..models import Game
from .charts import MODES, _player_id

router = APIRouter(prefix="/api/v1", tags=["insights"])

LIVE_MODES = ("rapid", "blitz", "bullet")
SESSION_GAP_S = 3600
# session boundary = >15 min IDLE between games (start_next - end_prev); chosen
# from the idle-gap distribution valley at 10-15 min (#26)
SESSION_IDLE_GAP_S = 15 * 60
REVENGE_GAP_S = 300
_PGN_START = {
    k: re.compile(r'\[' + k + r' "([^"]+)"\]') for k in ("UTCDate", "UTCTime")
}
_MOVENUM_RE = re.compile(r"(\d+)\.")

SCORE = {"win": 1.0, "draw": 0.5, "loss": 0.0}


def _move_count(pgn: str | None) -> int | None:
    if not pgn:
        return None
    movetext = pgn.split("\n\n", 1)[-1]
    # strip {...} comments first — live-game clock annotations contain digits
    # and brackets that poison the move-number regex
    movetext = re.sub(r"\{[^}]*\}", "", movetext)
    nums = _MOVENUM_RE.findall(movetext)
    return max((int(n) for n in nums), default=None)


def _streaks(games) -> dict:
    longest_win = longest_loss = cur = 0
    cur_kind = None
    for g in games:
        if g.result == "draw":
            cur, cur_kind = 0, None
            continue
        if g.result == cur_kind:
            cur += 1
        else:
            cur, cur_kind = 1, g.result
        if cur_kind == "win":
            longest_win = max(longest_win, cur)
        else:
            longest_loss = max(longest_loss, cur)
    current = {"kind": cur_kind, "length": cur} if cur_kind else {"kind": None, "length": 0}
    return {"longest_win": longest_win, "longest_loss": longest_loss, "current": current}


@router.get("/insights")
def insights(player: str | None = None) -> dict:
    with SessionLocal() as db:
        pid = _player_id(db, player)
        games = db.execute(
            select(Game).where(Game.player_id == pid).order_by(Game.end_time)
        ).scalars().all()

    rated = [g for g in games if g.rated]
    live = [g for g in games if g.time_class in LIVE_MODES]

    # ---- records & streaks ----
    upset = max(
        (g for g in rated if g.result == "win" and g.opponent_rating and g.my_rating),
        key=lambda g: g.opponent_rating - g.my_rating,
        default=None,
    )
    mates = [
        (g, _move_count(g.pgn))
        for g in games
        if g.result == "win" and g.termination == "checkmated" and g.pgn
    ]
    fastest_mate = min((m for m in mates if m[1]), key=lambda m: m[1], default=None)
    longest = max(
        ((g, _move_count(g.pgn)) for g in games if g.pgn),
        key=lambda m: m[1] or 0,
        default=None,
    )
    months: dict[str, dict] = defaultdict(lambda: {"win": 0, "loss": 0, "draw": 0})
    for g in games:
        months[g.end_time.strftime("%Y-%m")][g.result] += 1
    best_month = max(months.items(), key=lambda kv: kv[1]["win"], default=None)
    peaks = {
        m: max((g.my_rating for g in rated if g.time_class == m and g.my_rating), default=None)
        for m in MODES
    }
    records = {
        "streaks_overall": _streaks(games),
        "streaks_by_mode": {m: _streaks([g for g in games if g.time_class == m]) for m in MODES},
        "biggest_upset": {
            "gap": upset.opponent_rating - upset.my_rating,
            "opponent": upset.opponent,
            "opponent_rating": upset.opponent_rating,
            "my_rating": upset.my_rating,
            "url": upset.url,
        } if upset else None,
        "fastest_mate_moves": fastest_mate[1] if fastest_mate else None,
        "fastest_mate_url": fastest_mate[0].url if fastest_mate else None,
        "longest_game_moves": longest[1] if longest else None,
        "best_month": {"month": best_month[0], **best_month[1]} if best_month else None,
        "peak_ratings": peaks,
    }

    # ---- tilt detector (live modes, chronological) ----
    after = {"win": {"win": 0, "n": 0}, "loss": {"win": 0, "n": 0}}
    revenge = {"win": 0, "n": 0}
    prev = None
    for g in live:
        if prev is not None:
            gap = (g.end_time - prev.end_time).total_seconds()
            if prev.result in after:
                after[prev.result]["n"] += 1
                after[prev.result]["win"] += g.result == "win"
            if prev.result == "loss" and gap <= REVENGE_GAP_S:
                revenge["n"] += 1
                revenge["win"] += g.result == "win"
        prev = g

    def pct(d):
        return round(100 * d["win"] / d["n"], 1) if d["n"] else None

    tilt = {
        "after_win": {"winrate": pct(after["win"]), "games": after["win"]["n"]},
        "after_loss": {"winrate": pct(after["loss"]), "games": after["loss"]["n"]},
        "revenge": {"winrate": pct(revenge), "games": revenge["n"]},
    }

    # ---- performance rating & expectations (rated w/ opponent rating) ----
    perf_games = [g for g in rated if g.opponent_rating and g.my_rating]
    expected = sum(
        1 / (1 + 10 ** ((g.opponent_rating - g.my_rating) / 400)) for g in perf_games
    )
    actual = sum(SCORE[g.result] for g in perf_games)
    monthly_perf: dict[str, list] = defaultdict(list)
    for g in perf_games:
        monthly_perf[g.end_time.strftime("%Y-%m")].append(g)

    def perf_rating(gs):
        w = sum(g.result == "win" for g in gs)
        l = sum(g.result == "loss" for g in gs)
        avg_opp = sum(g.opponent_rating for g in gs) / len(gs)
        return round(avg_opp + 400 * (w - l) / len(gs))

    buckets = [(-10**6, -200), (-200, -100), (-100, 0), (0, 100), (100, 200), (200, 10**6)]
    bucket_stats = []
    for lo, hi in buckets:
        gs = [g for g in perf_games if lo <= g.opponent_rating - g.my_rating < hi]
        bucket_stats.append({
            "label": (f"{lo}..{hi}" if abs(lo) < 10**6 and abs(hi) < 10**6
                      else (f"<{hi}" if lo < -10**5 else f">{lo}")),
            "games": len(gs),
            "winrate": round(100 * sum(g.result == "win" for g in gs) / len(gs), 1) if gs else None,
        })
    performance = {
        "expected_score": round(expected, 1),
        "actual_score": round(actual, 1),
        "overperformance": round(actual - expected, 1),
        "games": len(perf_games),
        "monthly_performance_rating": {
            m: perf_rating(gs) for m, gs in sorted(monthly_perf.items())
        },
        "vs_rating_gap": bucket_stats,
    }

    # ---- clock & terminations ----
    win_by: dict[str, int] = defaultdict(int)
    loss_by: dict[str, int] = defaultdict(int)
    for g in games:
        if g.result == "win":
            win_by[g.termination or "unknown"] += 1
        elif g.result == "loss":
            loss_by[g.termination or "unknown"] += 1
    losses = sum(loss_by.values())
    live_losses = [g for g in live if g.result == "loss"]
    terminations = {
        "wins_by": dict(sorted(win_by.items(), key=lambda kv: -kv[1])),
        "losses_by": dict(sorted(loss_by.items(), key=lambda kv: -kv[1])),
        "flagged_loss_pct": round(
            100 * sum(g.termination == "timeout" for g in live_losses) / len(live_losses), 1
        ) if live_losses else None,
        "loss_count": losses,
    }

    return {
        "records": records,
        "tilt": tilt,
        "performance": performance,
        "terminations": terminations,
        "rivals": _rivals(games),
        "sessions": _session_perf(games),
    }


def _game_start(g):
    """Start timestamp from PGN headers (live games); fall back to end_time."""
    from datetime import datetime

    if g.pgn:
        d, t = _PGN_START["UTCDate"].search(g.pgn), _PGN_START["UTCTime"].search(g.pgn)
        if d and t:
            try:
                return datetime.strptime(f"{d.group(1)} {t.group(1)}", "%Y.%m.%d %H:%M:%S")
            except ValueError:
                pass
    return g.end_time


def _session_perf(games) -> dict:
    """Group live games into sessions (>15min idle = new session) and measure
    win rate by game-position within a session — the warm-up/tire-out curve (#26)."""
    live = sorted(
        (g for g in games if g.time_class in LIVE_MODES), key=lambda g: g.end_time
    )
    sessions: list[list] = []
    prev_end = None
    for g in live:
        if prev_end is None or (_game_start(g) - prev_end).total_seconds() > SESSION_IDLE_GAP_S:
            sessions.append([])
        sessions[-1].append(g)
        prev_end = g.end_time

    by_pos: dict[int, dict] = defaultdict(lambda: {"win": 0, "n": 0})
    multi = [s for s in sessions if len(s) > 1]
    for s in sessions:
        for i, g in enumerate(s, 1):
            bucket = min(i, 10)  # 10 = "10th or later game of the session"
            by_pos[bucket]["n"] += 1
            by_pos[bucket]["win"] += g.result == "win"

    def pct(d):
        return round(100 * d["win"] / d["n"], 1) if d["n"] else None

    session_minutes = [
        (s[-1].end_time - _game_start(s[0])).total_seconds() / 60 for s in sessions
    ]
    return {
        "idle_gap_minutes": SESSION_IDLE_GAP_S // 60,
        "total_sessions": len(sessions),
        "multi_game_sessions": len(multi),
        "avg_games_per_session": round(len(live) / len(sessions), 1) if sessions else 0,
        "avg_session_minutes": round(sum(session_minutes) / len(sessions)) if sessions else 0,
        "longest_session_games": max((len(s) for s in sessions), default=0),
        "by_position": [
            {"game": k, "winrate": pct(v), "games": v["n"]}
            for k, v in sorted(by_pos.items())
        ],
    }


def _rivals(games) -> dict:
    """Head-to-head aggregation. Nemesis = they beat me most (#17);
    dominee = I beat them most (#18)."""
    h2h: dict[str, dict] = {}
    for g in games:
        if not g.opponent:
            continue
        entry = h2h.setdefault(
            g.opponent,
            {"opponent": g.opponent, "win": 0, "loss": 0, "draw": 0,
             "modes": set(), "last_played": g.end_time},
        )
        entry[g.result] += 1
        entry["modes"].add(g.time_class)
        entry["last_played"] = max(entry["last_played"], g.end_time)

    def pack(entry):
        return {
            **{k: entry[k] for k in ("opponent", "win", "loss", "draw")},
            "games": entry["win"] + entry["loss"] + entry["draw"],
            "modes": sorted(entry["modes"]),
            "last_played": entry["last_played"].strftime("%Y-%m-%d"),
        }

    nemeses = sorted(h2h.values(), key=lambda e: (-e["loss"], -(e["win"] + e["loss"] + e["draw"])))
    dominees = sorted(h2h.values(), key=lambda e: (-e["win"], -(e["win"] + e["loss"] + e["draw"])))
    return {
        "nemeses": [pack(e) for e in nemeses[:5] if e["loss"] > 0],
        "dominees": [pack(e) for e in dominees[:5] if e["win"] > 0],
    }
