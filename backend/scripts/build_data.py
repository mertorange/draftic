"""Builds Draftić's datasets from the Hoop-Tac-Toe ones.

Reads backend/data/base/{nba,euroleague}_data.json (copied from basketball-xox) and writes
backend/data/{nba,euroleague}_data.json with more fields per player, for the draft slots
and the categories a draft is scored on:

    "positions": ["PF", "C"]       draft slots the player can fill
    "height": 211                  centimetres
    "weight": 129                  kilograms
    "birth_year": 1995
    "stats": {"games": 731, "minutes": 23468, "points": 15378, "rebounds": 7718,
              "assists": 4946, "steals": 952, "blocks": 534}
    "career": {"last_season": 2026, "seasons_played": 11}   NBA: seasons with games played

Sources, first one that knows wins (positions are merged from all of them):
  NBA        Basketball-Reference season totals and career info (github.com/sumitrodatta/
             bball-reference-datasets): stats from NBA and BAA seasons (not the ABA), weight,
             birth year; Basketball GM rosters 1995-96 .. 2025-26: height and positions;
             Wikidata: anything still missing
  EuroLeague the official EuroLeague API registrations (height, weight, birth date,
             Guard/Forward/Center), then Wikidata; the stats come with the base dataset

A career total is left out when a season in it has no figure (steals and blocks before
1973-74, rebounds before 1950-51, minutes before 1951-52): a short total would be wrong.

Downloads are cached in backend/data/cache; delete that folder to fetch everything again.
Standard library only:  python backend/scripts/build_data.py [nba] [euroleague]
"""

import csv
import io
import json
import re
import sys
import time
import unicodedata
import urllib.parse
import urllib.request
from collections import defaultdict
from datetime import date
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parents[1] / "data"
BASE_DIR = DATA_DIR / "base"
CACHE_DIR = DATA_DIR / "cache"
USER_AGENT = "draftic-builder/0.2 (basketball fan game)"

BBGM_BASE = "https://raw.githubusercontent.com/alexnoob/BasketBall-GM-Rosters/master/"
BBGM_FILES = ["1995-96.NBA.Roster.json", "2009-10 Rosters.json"] + [
    f"{y}-{str(y + 1)[-2:]}.NBA.Roster.json" for y in range(2015, 2026)
]
BREF_BASE = "https://raw.githubusercontent.com/sumitrodatta/bball-reference-datasets/master/Data/"
BREF_LEAGUES = {"NBA", "BAA"}
# Basketball-Reference column -> our stat name
BREF_STATS = {"g": "games", "mp": "minutes", "pts": "points", "trb": "rebounds", "ast": "assists",
              "stl": "steals", "blk": "blocks"}
EUROLEAGUE_PEOPLE_URL = (
    "https://api-live.euroleague.net/v2/competitions/E/seasons/E{season}/people?personType=J&limit=2000"
)
EUROLEAGUE_FIRST_SEASON = 2000
WIKIDATA_SPARQL_URL = "https://query.wikidata.org/sparql"

SLOTS = ["PG", "SG", "SF", "PF", "C"]

# Basketball GM / ESPN position codes -> draft slots
NBA_POSITIONS = {
    "PG": ["PG"], "SG": ["SG"], "G": ["PG", "SG"], "GF": ["SG", "SF"], "SF": ["SF"],
    "F": ["SF", "PF"], "PF": ["PF"], "FC": ["PF", "C"], "C": ["C"],
}
# The EuroLeague only registers three positions
EUROLEAGUE_POSITIONS = {"Guard": ["PG", "SG"], "Forward": ["SF", "PF"], "Center": ["C"]}
# Wikidata position labels (English) -> draft slots
WIKIDATA_POSITIONS = {
    "point guard": ["PG"], "shooting guard": ["SG"], "guard": ["PG", "SG"], "combo guard": ["PG", "SG"],
    "swingman": ["SG", "SF"], "small forward": ["SF"], "forward": ["SF", "PF"],
    "power forward": ["PF"], "stretch four": ["PF"], "point forward": ["SF"],
    "forward-center": ["PF", "C"], "center": ["C"], "centre": ["C"],
}

NAME_SUFFIXES = {"jr", "sr", "ii", "iii", "iv"}

# Basketball players with a Basketball-Reference NBA id / a EuroLeague id
WIKIDATA_QUERY = """
SELECT ?p ?name ?h ?w ?posLabel ?dob WHERE {
  ?p wdt:%s ?id .
  ?p rdfs:label ?name . FILTER(LANG(?name) = "en")
  OPTIONAL { ?p p:P2048/psn:P2048/wikibase:quantityAmount ?h }
  OPTIONAL { ?p p:P2067/psn:P2067/wikibase:quantityAmount ?w }
  OPTIONAL { ?p wdt:P413 ?pos }
  OPTIONAL { ?p wdt:P569 ?dob }
  SERVICE wikibase:label { bd:serviceParam wikibase:language "en". }
}
"""
WIKIDATA_ID_PROPERTY = {"nba": "P2685", "euroleague": "P3536"}

# Plausible ranges; anything outside is a typo in a source
HEIGHT_CM = (160, 235)
WEIGHT_KG = (55, 170)


# ---------------------------------------------------------------- helpers

# Letters NFKD does not split into a base letter plus accent
NON_DECOMPOSING = str.maketrans({"Đ": "D", "đ": "d", "Ø": "O", "ø": "o", "Ł": "L", "ł": "l", "ß": "ss",
                                 "Æ": "AE", "æ": "ae", "Œ": "OE", "œ": "oe", "Þ": "Th", "þ": "th", "ı": "i"})


def ascii_fold(text):
    text = text.translate(NON_DECOMPOSING)
    return unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii")


def parse_json_lenient(text):
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        # Some community roster files carry trailing commas
        return json.loads(re.sub(r",\s*([}\]])", lambda m: m.group(1), text))


def name_key(name):
    """Same key as basketball-xox: 'R.J. Barrett', 'RJ Barrett' and 'R. J. Barrett' share one."""
    key = ascii_fold(name).lower()
    key = re.sub(r"[.'’`]", "", key)
    key = re.sub(r"[-\s]+", " ", key).strip()
    return re.sub(r"\b([a-z]) (?=[a-z]\b)", r"\1", key)


def base_name_key(name):
    parts = name_key(name).split()
    while len(parts) > 1 and parts[-1] in NAME_SUFFIXES:
        parts.pop()
    return " ".join(parts)


def euroleague_name(raw_name):
    """'MCCORMACK, DAVID' -> 'david mccormack' (as a key, so the casing does not matter)."""
    parts = raw_name.split(",", 1)
    return f"{parts[1].strip()} {parts[0].strip()}" if len(parts) == 2 else raw_name


def in_range(value, bounds):
    return value if value is not None and bounds[0] <= value <= bounds[1] else None


def fetch(url, cache_name, params=None, accept=None):
    """GET with a file cache; returns text or None."""
    cache = CACHE_DIR / cache_name
    if cache.exists():
        return cache.read_text(encoding="utf-8")
    if params:
        url += "?" + urllib.parse.urlencode(params)
    headers = {"User-Agent": USER_AGENT}
    if accept:
        headers["Accept"] = accept
    for attempt in range(3):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=180) as r:
                text = r.read().decode("utf-8")
            CACHE_DIR.mkdir(parents=True, exist_ok=True)
            cache.write_text(text, encoding="utf-8")
            return text
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return None
            # Wikidata answers 429 when it's busy and says how long to wait
            wait = int(e.headers.get("Retry-After") or 0) if e.code == 429 else 0
            print(f"  HTTP {e.code}, retrying" + (f" in {wait}s" if wait else ""))
            time.sleep(min(wait, 120))
        except Exception as e:  # network hiccups
            print(f"  {e}, retrying")
        time.sleep(5 * (attempt + 1))
    return None


def slots_in_order(slots):
    return [s for s in SLOTS if s in slots]


class Facts:
    """What one source knows, by name: name key -> [entry], where an entry is a dict with any of
    born, first, last (seasons), height, weight, slots, stats."""

    def __init__(self):
        self.by_name = defaultdict(list)

    def add(self, name, entry):
        entry.setdefault("slots", set())
        for key in {name_key(name), base_name_key(name)}:
            self.by_name[key].append(entry)

    def lookup(self, names, born=None, seasons=None):
        """The entries for one player, merged; {} when nothing matches or two people can't be
        told apart. Same-named people are split by birth year, then by the seasons they played."""
        for name in names:
            for key in (name_key(name), base_name_key(name)):
                candidates = self.by_name.get(key)
                if not candidates:
                    continue
                picked = self._pick(candidates, born, seasons)
                if picked:
                    return merge(picked)
        return {}

    @staticmethod
    def _pick(candidates, born, seasons):
        def overlap(c):
            return max(0, min(seasons[1], c["last"]) - max(seasons[0], c["first"]) + 1)

        if seasons:
            # Someone by the same name whose career never crossed this player's is someone else
            # (Kenyon Martin Sr. for Kenyon Martin Jr.)
            candidates = [c for c in candidates if not c.get("first") or overlap(c)]
            if not candidates:
                return []
        people = {(c.get("born"), c.get("first")) for c in candidates}
        if len(people) <= 1:
            return candidates
        if born:
            picked = [c for c in candidates if c.get("born") in (None, born)]
            if picked:
                return picked
        if seasons:
            dated = [c for c in candidates if c.get("first")]
            best = max((overlap(c) for c in dated), default=0)
            picked = [c for c in dated if overlap(c) == best]
            if best and len({(c.get("born"), c.get("first")) for c in picked}) == 1:
                return picked
        # Entries without a birth year or seasons may all be one person (a roster snapshot each)
        if all(not c.get("born") and not c.get("first") for c in candidates):
            return candidates
        return []


def merge(entries):
    """Later entries win for single values (the newest season); slots are merged."""
    out = {"slots": set()}
    for entry in entries:
        for field, value in entry.items():
            if field == "slots":
                out["slots"] |= value
            elif value is not None:
                out[field] = value
    return out


# ---------------------------------------------------------------- sources

def bref_facts():
    """Basketball-Reference: career totals from NBA/BAA seasons, weight, birth year, positions."""
    print("Basketball-Reference: career info and season totals")
    info_text = fetch(BREF_BASE + "Player%20Career%20Info.csv", "bref_Player_Career_Info.csv")
    totals_text = fetch(BREF_BASE + "Player%20Totals.csv", "bref_Player_Totals.csv")
    if not info_text or not totals_text:
        print("  unavailable, skipped")
        return Facts()

    # Season rows: a player traded mid-season has one row per team plus a '2TM'/'3TM' total
    seasons = defaultdict(dict)   # player_id -> season -> row (the total row wins)
    for row in csv.DictReader(io.StringIO(totals_text)):
        if row["lg"] not in BREF_LEAGUES:
            continue
        current = seasons[row["player_id"]].get(row["season"])
        if current is None or row["team"].endswith("TM"):
            seasons[row["player_id"]][row["season"]] = row

    facts = Facts()
    for row in csv.DictReader(io.StringIO(info_text)):
        pid = row["player_id"]
        if pid not in seasons:
            continue  # ABA only
        stats = {}
        for column, stat in BREF_STATS.items():
            values = [r[column] for r in seasons[pid].values()]
            if all(v.isdigit() for v in values):
                stats[stat] = sum(int(v) for v in values)
        weight = round(int(row["wt"]) * 0.4536) if row["wt"].isdigit() else None
        slots = set()
        for part in row["pos"].replace("-", " ").split():
            slots.update(NBA_POSITIONS.get(part, []))
        played = sorted(int(s) for s in seasons[pid])
        facts.add(row["player"], {
            "born": int(row["birth_date"][:4]) if row["birth_date"][:4].isdigit() else None,
            "first": played[0], "last": played[-1],
            "weight": in_range(weight, WEIGHT_KG),
            "height": in_range(round(int(row["ht_in_in"]) * 2.54), HEIGHT_CM) if row["ht_in_in"].isdigit() else None,
            "slots": slots,
            "stats": stats,
            "career": {"last_season": played[-1], "seasons_played": len(played)},
        })
    print(f"  {len(seasons)} NBA/BAA players")
    return facts


def bbgm_facts():
    facts = Facts()
    for filename in BBGM_FILES:
        print(f"Basketball GM: {filename}")
        text = fetch(BBGM_BASE + urllib.parse.quote(filename), "bbgm_" + filename.replace(" ", "_"))
        if not text:
            print("  missing, skipped")
            continue
        data = parse_json_lenient(text)
        unreliable_born = filename.startswith("2009-10")
        for p in data.get("players", []):
            name = p.get("name") or f"{p.get('firstName', '')} {p.get('lastName', '')}".strip()
            if not name or p.get("tid", 0) < -1:  # -2 undrafted prospects, -3 retired, -4/-5 future draft
                continue
            hgt = p.get("hgt")
            if isinstance(hgt, list):  # some files keep a history: the newest value is last
                hgt = hgt[-1] if hgt else None
            if not isinstance(hgt, (int, float)) or not 63 <= hgt <= 93:
                hgt = None
            weight = p.get("weight")
            facts.add(name, {
                "born": None if unreliable_born else (p.get("born") or {}).get("year"),
                "height": round(hgt * 2.54) if hgt else None,
                "weight": in_range(round(weight * 0.4536), WEIGHT_KG) if isinstance(weight, (int, float)) else None,
                "slots": set(NBA_POSITIONS.get(p.get("pos"), [])),
            })
    return facts


def euroleague_facts():
    facts = Facts()
    for season in range(EUROLEAGUE_FIRST_SEASON, date.today().year + 1):
        text = fetch(EUROLEAGUE_PEOPLE_URL.format(season=season), f"el_people_{season}.json")
        rows = (json.loads(text).get("data") or []) if text else []
        print(f"EuroLeague {season}-{str(season + 1)[-2:]}: {len(rows)} registrations")
        for row in rows:
            person = row.get("person") or {}
            raw = (person.get("name") or "").strip()
            if len(raw) < 3:
                continue
            dob = (person.get("birthDate") or "")[:4]
            entry = {
                "born": int(dob) if dob.isdigit() else None,
                "height": in_range(person.get("height") or None, HEIGHT_CM),
                "weight": in_range(person.get("weight") or None, WEIGHT_KG),
                "slots": set(EUROLEAGUE_POSITIONS.get(row.get("positionName"), [])),
            }
            for name in {euroleague_name(raw), euroleague_name(person.get("alias") or raw)}:
                facts.add(name, dict(entry, slots=set(entry["slots"])))
    return facts


def wikidata_facts(league):
    facts = Facts()
    print(f"Wikidata: {league} players")
    text = fetch(WIKIDATA_SPARQL_URL, f"wikidata2_{league}.json",
                 params={"query": WIKIDATA_QUERY % WIKIDATA_ID_PROPERTY[league]},
                 accept="application/sparql-results+json")
    if not text:
        print("  Wikidata unavailable, skipped")
        return facts
    rows = json.loads(text)["results"]["bindings"]
    people = defaultdict(lambda: {"name": None, "born": None, "height": None, "weight": None, "slots": set()})
    for row in rows:
        entry = people[row["p"]["value"]]
        entry["name"] = row["name"]["value"]
        if "dob" in row and row["dob"]["value"][:4].isdigit():
            entry["born"] = int(row["dob"]["value"][:4])
        if "h" in row:
            entry["height"] = in_range(round(float(row["h"]["value"]) * 100), HEIGHT_CM)
        if "w" in row:
            entry["weight"] = in_range(round(float(row["w"]["value"])), WEIGHT_KG)
        if "posLabel" in row:
            entry["slots"].update(WIKIDATA_POSITIONS.get(row["posLabel"]["value"].lower(), []))
    for entry in people.values():
        name = entry.pop("name")
        facts.add(name, entry)
    print(f"  {len(people)} people")
    return facts


# ---------------------------------------------------------------- merge

def enrich(league, sources):
    """sources: {field: [Facts, ...]} in order of trust; slots come from every source."""
    base = json.loads((BASE_DIR / f"{league}_data.json").read_text(encoding="utf-8"))
    counts = defaultdict(int)
    every_source = {id(f): f for facts in sources.values() for f in facts}.values()
    for player in base["players"]:
        names = [player["name"], *player.get("aliases", [])]
        born = int(str(player["born"])[:4]) if player.get("born") else None
        found = {id(f): f.lookup(names, born, player.get("seasons")) for f in every_source}

        for field in ("height", "weight", "born"):
            value = next((found[id(f)].get(field) for f in sources[field] if found[id(f)].get(field)), None)
            if value:
                player["birth_year" if field == "born" else field] = value
                counts[field] += 1

        stats = dict(player.get("stats") or {})
        for f in sources["stats"]:
            stats.update(found[id(f)].get("stats") or {})
            if found[id(f)].get("career"):
                player["career"] = found[id(f)]["career"]
        if stats:
            player["stats"] = stats
            for stat in stats:
                counts[stat] += 1

        slots = set().union(*(found[id(f)].get("slots", set()) for f in every_source))
        # A player who only shows up as a 'pos' in the base dataset (same-named players)
        if not slots and player.get("pos"):
            slots = set(NBA_POSITIONS.get(player["pos"], []))
        if slots:
            player["positions"] = slots_in_order(slots)
            counts["positions"] += 1

    total = len(base["players"])
    print(f"{league}: " + ", ".join(f"{k} {v}/{total}" for k, v in sorted(counts.items())))
    out = DATA_DIR / f"{league}_data.json"
    out.write_text(json.dumps(base, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print(f"  wrote {out}")


def main():
    leagues = sys.argv[1:] or ["nba", "euroleague"]
    if "nba" in leagues:
        bref, bbgm, wiki = bref_facts(), bbgm_facts(), wikidata_facts("nba")
        enrich("nba", {"height": [bbgm, bref, wiki], "weight": [bref, bbgm, wiki],
                       "born": [bref, bbgm, wiki], "stats": [bref]})
    if "euroleague" in leagues:
        el, wiki = euroleague_facts(), wikidata_facts("euroleague")
        enrich("euroleague", {"height": [el, wiki], "weight": [el, wiki], "born": [el, wiki], "stats": []})


if __name__ == "__main__":
    main()
