"""Regression tests against hand-derived, closed-form NPI examples.

Every value here was independently verified by direct algebra (not just
simulation) during the engine's design -- see docs/npi_spec.md's validation
ladder. These are fast and fully deterministic, so they're the primary
regression guard: the GV-multiplication bug found during real-data
validation would have been caught immediately by test_isolated_pair alone.
"""
from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

import pytest

# Makes this file importable whether it's run via pytest (which honors
# pyproject.toml's pythonpath setting) or directly as a script (`python3
# this_file.py`), which does not -- Python only puts this file's own
# directory on sys.path in that case, not the repo root.
_REPO_ROOT = Path(__file__).resolve().parents[3]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from research.engine import Dials, Game, NPIEngine

D0 = date(2025, 9, 1)  # arbitrary common date; only relative ordering matters here
WSOC = Dials(sos_weight=0.80, win_weight=0.20, qwb_base=54.0, qwb_mult=0.5, min_wins=8.0)


def test_isolated_pair_converges_to_closed_form():
    """A beats B, first game of the season for both. Closed form (derived
    assuming the loser settles below the QWB base, then confirmed
    self-consistent): winner -> 500/9, loser -> 400/9."""
    games = [
        Game(team_id="A", opponent_id="B", date=D0, result="W"),
        Game(team_id="B", opponent_id="A", date=D0, result="L"),
    ]
    npi = NPIEngine(WSOC).calculate_npi(games, as_of=D0)
    assert npi["A"] == pytest.approx(500 / 9, abs=1e-6)
    assert npi["B"] == pytest.approx(400 / 9, abs=1e-6)


def test_disjoint_pairs_decompose_independently():
    """Two fully disjoint matchups (no shared opponents) must converge to
    the exact same winner/loser values as a single isolated pair -- nothing
    in Steps 1-6 may reference a team outside your own schedule. Margin of
    victory is irrelevant (NPI only sees W/L/T)."""
    games = [
        Game(team_id="A", opponent_id="B", date=D0, result="W"),
        Game(team_id="B", opponent_id="A", date=D0, result="L"),
        Game(team_id="C", opponent_id="D", date=D0, result="W"),
        Game(team_id="D", opponent_id="C", date=D0, result="L"),
    ]
    npi = NPIEngine(WSOC).calculate_npi(games, as_of=D0)
    for winner in ("A", "C"):
        assert npi[winner] == pytest.approx(500 / 9, abs=1e-6)
    for loser in ("B", "D"):
        assert npi[loser] == pytest.approx(400 / 9, abs=1e-6)


def _mirrored(team_id, opponent_id, dt, result):
    """One real game produces two Game rows, one per team's perspective."""
    inverse = {"W": "L", "L": "W", "T": "T"}[result]
    return [
        Game(team_id=team_id, opponent_id=opponent_id, date=dt, result=result),
        Game(team_id=opponent_id, opponent_id=team_id, date=dt, result=inverse),
    ]


def test_matchday2_square_and_hexagon():
    """10-team, 2-matchday scenario worked by hand across this project's
    design conversation. MD1: 1v2,3v4,5v6,7v8,9v10 (odd number wins).
    MD2: 1v3,2v4,5v7,6v9,8v10 (smaller number wins). Decomposes into a
    4-cycle {1,2,3,4} and a 6-cycle {5..10}, each independently solvable by
    algebra; exact values below were cross-checked against simulation."""
    d1, d2 = date(2025, 9, 1), date(2025, 9, 8)
    md1 = [(1, 2), (3, 4), (5, 6), (7, 8), (9, 10)]
    md2 = [(1, 3), (2, 4), (5, 7), (6, 9), (8, 10)]
    games: list[Game] = []
    for w, l in md1:
        games += _mirrored(str(w), str(l), d1, "W")
    for w, l in md2:
        games += _mirrored(str(w), str(l), d2, "W")

    npi = NPIEngine(WSOC).calculate_npi(games, as_of=d2)

    expected = {
        "1": 60.0, "2": 50.0, "3": 50.0, "4": 40.0,
        "5": 62.962963, "6": 53.703704, "7": 53.703704,
        "8": 46.296296, "9": 46.296296, "10": 37.037037,
    }
    for team, value in expected.items():
        assert npi[team] == pytest.approx(value, abs=1e-5), team


def test_quality_win_bonus_formula():
    """MIT vs Williams, decisive win, SOS(Williams)=56.888 -- from the
    NPI Calculator worksheet. GameRating = (56.888*0.80 + 20 +
    (56.888-54)*0.5) * 1.0 = 66.954."""
    gr = NPIEngine(WSOC)._game_rating(opp_prev_npi=56.888, is_win=True, gv=1.0)
    assert gr == pytest.approx(66.954, abs=1e-3)


def test_tie_split_halves_both_sides():
    """MIT vs Middlebury, tie, SOS=58.251. Win-half and loss-half each get
    Game Value 0.5, applied to the WHOLE bracket (not just the win bonus)."""
    engine = NPIEngine(WSOC)
    win_half = engine._game_rating(opp_prev_npi=58.251, is_win=True, gv=0.5)
    loss_half = engine._game_rating(opp_prev_npi=58.251, is_win=False, gv=0.5)
    assert win_half == pytest.approx(34.363, abs=1e-3)
    assert loss_half == pytest.approx(23.300, abs=1e-3)


def test_good_loss_gets_dropped():
    """A team that beat a weak opponent (prev NPI 20) and lost to a very
    strong one (prev NPI 90): the loss's computed value (72.0) exceeds what
    the team's rating would be without it, so it gets dropped entirely --
    final NPI is just the win's rating (36.0)."""
    engine = NPIEngine(WSOC)
    entries = [("weak", "W", 1.0), ("strong", "L", 1.0)]
    prev_npi = {"weak": 20.0, "strong": 90.0}
    result = engine._solve_team_pass(entries, prev_npi)
    assert result == pytest.approx(36.0, abs=1e-6)


def test_overtime_split_matches_source_example():
    """thatdonsoftware's worked example: H/A=0.9/1.1, OT win/loss=0.8/0.2,
    home team wins in overtime. Home receives (win=0.72, loss=0.22); away
    receives (win=0.22, loss=0.72)."""
    dials = Dials(
        sos_weight=0.8, win_weight=0.20, qwb_base=54.0, qwb_mult=0.5, min_wins=8.0,
        home_gv=0.9, away_gv=1.1, ot_win_dial=0.8, ot_loss_dial=0.2,
    )
    engine = NPIEngine(dials)
    home_games = [Game(team_id="H", opponent_id="A", date=D0, result="W", site="home", overtime=True)]
    away_games = [Game(team_id="A", opponent_id="H", date=D0, result="L", site="away", overtime=True)]

    home_entries = engine._split_entries(home_games)
    away_entries = engine._split_entries(away_games)

    assert sorted(gv for (_opp, _r, gv) in home_entries) == pytest.approx(sorted([0.72, 0.22]), abs=1e-6)
    assert sorted(gv for (_opp, _r, gv) in away_entries) == pytest.approx(sorted([0.22, 0.72]), abs=1e-6)


def test_default_overtime_dial_is_a_no_op():
    """At the WSOC default (100/0), a decisive OT result should behave
    exactly like a normal, unsplit decisive game -- one entry, full weight,
    no phantom zero-weight entry on the other side."""
    engine = NPIEngine(WSOC)
    games = [Game(team_id="T", opponent_id="O", date=D0, result="W", site="home", overtime=True)]
    entries = engine._split_entries(games)
    assert entries == [("O", "W", 1.0)]


def test_minimum_wins_floor_and_partial_inclusion():
    """Mount Union 2025 football, Pass 31 (sourced from thatdonsoftware.com):
    10 wins, no losses, Minimum Wins = 5. Exercises every branch of Step 5 --
    full-via-quality (Grove City), full-via-floor (Otterbein/Marietta/
    Muskingum), partial (Heidelberg, landing exactly on the floor), and
    zero (the remaining five). Final rating: 73.592909."""
    football = Dials(sos_weight=0.6, win_weight=0.40, qwb_base=54.0, qwb_mult=0.25, min_wins=5.0)
    # (opponent, prev_npi, game_value), in schedule order
    opponents = [
        ("grove_city", 57.308463, 1.1),
        ("otterbein", 57.159682, 0.9),
        ("marietta", 54.753555, 1.1),
        ("muskingum", 54.520574, 0.9),
        ("heidelberg", 52.918602, 1.1),
        ("wheaton_il", 52.673797, 0.9),
        ("wilmington_oh", 51.497358, 1.1),
        ("ohio_northern", 49.279094, 0.9),
        ("baldwin_wallace", 46.437031, 1.1),
        ("capital", 46.283255, 0.9),
    ]
    entries = [(opp, "W", gv) for opp, _prev, gv in opponents]
    prev_npi = {opp: prev for opp, prev, _gv in opponents}

    engine = NPIEngine(football)
    result = engine._solve_team_pass(entries, prev_npi)
    assert result == pytest.approx(73.592909, abs=1e-5)


if __name__ == "__main__":
    # Lets this file also be run directly (`python3 path/to/this_file.py`),
    # not just via `pytest`/`python -m pytest` -- both end up doing the same
    # thing, since this just hands execution to pytest itself.
    sys.exit(pytest.main([__file__, "-v"]))
