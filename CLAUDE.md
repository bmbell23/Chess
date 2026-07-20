# Chess — chess.com stats tracker

Self-hosted app for tracking, charting, and monitoring chess.com stats
(ratings over time, game history, openings, win/loss breakdowns, puzzle stats).

**Follow the house template:** `/home/brandon/projects/docker/docs/NEW_APP_TEMPLATE.md`
(shared rules: `/home/brandon/projects/CLAUDE.md`).

## Working rules (same process as GreatReads)

Repo: https://github.com/bmbell23/Chess · Board: **Project #7 "Chess"**
(https://github.com/users/bmbell23/projects/7)

- **GitHub Issues are the source of truth.** Plans, scoping, next-steps, and status
  live in issues — never in local planning `.md` files. Read `gh issue list` before
  starting work; comment/close/edit issues as work moves. The issues — not memory,
  not docs — are what the next session trusts.
- **Every issue is tagged `STORY:` or `BUG:`** in three synced places: title prefix,
  first line of the description, and the `story`/`bug` label.
- **No work without a ticket.** Create the ticket before touching code.
- **Board flow, in order: Scoping → Ready to Implement → In progress → In Review → Done.**
  Never skip columns. New tickets land in Scoping (open questions — ask the user,
  never build from a guess) or Ready to Implement (confidently scoped).
- **ONE active ticket at a time** in In progress + In Review (committed "watch"
  tickets sitting in In Review don't count). If the user pivots while an active
  uncommitted ticket is In Review, STOP and resolve it first.
- **Any code change → move the ticket to In Review and say so.** In-Review work
  stays **uncommitted**; uncommitted changes must match the one active ticket.
- **Done = the user blesses it.** Only then commit (via `gvc`).
- **Builds are explicit:** if a change needs a container rebuild or APK rebuild to
  be visible, say so plainly and ask who runs it — never let the user discover it.
- **Gated actions (always ask first):** (1) writes to `data/chess.db` (schema
  changes, migrations, data fixes — back up first; read-only queries are fine),
  (2) container/APK rebuilds, (3) `git commit` / `gvc` / `git push`.
- Remind the user of In-Review tickets at every task transition.

## Project facts
- **Host port: 8011** (next free in the app block; record in `.augment-guidelines` inventory when the container first comes up)
- Container: `chess_app`, network `chess_network`, URL `http://100.69.184.113:8011`
- Stack: Python 3.11 · FastAPI · SQLAlchemy · SQLite (`data/chess.db`) · Alembic · Jinja2 + vanilla JS with vendored Chart.js
- Background sync: APScheduler in `lifespan()`, gated by `ENABLE_SCHEDULERS=true`
- Android: LifeForge-style self-updating WebView APK (later, once the web app is useful)

## chess.com Published-Data API (public, read-only, **no API key**)
Base: `https://api.chess.com/pub`
- `/player/{username}` — profile
- `/player/{username}/stats` — current ratings/records per mode (rapid, blitz, bullet, daily, puzzles)
- `/player/{username}/games/archives` — list of monthly archive URLs
- `/player/{username}/games/{YYYY}/{MM}` — all games for a month (includes PGN, ratings, results, accuracies when available)
- `/player/{username}/games/{YYYY}/{MM}/pgn` — month as one PGN file

Etiquette/behavior:
- Send a descriptive `User-Agent` with contact info (chess.com asks for this; anonymous clients get throttled)
- Requests must be **serial** (no parallel hammering); expect `429` if too fast — back off
- Monthly archives for past months are immutable → fetch each once, cache forever in SQLite; only the current month needs re-polling
- Data is cached server-side (updates can lag ~15 min); ratings history must be **accumulated by us** — the API only exposes current stats plus per-game ratings, so the sync job should snapshot stats and ingest new games on a schedule

## Sync design (intended)
1. On demand + daily APScheduler job: fetch `/stats` snapshot → `rating_snapshots` table
2. Backfill: walk `/games/archives` serially, store every game (PGN + metadata) in `games`
3. Current month re-fetched on each sync; dedupe by game URL/UUID
4. Charts (Chart.js): rating over time per mode from per-game `rating` fields, win/loss/draw, openings (parse ECO from PGN headers), time-of-day performance
