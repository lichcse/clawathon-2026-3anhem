import asyncio
from datetime import date, datetime, timezone, timedelta
from fastapi import APIRouter
import httpx

# All times displayed in Vietnam timezone (UTC+7)
VN_TZ = timezone(timedelta(hours=7))

router = APIRouter()

# TheSportsDB — free public API, league 4429 = FIFA World Cup
SPORTSDB_BASE = "https://www.thesportsdb.com/api/v1/json/2"
SPORTSDB_LEAGUE_ID = "4429"

# ESPN — undocumented public scoreboard API
ESPN_BASE = "https://site.api.espn.com/apis/site/v2/sports/soccer/fifa.world"

ESPN_HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; 3anhem-agent/1.0)",
    "Accept": "application/json",
}

IN_PLAY_STATUSES = {"1H", "HT", "2H", "ET", "P", "LIVE", "INPLAY"}
FINISHED_STATUSES = {"FT", "AET", "PEN", "AP", "ABD"}


# ─── Normalised match format ────────────────────────────────────────────────

def _match(
    id, home_team, away_team,
    home_score=None, away_score=None,
    status="SCHEDULED", utc_date="",
    group="", venue="",
) -> dict:
    status_label = {
        "SCHEDULED": "Sắp diễn ra",
        "IN_PLAY": "LIVE",
        "FINISHED": "Kết thúc",
    }.get(status, status)

    local_time = ""
    local_date = ""
    if utc_date:
        try:
            dt = datetime.fromisoformat(utc_date.replace("Z", "+00:00"))
            vn_dt = dt.astimezone(VN_TZ)
            local_time = vn_dt.strftime("%H:%M")
            local_date = vn_dt.strftime("%d/%m")
        except Exception:
            pass

    return {
        "id": id,
        "home_team": home_team,
        "away_team": away_team,
        "home_score": home_score,
        "away_score": away_score,
        "status": status,
        "utc_date": utc_date,
        "group": group,
        "venue": venue,
        "status_label": status_label,
        "local_time": local_time,
        "local_date": local_date,
    }


# ─── ESPN parser ────────────────────────────────────────────────────────────

def _espn_status(event: dict) -> str:
    state = event.get("status", {}).get("type", {}).get("state", "")
    completed = event.get("status", {}).get("type", {}).get("completed", False)
    if completed or state == "post":
        return "FINISHED"
    if state == "in":
        return "IN_PLAY"
    return "SCHEDULED"


def _espn_parse(event: dict) -> dict:
    comp = (event.get("competitions") or [{}])[0]
    competitors = comp.get("competitors", [])

    home = next((c for c in competitors if c.get("homeAway") == "home"), {})
    away = next((c for c in competitors if c.get("homeAway") == "away"), {})

    def _score(c):
        s = c.get("score")
        if s is None or s == "":
            return None
        try:
            return int(float(s))
        except (ValueError, TypeError):
            return None

    status = _espn_status(event)

    venue_info = comp.get("venue", {})
    venue = venue_info.get("fullName", "")

    note = comp.get("notes", [{}])
    group = note[0].get("headline", "") if note else ""

    return _match(
        id=event.get("id"),
        home_team=home.get("team", {}).get("displayName") or home.get("team", {}).get("name", "?"),
        away_team=away.get("team", {}).get("displayName") or away.get("team", {}).get("name", "?"),
        home_score=_score(home) if status != "SCHEDULED" else None,
        away_score=_score(away) if status != "SCHEDULED" else None,
        status=status,
        utc_date=event.get("date", ""),
        group=group,
        venue=venue,
    )


async def _fetch_espn_upcoming(client: httpx.AsyncClient, today: str) -> list[dict] | None:
    """Fetch today + next 3 days in parallel to collect up to 5 upcoming/live matches."""
    days = [
        (datetime.strptime(today, "%Y-%m-%d") + timedelta(days=d)).strftime("%Y%m%d")
        for d in range(4)
    ]

    async def _day(ds: str) -> list[dict]:
        try:
            r = await client.get(
                f"{ESPN_BASE}/scoreboard",
                params={"dates": ds},
                headers=ESPN_HEADERS,
                timeout=12,
            )
            if r.status_code == 200:
                return [
                    _espn_parse(e)
                    for e in (r.json().get("events") or [])
                    if _espn_status(e) != "FINISHED"
                ]
        except Exception:
            pass
        return []

    day_results = await asyncio.gather(*[_day(d) for d in days])
    upcoming = [m for day in day_results for m in day]
    return upcoming[:5] if upcoming else None


async def _fetch_espn_recent(client: httpx.AsyncClient, today: str) -> list[dict]:
    """Fetch past 5 days from ESPN to get up to 5 recent results."""
    results = []
    try:
        for delta in range(1, 6):
            past_day = (datetime.strptime(today, "%Y-%m-%d") - timedelta(days=delta)).strftime("%Y%m%d")
            resp = await client.get(
                f"{ESPN_BASE}/scoreboard",
                params={"dates": past_day},
                headers=ESPN_HEADERS,
                timeout=10,
            )
            if resp.status_code == 200:
                data = resp.json()
                for e in (data.get("events") or []):
                    m = _espn_parse(e)
                    if m["status"] == "FINISHED":
                        results.append(m)
            if len(results) >= 5:
                break
    except Exception:
        pass
    return results[:5]


# ─── TheSportsDB parser ──────────────────────────────────────────────────────

def _sportsdb_status(raw: str) -> str:
    s = (raw or "").upper()
    if s in FINISHED_STATUSES:
        return "FINISHED"
    if s in IN_PLAY_STATUSES:
        return "IN_PLAY"
    return "SCHEDULED"


def _sportsdb_parse(e: dict) -> dict:
    def _score(v):
        if v is None or v == "" or str(v).lower() == "null":
            return None
        try:
            return int(float(v))
        except (ValueError, TypeError):
            return None

    date_str = e.get("dateEvent", "")
    time_str = (e.get("strTime") or "00:00:00").strip()
    utc_date = f"{date_str}T{time_str}Z" if date_str else ""
    status = _sportsdb_status(e.get("strStatus", ""))

    return _match(
        id=e.get("idEvent"),
        home_team=e.get("strHomeTeam", "?"),
        away_team=e.get("strAwayTeam", "?"),
        home_score=_score(e.get("intHomeScore")) if status != "SCHEDULED" else None,
        away_score=_score(e.get("intAwayScore")) if status != "SCHEDULED" else None,
        status=status,
        utc_date=utc_date,
        group=e.get("strRound") or str(e.get("intRound") or ""),
        venue=e.get("strVenue", ""),
    )


async def _fetch_sportsdb(client: httpx.AsyncClient, today: str):
    """Fetch today + recent from TheSportsDB. Returns (today_list, recent_list)."""
    async def _get(url, params=None):
        try:
            r = await client.get(url, params=params, timeout=12)
            return r.json() if r.status_code == 200 else {}
        except Exception:
            return {}

    r_day, r_next, r_past = await asyncio.gather(
        _get(f"{SPORTSDB_BASE}/eventsday.php", {"d": today}),
        _get(f"{SPORTSDB_BASE}/eventsnextleague.php", {"id": SPORTSDB_LEAGUE_ID}),
        _get(f"{SPORTSDB_BASE}/eventspastleague.php", {"id": SPORTSDB_LEAGUE_ID}),
    )

    today_events: list[dict] = []
    seen: set = set()

    for e in (r_day.get("events") or []):
        if e.get("idLeague") == SPORTSDB_LEAGUE_ID or "World Cup" in (e.get("strLeague") or ""):
            eid = e.get("idEvent")
            if eid not in seen:
                seen.add(eid)
                today_events.append(_sportsdb_parse(e))

    # Include upcoming matches from next-league (not just today)
    for e in (r_next.get("events") or []):
        eid = e.get("idEvent")
        if eid not in seen:
            seen.add(eid)
            today_events.append(_sportsdb_parse(e))

    # Keep only scheduled/live, up to 5
    upcoming_events = [m for m in today_events if m["status"] != "FINISHED"][:5]

    recent = [
        _sportsdb_parse(e)
        for e in (r_past.get("events") or [])
        if e.get("dateEvent") != today
    ][:5]

    return upcoming_events, recent


# ─── Main endpoint ───────────────────────────────────────────────────────────

@router.get("/worldcup/today")
async def today_matches():
    today = datetime.now(VN_TZ).strftime("%Y-%m-%d")

    try:
        async with httpx.AsyncClient() as client:
            # Try ESPN first (parallel: upcoming from today+next days, and recent)
            espn_upcoming, espn_recent = await asyncio.gather(
                _fetch_espn_upcoming(client, today),
                _fetch_espn_recent(client, today),
            )

            if espn_upcoming is not None:
                return {
                    "upcoming": espn_upcoming,
                    "recent": espn_recent,
                    "source": "espn",
                    "as_of": today,
                }

            # Fallback: TheSportsDB
            sdb_upcoming, sdb_recent = await _fetch_sportsdb(client, today)
            return {
                "upcoming": sdb_upcoming,
                "recent": sdb_recent,
                "source": "thesportsdb",
                "as_of": today,
            }

    except Exception as exc:
        return {"upcoming": [], "recent": [], "source": "error", "error": str(exc)}
