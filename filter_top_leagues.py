#!/usr/bin/env python3
"""
Fetches sports playlist, filters to Top Major Leagues worldwide,
converts all times to Spain timezone, and outputs clean JSON.
"""

import json
import os
import re
import sys
import urllib.request
from datetime import datetime, timezone, timedelta

# ──────────────────────────────────────────────────────
# Spain timezone: CEST (UTC+2) in summer, CET (UTC+1) in winter
# 21 Aug 2026 → CEST (UTC+2)
# ──────────────────────────────────────────────────────
SPAIN_TZ = timezone(timedelta(hours=2))   # CEST (summer)
SPAIN_TZ_WINTER = timezone(timedelta(hours=1))  # CET (winter)

# Spain DST 2026: last Sunday March → last Sunday October
# March 29 2026 (clocks forward) → Oct 25 2026 (clocks back)
DST_START_2026 = datetime(2026, 3, 29, 2, 0, 0)
DST_END_2026 = datetime(2026, 10, 25, 3, 0, 0)


def spain_offset(dt_utc):
    """Return correct Spain offset for a given UTC datetime."""
    if DST_START_2026 <= dt_utc.replace(tzinfo=None) < DST_END_2026:
        return SPAIN_TZ       # UTC+2
    return SPAIN_TZ_WINTER    # UTC+1


# ──────────────────────────────────────────────────────
# MAJOR LEAGUES CONFIG  {sport: {keywords, teams?}}
# keywords → matched against league_name (case-insensitive)
# teams    → if no league keyword hit, try matching team names
# ──────────────────────────────────────────────────────
MAJOR_LEAGUES = {
    # ── FOOTBALL ──────────────────────────────────────
    "Football": {
        "keywords": [
            "premier league",       # English PL
            "la liga",              # Spain
            "bundesliga",           # Germany (also Austrian, but both top-tier)
            "serie a",              # Italy
            "ligue 1",              # France
            "eredivisie",           # Netherlands
            "primeira liga",        # Portugal
            "dfb pokal",            # German Cup
            "copa del rey",         # Spanish Cup
            "fa cup",               # English Cup
            "champions league",     # UEFA CL
            "europa league",        # UEFA EL
            "conference league",    # UEFA ECL
            "super cup",            # UEFA Super Cup
            "liga profesional",     # Argentina
            "brasileir",            # Brazil
            "liga mx",              # Mexico
            "mls",                  # USA/Canada
            "saudi",                # Saudi Pro League
            "pro league",           # Saudi / UAE top flight
            "j1 league",            # Japan
            "super lig",            # Turkey
        ],
    },

    # ── CRICKET ───────────────────────────────────────
    "Cricket": {
        "keywords": [
            "test",                 # Test cricket (1st Test, 2nd Test…)
            "odi",                  # One Day International
            "t20",                  # T20I
            "ipl",                  # Indian Premier League
            "big bash",             # Australia
            "ashes",                # The Ashes
            "world cup",            # ICC World Cup
            "hundred",              # The Hundred
            "psl",                  # Pakistan Super League
            "cpl",                  # Caribbean PL
            "bbl",                  # Big Bash alt
            "county championship",  # England
        ],
        "teams": [
            "india", "australia", "england", "pakistan",
            "new zealand", "south africa", "sri lanka",
            "west indies", "bangladesh", "zimbabwe",
        ],
    },

    # ── FORMULA 1 ────────────────────────────────────
    "Formula 1": {
        "keywords": [
            "formula 1", "f1 ", "f1",
        ],
    },

    # ── MOTOGP ────────────────────────────────────────
    "MotoGP": {
        "keywords": ["motogp", "moto gp"],
    },

    # ── TENNIS ────────────────────────────────────────
    "Tennis": {
        "keywords": [
            "roland garros", "french open",
            "australian open",
            "atp final", "wta final",
            "masters 1000", "cincinnati open", "indian wells",
            "miami open", "monte carlo", "rome open",
            "canada open", "shanghai master", "paris master",
        ],
        "league_only": [
            # These must appear in league_name only (not match name)
            "wimbledon", "us open",
            "atp ", "wta ",
        ],
    },

    # ── GOLF ──────────────────────────────────────────
    "Golf": {
        "keywords": [
            "pga tour", "pga championship",
            "the masters", "british open", "the open",
            "ryder cup", "lpga", "dp world tour",
            "fedex cup",
        ],
        "league_only": [
            # "us open" in golf only if league_name contains it
            "us open",
        ],
    },

    # ── CYCLING ───────────────────────────────────────
    "Cycling": {
        "keywords": [
            "tour de france", "giro d'italia", "la vuelta",
            "vuelta a españa",
            "world championship",
        ],
    },

    # ── BASKETBALL ────────────────────────────────────
    "Basketball": {
        "keywords": [
            "nba", "euroleague", "acb", "liga endesa",
            "ncaa", "wnba",
        ],
    },

    # ── AMERICAN FOOTBALL ────────────────────────────
    "American Football": {
        "keywords": ["nfl", "super bowl", "ncaa football", "college football"],
    },

    # ── BASEBALL ──────────────────────────────────────
    "Baseball": {
        "keywords": ["mlb", "npb"],
        "league_only": [
            "world series",   # Only if league_name has it (avoid UCI cycling)
        ],
    },

    # ── ICE HOCKEY ────────────────────────────────────
    "Ice Hockey": {
        "keywords": ["nhl", "khl", "stanley cup"],
    },

    # ── AUSTRALIAN FOOTBALL ───────────────────────────
    "Australian Football": {
        "keywords": [
            "afl",   # Australian Football League (check before Rugby's premiership)
        ],
    },

    # ── RUGBY ─────────────────────────────────────────
    "Rugby": {
        "keywords": [
            "six nations", "rugby championship",
            "top 14", "super rugby",
            "rugby world cup",
            "currie cup",
            "premiership",   # English rugby union Premiership
        ],
    },

    # ── BOXING ────────────────────────────────────────
    "Boxing": {
        "keywords": [
            "world championship", "title fight", "undisputed",
            "heavyweight", "wbc ", "wba ", "ibf ", "wbo ",
        ],
    },

    # ── MMA ───────────────────────────────────────────
    "MMA": {
        "keywords": ["ufc", "bellator", "pfl"],
    },

    # ── DARTS ─────────────────────────────────────────
    "Darts": {
        "keywords": ["pdc", "darts", "world matchplay"],
    },

    # ── SNOOKER ───────────────────────────────────────
    "Snooker": {
        "keywords": ["snooker", "world snooker"],
    },
}

# ──────────────────────────────────────────────────────
# Leagues / keywords to EXCLUDE even if they match above
# (lower-tier, youth, women's friendlies, etc.)
# ──────────────────────────────────────────────────────
EXCLUDE_KEYWORDS = [
    "premier league 2",     # U21/reserve league
    "youth championship",   # Youth
    "women",                # Women's (unless explicitly major)
    "u19", "u20", "u21", "u23",
    "friendly", "friendlies",
    "womens", "frauen",     # Women's leagues (less common)
    "ofc ", "ofc",          # OFC Champions League (Oceania - minor)
    "afc ", "afc",          # AFC Champions League (Asia - minor, unless top teams)
    "conmebol",             # South American continental cups (minor)
    "concacaf",             # North American continental cups (minor)
    "caf ", "caf",          # African continental cups (minor)
    "oceania",              # Oceania competitions (minor)
    "uci ", "uci",          # UCI cycling events (not major league sport)
    "mountain bike",        # Cycling sub-discipline
]


def lc(text):
    """Lowercase helper."""
    return text.lower() if text else ""


def is_excluded(match):
    """Check if match should be excluded despite matching a major league."""
    league = lc(match.get("league_name", ""))
    name = lc(match.get("name", ""))
    combined = f"{league} {name}"
    return any(kw in combined for kw in EXCLUDE_KEYWORDS)


def find_sport(match):
    """
    Determine if a match belongs to a top major league.
    Uses word-boundary regex to avoid false positives.
    Returns (sport, matched_keyword) or (None, None).
    """
    if is_excluded(match):
        return None, None

    league = lc(match.get("league_name", ""))
    teams = " ".join([
        lc(match.get("localteam_name", "")),
        lc(match.get("visitorteam_name", "")),
    ])
    match_name = lc(match.get("name", ""))

    for sport, cfg in MAJOR_LEAGUES.items():
        # 1) Check league_name + match_name with word-boundary regex
        for kw in cfg.get("keywords", []):
            pattern = r'\b' + re.escape(kw.strip()) + r'\b'
            if re.search(pattern, league) or re.search(pattern, match_name):
                return sport, kw

        # 2) league_only keywords: only check league_name (not match_name)
        for kw in cfg.get("league_only", []):
            pattern = r'\b' + re.escape(kw.strip()) + r'\b'
            if re.search(pattern, league):
                return sport, kw

        # 3) Fallback: team-name matching (useful for Cricket, F1, etc.)
        for kw in cfg.get("teams", []):
            if re.search(r'\b' + re.escape(kw) + r'\b', teams):
                return sport, kw

    return None, None


def ts_to_spain(ts_unix):
    """Convert Unix timestamp → Spain local datetime string."""
    if not ts_unix:
        return None
    dt_utc = datetime.fromtimestamp(int(ts_unix), tz=timezone.utc)
    dt_spain = dt_utc.astimezone(spain_offset(dt_utc))
    return dt_spain.strftime("%Y-%m-%d %H:%M:%S CEST")


def main():
    # Read URL from environment variable (set via GitHub Secrets)
    url = os.environ.get("PLAYLIST_URL")
    if not url:
        print("ERROR: PLAYLIST_URL environment variable not set", file=sys.stderr)
        sys.exit(1)

    print("⏳  Fetching playlist…", file=sys.stderr)
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        data = json.loads(resp.read().decode())

    matches = data.get("matches", [])
    print(f"📥  Total matches fetched: {len(matches)}", file=sys.stderr)

    # ── Filter to major leagues ──────────────────────
    kept = []
    sport_counts = {}

    for m in matches:
        sport, keyword = find_sport(m)
        if not sport:
            continue

        start_ts = m.get("start_at") or m.get("timestamp")

        entry = {
            "id":              m.get("id"),
            "sport":           sport,
            "league":          m.get("league_name", ""),
            "match":           m.get("name", ""),
            "status":          m.get("status", ""),
            "score":           m.get("score", ""),
            "home_team":       m.get("localteam_name", ""),
            "away_team":       m.get("visitorteam_name", ""),
            "spain_time":      ts_to_spain(start_ts),
            "start_unix":      start_ts,
            "is_live":         m.get("is_playing", False),
            "matched_keyword": keyword,
            "stream_count":    len(m.get("link_live", [])),
            "streams":         m.get("link_live", []),
            "cdn_domain":      m.get("cdn_domain", ""),
            "referer":         m.get("referer", ""),
        }
        kept.append(entry)
        sport_counts[sport] = sport_counts.get(sport, 0) + 1

    # Sort: live first, then by start time
    kept.sort(key=lambda x: (not x["is_live"], x["start_unix"] or 0))

    # ── Group by sport → league ──────────────────────
    grouped = {}
    for m in kept:
        key = f"{m['sport']} › {m['league']}"
        grouped.setdefault(key, []).append(m)

    # ── Build output ─────────────────────────────────
    output = {
        "source":       url,
        "generated_at": datetime.now(spain_offset(datetime.now(timezone.utc)))
                        .strftime("%Y-%m-%d %H:%M:%S CEST"),
        "timezone":     "Europe/Madrid (auto CEST/CET)",
        "summary": {
            "total_matches":  len(matches),
            "major_leagues":  len(kept),
            "by_sport":       sport_counts,
        },
        "matches":      grouped,
    }

    # ── Write JSON ───────────────────────────────────
    out_path = "top_leagues_spain.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(output, f, indent=2, ensure_ascii=False)

    # Also print to stdout
    print(json.dumps(output, indent=2, ensure_ascii=False))

    # ── Stats ────────────────────────────────────────
    print(f"\n✅  Kept {len(kept)} matches from major leagues:", file=sys.stderr)
    for sport, count in sorted(sport_counts.items(), key=lambda x: -x[1]):
        print(f"    {sport:25s}  {count}", file=sys.stderr)
    print(f"📁  Saved → {out_path}", file=sys.stderr)


if __name__ == "__main__":
    main()
