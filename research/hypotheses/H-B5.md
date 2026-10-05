# H-B5: Matchup interactions (preregistered)

Registered 2026-10-04. All interactions are products of opponent-adjusted offensive and
defensive components (both teams, both directions), added to the B4 feature set in the
same expanding-window ridge.

| ID | Interaction | Feature |
|---|---|---|
| H-B5-1 | 3PA-heavy offense vs 3PA-allowing defense | off_fg3a_rate × def_fg3a_rate |
| H-B5-2 | offensive rebounding vs defensive rebounding | off_orb × def_orb |
| H-B5-3 | turnover pressure vs ball security | off_to × def_to |
| H-B5-4 | foul generation vs foul susceptibility | off_ftr × def_ftr |
| H-B5-5 | pace control | tempo_h × tempo_a |
| H-B5-6 | interior offense vs interior defense (2P%) | off_fg2 × def_fg2 |

* Accept the block only if validation margin RMSE(B5) < RMSE(B4) and total RMSE does not
  worsen. Individual interactions are not cherry-picked after the fact.
* Rim-vs-rim (shot-zone) interactions need the NCAA lineup rim/mid/3 data → deferred to B6.
