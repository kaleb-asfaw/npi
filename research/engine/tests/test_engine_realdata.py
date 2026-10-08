"""Validates the engine against real, published NCAA NPI snapshots.

After fixing the Game-Value-multiplication bug and excluding teams with no
published NPI from the valid-opponent roster (see schedule.py's
_load_team_roster -- Carlow/Regent/etc. have real schedules but no
published NPI, and letting other teams use them as opponents was
inheriting a phantom rating NCAA never publishes), measured error is mean
~0.01-0.02, median ~0.004-0.005, max under 1.0, with zero teams missing by
more than 1.0 point across both validated dates. Tolerances below are set
with real margin above that, not tightened to the noise floor.
"""
from __future__ import annotations

import csv
import statistics
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

from research.engine import WSOC, NPIEngine
from research.engine.schedule import DEFAULT_DATA_ROOT, load_season_games

NPI_DIR = DEFAULT_DATA_ROOT / "wsoc" / "25-26" / "npi"

# allowable error bounds for homemade calculation vs NCAA-listed ones
MEAN_ERROR_TOLERANCE = 0.02
MEDIAN_ERROR_TOLERANCE = 0.01


def _published_npi(snapshot_csv: Path) -> dict[str, float]:
    published = {}
    with snapshot_csv.open() as f:
        for row in csv.DictReader(f):
            if row["NPI"].strip():
                published[row["team_id"]] = float(row["NPI"])
    return published


SNAPSHOT_CASES = [
    ("2025-10-05.csv", date(2025, 10, 5)), # first available NPI
    ("2025-11-09_selections.csv", date(2025, 11, 9)), # end of regular season
]


@pytest.mark.parametrize("snapshot_file, as_of", SNAPSHOT_CASES)
def test_matches_published_snapshot(snapshot_file, as_of):
    snapshot_csv = NPI_DIR / snapshot_file
    published = _published_npi(snapshot_csv)

    games = load_season_games("wsoc", "25-26", roster_snapshot=snapshot_file)
    computed = NPIEngine(WSOC).calculate_npi(games, as_of=as_of)

    errors = [abs(computed.get(tid, 0.0) - value) for tid, value in published.items()]
    mean_err = statistics.mean(errors)
    median_err = statistics.median(errors)

    assert mean_err < MEAN_ERROR_TOLERANCE, f"mean error {mean_err:.4f} too high for {snapshot_file}"
    assert median_err < MEDIAN_ERROR_TOLERANCE, f"median error {median_err:.4f} too high for {snapshot_file}"


if __name__ == "__main__":
    # Lets this file also be run directly (`python3 path/to/this_file.py`),
    # not just via `pytest`/`python -m pytest` -- both end up doing the same
    # thing, since this just hands execution to pytest itself.
    sys.exit(pytest.main([__file__, "-v"]))
