# NCAA Power Index (NPI) — Calculation Spec

In this doc, we'll be going over how the NCAA computes NPI, how NPI differs
on a sport-by-sport basis, and instructions to recreate NPIs for any available
season of DIII college sports. These specifications are implemented in code
at `research/engine/`

**Indices.** `i` = team, `g` = one game (after Step 1's tie/OT splitting —
see §1), `t` = iteration/pass (when calculating NPI, we run a Jacobi iteration
until convergence.), `t=0` is the initial bootstrap. `G(i)` = the
games team `i` has played, as of the date being computed. `opp(g)` = the
opponent in game `g`.

## Dials

Every dial below is part of the one shared NPI framework; a sport
committee picks the *values*, never a different formula. `Dials` in
`research/engine/dials.py` is this exact set of knobs.

For each sport, a committee selects a set of dials (see below) to choose what factors
deserve more emphasis when determining NPI.
(*Example: n away win may be more telling than a  home win against the same team. Thus, 
some sports see an Away win multiplier of 1.1*)


| Dial | Code field | Meaning | Constraint |
|---|---|---|---|
| SOS weight | `sos_weight` | Fraction of a Game Rating driven by opponent strength | sos_weight $\in$ [0, 1] |
| Win% weight | `win_weight` | Fraction of Game Rating driven by winning itself | `sos_weight + win_weight = 1` |
| QWB threshold | `qwb_base` | NPI an opponent must clear to trigger a bonus | — |
| QWB multiplier | `qwb_mult` | Bonus awarded per point an opponent clears the threshold | — |
| Minimum (adjusted) wins | `min_wins` | Floor of counted wins a team can't drop below | — |
| Home win / away loss value | `home_gv` | Game Value when the home team wins | `home_gv + away_gv = 2` |
| Away win / home loss value | `away_gv` | Game Value when the away team wins | (same) |
| OT win multiplier | `ot_win_dial` | Fraction of credit for the side that won in overtime | `ot_win_dial + ot_loss_dial = 1` |
| OT loss multiplier | `ot_loss_dial` | Fraction of credit for the side that lost in overtime | (same) |



### Dial Config across all DIII sports

These can be found for the most recently completed season at https://ncaaorg.s3.amazonaws.com/committees/d3/champs/D3CC_NPIWeights.pdf


## 1. Game Value — `GV(g)`

Let `site ∈ {home, away, neutral}` and `won ∈ {true, false}`, both from team
`i`'s own perspective in game `g`.

**Decisive, not overtime** — determined by who actually won, not by site
alone. 

| site | won | `GV(g)` |
|---|---|---|
| home | true | `home_gv` |
| home | false | `away_gv` |
| away | true | `away_gv` |
| away | false | `home_gv` |
| neutral | — | `1` |

*For intuition on why we use the home_gv multiplier for a losing away team, we say that losing away may be (depending on the dial value)
deemed better than losing at home to the same team. Since `home_gv` $\leq$ `away_gv`, we'll apply a less strict punishment to the away team.*

**Tie:** This is a slight peculiarity, but makes later processes smoother. When a tie occurs, we actually split it into a win-entry and a 
loss-entry. Intuitively, we act as though 2 matches were played: one where team i beats team j, and a second where team j beats team i, and 
then divide each of their game values by 2

**GV(win-entry)** = $\frac{1}{2} \cdot \text{GV}(g, \text{won=true})$ 

**GV(loss-entry)** = $\frac{1}{2} \cdot \text{GV}(g, \text{won=false})$

\
**Decisive result reached in overtime:** also splits into a win-entry and
loss-entry, but scaled asymmetrically by `ot_win_dial`/`ot_loss_dial`
instead of a flat `0.5`/`0.5` — the exact per-team assignment (it depends
on which side actually won) is in **Appendix B**. At a `100/0` dial (most
sports' default, including Women's Soccer — see the Dials table above)
this collapses to a regular win/loss game value. If the OT dial is anything
than 100/0, then the split will actually "do something" 
(*ice hockey's regular-season `67/33`, meaning we'd have the following GVs*)

**GV(win-entry)** = $\frac{2}{3} \cdot \text{GV}(g, \text{won=true})$

**GV(loss-entry)** = $\frac{1}{3} \cdot \text{GV}(g, \text{won=false})$



## 2. Adjusted Win % — `AW(i)`

`G(i)` is the set of games team `i` has played, as of the date in question,
**after** Step 1's tie/OT splitting — so a tie or OT result already
contributes two separate entries to `G(i)`, never one `T`-flagged entry.
For an entry `g_i ∈ G(i)`:
- `o(g_i)` — team `i`'s opponent in game .
- `r(g_i) ∈ {W, L}` — team `i`'s result in that game (always decisive,
  since Step 1 has already split out anything that wasn't).

```
AW(i) = 100 · [ Σ_{g_i∈G(i): r(g_i)=W} GV(g_i) ]  /  [ Σ_{g_i∈G(i)} GV(g_i) ]
```

## 3. Initial NPI — `NPI(i, 0)`

```
NPI(i, 0) = sos_weight · [ Σ_{g∈G(i)} AW(opp(g))·GV(g) ]  /  [ Σ_{g∈G(i)} GV(g) ]
```
Uses **opponents'** adjusted win%, never team `i`'s own — at `t=0` as an initial NPI value
before iteration. Notice how it only depends on the game values of each game played by team i thus far,
as well as the adjusted win % of each `o(g_i)` (opponent of team i for each game that they played).
In the next part, we'll incorporate our dials to iterate/calculate a true NPI value.


## 4. Game Rating — `GR(i, g, t)`

For every game that team i has participated in, we need to calculate a "game rating". For all intents and purposes,
you can intuit a game rating as an "NPI value" of a game. Since higher NPIs indicate a strong team, a higher game rating
is meant to indicate your performance (*Example: If you beat a very good team, game rating will be very high. Losing to a good team will cause the 
game rating [for you] to be lower; however, not as low as if you lost to a very bad team*).
Also, note that game rating also depends on our stage of iteration (as we include a t parameter in the calculation).

For `g ∈ G(i)`, at iteration `t ≥ 1`, using iteration `t-1`'s complete NPI
snapshot (never any other team's iteration-`t` value — see Appendix B's
note on why this must be a synchronous/Jacobi update):

**Game Quality Bonus:**
$$\text{QWB}(i, g, t) = \max\bigl(0, \text{NPI}(\text{opp}(g), t-1) - \text{qwb\_base}\bigr) \cdot \text{qwb\_mult} \quad \text{(if } g \text{ is a win, else } 0\text{)}$$

**Game Rating:**
$$\text{GR}(i, g, t) = \Big[ \text{sos\_weight} \cdot \text{NPI}(\text{opp}(g), t-1) + 100 \cdot \text{win\_weight} \cdot \mathbb{I}[g \text{ is a win}] + \text{QWB}(i, g, t) \Big] \cdot \text{GV}(g)$$

A couple notes. Firstly, game quality bonus is effectively a ReLU function (0 if below the threshold, else linear with slope `qwb_mult`). Another thing that you've probably noticed: game rating depends on NPI. But as you'll see **Step 5** (NPI Update step), NPI is a weighted average of game ratings! Unlike other rating systems (eg. ELO) which operate as Markov processes, NPI is recursively defined (with an arbitrary starting point as we saw in our **Initial NPI** NPI(i, 0)). Thus, game rating is subject to change as we continue trying to find a team's "true" current NPI.

## 5. NPI Update Step — $NPI(i, t)$

$$\text{NPI}(i, t) = \frac{\sum_{g \in G(i)} w(i, g, t) \cdot \frac{\text{GR}(i, g, t)}{\text{GV}(g)}}{\sum_{g \in G(i)} w(i, g, t)}$$

$w(i, g, t) \in [0, \text{GV}(g)]$ is how much of game $g$'s Game Value actually counts toward team $i$'s NPI at iteration $t$ — decided by the Minimum-Wins / Check-Losses selection procedure. **Full definition: Appendix B.** Note: in most cases, w(i, g, t) will simply evaluate to GV(g)

**Special case** — team $i$ has zero wins and zero ties in $G(i)$. This ends up reducing to the following:
$$\text{NPI}(i, t) = \text{sos\_weight} \cdot \min_{g \in G(i)} \text{NPI}(\text{opp}(g), t-1)$$
Note that this looks exactly like the first term in the game rating calculation. Why do we take the minimum? This simply follows with our policy that losses should never boost your NPI.

**Convergence.** Repeat $t = 1, 2, 3, \dots$ until $\max_i |\text{NPI}(i,t) - \text{NPI}(i,t-1)| < \varepsilon$ (elementwise); that final $\text{NPI}(i,t)$ is the published rating. (Engine defaults: $\varepsilon = 10^{-10}$, cutoff at 10,000 passes — see Appendix D on where these specific numbers come from.)

---


## Appendix

### A. Sources

- **thatdonsoftware.com**, "NCAA Power Index Calculation Method" — an
  unofficial but extremely detailed, worked-example walkthrough, written by
  Don Del Grande with input from NCAA staff (J.P. Williams, Kevin Alcox) who
  "provid[ed] NPI values used to verify" the method. This is the only source
  that documents the **recursive/iterative solver** (which we later verify)\
  Pages:
  `NPI_Calculation_Method.html` (overview/dials) through
  `..._1_GameValues.html` → `..._7_CheckDifferences.html` (the 7 steps).
- **NCAA's own documents** (`docs/resources/`, plus live S3 PDFs):
  - `D3CC_SelectionCriteriaDatabaseFAQ.pdf` — FAQ + cheat sheet, confirms the
    same formulas in NCAA's own words (SOS, QWB, H/A, OT, min wins).
  - `D3CC_NPIWeights.pdf` (https://ncaaorg.s3.amazonaws.com/committees/d3/champs/D3CC_NPIWeights.pdf)
    — **the authoritative, current-season dial values for every DIII sport**.
  - `Sep2026D3Gov_Webinar.pdf` — confirms terminology ("Retained Wins" =
    Minimum Wins dial), confirms data-push cadence, and says explicitly:
    *"Nothing is final until the season ends. Games can move in and out of a
    team's NPI calculation as new results are added throughout the season."*
  - `docs/resources/NPI Calculation (1).docx`, `NPI Calculator (1).xlsx` —
    internal worked examples (other sports) that independently confirm the
    per-game formula structure constructed by MIT DAPER staff Aaron Acker
  - NCAA DII's `D2_NPIOverview.pdf` (Karen Kirsch, Director of Championships)
    — independently re-confirms every formula and dial relationship above
    with zero discrepancies, including the home/away "away = 2 − home" rule.


### B. `w(i, g, t)` — full definition

`w(i,g,t)` is an adjusted game value of sorts, such that $w(i, g, t) \in [0, \text{GV}(g)]$)
A maximum of `min_wins` wins are able to count towards a team's NPI: thus, this procedure
is important for figuring out which of team i's games to count towards its NPI.
We implement the procedure as detailed below, with "win quality" being quantified as 
GR(i, g, t)/GV(g) (in other words, game rating over game value). Thus, we want to count the 
wins with the highest GR(i, g, t)/GV(g) values (at most `min_wins` of them). 
The algorithm also ensures that a team can reach the `min_wins` threshold through ties and 
atypical game values (eg. when there's a multiplier applied, games can count for 1.1, 0.8, etc.).
It also ensures that a team that loses can't gain NPI from a loss.

```
Input:  Wins(i), Losses(i)  — G(i) split by result, each sorted
         descending by GR(i,g,t)/GV(g)
Output: w(i,g,t) for every g ∈ G(i)
_______________________________________________________________________________________
TGR ← Σ_{g∈Losses(i)} GR(i,g,t);  TGV ← Σ_{g∈Losses(i)} GV(g)     # 0 if Losses(i)=∅
Cur ← TGR/TGV  (0 if Losses(i)=∅);  CW ← 0

for g in Wins(i), in sorted order:
   trial ← (TGR + GR(i,g,t)) / (TGV + GV(g))
   if trial ≥ Cur  or  CW + GV(g) ≤ min_wins:
   w(i,g,t) ← GV(g)                            # full: good win, or floor not yet met
   elif CW ≥ min_wins:
   w(i,g,t) ← 0                                # zero: floor already met
   else:
   f ← (min_wins − CW) / GV(g)
   w(i,g,t) ← f · GV(g)                        # partial win is needed
   (TGR, TGV, CW) ← (TGR, TGV, CW) + (w(i,g,t)/GV(g)) · (GR(i,g,t), GV(g), GV(g))
   Cur ← TGR / TGV

for g in Losses(i), in sorted order:
   trial ← (TGR − GR(i,g,t)) / (TGV − GV(g))
   if trial < Cur:                               # here, g is propping up the NPI. Don't use it
   w(i,g,t) ← 0;  (TGR, TGV) ← (TGR, TGV) − (GR(i,g,t), GV(g));  Cur ← TGR/TGV 
   else:
   w(i,g,t) ← GV(g)                                                         

return w(·,·,t)
```
No minimum number of losses — all of them can be dropped if every one
raises the rating.



**Overtime split** (referenced from §1): for a decisive result reached in
OT, from team `i`'s perspective with `actually_won ∈ {true, false}`:
```
if actually_won:
    GV(win-entry)  = GV(site, won=true)  · ot_win_dial
    GV(loss-entry) = GV(site, won=false) · ot_loss_dial
else:
    GV(win-entry)  = GV(site, won=true)  · ot_loss_dial
    GV(loss-entry) = GV(site, won=false) · ot_win_dial
```

**The "regular case" — when §5 is actually linear.** When `w(i,g,t)=GV(g)`
for every `g` (nothing dropped) and `QWB(i,g,t)=0` for every `g` (bonus
never fires), §5 collapses to:
```
NPI(i,t) = [ sos_weight·Σ_{g∈G(i)} NPI(opp(g),t-1)  +  100·win_weight·W(i) ]  /  k(i)
```
where `k(i) = Σ_g GV(g)` (games played) and `W(i) = Σ_{Wins(i)} GV(g)`
(games won). In vector form: `x_t = M·x_{t-1} + c`, with
`M[i,opp] = sos_weight/k(i)` and `c[i] = 100·win_weight·W(i)/k(i)` — a
Jacobi iteration for the linear system `(I-M)x = c`. Every row of `M` sums
to exactly `sos_weight`, which is the source of the `Σ NPI = 50·N`
conservation law (WSOC specifically — `100·win_weight/(1-sos_weight) = 20`
"points of mass" injected per game, split across 2 teams).

**Why synchronous (Jacobi), not sequential (Gauss-Seidel) iteration.** `GR(i,g,t)`
is defined purely off iteration `t-1`'s snapshot. Every team's iteration-`t`
value is computed off the *same* frozen snapshot in parallel (conceptually)
This model of computation where a single weight-tied layer is applied recurrently 
until some convergence criteria is similar to an equilibrium/DEQ-style model.

### C. Validation

All validation lives in `research/engine/tests/`

- `test_engine_toy.py` — hand-derived scenarios (isolated pairs,
  disjoint-pair decomposition, a 10-team multi-matchday scenario, the
  good-loss-drop and minimum-wins-floor/partial branches, the overtime
  split) checked against exact expected values that I computed by hand
- `test_engine_realdata.py` — the full engine run against real, published
  NCAA NPI snapshots (`research/data/wsoc/25-26/npi/`). Current measured accuracy,
  both validated dates: **median error ≈ 0.004 NPI points, mean ≈ 0.01-0.02**
  when tested against WSOC data from the 25-26 season
  (published values are themselves only reported to 3 decimal places).

Run `pytest research/engine/tests/` to reproduce.

### D. Open questions

1. **Convergence tolerance / max passes.** `ε=1e-10` (from thatdonsoftware NPI 
   article) and a 10,000-pass cutoff (`research/engine/npi_engine.py`) are 
   reverse-engineered defaults, not confirmed NCAA internals. In
   practice we converge to real published data well inside this budget
   (~100-150 passes for the full ~400-team WSOC graph).
2. **Rounding.** Published NPI values are 3 decimal places, but I carry full
   float precision internally and only round at the display/comparison
   boundary. this reproduces real data to within measurement noise (mean
   abs error ~`0.01`-`0.02`, median ~ `0.0045` for WSOC 25-26), 
3. **`Win Value`/`Loss Value`/`vAbove`/`vBelow`** columns in the scraped
   Nitty Gritty CSVs aren't explained by any source we have. Working theory:
   average `GameRating` among a team's *counted* wins vs. losses, and a
   W-L-T split vs. teams above/below .500, or teams above/below their own NPI
4. **Postseason/conference-tournament games** — These NPI values are technically
   calculatable. May be useful for future NPI analysis correlating NPI to win
    probabilities.
