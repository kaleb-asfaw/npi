"""
NPI dial configurations.

Full set of knobs used to calculate NPI. These change per sport, so 
define a sport's NPI architecture HERE
"""
from __future__ import annotations

from dataclasses import dataclass

_TOL = 1e-10


def _assert_close(total: float, expected: float, label: str) -> None:
    if abs(total - expected) > _TOL:
        raise ValueError(f"{label} must sum to {expected}, got {total}")


@dataclass(frozen=True)
class Dials:
    sos_weight: float   # Stregth-of-schedule [SOS] weight \in [0, 1]
    win_weight: float   # Win % weight \in [0, 1] st. sos_weight + win_weight = 1
    qwb_base: float      # Quality Win Bonus threshold, e.g. 54.0
    qwb_mult: float      # Quality Win Bonus multiplier, e.g. 0.5
    min_wins: float       # Minimum Wins floor
    home_gv: float = 1.0  # Game Value for a home win / away loss
    away_gv: float = 1.0  # Game Value for an away win / home loss
    ot_win_dial: float = 1.0   # multiply by game value in case of OT win
    ot_loss_dial: float = 0.0  # multiply by game value in case of OT loss
    # (ot_win_dial + ot_loss_dial == 1)

    def __post_init__(self) -> None:
        _assert_close(self.sos_weight + self.win_weight, 1.0, "sos_weight + win_weight")
        _assert_close(self.ot_win_dial + self.ot_loss_dial, 1.0, "ot_win_dial + ot_loss_dial")
        _assert_close(self.home_gv + self.away_gv, 2.0, "home_gv + away_gv")


# NCAA DIII Women's Soccer dials (used in 25/26 season)
# Source: D3CC_NPIWeights.pdf (https://ncaaorg.s3.amazonaws.com/committees/d3/champs/D3CC_NPIWeights.pdf)
WSOC = Dials(
    sos_weight=0.80,
    win_weight=0.20,
    qwb_base=54.0,
    qwb_mult=0.5,
    min_wins=8.0,
    home_gv=1.0,
    away_gv=1.0,
    ot_win_dial=1.0,
    ot_loss_dial=0.0,
)
