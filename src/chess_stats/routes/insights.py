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
REVENGE_GAP_S = 300
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
    fatigue: dict[int, dict] = defaultdict(lambda: {"win": 0, "n": 0})
    prev = None
    session_idx = 0
    for g in live:
        if prev is not None:
            gap = (g.end_time - prev.end_time).total_seconds()
            if prev.result in after:
                after[prev.result]["n"] += 1
                after[prev.result]["win"] += g.result == "win"
            if prev.result == "loss" and gap <= REVENGE_GAP_S:
                revenge["n"] += 1
                revenge["win"] += g.result == "win"
            session_idx = session_idx + 1 if gap <= SESSION_GAP_S else 1
        else:
            session_idx = 1
        bucket = min(session_idx, 8)  # 8 = "8th or later game of the session"
        fatigue[bucket]["n"] += 1
        fatigue[bucket]["win"] += g.result == "win"
        prev = g

    def pct(d):
        return round(100 * d["win"] / d["n"], 1) if d["n"] else None

    tilt = {
        "after_win": {"winrate": pct(after["win"]), "games": after["win"]["n"]},
        "after_loss": {"winrate": pct(after["loss"]), "games": after["loss"]["n"]},
        "revenge": {"winrate": pct(revenge), "games": revenge["n"]},
        "fatigue_curve": [
            {"game_in_session": k, "winrate": pct(v), "games": v["n"]}
            for k, v in sorted(fatigue.items())
        ],
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
