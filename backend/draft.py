"""One draft: two teams, six rounds, one slot and one criterion per round.

Rounds go PG, SG, SF, PF, C, then a sixth man of any position, so each team ends with a
starting five and one player off the bench: twelve picks in all. Both teams pick in every
round, for the same slot and criterion, and the order alternates: A then B, B then A, A then
B... (A is whoever starts this draft).

Rosters are scored on one category, dealt at random when the draft starts among the ones
the league has data for (height, weight, points, assists... see catalog.CATEGORIES); the
higher total wins. Only players with a value in that category can be drafted. With reveal "end" the values stay on the server until the draft is over; with
"live" each value goes out as soon as the player is drafted, with running totals.

A turnover (shot clock out, or in extreme mode a player who doesn't fit or is taken)
hands the team the player with the lowest value still available for that round. In extreme
mode, a player with no value in the category counts as one who doesn't fit.
"""

import random
import secrets
import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from .catalog import CATEGORIES, SIXTH_MAN, SLOT_NAMES, SLOTS, Catalog, Category, Criterion, Player

ROUNDS = SLOTS + [SIXTH_MAN]
MARKS = ("X", "O")
PICK_MODES = ("eligible", "extreme")
REVEALS = ("end", "live")


class DraftError(Exception):
    """A request the draft refuses (not a turnover): wrong turn, unknown player..."""


class DraftsBusy(DraftError):
    """No room for another draft right now: every one held is still being played."""


def other(mark: str) -> str:
    return "O" if mark == "X" else "X"


@dataclass
class Pick:
    mark: str
    round: int
    slot: str
    player: Player
    criterion: Criterion
    value: float                     # the player's value in the draft's category
    turnover: Optional[str] = None   # why the player was handed over instead of picked

    def public(self, reveal: bool) -> dict:
        out = {"mark": self.mark, "round": self.round, "slot": self.slot, "id": self.player.id,
               "name": self.player.name, "criterion": self.criterion.label, "turnover": self.turnover}
        if reveal:
            out["value"] = self.value
        return out


@dataclass
class Draft:
    catalog: Catalog
    mode: str = "eligible"            # eligible: pick from who fits; extreme: from everyone
    style: str = "classic"            # which criteria come up (see catalog.CRITERIA_STYLES)
    category: Optional[str] = None    # what rosters are scored on; None deals one at random
    reveal: str = "end"               # end: values hidden until the last pick; live: after each pick
    starter: str = "X"
    seed: Optional[int] = None
    id: str = field(default_factory=lambda: secrets.token_urlsafe(8))
    round: int = 0
    turn: int = 0                     # 0: the round's first pick, 1: its second
    criteria: List[Criterion] = field(default_factory=list)
    picks: Dict[str, List[Optional[Pick]]] = field(default_factory=lambda: {m: [None] * len(ROUNDS) for m in MARKS})
    log: List[Pick] = field(default_factory=list)
    status: str = "in_progress"

    def __post_init__(self):
        if self.mode not in PICK_MODES:
            raise DraftError("Unknown pick mode.")
        if self.reveal not in REVEALS:
            raise DraftError("Unknown reveal setting.")
        self.rng = random.Random(self.seed)
        if self.category is None:
            self.category = self.rng.choice(self.catalog.categories)
        if self.category not in self.catalog.categories:
            raise DraftError("This league has no data for that category.")
        self._deal()

    # ---------- state ----------

    @property
    def taken(self) -> set:
        return {p.player.id for p in self.log}

    @property
    def slot(self) -> str:
        return ROUNDS[self.round]

    @property
    def criterion(self) -> Criterion:
        return self.criteria[self.round]

    @property
    def on_clock(self) -> Optional[str]:
        if self.status != "in_progress":
            return None
        first = self.starter if self.round % 2 == 0 else other(self.starter)
        return first if self.turn == 0 else other(first)

    @property
    def metric(self) -> Category:
        return CATEGORIES[self.category]

    def pick_count(self) -> int:
        return len(self.log)

    def pool(self) -> List[Player]:
        return self.catalog.pool(self.slot, self.criterion, self.category, self.taken)

    def totals(self) -> Dict[str, int]:
        return {m: sum(p.value for p in self.picks[m] if p) for m in MARKS}

    def winner(self) -> Optional[str]:
        """'X', 'O' or 'draw' once the draft is over."""
        if self.status != "final":
            return None
        totals = self.totals()
        if totals["X"] == totals["O"]:
            return "draw"
        return "X" if totals["X"] > totals["O"] else "O"

    # ---------- moves ----------

    def pick(self, mark: str, player_id: int) -> Pick:
        self._check_turn(mark)
        if not 0 <= player_id < len(self.catalog.players):
            raise DraftError("No such player.")
        player = self.catalog.players[player_id]
        if self.mode == "eligible":
            # The list only offers who fits and is free, so anything else is a stale request
            if player.id in self.taken:
                raise DraftError(f"{player.name} is already drafted.")
            if not self.catalog.fits(player, self.slot, self.criterion) or self.category not in player.values:
                raise DraftError(f"{player.name} doesn't fit this round.")
            return self._record(mark, player)
        if player.id in self.taken:
            return self._turnover(mark, f"{player.name} was already drafted")
        if not self.catalog.fits(player, self.slot, self.criterion):
            return self._turnover(mark, f"{player.name} doesn't fit")
        if self.category not in player.values:
            return self._turnover(mark, f"{player.name} has no {self.metric.label.lower()} on record")
        return self._record(mark, player)

    def shot_clock(self, mark: str) -> Pick:
        self._check_turn(mark)
        return self._turnover(mark, "shot clock violation")

    def _check_turn(self, mark: str) -> None:
        if self.status != "in_progress":
            raise DraftError("The draft is over.")
        if mark != self.on_clock:
            raise DraftError("Not your pick.")

    def _turnover(self, mark: str, reason: str) -> Pick:
        pool = self.pool()
        lowest = min(pool, key=lambda p: (p.values[self.category], p.fame))
        return self._record(mark, lowest, reason)

    def _record(self, mark: str, player: Player, turnover: Optional[str] = None) -> Pick:
        pick = Pick(mark, self.round, self.slot, player, self.criterion, player.values[self.category], turnover)
        self.picks[mark][self.round] = pick
        self.log.append(pick)
        if self.turn == 0:
            self.turn = 1
        elif self.round + 1 < len(ROUNDS):
            self.round += 1
            self.turn = 0
            self._deal()
        else:
            self.status = "final"
        return pick

    def _deal(self) -> None:
        self.criteria.append(self.catalog.deal(self.slot, self.style, self.category, self.rng, self.taken,
                                               set(self.criteria)))

    # ---------- what clients see ----------

    def public(self) -> dict:
        final = self.status == "final"
        shown = final or self.reveal == "live"
        state = {
            "id": self.id,
            "league": self.catalog.league,
            "mode": self.mode,
            "style": self.style,
            "category": self.metric.public(),
            "reveal": self.reveal,
            "status": self.status,
            "slots": ROUNDS,
            "round": self.round,
            "rounds": len(ROUNDS),
            "pick_no": len(self.log) + (0 if final else 1),
            "on_clock": self.on_clock,
            "starter": self.starter,
            "picks": {m: [p.public(shown) if p else None for p in self.picks[m]] for m in MARKS},
            "last": self.log[-1].public(shown) if self.log else None,
        }
        if shown:
            state["totals"] = self.totals()
        if not final:
            state["current"] = {"slot": self.slot, "slot_name": SLOT_NAMES[self.slot],
                                "criterion": self.criterion.public()}
            if self.mode == "eligible":
                # Names only, shuffled: fame follows the big numbers, so a ranked list would give the
                # answer away. The order holds for the whole pick (refreshes, reconnects) and changes
                # with the next one.
                pool = self.pool()
                random.Random(f"{self.id}:{len(self.log)}").shuffle(pool)
                state["pool"] = [_name_entry(p) for p in pool]
        else:
            state["winner"] = self.winner()
        return state


def _name_entry(player: Player) -> dict:
    entry = {"id": player.id, "name": player.name}
    if player.born:
        entry["born"] = player.born
    if player.aliases:
        entry["aka"] = player.aliases
    return entry


class DraftStore:
    """Hot-seat drafts by id. Memory stays flat without ever cutting a game short: only drafts that
    are over, or that nobody has touched for `idle` seconds, make room for new ones. The dict is
    kept in order of last use, so those go oldest first. One address (which may be a whole school
    or office behind one IP) holds at most `per_owner`; past that, or when the store is full of
    games in play, a new draft is refused rather than someone else's being dropped."""

    def __init__(self, catalogs: Dict[str, Catalog], max_age: float = 6 * 3600, max_drafts: int = 5000,
                 per_owner: int = 100, idle: float = 15 * 60):
        self.catalogs = catalogs
        self.max_age = max_age
        self.max_drafts = max_drafts
        self.per_owner = per_owner
        self.idle = idle
        self.drafts: Dict[str, Draft] = {}
        self.owners: Dict[str, str] = {}     # draft id -> the address that created it
        self.used: Dict[str, float] = {}     # draft id -> when it was last asked for

    def create(self, league: str, mode: str, style: str, category: Optional[str] = None, reveal: str = "end",
               starter: str = "X", owner: str = "") -> Draft:
        if league not in self.catalogs:
            raise DraftError("Unknown league.")
        self._prune(owner)
        draft = Draft(self.catalogs[league], mode=mode, style=style, category=category, reveal=reveal,
                      starter=starter)
        self.drafts[draft.id] = draft
        self.owners[draft.id] = owner
        self.used[draft.id] = time.monotonic()
        return draft

    def get(self, draft_id: str) -> Draft:
        draft = self.drafts.pop(draft_id, None)
        if not draft:
            raise DraftError("No such draft.")
        self.drafts[draft_id] = draft   # back in at the end: the most recently used
        self.used[draft_id] = time.monotonic()
        return draft

    def _drop(self, draft_id: str) -> None:
        del self.drafts[draft_id], self.owners[draft_id], self.used[draft_id]

    def _done_with(self, key: str, now: float) -> bool:
        """Over, or left alone long enough that nobody is coming back to it."""
        return self.drafts[key].status != "in_progress" or now - self.used[key] > self.idle

    def _prune(self, owner: str) -> None:
        now = time.monotonic()
        for key in [k for k in self.drafts if now - self.used[k] > self.max_age]:
            self._drop(key)
        mine = [k for k in self.drafts if self.owners[k] == owner]
        if len(mine) >= self.per_owner:
            for key in [k for k in mine if self._done_with(k, now)][:len(mine) - self.per_owner + 1]:
                self._drop(key)
            if sum(self.owners[k] == owner for k in self.drafts) >= self.per_owner:
                raise DraftsBusy("Too many games in progress from your network. Finish one, or try again "
                                 "in a few minutes.")
        if len(self.drafts) >= self.max_drafts:
            spare = [k for k in self.drafts if self._done_with(k, now)]
            for key in spare[:len(self.drafts) - self.max_drafts + 1]:
                self._drop(key)
            if len(self.drafts) >= self.max_drafts:
                raise DraftsBusy("The server is full of games right now. Try again in a few minutes.")
