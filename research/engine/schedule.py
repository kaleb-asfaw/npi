"""Loads real, played games from the scraped data/ directory into Game
objects the engine can consume.

This module owns all of the messy, source-specific concerns (team-name
normalization, filtering out non-DIII/non-member opponents, parsing
stats.ncaa.org's date/result formatting) so that NPIEngine itself never has
to know anything about CSVs or how a particular opponent's name is spelled.
"""
from __future__ import annotations

import csv
import re
from datetime import date
from pathlib import Path

from .types import Game, Result, Site

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DATA_ROOT = REPO_ROOT / "research" / "data"

_AQ_SUFFIX = re.compile(r"\s*\(AQ\)\s*$")
_VALID_OUTCOMES = {"W", "L", "T"}
_SITE_MAP: dict[str, Site] = {"home": "home", "away": "away", "neutral": "neutral"}


def _strip_aq(name: str) -> str:
    return _AQ_SUFFIX.sub("", name).strip()


def _parse_date(s: str) -> date:
    m, d, y = s.split("/")
    return date(int(y), int(m), int(d))


def _load_team_roster(npi_csv: Path) -> dict[str, str]:
    """{normalized team name: team_id} from an NPI snapshot CSV, used only
    as a team directory -- the NPI *values* in this file are never read.

    Rows with no published NPI (e.g. Carlow, Regent in 2025-26 -- real DIII
    teams with real schedules, but excluded from NCAA's own NPI pool for
    reasons the published data doesn't explain) are skipped. Confirmed by
    direct measurement: including them as valid opponents meant a handful
    of winless teams (whose rating is just their single weakest opponent's
    NPI) inherited a phantom, unpublished rating for that opponent -- e.g.
    Wesleyan (GA)'s computed NPI was exactly 0.8x a synthetic "Regent"
    rating NCAA never publishes. Excluding these 4 teams from the valid
    roster dropped mean error 6x (0.11 -> 0.018) and eliminated every
    >1.0 miss across both validated snapshot dates."""
    name_to_id: dict[str, str] = {}
    with npi_csv.open() as f:
        for row in csv.DictReader(f):
            if not row["NPI"].strip():
                continue
            name_to_id[_strip_aq(row["Team"])] = row["team_id"]
    return name_to_id


def load_season_games(
    sport: str,
    season: str,
    data_root: Path = DEFAULT_DATA_ROOT,
    roster_snapshot: str | None = None,
) -> list[Game]:
    """Loads every real, played game for `sport`/`season`.

    Reads data_root/{sport}/{season}/schedule/*.csv for every team, keeping
    only games where both participants are in the known roster (filters out
    non-DIII/non-member opponents, e.g. NAIA crossover games). Returns the
    FULL season's games, unfiltered by date -- pass the result straight to
    NPIEngine.calculate_npi(games, as_of) to compute a leaderboard as of any
    date, or splice in hypothetical Games for simulation.

    roster_snapshot: filename under .../npi/ to use purely as a team
    id<->name directory. Defaults to the earliest available snapshot.
    """
    season_dir = data_root / sport / season
    npi_dir = season_dir / "npi"
    schedule_dir = season_dir / "schedule"

    if roster_snapshot is None:
        candidates = sorted(p for p in npi_dir.glob("*.csv"))
        if not candidates:
            raise FileNotFoundError(f"No NPI snapshot CSVs found in {npi_dir} to use as a team roster")
        roster_csv = candidates[0]
    else:
        roster_csv = npi_dir / roster_snapshot

    name_to_id = _load_team_roster(roster_csv)
    known_ids = set(name_to_id.values())

    games: list[Game] = []
    for fn in schedule_dir.glob("*.csv"):
        team_id = fn.name.split("_", 1)[0]
        if team_id not in known_ids:
            continue
        with fn.open() as f:
            for row in csv.DictReader(f):
                outcome = row.get("outcome", "").strip()
                date_s = row.get("date_parsed", "").strip()
                if outcome not in _VALID_OUTCOMES or not date_s:
                    continue
                try:
                    game_date = _parse_date(date_s)
                except ValueError:
                    continue
                opp_name = row.get("opponent", "").strip().lstrip("@").strip()
                opp_id = name_to_id.get(opp_name)
                if opp_id is None:
                    continue  # not a known DIII opponent ==> out of scope for NPI
                site = _SITE_MAP.get(row.get("home_away", "").strip(), "neutral")
                overtime = row.get("overtime", "").strip() == "True"
                games.append(
                    Game(
                        team_id=team_id,
                        opponent_id=opp_id,
                        date=game_date,
                        result=outcome,  
                        site=site,
                        overtime=overtime,
                    )
                )
    return games
