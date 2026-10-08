Meeting w Aaron

stats.ncaa.org

NPI weights are published at the beginning of the season/preseason
Each sport has their own, is [potentially] adjusted every 2 years
Lots of fluctuations in QWB based on weights
Currently on 3rd year of NPI
Before, the 2 ways to qualify were a) win conference or b) be voted by regional committee (they’d rank their area, which informs how non-auto qualifiers are selected for national tournament)
Weights Definitions:
QWB: a threshold for teams’ WPI that incurs the bonus multiplier
QWB Multiplier: (team_QWB - QWB)*QWB_Multiplier
SOS: Strength of schedule is a weight of your opponents WPI
Win %/SOS: Tells us the emphasis on winning vs strength of schedule
H/A Win/Loss: Tells us the emphasis on Home and Away wins/losses
Eg. 0.9/1.1 means 0.9 wins marked at home, 1.1 wins marked away
Minimum wins: Sets threshold for # of wins required to NOT count wins that’d lower NPI
*** Losing to a good team also shouldn’t increase NPI
*** If min wins = 8, and we are at 7.5 wins (from a) tying or b) H/A fractional wins), then, we can take the next-best fractional win to create the 8 minimum wins
We don’t see NPI scores until halfway through the season (values need to calibrate for a while)
CAVEAT: Ties
You count the game for half a win AND half a loss
Potentially, tying a bad team could LOWER your NPI
In addition to schedule optimization, should also be looking at how modifying the various weights (eg. Minimum wins, QWB) would affect qualification.

NEED TO FIGURE OUT THE INITIAL NPI NUMBER THAT IS GENERATED 
ASK PEKO FOR THE CODE THAT GENERATE PROBABILITIES OF TEAMS W


OFFICE HOURS PEKO (9/14)

Given schedule, provide an expected NPI and variance
Plot graph with E[NPI] as x-axis (variance as y-axis)
1) Run NPI calculations for last year and see if we can replicate (eg. assume they use the previous season’s final NPI as a starting point)
Check if the NPI value converges to the value posted by week 5-6
2) Coaches probably want a dashboard. 
Input: schedule; output: expected NPI + confidence intervals
3) Given 2 NPI’s, what is the probability of winning? 
Likely, logistic regression on past data
4) Can we closed form/analytically solve E[NPI_{MIT, time = t}] = E[NPI_{MIT, time = t-1}, NPI_{opp, time = t-1}, …] (calculated 2 steps out)
NPI_{t+1} = F(NPI_{t}, NPI_{t, opp}) 

Likely thesis outputs: 
NPI dashboard
E[NPI] vs Variance graph


9/16:
Get schedule data: https://stats.ncaa.org/teams/603722 (Women’s Soccer)


References: 
“NCAA POWER INDEX CALCULATION METHOD”: (toggle steps) https://www.thatdonsoftware.com/NPI_Calculation_Method_3_InitialRatings.html 
"NPI UPDATES: https://ncaaorg.s3.amazonaws.com/governance/d3/webinar/Sep2026D3Gov_Webinar.pdf?utm_source=www.d3playbook.com&utm_medium=newsletter&utm_campaign=learning-more-about-the-npi 
"NCAA POWER INDEX (NPI) FAQ and CHEAT SHEET": https://ncaaorg.s3.amazonaws.com/committees/d3/champs/D3CC_SelectionCriteriaDatabaseFAQ.pdf 
