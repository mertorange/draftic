import pytest
from fastapi import WebSocketDisconnect
from fastapi.testclient import TestClient

from backend.app import app
from backend.catalog import CATEGORIES, MIN_POOL, SLOTS, load_catalogs
from backend.draft import ROUNDS, Draft, DraftError

CATALOGS = load_catalogs()


@pytest.fixture
def client():
    return TestClient(app)


def run_draft(draft, choose=lambda pool: pool[0]["id"]):
    order = []
    while draft.status == "in_progress":
        state = draft.public()
        order.append(draft.on_clock)
        draft.pick(draft.on_clock, choose(state["pool"]))
    return order


@pytest.mark.parametrize("league", ["nba", "euroleague"])
def test_every_player_has_slots_and_sane_values(league):
    catalog = CATALOGS[league]
    assert len(catalog.players) > 2000
    for p in catalog.players:
        assert p.positions and set(p.positions) <= set(SLOTS)
        assert 155 <= p.values.get("height", 200) <= 235
        assert 50 <= p.values.get("weight", 100) <= 170
        assert 16 <= p.values.get("age", 30) <= 50


def test_leagues_offer_body_and_career_categories():
    nba, euroleague = CATALOGS["nba"].categories, CATALOGS["euroleague"].categories
    assert {"height", "weight", "age", "games", "points", "rebounds", "assists", "steals", "blocks"} <= set(nba)
    assert {"height", "weight", "age", "games", "points", "rebounds", "assists"} <= set(euroleague)
    assert "steals" not in euroleague  # no EuroLeague steals in the data


@pytest.mark.parametrize("league", ["nba", "euroleague"])
def test_every_category_plays_a_full_draft(league):
    catalog = CATALOGS[league]
    for category in catalog.categories:
        draft = Draft(catalog, style="mixed", category=category, seed=11)
        while draft.status == "in_progress":
            if draft.turn == 0:
                assert len(draft.pool()) >= MIN_POOL, (category, draft.round)
            draft.pick(draft.on_clock, draft.public()["pool"][0]["id"])
        assert all(category in p.player.values for p in draft.log)


def test_category_is_dealt_at_random():
    dealt = {Draft(CATALOGS["nba"], seed=seed).category for seed in range(40)}
    assert len(dealt) >= 6
    assert dealt <= set(CATALOGS["nba"].categories)


@pytest.mark.parametrize("league", ["nba", "euroleague"])
@pytest.mark.parametrize("style", ["classic", "mixed"])
def test_full_draft_two_per_slot(league, style):
    for seed in range(5):
        draft = Draft(CATALOGS[league], style=style, seed=seed)
        run_draft(draft)
        assert draft.status == "final"
        for mark in "XO":
            slots = [p.slot for p in draft.picks[mark]]
            assert slots == ["PG", "SG", "SF", "PF", "C", "6M"]
        ids = [p.player.id for p in draft.log]
        assert len(ids) == len(set(ids)) == 12


def test_sixth_man_takes_any_position():
    draft = Draft(CATALOGS["nba"], seed=8, category="points")
    while draft.slot != "6M":
        draft.pick(draft.on_clock, draft.public()["pool"][0]["id"])
    state = draft.public()
    assert state["current"]["slot_name"] == "Sixth man (any position)"
    positions = {s for p in draft.pool() for s in p.positions}
    assert positions == set(SLOTS)  # guards, forwards and centers all fit
    assert len(ROUNDS) == 6


def test_pick_order_alternates_each_round():
    draft = Draft(CATALOGS["nba"], seed=3)
    order = run_draft(draft)
    assert order[:8] == ["X", "O", "O", "X", "X", "O", "O", "X"]
    draft = Draft(CATALOGS["nba"], seed=3, starter="O")
    assert run_draft(draft)[:4] == ["O", "X", "X", "O"]


def test_rounds_always_leave_a_pool():
    for seed in range(20):
        draft = Draft(CATALOGS["euroleague"], style="mixed", seed=seed)
        while draft.status == "in_progress":
            if draft.turn == 0:
                assert len(draft.pool()) >= MIN_POOL
            draft.pick(draft.on_clock, draft.public()["pool"][0]["id"])


def test_heights_hidden_until_final():
    draft = Draft(CATALOGS["nba"], seed=1, category="points")
    draft.pick("X", draft.public()["pool"][0]["id"])
    state = draft.public()
    assert "value" not in state["picks"]["X"][0]
    assert {k: state["category"][k] for k in ("key", "label", "unit", "kind")} ==         {"key": "points", "label": "Points", "unit": "pts", "kind": "career"}
    assert state["category"]["hint"]
    assert "totals" not in state
    run_draft(draft)
    state = draft.public()
    assert all("value" in p for p in state["picks"]["X"])
    assert state["totals"]["X"] == sum(p["value"] for p in state["picks"]["X"])
    assert state["winner"] in ("X", "O", "draw")


def test_wrong_turn_and_ineligible_refused():
    draft = Draft(CATALOGS["nba"], seed=2)
    pool_ids = {p["id"] for p in draft.public()["pool"]}
    with pytest.raises(DraftError):
        draft.pick("O", next(iter(pool_ids)))
    outsider = next(p.id for p in CATALOGS["nba"].players if p.id not in pool_ids)
    with pytest.raises(DraftError):
        draft.pick("X", outsider)


def test_shot_clock_hands_over_the_lowest_value():
    draft = Draft(CATALOGS["nba"], seed=4, category="assists")
    fewest = min(p.values["assists"] for p in draft.pool())
    pick = draft.shot_clock("X")
    assert pick.value == fewest
    assert pick.turnover == "shot clock violation"


def test_extreme_mode_wrong_pick_is_a_turnover():
    draft = Draft(CATALOGS["nba"], mode="extreme", seed=5)
    assert "pool" not in draft.public()
    pool_ids = {p.id for p in draft.pool()}
    outsider = next(p for p in CATALOGS["nba"].players if p.id not in pool_ids)
    pick = draft.pick("X", outsider.id)
    assert pick.turnover and outsider.name in pick.turnover
    assert pick.player.id in pool_ids
    # The same player again for O: already drafted
    again = draft.pick("O", pick.player.id)
    assert "already drafted" in again.turnover


def test_http_hotseat_flow(client):
    state = client.post("/api/drafts", json={"league": "euroleague"}).json()
    while state["status"] == "in_progress":
        r = client.post(f"/api/drafts/{state['id']}/pick", json={"mark": state["on_clock"], "id": state["pool"][0]["id"]})
        assert r.status_code == 200
        state = r.json()
    assert state["winner"]
    bad = client.post(f"/api/drafts/{state['id']}/pick", json={"mark": "X", "id": 1})
    assert bad.status_code == 400


def test_live_reveal_shows_values_and_running_totals():
    draft = Draft(CATALOGS["nba"], seed=6, reveal="live")
    pick = draft.pick("X", draft.public()["pool"][0]["id"])
    state = draft.public()
    assert state["picks"]["X"][0]["value"] == pick.value
    assert state["totals"] == {"X": pick.value, "O": 0}
    assert "winner" not in state


def test_unknown_category_refused(client):
    assert client.post("/api/drafts", json={"league": "nba", "category": "shoe_size"}).status_code == 400
    assert client.post("/api/drafts", json={"league": "nba", "reveal": "never"}).status_code == 400
    # A category the league has no data for
    assert client.post("/api/drafts", json={"league": "euroleague", "category": "steals"}).status_code == 400
    assert client.get("/api/leagues").json()["nba"]["categories"][0]["key"] == "height"


def test_players_list_has_no_heights(client):
    players = client.get("/api/players", params={"league": "nba"}).json()["players"]
    assert len(players) > 2000 and "height" not in players[0]


def test_online_room_full_draft(client):
    code = client.post("/api/rooms", json={"league": "nba", "mode": "eligible", "style": "classic", "clock": 0}).json()["code"]
    with client.websocket_connect(f"/ws/rooms/{code}") as a, client.websocket_connect(f"/ws/rooms/{code}") as b:
        a.send_json({"type": "join", "name": "Ana"})
        assert a.receive_json()["mark"] == "X"
        a.receive_json()
        b.send_json({"type": "join", "name": "Bo"})
        assert b.receive_json()["mark"] == "O"
        b.receive_json(); a.receive_json()
        a.send_json({"type": "ready"}); a.receive_json(); b.receive_json()
        b.send_json({"type": "ready"})
        room = a.receive_json(); b.receive_json()
        assert room["phase"] == "playing"
        sockets = {"X": a, "O": b}
        while room["draft"]["status"] == "in_progress":
            draft = room["draft"]
            sockets[draft["on_clock"]].send_json({"type": "pick", "id": draft["pool"][0]["id"]})
            room = a.receive_json(); b.receive_json()
        assert room["phase"] == "final"
        a.send_json({"type": "rematch"}); a.receive_json(); b.receive_json()
        b.send_json({"type": "rematch"})
        room = a.receive_json(); b.receive_json()
        assert room["draft_no"] == 2 and room["draft"]["on_clock"] == "O"


def test_rate_limits_refuse_bursts():
    from backend.app import create_app
    from backend.limits import Limits

    limited = TestClient(create_app(Limits(create=(1, 2), api=(1, 3), sockets=(1, 1))))
    codes = [limited.post("/api/drafts", json={"league": "nba"}).status_code for _ in range(3)]
    assert codes == [200, 200, 429]
    refused = limited.post("/api/rooms", json={"league": "nba"})
    assert refused.status_code == 429 and int(refused.headers["retry-after"]) > 0
    assert [limited.get("/api/leagues").status_code for _ in range(4)] == [200, 200, 200, 429]
    assert limited.get("/health").status_code == 200  # only the API is limited

    with limited.websocket_connect("/ws/rooms/ABCDE") as ws:
        assert ws.receive_json()["type"] == "error"  # no such room, but the socket was let in
    with pytest.raises(WebSocketDisconnect):  # the second handshake is refused
        with limited.websocket_connect("/ws/rooms/ABCDE") as ws:
            ws.receive_json()


def test_oversized_requests_refused(client):
    big = {"league": "nba", "padding": "x" * 20_000}
    assert client.post("/api/rooms", json=big).status_code == 413


def unlimited_client():
    from backend.app import create_app
    from backend.limits import Limits

    return TestClient(create_app(Limits(enabled=False)))


def test_rooms_capped_per_address_and_empty_ones_expire():
    from backend import rooms as R

    c = unlimited_client()
    codes = [c.post("/api/rooms", json={"league": "nba"}).json()["code"] for _ in range(R.ROOMS_PER_IP)]
    refused = c.post("/api/rooms", json={"league": "nba"})
    assert refused.status_code == 400 and "too many open rooms" in refused.json()["detail"]
    for room in c.app.state.rooms.rooms.values():
        room.last_activity -= R.EMPTY_TTL + 1   # nobody ever sat down
    assert c.post("/api/rooms", json={"league": "nba"}).status_code == 200
    assert not set(codes) & set(c.app.state.rooms.rooms)


def test_one_seat_holds_a_few_sockets_at_most():
    from backend import rooms as R

    c = unlimited_client()
    code = c.post("/api/rooms", json={"league": "nba"}).json()["code"]
    with c.websocket_connect(f"/ws/rooms/{code}") as first:
        first.send_json({"type": "join", "name": "Ana"})
        token = first.receive_json()["token"]
        first.receive_json()
        extra = []
        for _ in range(R.SOCKETS_PER_SEAT):
            cm = c.websocket_connect(f"/ws/rooms/{code}")
            ws = cm.__enter__()
            extra.append(cm)
            ws.send_json({"type": "join", "token": token})
            assert ws.receive_json()["type"] == "welcome"
        while (msg := first.receive_json())["type"] == "room":
            pass
        assert msg["type"] == "error" and msg["closed"]   # the oldest was shut out
        assert len(c.app.state.rooms.rooms[code].seats["X"].sockets) == R.SOCKETS_PER_SEAT
        for cm in extra:
            cm.__exit__(None, None, None)


def test_open_sockets_capped_per_address():
    from backend.app import create_app
    from backend.limits import Limits

    c = TestClient(create_app(Limits(sockets=(600, 100), open_sockets=2)))
    code = c.post("/api/rooms", json={"league": "nba"}).json()["code"]
    with c.websocket_connect(f"/ws/rooms/{code}") as a, c.websocket_connect(f"/ws/rooms/{code}") as b:
        for ws in (a, b):
            ws.send_json({"type": "join", "name": "Ana"})
            assert ws.receive_json()["type"] == "welcome"
        with pytest.raises(WebSocketDisconnect):   # a third, held at the same time, is refused
            with c.websocket_connect(f"/ws/rooms/{code}") as ws:
                ws.receive_json()
    with c.websocket_connect("/ws/rooms/ABCDE") as ws:   # closed ones count no longer
        assert ws.receive_json()["type"] == "error"


def test_draft_flood_only_pushes_out_its_own_drafts():
    from backend.draft import DraftStore

    store = DraftStore(CATALOGS, max_drafts=5, per_owner=3)
    victim = store.create("nba", "eligible", "classic", owner="player").id
    flood = [store.create("nba", "eligible", "classic", owner="flood").id for _ in range(10)]
    assert victim in store.drafts and flood[-3:] == [k for k in store.drafts if k != victim]

    # A full store drops the draft untouched longest, not the oldest one
    store = DraftStore(CATALOGS, max_drafts=3, per_owner=10)
    ids = [store.create("nba", "eligible", "classic", owner=str(i)).id for i in range(3)]
    store.get(ids[0])
    store.create("nba", "eligible", "classic", owner="new")
    assert ids[0] in store.drafts and ids[1] not in store.drafts


def test_chunked_oversized_body_gets_a_clean_413(client):
    r = client.post("/api/rooms", content=iter([b'{"league": "nba", "x": "', b"x" * 20_000, b'"}']),
                    headers={"content-type": "application/json"})
    assert r.status_code == 413


def test_security_headers_and_compressed_player_list(client):
    page = client.get("/")
    assert "frame-ancestors 'none'" in page.headers["content-security-policy"]
    assert page.headers["x-content-type-options"] == "nosniff"
    names = client.get("/api/players", params={"league": "nba"}, headers={"accept-encoding": "gzip"})
    assert names.headers["content-encoding"] == "gzip" and "max-age" in names.headers["cache-control"]
