import asyncio
import re
from datetime import datetime, timezone, timedelta
from fastapi import APIRouter
import httpx

# Vietnam timezone (UTC+7)
VN_TZ = timezone(timedelta(hours=7))

router = APIRouter()

URL_24H = (
    "https://www.24h.com.vn/world-cup-2026/"
    "ket-qua-thi-dau-bong-da-world-cup-2026-moi-nhat-c860a1747405.html"
)
HEADERS_BROWSER = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "vi-VN,vi;q=0.9",
    "Accept": "text/html,application/xhtml+xml",
}

# Vietnamese → English team name mapping (24h.com.vn uses Vietnamese names)
_VN_TO_EN: dict[str, str] = {
    "Úc": "Australia",
    "Thổ Nhĩ Kỳ": "Türkiye",
    "Tây Ban Nha": "Spain",
    "Cabo Verde": "Cape Verde",
    "Bỉ": "Belgium",
    "Ai Cập": "Egypt",
    "Saudi Arabia": "Saudi Arabia",
    "Ả Rập Xê Út": "Saudi Arabia",
    "Uruguay": "Uruguay",
    "Iran": "Iran",
    "New Zealand": "New Zealand",
    "Pháp": "France",
    "Senegal": "Senegal",
    "Iraq": "Iraq",
    "Na Uy": "Norway",
    "Argentina": "Argentina",
    "Algeria": "Algeria",
    "Áo": "Austria",
    "Jordan": "Jordan",
    "Bồ Đào Nha": "Portugal",
    "Congo DR": "Congo DR",
    "Anh": "England",
    "Croatia": "Croatia",
    "Ghana": "Ghana",
    "Panama": "Panama",
    "Uzbekistan": "Uzbekistan",
    "Colombia": "Colombia",
    "Séc": "Czechia",
    "Nam Phi": "South Africa",
    "Thụy Sĩ": "Switzerland",
    "Bosnia-Herzegovina": "Bosnia and Herzegovina",
    "Bosnia": "Bosnia and Herzegovina",
    "Canada": "Canada",
    "Qatar": "Qatar",
    "Mexico": "Mexico",
    "Hàn Quốc": "South Korea",
    "Hà Lan": "Netherlands",
    "Nhật Bản": "Japan",
    "Đức": "Germany",
    "Curacao": "Curaçao",
    "Bờ Biển Ngà": "Ivory Coast",
    "Ecuador": "Ecuador",
    "Thụy Điển": "Sweden",
    "Tunisia": "Tunisia",
    "Brazil": "Brazil",
    "Ma Rốc": "Morocco",
    "Haiti": "Haiti",
    "Scotland": "Scotland",
    "Mỹ": "United States",
    "Paraguay": "Paraguay",
    "Bồ Đào Nha": "Portugal",
    "Đan Mạch": "Denmark",
    "Serbia": "Serbia",
    "Thụy Sĩ": "Switzerland",
    "Nigeria": "Nigeria",
    "Cameroon": "Cameroon",
    "Senegal": "Senegal",
    "Maroc": "Morocco",
    "Nga": "Russia",
    "Ba Lan": "Poland",
    "Romani": "Romania",
    "Bungari": "Bulgaria",
    "Hy Lạp": "Greece",
    "Thổ Nhĩ Kỳ": "Türkiye",
}


def _en(name: str) -> str:
    """Convert Vietnamese team name to English. Returns original if not found."""
    return _VN_TO_EN.get(name, name)


ESPN_BASE = "https://site.api.espn.com/apis/site/v2/sports/soccer/fifa.world"
ESPN_HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; 3anhem-agent/1.0)",
    "Accept": "application/json",
}


# ─── Normalised match format ────────────────────────────────────────────────

def _match(
    id, home_team, away_team,
    home_score=None, away_score=None,
    status="SCHEDULED", utc_date="",
    group="", venue="",
) -> dict:
    status_label = {
        "SCHEDULED": "Sắp diễn ra",
        "IN_PLAY": "Đang diễn ra",
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


# ─── 24h.com.vn scraper ─────────────────────────────────────────────────────

def _parse_24h_item(item, current_year: int) -> dict | None:
    """Parse one .box-items div from 24h.com.vn. Returns None if not a valid match."""
    # Group and date/time from .box-l
    group = ""
    box_l = item.find(class_="box-table")
    if box_l:
        group = box_l.get_text(strip=True)

    date_part = ""
    time_part = ""
    box_time = item.find(class_="box-time")
    if box_time:
        time_span = box_time.find("span")
        if time_span:
            time_part = time_span.get_text(strip=True)         # "11:00"
            time_span.extract()
        date_part = box_time.get_text(strip=True)              # "14/06"

    # Home team: .team-name.text-right
    home_el = item.find(class_="team-name text-right") or item.find("span", class_=lambda c: c and "team-name" in c and "text-right" in c)
    if not home_el:
        # Try via img alt inside first .box-clb
        clbs = item.find_all(class_="box-clb")
        if clbs:
            img = clbs[0].find("img")
            home_name = img["alt"] if img and img.get("alt") else ""
        else:
            return None
    else:
        home_name = home_el.get_text(strip=True)

    # Away team: .team-name without text-right (second occurrence)
    team_names = item.find_all("span", class_=lambda c: c and "team-name" in c)
    away_name = ""
    for tn in team_names:
        cls = " ".join(tn.get("class", []))
        if "text-right" not in cls:
            away_name = tn.get_text(strip=True)
            break
    if not away_name:
        # Fallback: img alt in second .box-clb
        clbs = item.find_all(class_="box-clb")
        if len(clbs) >= 2:
            img = clbs[-1].find("img")
            away_name = img["alt"] if img and img.get("alt") else ""

    if not home_name or not away_name:
        return None

    # Score from .box-score .box-t
    score_raw = ""
    box_score = item.find(class_="box-score")
    if box_score:
        box_t = box_score.find(class_="box-t")
        if box_t:
            score_raw = box_t.get_text(strip=True)

    # Status from .box-r text
    box_r = item.find(class_="box-r")
    box_r_text = box_r.get_text(strip=True).lower() if box_r else ""

    # Parse score and determine status
    home_score = away_score = None
    score_match = re.match(r"(\d+)\s*[-:]\s*(\d+)", score_raw)
    if score_match:
        home_score = int(score_match.group(1))
        away_score = int(score_match.group(2))
        status = "FINISHED" if ("highlight" in box_r_text or "video" in box_r_text) else "IN_PLAY"
    else:
        status = "SCHEDULED"

    # Parse date/time (VN timezone) → UTC
    utc_date = ""
    if date_part and time_part and re.match(r"\d{2}/\d{2}", date_part):
        try:
            dt_vn = datetime.strptime(
                f"{date_part} {time_part}/{current_year}", "%d/%m %H:%M/%Y"
            ).replace(tzinfo=VN_TZ)
            utc_date = dt_vn.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        except Exception:
            pass

    return _match(
        id=f"24h_{home_name}_{away_name}_{date_part}",
        home_team=_en(home_name),
        away_team=_en(away_name),
        home_score=home_score,
        away_score=away_score,
        status=status,
        utc_date=utc_date,
        group=group,
    )


async def _fetch_24h_all(client: httpx.AsyncClient) -> list[dict] | None:
    """Scrape 24h.com.vn. Returns all matches (unsorted) or None on failure."""
    try:
        from bs4 import BeautifulSoup
    except ImportError:
        return None

    try:
        resp = await client.get(
            URL_24H,
            headers=HEADERS_BROWSER,
            timeout=15,
            follow_redirects=True,
        )
        if resp.status_code != 200:
            return None

        soup = BeautifulSoup(resp.text, "html.parser")
        current_year = datetime.now(VN_TZ).year
        all_matches: list[dict] = []

        for item in soup.find_all(class_="box-items"):
            m = _parse_24h_item(item, current_year)
            if m:
                all_matches.append(m)

        return all_matches if all_matches else None

    except Exception:
        return None


# ─── ESPN fallback ───────────────────────────────────────────────────────────

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
        try:
            return int(float(s)) if s not in (None, "") else None
        except (ValueError, TypeError):
            return None

    status = _espn_status(event)
    note = comp.get("notes", [{}])
    group = note[0].get("headline", "") if note else ""

    return _match(
        id=event.get("id"),
        home_team=home.get("team", {}).get("displayName") or "?",
        away_team=away.get("team", {}).get("displayName") or "?",
        home_score=_score(home) if status != "SCHEDULED" else None,
        away_score=_score(away) if status != "SCHEDULED" else None,
        status=status,
        utc_date=event.get("date", ""),
        group=group,
        venue=comp.get("venue", {}).get("fullName", ""),
    )


async def _fetch_espn_all(client: httpx.AsyncClient) -> dict[tuple, dict] | None:
    """Fetch ESPN scores for UTC today ± 5 days.
    Returns lookup dict keyed by (home_team_lower, away_team_lower), or None on failure."""
    today_utc = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    base = datetime.strptime(today_utc, "%Y-%m-%d")
    days = [(base + timedelta(days=d)).strftime("%Y%m%d") for d in range(-5, 5)]

    async def _day(ds: str) -> list[dict]:
        try:
            r = await client.get(
                f"{ESPN_BASE}/scoreboard",
                params={"dates": ds},
                headers=ESPN_HEADERS,
                timeout=12,
            )
            if r.status_code == 200:
                return [_espn_parse(e) for e in (r.json().get("events") or [])]
        except Exception:
            pass
        return []

    results = await asyncio.gather(*[_day(d) for d in days])
    lookup: dict[tuple, dict] = {}
    for day_matches in results:
        for m in day_matches:
            key = (m["home_team"].lower(), m["away_team"].lower())
            lookup[key] = m
    return lookup if lookup else None


# ─── Merge helpers ──────────────────────────────────────────────────────────

def _split(matches: list[dict]) -> tuple[list[dict], list[dict]]:
    """Split match list into (upcoming[:5], recent[:5]) sorted by utc_date."""
    finished = sorted(
        [m for m in matches if m["status"] == "FINISHED"],
        key=lambda m: m["utc_date"], reverse=True,
    )
    upcoming = sorted(
        [m for m in matches if m["status"] != "FINISHED"],
        key=lambda m: m["utc_date"],
    )
    return upcoming[:5], finished[:5]


def _overlay_espn(matches: list[dict], espn: dict[tuple, dict]) -> list[dict]:
    """Overlay ESPN score/status onto each 24h match. Keeps 24h schedule info."""
    result = []
    for m in matches:
        key = (m["home_team"].lower(), m["away_team"].lower())
        em = espn.get(key)
        if em:
            m = dict(m)
            m["status"] = em["status"]
            m["status_label"] = em["status_label"]
            m["home_score"] = em["home_score"]
            m["away_score"] = em["away_score"]
        result.append(m)
    return result


# ─── Main endpoint ───────────────────────────────────────────────────────────

@router.get("/worldcup/today")
async def today_matches():
    today = datetime.now(VN_TZ).strftime("%Y-%m-%d")

    try:
        async with httpx.AsyncClient() as client:
            # Fetch both sources in parallel
            matches_24h, espn_lookup = await asyncio.gather(
                _fetch_24h_all(client),
                _fetch_espn_all(client),
            )

            if matches_24h:
                # 24h provides schedule; ESPN overlays real-time scores
                merged = _overlay_espn(matches_24h, espn_lookup or {})
                upcoming, recent = _split(merged)
                source = "24h+espn" if espn_lookup else "24h"
                return {"upcoming": upcoming, "recent": recent, "source": source, "as_of": today}

            if espn_lookup:
                # 24h unavailable — fall back to ESPN standalone
                espn_matches = list(espn_lookup.values())
                upcoming, recent = _split(espn_matches)
                return {"upcoming": upcoming, "recent": recent, "source": "espn", "as_of": today}

    except Exception as exc:
        return {"upcoming": [], "recent": [], "source": "error", "error": str(exc)}

    return {"upcoming": [], "recent": [], "source": "none", "as_of": today}
