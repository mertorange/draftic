# Draftić roadmap

Where the game stands and where it goes next. Items near the top come first; nothing here has a
date. Ideas and pull requests are welcome.

## Where it stands
- Two-player drafts of six players a side (a starting five and a sixth man) on NBA and
  EuroLeague catalogs, scored on a stat dealt at random.
- Two ways to play: hot-seat on one device, and online rooms over WebSockets with a
  server-owned shot clock and seats that survive a dropped connection.
- Per-IP request limits, a Docker image and a compose file.
- Backend tests with pytest. The frontend has no tests yet.

## Now: ready to host
The goal is a public instance people can play on.

- [ ] **CI:** GitHub Actions running the tests on every push and pull request.
- [ ] **Image builds:** build the Docker image in CI and publish it to GitHub Container Registry.
- [ ] **First deployment:** a hosted instance behind HTTPS, with a reverse proxy that passes
      WebSocket upgrades and real client IPs (`FORWARDED_ALLOW_IPS`).
- [ ] **Logs and monitoring:** structured request logs, uptime checks on `/health`, and alerts.
- [ ] **Restarts without lost games:** drain open rooms on shutdown, or warn players that the
      server is restarting.
- [ ] **Health endpoint:** decide whether room and draft counts stay public.

## Next: more to play
- [ ] **Play the computer:** a single-player mode against a bot that picks from the eligible
      pool, at a few difficulty levels.
- [ ] **Daily draft:** one seeded draft a day, the same rounds and stat for everyone, with a
      shareable result.
- [ ] **Share a result:** an image or link of the finished board that players can post.
- [ ] **New criteria:** draft class, awards (All-Star, All-NBA, EuroLeague MVP), and players
      who were teammates.
- [ ] **Series:** best-of-three or best-of-five rematches, with a running score in the room.
- [ ] **Spectators:** watch an online room without a seat.
- [ ] **Custom drafts:** choose the round count, the slots and the shot-clock length per room.

## Later: reach and scale
- [ ] **More leagues:** WNBA, then domestic leagues such as the Turkish BSL or Spain's ACB, if
      good data exists.
- [ ] **Translations:** a Turkish interface first, then others.
- [ ] **Installable app:** an offline-capable PWA for hot-seat games.
- [ ] **Accessibility:** full keyboard play, screen-reader labels on the board, and a
      reduced-motion option for the reveals.
- [ ] **Shared state:** move rooms and drafts out of process memory (Redis or SQLite) so the
      server can run more than one worker and keep games across restarts.
- [ ] **Accounts (optional):** saved names, match history and stats, kept light and never
      required to play.

## Data upkeep
- [ ] **Season refresh:** rerun `backend/scripts/build_data.py` after each season, ideally as
      a scheduled CI job that opens a pull request with the new data.
- [ ] **Coverage gaps:** fill missing EuroLeague weights (about 1,970 of 2,293 players have
      one) and pre-1973 NBA steals and blocks where reliable sources exist.
- [ ] **Data checks:** tests that catch a bad rebuild (players lost, sudden jumps in totals).

## Code health
- [ ] **Frontend tests:** cover the draft board, the shot clock and reconnecting to a room,
      for example with Playwright.
- [ ] **Load test:** check how many rooms and sockets one instance handles, and tune the
      request limits and room cap (`MAX_ROOMS`) to match.
