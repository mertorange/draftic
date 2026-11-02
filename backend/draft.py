"""One draft: two teams, ten rounds, one slot and one criterion per round.

Rounds go PG, SG, SF, PF, C, then the same five again, so each team ends with two players
at every position. Both teams pick in every round, for the same slot and criterion, and
the order alternates: A then B, B then A, A then B... (A is whoever starts this draft).

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

from .catalog import CATEGORIES, SLOT_NAMES, SLOTS, Catalog, Category, Criterion, Player

ROUNDS = SLOTS * 2
MARKS = ("X", "O")
PICK_MODES = ("eligible", "extreme")
REVEALS = ("end", "live")


class DraftError(Exception):
    """A request the draft refuses (not a turnover): wrong turn, unknown player..."""


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
    created: float = field(default_factory=time.monotonic)

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
                # Names only, in the order the autocomplete ranks ties: the best known first
                state["pool"] = [_name_entry(p) for p in sorted(self.pool(), key=lambda p: -p.fame)]
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
    """Hot-seat drafts by id; old ones are dropped so memory stays flat."""

    def __init__(self, catalogs: Dict[str, Catalog], max_age: float = 6 * 3600, max_drafts: int = 2000):
        self.catalogs = catalogs
        self.max_age = max_age
        self.max_drafts = max_drafts
        self.drafts: Dict[str, Draft] = {}

    def create(self, league: str, mode: str, style: str, category: Optional[str] = None, reveal: str = "end",
               starter: str = "X") -> Draft:
        if league not in self.catalogs:
            raise DraftError("Unknown league.")
        self._prune()
        draft = Draft(self.catalogs[league], mode=mode, style=style, category=category, reveal=reveal,
                      starter=starter)
        self.drafts[draft.id] = draft
        return draft

    def get(self, draft_id: str) -> Draft:
        draft = self.drafts.get(draft_id)
        if not draft:
            raise DraftError("No such draft.")
        return draft

    def _prune(self) -> None:
        now = time.monotonic()
        for key, draft in list(self.drafts.items()):
            if now - draft.created > self.max_age:
                del self.drafts[key]
        while len(self.drafts) >= self.max_drafts:
            del self.drafts[next(iter(self.drafts))]
