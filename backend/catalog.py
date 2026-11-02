"""Player catalogs, the categories a draft is scored on, and the criteria a round can ask for.

A league's catalog holds every player with at least one position (see
backend/scripts/build_data.py). Players are referred to by their index in the catalog.

A category is what rosters are scored on: height, weight, age, or a career total such as
points or games. Every draft is dealt one at random, among the categories the league has
data for. A criterion is a team, a birth country, a decade or a college; a round asks for one
slot (PG, SG, SF, PF, C) plus one criterion.
"""

import json
import os
import random
import re
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Dict, List, Optional

DATA_DIR = Path(os.environ.get("DRAFTIC_DATA_DIR") or Path(__file__).resolve().parent / "data")
LEAGUES = {"nba": "NBA", "euroleague": "EuroLeague"}
SLOTS = ["PG", "SG", "SF", "PF", "C"]
SLOT_NAMES = {"PG": "Point guard", "SG": "Shooting guard", "SF": "Small forward",
              "PF": "Power forward", "C": "Center"}

# A round is only dealt when at least this many undrafted players fit it
MIN_POOL = 8

# A league offers a category only when at least this share of its players have a value for it
MIN_COVERAGE = 0.6

# How often each kind of criterion comes up
CRITERIA_STYLES = {
    "classic": {"team": 0.7, "country": 0.3},
    "mixed": {"team": 0.5, "country": 0.2, "era": 0.15, "college": 0.15},
}

# Too broad to be a question: almost everyone fits
SKIPPED_COUNTRIES = {"nba": {"USA"}, "euroleague": set()}

NON_DECOMPOSING = str.maketrans({"Đ": "D", "đ": "d", "Ø": "O", "ø": "o", "Ł": "L", "ł": "l", "ß": "ss",
                                 "Æ": "AE", "æ": "ae", "Œ": "OE", "œ": "oe", "Þ": "Th", "þ": "th", "ı": "i"})


def fold(text: str) -> str:
    """Lower case, no accents or punctuation: what name searches compare."""
    text = unicodedata.normalize("NFKD", text.translate(NON_DECOMPOSING)).encode("ascii", "ignore").decode()
    text = re.sub(r"[.,'’`\"]", "", text.lower())
    return re.sub(r"[-\s]+", " ", text).strip()


@dataclass
class Player:
    id: int
    name: str
    positions: List[str]
    teams: List[str]
    country: str
    seasons: Optional[List[int]]
    college: Optional[str]
    fame: float
    aliases: List[str]
    born: Optional[str] = None       # only for players who share a name
    values: Dict[str, int] = field(default_factory=dict)  # category key -> value


@dataclass(frozen=True)
class Category:
    """What a roster is scored on: the higher total wins."""
    key: str
    label: str                                  # 'Points'
    unit: str                                   # 'pts'
    kind: str                                   # 'body' or 'career'
    value: Callable[[dict], Optional[int]]      # from the player's raw record
    hint: str = ""                              # one line on what to draft for, shown when it's dealt

    def public(self) -> dict:
        return {"key": self.key, "label": self.label, "unit": self.unit, "kind": self.kind, "hint": self.hint}


def _stat(name):
    return lambda raw: (raw.get("stats") or {}).get(name)


def _last_season(raw):
    """From the seasons with games played where known (NBA): the team histories in the base
    data sometimes run on into a player's coaching years."""
    career = raw.get("career") or {}
    seasons = raw.get("seasons")
    return career.get("last_season") or (seasons[1] if seasons else None)


def _age_in_last_season(raw):
    """Seasons are named by the year they end in: 2025-26 is 2026, so someone born in 1984
    is 41 during it."""
    born, last = raw.get("birth_year"), _last_season(raw)
    if not born or not last:
        return None
    age = last - born - 1
    return age if 16 <= age <= 50 else None


def _seasons_played(raw):
    career = raw.get("career") or {}
    if career.get("seasons_played"):
        return career["seasons_played"]
    stints = raw.get("stints") or {}
    played = {season for seasons in stints.values() for season in seasons}
    return len(played) or None


CATEGORIES = {c.key: c for c in [
    Category("height", "Height", "cm", "body", lambda raw: raw.get("height"),
             "Draft tall. Every centimetre counts."),
    Category("weight", "Weight", "kg", "body", lambda raw: raw.get("weight"),
             "Draft heavy. The scale decides."),
    Category("age", "Age in last season", "yrs", "body", _age_in_last_season,
             "Draft the veterans: how old each player was in his last season."),
    Category("games", "Games played", "games", "career", _stat("games"),
             "Draft the iron men: career games played."),
    Category("minutes", "Minutes played", "min", "career", _stat("minutes"),
             "Draft the workhorses: career minutes on the floor."),
    Category("points", "Points", "pts", "career", _stat("points"),
             "Draft the scorers: career points."),
    Category("rebounds", "Rebounds", "reb", "career", _stat("rebounds"),
             "Draft the glass cleaners: career rebounds."),
    Category("assists", "Assists", "ast", "career", _stat("assists"),
             "Draft the passers: career assists."),
    Category("steals", "Steals", "stl", "career", _stat("steals"),
             "Draft the pickpockets: career steals."),
    Category("blocks", "Blocks", "blk", "career", _stat("blocks"),
             "Draft the rim protectors: career blocks."),
    Category("seasons", "Seasons played", "seasons", "career", _seasons_played,
             "Draft the long careers: seasons with games played."),
    Category("teams", "Teams played for", "teams", "career", lambda raw: len(raw.get("teams") or []) or None,
             "Draft the journeymen: how many teams each player suited up for."),
]}


@dataclass(frozen=True)
class Criterion:
    kind: str     # team | country | era | college
    value: str
    label: str    # what the round card shows: 'Fenerbahçe', 'Born in Serbia', 'Played in the 1990s'

    def public(self) -> dict:
        return {"kind": self.kind, "value": self.value, "label": self.label}


def _fame(raw: dict) -> float:
    stats = raw.get("stats") or {}
    return (raw.get("wiki_pages") or 0) * 10 + (stats.get("games") or 0) + len(raw.get("awards") or []) * 50


class Catalog:
    def __init__(self, league: str, data: dict):
        self.league = league
        self.title = LEAGUES[league]
        self.teams: List[str] = data["teams"]
        self.players: List[Player] = []
        for raw in data["players"]:
            if not raw.get("positions"):
                continue
            values = {}
            for key, category in CATEGORIES.items():
                value = category.value(raw)
                if value is not None:
                    values[key] = int(value)
            self.players.append(Player(
                id=len(self.players), name=raw["name"], positions=raw["positions"],
                teams=raw["teams"], country=raw.get("country") or "", seasons=raw.get("seasons"),
                college=raw.get("college"), fame=_fame(raw), aliases=raw.get("aliases") or [],
                born=raw.get("born"), values=values,
            ))
        self._tests: Dict[str, Callable[[Player, str], bool]] = {
            "team": lambda p, v: v in p.teams,
            "country": lambda p, v: p.country == v,
            "era": lambda p, v: bool(p.seasons) and p.seasons[0] <= int(v) + 10 and p.seasons[1] >= int(v) + 1,
            "college": lambda p, v: p.college == v,
        }
        self.values = self._criterion_values()
        # The categories this league has enough data for, in the order CATEGORIES lists them
        self.categories = [key for key in CATEGORIES
                           if sum(key in p.values for p in self.players) >= MIN_COVERAGE * len(self.players)]

    @classmethod
    def load(cls, league: str) -> "Catalog":
        path = DATA_DIR / f"{league}_data.json"
        return cls(league, json.loads(path.read_text(encoding="utf-8")))

    def _criterion_values(self) -> Dict[str, List[str]]:
        countries = sorted({p.country for p in self.players if p.country} - SKIPPED_COUNTRIES[self.league])
        first = min((p.seasons[0] for p in self.players if p.seasons), default=2000)
        last = max((p.seasons[1] for p in self.players if p.seasons), default=2000)
        # A decade is the seasons ending in its years plus one: the 1990s are 1990-91 .. 1999-2000
        decades = [str(d) for d in range((first - 1) // 10 * 10, last, 10)]
        colleges = sorted({p.college for p in self.players if p.college})
        return {"team": list(self.teams), "country": countries, "era": decades, "college": colleges}

    def criterion(self, kind: str, value: str) -> Criterion:
        if kind == "team":
            label = value
        elif kind == "country":
            label = f"Born in {value}"
        elif kind == "era":
            label = f"Played in the {value}s"
        else:
            label = f"{value} (college)"
        return Criterion(kind, value, label)

    def fits(self, player: Player, slot: str, criterion: Criterion) -> bool:
        return slot in player.positions and self._tests[criterion.kind](player, criterion.value)

    def pool(self, slot: str, criterion: Criterion, category: str, taken=frozenset()) -> List[Player]:
        """Undrafted players who fit the round and have a value in the draft's category."""
        return [p for p in self.players
                if p.id not in taken and category in p.values and self.fits(p, slot, criterion)]

    def deal(self, slot: str, style: str, category: str, rng: random.Random, taken=frozenset(),
             used=frozenset()) -> Criterion:
        """A random criterion for the slot with at least MIN_POOL undrafted players."""
        weights = CRITERIA_STYLES.get(style, CRITERIA_STYLES["classic"])
        kinds = [k for k in weights if self.values.get(k)]
        for _ in range(400):
            kind = rng.choices(kinds, [weights[k] for k in kinds])[0]
            criterion = self.criterion(kind, rng.choice(self.values[kind]))
            if criterion in used:
                continue
            if len(self.pool(slot, criterion, category, taken)) >= MIN_POOL:
                return criterion
        # Practically never: fall back to the team with the most players at the slot
        best = max(self.teams, key=lambda t: len(self.pool(slot, self.criterion("team", t), category, taken)))
        return self.criterion("team", best)

    def names(self) -> List[dict]:
        """Every name for the extreme-mode autocomplete: no values, teams or positions."""
        out = []
        for p in self.players:
            entry = {"id": p.id, "name": p.name}
            if p.born:
                entry["born"] = p.born
            if p.aliases:
                entry["aka"] = p.aliases
            out.append(entry)
        return out


def load_catalogs() -> Dict[str, Catalog]:
    return {league: Catalog.load(league) for league in LEAGUES}
