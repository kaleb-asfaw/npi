"""The NPI calculation engine.
Implements the recursive NPI algorithm as derived in docs/npi_spec.md,
"""
from __future__ import annotations

from collections import defaultdict
from datetime import date

from .dials import Dials
from .types import Game

MAX_PASSES = 10_000
CONVERGENCE_TOL = 1e-10

# One game's worth of bookkeeping
_Entry = tuple[str, str, float]


class NPIConvergenceError(RuntimeError):
    """Raised when the pass loop fails to converge within MAX_PASSES, or
    diverges outright. See docs/npi_spec.md's 'Open questions' section --
    safeguard for garbage NPIs.
    """


class NPIEngine:
    def __init__(self, dials: Dials):
        self.dials = dials

    def _game_value(self, site: str, won: bool) -> float:
        """Game Value for a decisive result at `site`, from the team's own
        perspective. The same value applies to both participants of a given
        game; neutral site (or an unrecognized site) is always 1.0."""
        d = self.dials
        if site == "home":
            return d.home_gv if won else d.away_gv
        if site == "away":
            return d.away_gv if won else d.home_gv
        return 1.0

    def _overtime_split(self, site: str, actually_won: bool) -> tuple[float, float]:
        """Game Values for a decisive result reached in overtime: split like
        a tie (a win-piece and a loss-piece), but scaled asymmetrically by
        the OT Win/Loss dial rather than a flat 0.5/0.5. Verified against
        thatdonsoftware's worked example: H/A=0.9/1.1, OT=0.8/0.2, home wins
        in OT -> home receives (win=0.72, loss=0.22), away receives
        (win=0.22, loss=0.72). With the default 100/0 dial this collapses
        to a normal, unsplit decisive result (loss-piece Game Value = 0)."""
        d = self.dials
        if actually_won:
            return (
                self._game_value(site, won=True) * d.ot_win_dial,
                self._game_value(site, won=False) * d.ot_loss_dial,
            )
        return (
            self._game_value(site, won=True) * d.ot_loss_dial,
            self._game_value(site, won=False) * d.ot_win_dial,
        )

    def _split_entries(self, team_games: list[Game]) -> list[_Entry]:
        """Converts one team's raw Game rows into (opponent_id, 'W'/'L', GV)
        entries: a tie always splits into a half-weight win entry and a
        half-weight loss entry (Convention A); a decisive result reached in
        overtime splits via the OT dial instead (a no-op at the 100/0
        default, which is why this was invisible until the dial was wired
        up); every other decisive game stays a single, unsplit entry."""
        entries: list[_Entry] = []
        for g in team_games:
            if g.result == "T":
                entries.append((g.opponent_id, "W", self._game_value(g.site, won=True) / 2.0))
                entries.append((g.opponent_id, "L", self._game_value(g.site, won=False) / 2.0))
            elif g.overtime:
                win_gv, loss_gv = self._overtime_split(g.site, actually_won=(g.result == "W"))
                if win_gv > 0:
                    entries.append((g.opponent_id, "W", win_gv))
                if loss_gv > 0:
                    entries.append((g.opponent_id, "L", loss_gv))
            elif g.result == "W":
                entries.append((g.opponent_id, "W", self._game_value(g.site, won=True)))
            else:
                entries.append((g.opponent_id, "L", self._game_value(g.site, won=False)))
        return entries


    def _adjusted_win_pct(self, entries: list[_Entry]) -> float:
        if not entries:
            return 0.0
        win_gv = sum(gv for (_, r, gv) in entries if r == "W")
        total_gv = sum(gv for (_, r, gv) in entries)
        return 100.0 * win_gv / total_gv if total_gv > 0 else 0.0


    def _initial_ratings(
        self, entries_by_team: dict[str, list[_Entry]], adj_win_pct: dict[str, float]
    ) -> dict[str, float]:
        d = self.dials
        npi0: dict[str, float] = {}
        for team_id, entries in entries_by_team.items():
            if not entries:
                npi0[team_id] = 0.0
                continue
            num = sum(adj_win_pct[opp] * gv for (opp, _r, gv) in entries)
            den = sum(gv for (_opp, _r, gv) in entries)
            npi0[team_id] = d.sos_weight * (num / den) if den > 0 else 0.0
        return npi0


    def _game_rating(self, opp_prev_npi: float, is_win: bool, gv: float) -> float:
        d = self.dials
        sos = opp_prev_npi * d.sos_weight
        if is_win:
            # win_weight is a fraction (same units as sos_weight, so the two
            # sum to 1) -- scale to "points" (100% win * weight) here, same
            # as a per-game Win% value in the worksheet source: 100 * 0.20.
            win_bonus = 100.0 * d.win_weight
            qwb = max(0.0, opp_prev_npi - d.qwb_base) * d.qwb_mult
            return (sos + win_bonus + qwb) * gv
        return sos * gv


    def _solve_team_pass(self, entries: list[_Entry], prev_npi: dict[str, float]) -> float:
        d = self.dials
        wins: list[tuple[float, float]] = []   # (gv, gr)
        losses: list[tuple[float, float]] = []
        for opp, r, gv in entries:
            opp_prev = prev_npi.get(opp, 0.0)
            gr = self._game_rating(opp_prev, r == "W", gv)
            (wins if r == "W" else losses).append((gv, gr))

        if not wins:
            if not entries:
                return 0.0
            # No wins (and no ties, since a tie always contributes a win
            # entry): rating is the SOS-scaled rating of the single
            # lowest-rated opponent.
            return d.sos_weight * min(prev_npi.get(opp, 0.0) for (opp, _r, _gv) in entries)

        wins.sort(key=lambda x: -(x[1] / x[0]))
        losses.sort(key=lambda x: -(x[1] / x[0]))

        tgr = sum(gr for (_gv, gr) in losses)
        tgv = sum(gv for (gv, _gr) in losses)
        cur = tgr / tgv if tgv > 0 else 0.0
        cw = 0.0

        for gv, gr in wins:
            trial = (tgr + gr) / (tgv + gv)
            if trial >= cur or cw + gv <= d.min_wins:
                tgr += gr
                tgv += gv
                cw += gv
                cur = tgr / tgv
            elif cw >= d.min_wins:
                pass  # excess win beyond the floor that would lower the rating: drop it
            else:
                f = (d.min_wins - cw) / gv
                tgr += f * gr
                tgv += f * gv
                cw += f * gv
                cur = tgr / tgv

        for gv, gr in losses:
            if tgv - gv <= 0:
                continue
            trial = (tgr - gr) / (tgv - gv)
            if trial < cur:
                tgr -= gr
                tgv -= gv
                cur = tgr / tgv if tgv > 0 else 0.0

        return cur


    def calculate_npi(self, games: list[Game], as_of: date) -> dict[str, float]:
        """
        Computes the full NPI leaderboard as of `as_of`, from `games`.
        This is public endpoint that should be used for research/sims
        """
        relevant = [g for g in games if g.date <= as_of]

        games_by_team: dict[str, list[Game]] = defaultdict(list)
        teams: set[str] = set()
        for g in relevant:
            games_by_team[g.team_id].append(g)
            teams.add(g.team_id)
            teams.add(g.opponent_id)

        entries_by_team = {t: self._split_entries(games_by_team.get(t, [])) for t in teams}
        adj_win_pct = {t: self._adjusted_win_pct(entries_by_team[t]) for t in teams}
        npi = self._initial_ratings(entries_by_team, adj_win_pct)

        for _pass_num in range(1, MAX_PASSES + 1):
            new_npi = {t: self._solve_team_pass(entries_by_team[t], npi) for t in teams}
            if not teams:
                return {}
            max_delta = max(abs(new_npi[t] - npi[t]) for t in teams)
            npi = new_npi
            if max_delta < CONVERGENCE_TOL:
                return npi
            if max(npi.values(), default=0.0) > 1e8:
                raise NPIConvergenceError(
                    f"NPI calculation diverged (pass {_pass_num}, max value "
                    f"{max(npi.values()):.3e}) -- see docs/npi_spec.md Open Questions."
                )

        raise NPIConvergenceError(
            f"NPI calculation did not converge within {MAX_PASSES} passes."
        )
