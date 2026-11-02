"""Online rooms: two seats, one draft at a time, a shot clock the server owns.

Client -> server messages (JSON over /ws/rooms/{code}):
  {"type": "join", "name": "...", "token": "..."|null}   first message; the token gets a seat back
  {"type": "ready"}                                      both ready: the draft starts
  {"type": "pick", "id": 123}                            the player on the clock drafts someone
  {"type": "rematch"}                                    both asked: a new draft, the other team starts
  {"type": "leave"}

Server -> client: {"type": "welcome", "mark", "token"}, {"type": "room", ...the whole room...},
{"type": "error", "reason"}. Every change happens under the room's lock and is followed by
the whole room going to both players, so a pick and an expiring clock never both apply.

A player who drops mid-draft keeps their seat: the clock keeps running, so their picks
become turnovers until they come back.
"""

import asyncio
import json
import secrets
import time
from dataclasses import dataclass, field
from typing import Dict, Optional, Set

from fastapi import APIRouter, HTTPException, WebSocket, WebSocketDisconnect

from .draft import PICK_MODES, REVEALS, Draft, DraftError, other
from .catalog import CRITERIA_STYLES, Catalog

CODE_ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ"  # no I, L or O: easy to read out loud
CODE_LENGTH = 5
CLOCKS = (0, 30, 60, 120)
IDLE_TTL = 30 * 60       # rooms nobody is in, untouched this long, are removed
MAX_ROOMS = 500
JOIN_TIMEOUT = 10.0
CLOCK_GRACE = 0.4        # seconds past the deadline before the server calls it, for latency


class RoomError(Exception):
    """A request the room refuses; the reason goes back to the client."""


@dataclass(eq=False)
class Seat:
    mark: str
    name: str
    token: str
    sockets: Set = field(default_factory=set)
    ready: bool = False
    rematch: bool = False

    @property
    def connected(self) -> bool:
        return bool(self.sockets)


@dataclass(eq=False)
class Room:
    code: str
    settings: dict
    seats: Dict[str, Seat] = field(default_factory=dict)
    draft: Optional[Draft] = None
    draft_no: int = 0
    deadline: Optional[float] = None   # event-loop time the current pick runs out
    clock_task: Optional[asyncio.Task] = None
    last_activity: float = field(default_factory=time.monotonic)
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)


def clean_settings(raw: dict, catalogs: Dict[str, Catalog]) -> dict:
    league = raw.get("league")
    mode = raw.get("mode", "eligible")
    style = raw.get("style", "classic")
    reveal = raw.get("reveal", "end")
    clock = raw.get("clock", 60)
    if (league not in catalogs or mode not in PICK_MODES or style not in CRITERIA_STYLES
            or reveal not in REVEALS or clock not in CLOCKS):
        raise RoomError("Unknown game settings.")
    return {"league": league, "mode": mode, "style": style, "reveal": reveal, "clock": clock}


def clean_name(name) -> str:
    name = " ".join(str(name or "").split())[:16]
    return name or "Player"


class RoomManager:
    def __init__(self, catalogs: Dict[str, Catalog]):
        self.catalogs = catalogs
        self.rooms: Dict[str, Room] = {}

    # ---------- rooms ----------

    def create(self, settings: dict) -> Room:
        self.remove_idle()
        if len(self.rooms) >= MAX_ROOMS:
            raise RoomError("The server is full, try again later.")
        settings = clean_settings(settings, self.catalogs)
        while True:
            code = "".join(secrets.choice(CODE_ALPHABET) for _ in range(CODE_LENGTH))
            if code not in self.rooms:
                break
        room = Room(code, settings)
        self.rooms[code] = room
        return room

    def get(self, code: str) -> Optional[Room]:
        return self.rooms.get(code.upper())

    def phase(self, room: Room) -> str:
        if room.draft:
            return "playing" if room.draft.status == "in_progress" else "final"
        return "lobby" if len(room.seats) == 2 else "waiting"

    def remove_idle(self) -> None:
        now = time.monotonic()
        for code, room in list(self.rooms.items()):
            if any(s.connected for s in room.seats.values()) or now - room.last_activity < IDLE_TTL:
                continue
            self._stop_clock(room)
            del self.rooms[code]

    # ---------- people ----------

    async def connect(self, room: Room, ws: WebSocket, name, token) -> Seat:
        async with room.lock:
            seat = next((s for s in room.seats.values() if token and secrets.compare_digest(s.token, token)), None)
            if not seat:
                if len(room.seats) >= 2:
                    raise RoomError("This room is full.")
                if room.draft:
                    raise RoomError("This draft has already started.")
                mark = "X" if "X" not in room.seats else "O"
                seat = Seat(mark, clean_name(name), secrets.token_urlsafe(16))
                room.seats[mark] = seat
            seat.sockets.add(ws)
            room.last_activity = time.monotonic()
            await self._send(ws, {"type": "welcome", "mark": seat.mark, "token": seat.token})
            await self._broadcast(room)
            return seat

    async def disconnect(self, room: Room, seat: Seat, ws: WebSocket, leaving: bool = False) -> None:
        async with room.lock:
            seat.sockets.discard(ws)
            room.last_activity = time.monotonic()
            # Before the draft a seat that leaves is freed; during it, the seat is kept
            if leaving and not (room.draft and room.draft.status == "in_progress"):
                if room.seats.get(seat.mark) is seat:
                    del room.seats[seat.mark]
                for s in room.seats.values():
                    s.ready = s.rematch = False
                if not room.seats:
                    self._stop_clock(room)
                    room.draft = None
            await self._broadcast(room)

    # ---------- messages ----------

    async def handle(self, room: Room, seat: Seat, msg: dict) -> None:
        kind = msg.get("type")
        async with room.lock:
            room.last_activity = time.monotonic()
            if kind == "ready":
                if room.draft:
                    raise RoomError("The draft has already started.")
                seat.ready = True
                if len(room.seats) == 2 and all(s.ready for s in room.seats.values()):
                    self._start(room, "X")
            elif kind == "pick":
                draft = self._live(room)
                player_id = msg.get("id")
                if not isinstance(player_id, int):
                    raise RoomError("Pick a player from the list.")
                try:
                    draft.pick(seat.mark, player_id)
                except DraftError as e:
                    raise RoomError(str(e)) from None
                self._after_pick(room)
            elif kind == "rematch":
                if not room.draft or room.draft.status != "final":
                    raise RoomError("The draft isn't over yet.")
                if len(room.seats) < 2:
                    raise RoomError("Your opponent has left the room.")
                seat.rematch = True
                if all(s.rematch for s in room.seats.values()):
                    self._start(room, other(room.draft.starter))
            elif kind == "leave":
                return
            else:
                raise RoomError("Unknown message.")
            await self._broadcast(room)

    def _live(self, room: Room) -> Draft:
        if not room.draft or room.draft.status != "in_progress":
            raise RoomError("No draft in progress.")
        return room.draft

    def _start(self, room: Room, starter: str) -> None:
        s = room.settings
        room.draft = Draft(self.catalogs[s["league"]], mode=s["mode"], style=s["style"], reveal=s["reveal"],
                           starter=starter)
        room.draft_no += 1
        for seat in room.seats.values():
            seat.ready = seat.rematch = False
        self._restart_clock(room)

    def _after_pick(self, room: Room) -> None:
        draft = room.draft
        if draft.status == "final":
            self._stop_clock(room)
        else:
            self._restart_clock(room)

    # ---------- the shot clock ----------

    def _restart_clock(self, room: Room) -> None:
        self._stop_clock(room)
        length = room.settings["clock"]
        if not length:
            return
        loop = asyncio.get_running_loop()
        room.deadline = loop.time() + length
        room.clock_task = loop.create_task(self._run_clock(room, room.draft, room.draft.pick_count()))

    def _stop_clock(self, room: Room) -> None:
        if room.clock_task and room.clock_task is not asyncio.current_task():
            room.clock_task.cancel()
        room.clock_task = None
        room.deadline = None

    async def _run_clock(self, room: Room, draft: Draft, pick_count: int) -> None:
        await asyncio.sleep(room.settings["clock"] + CLOCK_GRACE)
        async with room.lock:
            # The pick may have been made while this task waited for the lock
            if room.draft is not draft or draft.status != "in_progress" or draft.pick_count() != pick_count:
                return
            room.clock_task = None
            draft.shot_clock(draft.on_clock)
            self._after_pick(room)
            await self._broadcast(room)

    # ---------- sending ----------

    def snapshot(self, room: Room) -> dict:
        ms_left = None
        if room.deadline is not None:
            ms_left = max(0, int((room.deadline - asyncio.get_running_loop().time()) * 1000))
        return {
            "type": "room",
            "code": room.code,
            "phase": self.phase(room),
            "settings": room.settings,
            "seats": [{"mark": s.mark, "name": s.name, "connected": s.connected, "ready": s.ready,
                       "rematch": s.rematch} for s in sorted(room.seats.values(), key=lambda s: s.mark)],
            "draft_no": room.draft_no,
            "draft": room.draft.public() if room.draft else None,
            "ms_left": ms_left,
        }

    async def _broadcast(self, room: Room) -> None:
        snapshot = self.snapshot(room)
        for seat in list(room.seats.values()):
            for ws in list(seat.sockets):
                await self._send(ws, snapshot)

    @staticmethod
    async def _send(ws: WebSocket, payload: dict) -> None:
        try:
            await asyncio.wait_for(ws.send_json(payload), 3.0)
        except Exception:
            pass  # a dead socket is cleaned up by its own receive loop


def build_room_router(rooms: RoomManager) -> APIRouter:
    router = APIRouter()

    @router.post("/api/rooms")
    def create_room(settings: dict):
        try:
            return {"code": rooms.create(settings).code}
        except RoomError as e:
            raise HTTPException(status_code=400, detail=str(e))

    @router.get("/api/rooms/{code}")
    def room_info(code: str):
        room = rooms.get(code)
        if not room:
            raise HTTPException(status_code=404, detail="No room with that code")
        return {"code": room.code, "phase": rooms.phase(room), "players": len(room.seats),
                "settings": room.settings}

    @router.websocket("/ws/rooms/{code}")
    async def room_socket(ws: WebSocket, code: str):
        await ws.accept()
        room = rooms.get(code)
        if not room:
            await _refuse(ws, "No room with that code.")
            return
        seat = None
        leaving = False
        try:
            first = await asyncio.wait_for(_receive(ws), JOIN_TIMEOUT)
            if first.get("type") != "join":
                raise RoomError("Join the room first.")
            seat = await rooms.connect(room, ws, first.get("name"), first.get("token"))
            while True:
                msg = await _receive(ws)
                if msg.get("type") == "leave":
                    leaving = True
                    break
                try:
                    await rooms.handle(room, seat, msg)
                except RoomError as e:
                    await ws.send_json({"type": "error", "reason": str(e)})
        except WebSocketDisconnect:
            pass
        except asyncio.TimeoutError:
            await _refuse(ws, "Took too long to join.")
        except RoomError as e:
            await _refuse(ws, str(e))
        finally:
            if seat:
                await rooms.disconnect(room, seat, ws, leaving)

    return router


async def _receive(ws: WebSocket) -> dict:
    frame = await ws.receive()
    if frame["type"] == "websocket.disconnect":
        raise WebSocketDisconnect(frame.get("code", 1000))
    try:
        msg = json.loads(frame.get("text") or "")
    except (ValueError, RecursionError):
        raise RoomError("Malformed message.") from None
    if not isinstance(msg, dict):
        raise RoomError("Malformed message.")
    return msg


async def _refuse(ws: WebSocket, reason: str) -> None:
    try:
        await ws.send_json({"type": "error", "reason": reason})
        await ws.close()
    except Exception:
        pass
