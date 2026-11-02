# 🏀 Draftić

A two-player basketball draft game, in the spirit of Draftinho, on the same scoresheet design as
[Hoop-Tac-Toe](https://github.com/mertorange/basketball-xox).

Two teams draft six players each: a starting five (PG, SG, SF, PF, C) and a sixth man of any
position. Every round deals
one slot plus one random criterion, such as *PG · Fenerbahçe* or *C · Born in Serbia*. Both teams
draft a player who fits it. Every draft is scored on a stat dealt at random when it starts
(height, points, assists, age...), and the higher team total wins.

## Rules
1. **The stat:** dealt at random for each draft, among the ones the league has data for:

   | | NBA | EuroLeague |
   |---|---|---|
   | Body | height, weight, age in last season | height, weight, age in last season |
   | Career | games, minutes, points, rebounds, assists, steals, blocks, seasons played, teams played for | games, points, rebounds, assists, seasons played, teams played for |

   NBA totals are regular-season NBA (and BAA) games, not the ABA; EuroLeague totals are its
   games since 2000-01. Only players with a number in the dealt stat can be drafted.
2. **Six rounds, twelve picks:** PG, SG, SF, PF, C, then the sixth man, who can play any
   position.
3. **Pick order swings:** A then B, B then A, A then B... Rematches swap who starts.
4. **Criteria:** *Classic* deals teams and countries of birth. *Mixed* adds decades and (NBA)
   colleges. Every round is dealt so at least 8 undrafted players fit it.
5. **Player search:** *Eligible only* lists just the players who fit the round. In *Extreme*,
   every player in the league is listed, and you have to know who fits.
6. **Revealing the numbers:** *After the last pick* keeps every number hidden until the draft
   is over, then lights them up one by one on the board. *As you go* shows each number as soon
   as the player is drafted. Either way the scoreboard adds up each team's total, and the
   winner is only called once every number is on the board.
7. **Turnovers:** an expired shot clock (or, in Extreme, a player who doesn't fit, is already
   taken or has no number in the stat) hands you the player with the **lowest** number still
   available for that round.
8. **Positions** come from the player's career: a combo guard fits PG and SG. EuroLeague
   registrations only say Guard / Forward / Center, so a EuroLeague guard fits both guard slots
   and a forward both forward slots.

## Play
- **Same device:** pass the phone. The shot clock runs in the browser.
- **Online room:** create a room, send the link or the five-letter code. The server owns the
  draft and the shot clock. A player who drops keeps their seat, and their clock keeps running.
  A rematch swaps who picks first.

## Run
```bash
pip install -r requirements.txt
python run.py            # http://localhost:8010
```
Tests: `pip install -r requirements-dev.txt` then `python -m pytest tests`.

## Data
`backend/data/base/` holds the Hoop-Tac-Toe datasets as they were copied over (teams, birth
countries, seasons, colleges...). `backend/scripts/build_data.py` adds the positions and the
numbers the stats are scored on, and writes `backend/data/{nba,euroleague}_data.json`:

| Field | NBA source | EuroLeague source |
|---|---|---|
| `positions` | Basketball GM rosters, Basketball-Reference and Wikidata, merged | EuroLeague API registrations plus Wikidata, merged |
| `height` (cm) | Basketball GM rosters 1995-96 to 2025-26, then Basketball-Reference, then Wikidata | EuroLeague API, then Wikidata |
| `weight` (kg), `birth_year` | Basketball-Reference, then Basketball GM, then Wikidata | EuroLeague API, then Wikidata |
| `stats` | Basketball-Reference season totals ([sumitrodatta/bball-reference-datasets](https://github.com/sumitrodatta/bball-reference-datasets)), NBA and BAA seasons | the base dataset (official EuroLeague career totals) |
| `career` | seasons with games played, from the same totals | — |

A career total is left out when one of its seasons has no figure (steals and blocks before
1973-74, rebounds before 1950-51, minutes before 1951-52): a short total would be wrong.
Coverage (NBA / EuroLeague): positions 4,806 / 2,293, height 4,814 / 2,285, weight 4,805 /
1,971, points 4,611 / 2,028, steals 3,919 / —. A stat is offered in a league only when at least
60% of its players have it. Players without a position are left out of the game. Downloads are cached in `backend/data/cache/`
(delete it to refetch). To pick up a newer Hoop-Tac-Toe dataset, copy its two JSON files into
`backend/data/base/` and rerun the script.

## Layout
```
backend/
  catalog.py   players, the stats a draft is scored on, criteria, dealing a round
  draft.py     the draft: its stat, rounds, pick order, turnovers, totals, when numbers show
  rooms.py     online rooms over WebSockets, server-side shot clock, rematches
  app.py       HTTP routes for same-device drafts, static frontend
  scripts/build_data.py
frontend/
  index.html, style.css
  js/  main.js (menu, screens) · hotseat.js / onlinegame.js (controllers) · sheet.js (drawing)
       slip.js (player search) · names.js · online.js · clock.js · sound.js · api.js · dom.js
tests/test_draft.py
```
