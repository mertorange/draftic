"""Draftić server: the player catalogs, hot-seat drafts over HTTP, online rooms over WebSockets."""

from pathlib import Path
from typing import Optional

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from .catalog import CATEGORIES, CRITERIA_STYLES, load_catalogs
from .draft import MARKS, PICK_MODES, REVEALS, DraftError, DraftStore
from .limits import LimitMiddleware, Limits
from .rooms import RoomManager, build_room_router

FRONTEND = Path(__file__).resolve().parent.parent / "frontend"


class FrontendFiles(StaticFiles):
    """The frontend's files, which browsers must check again on every load: the JS modules
    import each other without version numbers, so a cached one could outlive an update."""

    def file_response(self, *args, **kwargs):
        response = super().file_response(*args, **kwargs)
        response.headers["Cache-Control"] = "no-cache"
        return response


class NewDraft(BaseModel):
    league: str = "nba"
    mode: str = "eligible"
    style: str = "classic"
    category: Optional[str] = None   # None: dealt at random
    reveal: str = "end"
    starter: str = "X"


class PickRequest(BaseModel):
    mark: str
    id: int


class ClockRequest(BaseModel):
    mark: str


def create_app(limits: Optional[Limits] = None) -> FastAPI:
    limits = limits or Limits.from_env()
    catalogs = load_catalogs()
    drafts = DraftStore(catalogs)
    rooms = RoomManager(catalogs)
    app = FastAPI(title="Draftić")
    app.add_middleware(LimitMiddleware, limits=limits)
    app.state.catalogs, app.state.drafts, app.state.rooms = catalogs, drafts, rooms

    def refuse(e: DraftError):
        return HTTPException(status_code=400, detail=str(e))

    @app.get("/api/leagues")
    def leagues():
        return {key: {"title": c.title, "players": len(c.players), "teams": len(c.teams),
                      "categories": [CATEGORIES[k].public() for k in c.categories]}
                for key, c in catalogs.items()}

    @app.get("/api/players")
    def players(league: str):
        """Every name in the league, for the extreme-mode autocomplete."""
        if league not in catalogs:
            raise HTTPException(status_code=404, detail="Unknown league")
        return {"players": catalogs[league].names()}

    @app.post("/api/drafts")
    def new_draft(req: NewDraft):
        unknown_category = req.category is not None and req.category not in CATEGORIES
        if (req.mode not in PICK_MODES or req.style not in CRITERIA_STYLES or unknown_category
                or req.reveal not in REVEALS or req.starter not in MARKS):
            raise HTTPException(status_code=400, detail="Unknown game settings")
        try:
            return drafts.create(req.league, req.mode, req.style, req.category, req.reveal, req.starter).public()
        except DraftError as e:
            raise refuse(e)

    @app.get("/api/drafts/{draft_id}")
    def get_draft(draft_id: str):
        try:
            return drafts.get(draft_id).public()
        except DraftError as e:
            raise HTTPException(status_code=404, detail=str(e))

    @app.post("/api/drafts/{draft_id}/pick")
    def pick(draft_id: str, req: PickRequest):
        try:
            draft = drafts.get(draft_id)
            draft.pick(req.mark, req.id)
            return draft.public()
        except DraftError as e:
            raise refuse(e)

    @app.post("/api/drafts/{draft_id}/shot-clock")
    def shot_clock(draft_id: str, req: ClockRequest):
        try:
            draft = drafts.get(draft_id)
            draft.shot_clock(req.mark)
            return draft.public()
        except DraftError as e:
            raise refuse(e)

    app.include_router(build_room_router(rooms, limits))

    @app.get("/health")
    def health():
        return {"ok": True, "players": {k: len(c.players) for k, c in catalogs.items()},
                "rooms": len(rooms.rooms), "drafts": len(drafts.drafts)}

    @app.get("/")
    def index():
        return FileResponse(FRONTEND / "index.html", headers={"Cache-Control": "no-cache"})

    app.mount("/static", FrontendFiles(directory=FRONTEND), name="static")
    return app


app = create_app()
