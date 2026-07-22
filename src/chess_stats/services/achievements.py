"""Achievements: a data-defined catalog + an evaluation engine.

The catalog is generated from tiered "ladders" (games played 10/100/500/…, rating
milestones, streaks, …) plus one-off achievements, giving ~200 that auto-extend
over time. Each achievement maps to a numeric metric in the per-player CONTEXT and
a threshold; earned = context[metric] >= threshold. Points scale with tier.
"""
import re
from collections import Counter, defaultdict
from datetime import timezone
from zoneinfo import ZoneInfo

from sqlalchemy import select

from ..config import get_settings
from ..database import SessionLocal
from ..models import AwardedAchievement, Game, MoveStats, Player

_MOVENUM_RE = re.compile(r"(\d+)\.")


def _move_count(pgn: str | None) -> int | None:
    if not pgn:
        return None
    movetext = re.sub(r"\{[^}]*\}", "", pgn.split("\n\n", 1)[-1])
    nums = _MOVENUM_RE.findall(movetext)
    return max((int(n) for n in nums), default=None)


# ---- ladder definitions: (metric, category, icon, name, unit, [thresholds]) ----
# points per tier index, extended by repeating the last value
_POINTS = [5, 10, 10, 25, 25, 50, 50, 100, 100, 100]


def _points(i: int) -> int:
    return _POINTS[min(i, len(_POINTS) - 1)]


MODES = ("rapid", "blitz", "bullet", "daily")
MODE_ICON = {"rapid": "🟢", "blitz": "🟠", "bullet": "⚪", "daily": "🟡"}

# reusable tier presets
BIG = [10, 25, 50, 100, 150, 200, 300, 400, 500, 750, 1000, 1500, 2000, 3000, 5000, 7500, 10000]
MED = [10, 25, 50, 100, 200, 300, 500, 750, 1000, 1500, 2000, 3000]
SMALL = [5, 10, 25, 50, 100, 200, 500, 1000]
TINY = [1, 5, 10, 25, 50, 100, 250]
D6 = [5, 10, 25, 50, 100, 200]
RATING = list(range(300, 2525, 25))  # 89 tiers, 300…2500 in 25s
STREAK = [3, 5, 7, 10, 12, 15, 20, 25, 30, 40, 50, 75, 100]
DAYS = [3, 5, 7, 10, 14, 21, 30, 45, 60, 90, 120, 180, 270, 365, 500, 730, 1000]

# overall ladders: (metric, category, icon, name, unit, tiers)
LADDERS = [
    ("games", "Milestones", "♟", "Games Played", "games", BIG),
    ("wins", "Milestones", "🏆", "Victories", "wins", BIG),
    ("losses", "Milestones", "💪", "Character Building", "losses", MED),
    ("draws", "Milestones", "🤝", "Peacemaker", "draws", SMALL),
    ("wins_white", "Milestones", "⬜", "Light Side", "wins as White", MED),
    ("wins_black", "Milestones", "⬛", "Dark Side", "wins as Black", MED),
    ("checkmates", "Tactics", "♚", "Executioner", "checkmates delivered", MED),
    ("resign_wins", "Tactics", "🏳", "Submission", "wins by resignation", SMALL),
    ("win_streak", "Streaks", "🔥", "Win Streak", "wins in a row", STREAK),
    ("day_streak", "Streaks", "📅", "Daily Grind", "day streak", DAYS),
    ("distinct_ecos", "Openings", "📖", "Opening Explorer", "openings won with",
     [5, 10, 15, 20, 25, 30, 40, 50, 75, 100, 150, 200]),
    ("top_opening_wins", "Openings", "🎯", "Opening Specialist", "wins with one opening",
     [10, 25, 50, 75, 100, 150, 200, 300]),
    ("brilliants", "Brilliance", "💎", "Brilliant!", "brilliant moves",
     [1, 5, 10, 25, 50, 100, 150, 250, 500, 1000]),
    ("greats", "Brilliance", "✨", "Great Moves", "great moves",
     [10, 25, 50, 100, 250, 500, 1000, 2000, 5000]),
    ("bests", "Brilliance", "⭐", "Best Moves", "engine-best moves",
     [50, 100, 250, 500, 1000, 2500, 5000, 10000]),
    ("excellents", "Precision", "👍", "Excellent", "excellent moves",
     [50, 100, 250, 500, 1000, 2500, 5000]),
    ("blunderfree", "Precision", "🛡", "Clean Sheet", "blunder-free games", SMALL),
    ("sub20_wins", "Speed", "⚡", "Quick Kill", "wins under 20 moves", SMALL),
    ("sub15_wins", "Speed", "💨", "Lightning Strike", "wins under 15 moves", TINY),
    ("flag_wins", "Speed", "⏱", "Time Lord", "wins on time", SMALL),
    ("best_upset", "Giant Slayer", "🗡", "Giant Slayer", "rating-point upset",
     [50, 100, 150, 200, 250, 300, 400, 500, 600]),
    ("night_games", "Quirky", "🌙", "Night Owl", "games after midnight", SMALL),
    ("morning_games", "Quirky", "🌅", "Early Bird", "morning games", SMALL),
    ("afternoon_games", "Quirky", "☀", "Afternoon Delight", "afternoon games", SMALL),
    ("evening_games", "Quirky", "🌆", "Evening Regular", "evening games", MED),
    ("weekend_games", "Quirky", "🎉", "Weekend Warrior", "weekend games", MED),
    ("weekday_games", "Quirky", "💼", "Nine to Five", "weekday games", MED),
    ("total_minutes", "Dedication", "⏳", "Time Invested", "minutes played",
     [60, 300, 600, 1200, 3000, 6000, 12000, 24000, 48000, 96000]),
    ("max_day_games", "Dedication", "🔂", "Marathon", "games in one day",
     [5, 10, 20, 30, 50, 75, 100, 150]),
    ("opponents", "Social", "🌍", "Well Traveled", "distinct opponents faced", MED),
    ("puzzles_solved", "Puzzles", "🧩", "Puzzler", "puzzles solved", MED),
    ("puzzle_attempts", "Puzzles", "🧪", "Puzzle Grinder", "puzzles attempted", MED),
    ("puzzle_rating", "Puzzles", "🧠", "Tactician", "puzzle rating", RATING),
]

# per-mode ladders: (metric_suffix, category, name, unit, tiers)
PERMODE = [
    ("games", "Milestones", "{M} Regular", "{m} games", MED),
    ("wins", "Milestones", "{M} Winner", "{m} wins", MED),
    ("losses", "Milestones", "{M} Grinder", "{m} losses", SMALL),
    ("draws", "Milestones", "{M} Diplomat", "{m} draws", D6),
    ("checkmates", "Tactics", "{M} Executioner", "{m} checkmates", SMALL),
    ("peak", "Rating", "{M} Rating", "{m} rating", RATING),
    ("win_streak", "Streaks", "{M} Streak", "{m} wins in a row", STREAK),
    ("sub20_wins", "Speed", "{M} Quick Kill", "quick {m} wins", D6),
    ("flag_wins", "Speed", "{M} Time Lord", "{m} wins on time", [5, 10, 25, 50, 100]),
    ("brilliants", "Brilliance", "{M} Brilliance", "brilliant {m} moves",
     [1, 5, 10, 25, 50, 100, 250]),
    ("bests", "Brilliance", "{M} Precision", "best {m} moves",
     [25, 50, 100, 250, 500, 1000, 2500]),
    ("blunderfree", "Precision", "{M} Clean Sheet", "blunder-free {m} games", D6),
]


def build_catalog() -> list[dict]:
    catalog = []

    def add(metric, category, icon, name, unit, thresholds):
        for i, thr in enumerate(thresholds):
            catalog.append({
                "id": f"{metric}_{thr}",
                "name": f"{name} {_roman(i + 1)}",
                "description": f"Reach {thr:,} {unit}",
                "category": category,
                "icon": icon,
                "metric": metric,
                "threshold": thr,
                "points": _points(i),
            })

    for spec in LADDERS:
        add(*spec)
    for suffix, category, name_t, unit_t, tiers in PERMODE:
        for m in MODES:
            add(
                f"{suffix}_{m}", category, MODE_ICON[m],
                name_t.format(M=m.capitalize(), m=m),
                unit_t.format(M=m.capitalize(), m=m), tiers,
            )
    return catalog


def _roman(n: int) -> str:
    numerals = [(10, "X"), (9, "IX"), (5, "V"), (4, "IV"), (1, "I")]
    out = ""
    for v, s in numerals:
        while n >= v:
            out += s
            n -= v
    return out


CATALOG = build_catalog()
CATALOG_BY_ID = {a["id"]: a for a in CATALOG}
TOTAL_POINTS = sum(a["points"] for a in CATALOG)


_RESULT_KEY = {"win": "wins", "loss": "losses", "draw": "draws"}


def compute_context(db, player: Player) -> dict:
    """One pass over the player's games (+ move_stats, +best-effort training)
    producing every metric the catalog references (overall + per-mode)."""
    games = db.execute(
        select(Game).where(Game.player_id == player.id).order_by(Game.end_time)
    ).scalars().all()
    tz = ZoneInfo(get_settings().tz)
    utc = ZoneInfo("UTC")

    ctx = Counter()
    ctx["games"] = len(games)
    eco_wins = Counter()
    opponents = set()
    day_counts = Counter()
    peaks = dict.fromkeys(MODES, 0)
    streak_overall = 0
    streak_mode = dict.fromkeys(MODES, 0)
    best_overall = 0
    best_mode = dict.fromkeys(MODES, 0)

    for g in games:
        m = g.time_class if g.time_class in MODES else None
        ctx[_RESULT_KEY[g.result]] += 1
        if m:
            ctx[f"games_{m}"] += 1
            ctx[f"{_RESULT_KEY[g.result]}_{m}"] += 1
        if g.opponent:
            opponents.add(g.opponent)
        local = g.end_time.replace(tzinfo=utc).astimezone(tz)
        day_counts[local.date()] += 1
        h = local.hour
        bucket = ("night_games" if h < 5 else "morning_games" if h < 12
                  else "afternoon_games" if h < 18 else "evening_games")
        ctx[bucket] += 1
        ctx["weekend_games" if local.weekday() >= 5 else "weekday_games"] += 1
        if g.rated and g.my_rating and m:
            peaks[m] = max(peaks[m], g.my_rating)

        if g.result == "win":
            if g.termination == "checkmated":
                ctx["checkmates"] += 1
                if m:
                    ctx[f"checkmates_{m}"] += 1
            if g.termination == "timeout":
                ctx["flag_wins"] += 1
                if m:
                    ctx[f"flag_wins_{m}"] += 1
            if g.termination == "resigned":
                ctx["resign_wins"] += 1
            ctx["wins_white" if g.color == "white" else "wins_black"] += 1
            if g.eco:
                eco_wins[g.eco] += 1
            mc = _move_count(g.pgn)
            if mc and mc < 20:
                ctx["sub20_wins"] += 1
                if m:
                    ctx[f"sub20_wins_{m}"] += 1
            if mc and mc < 15:
                ctx["sub15_wins"] += 1
            if g.rated and g.opponent_rating and g.my_rating:
                ctx["best_upset"] = max(ctx["best_upset"], g.opponent_rating - g.my_rating)
            streak_overall += 1
            best_overall = max(best_overall, streak_overall)
            if m:
                streak_mode[m] += 1
                best_mode[m] = max(best_mode[m], streak_mode[m])
        elif g.result == "loss":
            streak_overall = 0
            if m:
                streak_mode[m] = 0

    ctx["win_streak"] = best_overall
    ctx["distinct_ecos"] = len(eco_wins)
    ctx["top_opening_wins"] = max(eco_wins.values(), default=0)
    ctx["opponents"] = len(opponents)
    ctx["max_day_games"] = max(day_counts.values(), default=0)
    for mode in MODES:
        ctx[f"peak_{mode}"] = peaks[mode]
        ctx[f"win_streak_{mode}"] = best_mode[mode]

    # day streak (longest run of consecutive played days)
    prev = run = longest_days = 0
    for d in sorted(day_counts):
        run = run + 1 if prev and (d - prev).days == 1 else 1
        longest_days = max(longest_days, run)
        prev = d
    ctx["day_streak"] = longest_days

    # move-quality aggregates (overall + per-mode)
    ms = db.execute(
        select(MoveStats, Game.time_class)
        .join(Game, MoveStats.game_id == Game.id)
        .where(Game.player_id == player.id)
    ).all()
    for stat, tc in ms:
        ctx["brilliants"] += stat.brilliant
        ctx["greats"] += stat.great
        ctx["bests"] += stat.best
        ctx["excellents"] += stat.excellent
        if stat.blunder == 0 and stat.moves > 0:
            ctx["blunderfree"] += 1
        if tc in MODES:
            ctx[f"brilliants_{tc}"] += stat.brilliant
            ctx[f"bests_{tc}"] += stat.best
            if stat.blunder == 0 and stat.moves > 0:
                ctx[f"blunderfree_{tc}"] += 1

    ctx["total_minutes"] = _total_minutes(games)

    # best-effort puzzles (unofficial endpoint; never fatal)
    try:
        from .chesscom_web import training_stats

        t = training_stats(player.username)
        if t.get("puzzles"):
            ctx["puzzles_solved"] = t["puzzles"].get("passed") or 0
            ctx["puzzle_attempts"] = t["puzzles"].get("attempts") or 0
            ctx["puzzle_rating"] = t["puzzles"].get("highest_rating") or 0
    except Exception:
        pass

    return dict(ctx)


_HDR = {k: re.compile(r'\[' + k + r' "([^"]+)"\]') for k in ("UTCDate", "UTCTime", "EndDate", "EndTime")}


def _total_minutes(games) -> int:
    from datetime import datetime

    total = 0.0
    for g in games:
        if g.time_class not in ("rapid", "blitz", "bullet") or not g.pgn:
            continue
        h = {k: rx.search(g.pgn) for k, rx in _HDR.items()}
        if all(h.values()):
            try:
                s = datetime.strptime(f"{h['UTCDate'].group(1)} {h['UTCTime'].group(1)}", "%Y.%m.%d %H:%M:%S")
                e = datetime.strptime(f"{h['EndDate'].group(1)} {h['EndTime'].group(1)}", "%Y.%m.%d %H:%M:%S")
                d = (e - s).total_seconds()
                if 0 < d <= 6 * 3600:
                    total += d
            except ValueError:
                pass
    return round(total / 60)


def evaluate(username: str) -> dict:
    """Compute earned achievements, persist newly-earned, return full status
    (earned/locked with progress, score, and any newly-unlocked for the recap)."""
    from .sync import normalize_username

    username = normalize_username(username)
    with SessionLocal() as db:
        player = db.execute(
            select(Player).where(Player.username == username)
        ).scalar_one_or_none()
        if player is None:
            return {"player": username, "available": False}

        ctx = compute_context(db, player)
        already = {
            a.achievement_id: a.awarded_at
            for a in db.execute(
                select(AwardedAchievement).where(AwardedAchievement.player_id == player.id)
            ).scalars()
        }

        newly = []
        items = []
        earned_count = score = 0
        by_category: dict[str, dict] = defaultdict(lambda: {"earned": 0, "total": 0, "points": 0})
        for a in CATALOG:
            value = ctx.get(a["metric"], 0)
            earned = value >= a["threshold"]
            cat = by_category[a["category"]]
            cat["total"] += 1
            if earned:
                earned_count += 1
                score += a["points"]
                cat["earned"] += 1
                cat["points"] += a["points"]
                if a["id"] not in already:
                    db.add(AwardedAchievement(player_id=player.id, achievement_id=a["id"]))
                    newly.append(a)
            items.append({
                **{k: a[k] for k in ("id", "name", "description", "category", "icon", "metric", "points", "threshold")},
                "earned": earned,
                "value": value,
                "progress": min(1.0, round(value / a["threshold"], 3)) if a["threshold"] else 0,
            })
        # first evaluation ever = recap moment (all earned are "new")
        first_run = len(already) == 0 and earned_count > 0
        db.commit()

    return {
        "player": username,
        "available": True,
        "score": score,
        "max_score": TOTAL_POINTS,
        "earned_count": earned_count,
        "total_count": len(CATALOG),
        "first_run": first_run,
        "newly_unlocked": [
            {"name": a["name"], "icon": a["icon"], "points": a["points"]} for a in newly
        ],
        "categories": {k: v for k, v in sorted(by_category.items())},
        "achievements": items,
    }
