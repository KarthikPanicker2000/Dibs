"""Agent HTTP service (PLAN.md section 10). One process / VM per participant.

Run: PARTICIPANT_ID=ana uvicorn agent.service:app --port 8001
The orchestrator pushes the public catalog with POST /setup, so one agent
process can serve whichever scenario is loaded.
"""
from __future__ import annotations

import os
from pathlib import Path

import httpx
from fastapi import Body, FastAPI, Header, HTTPException
from fastapi.responses import HTMLResponse, Response

from .logic import AgentLogic

FORM = Path(__file__).resolve().parent / "form.html"


def create_app(logic: AgentLogic) -> FastAPI:
    app = FastAPI(title=f"Parley agent {logic.pid or ''}")

    @app.get("/", response_class=HTMLResponse)
    def form():
        return FORM.read_text()

    @app.get("/status")
    def status():
        return logic.status()

    @app.get("/health")
    def health():
        return {"ok": True}

    @app.post("/chat")
    def chat(body: dict = Body(default={})):
        # Maritime's container contract wants POST /chat; it only ever returns public status.
        st = logic.status()
        return {"response": f"I'm {st['name']}'s private Parley agent. My numbers stay with me until the verdict is final.",
                "status": st}

    @app.get("/catalog")
    def catalog():
        if not logic.scenario:
            raise HTTPException(409, "no scenario loaded yet")
        sc = logic.scenario
        return {"id": sc.id, "title": sc.title, "you": logic.pid, "name": logic.name,
                "max_top_ratings": sc.max_top_ratings, "will": sc.will,
                "items": [i.model_dump() for i in sc.items],
                "has_prefs": logic.prefs is not None, "has_demo": logic.demo_prefs() is not None}

    @app.post("/setup")
    def setup(body: dict = Body(...)):
        if body.get("orch_url"):
            logic.orch_url = body["orch_url"]
        return logic.setup(body["scenario"], body.get("participant_id"), bool(body.get("reset")))

    @app.get("/images/{name}")
    def image(name: str):
        # item photos relayed from the room, so the phone still only talks to its own agent
        if not logic.orch_url:
            raise HTTPException(404, "not connected to a room yet")
        r = httpx.get(f"{logic.orch_url}/images/{name}", timeout=10)
        if r.status_code != 200:
            raise HTTPException(r.status_code, "no such image")
        return Response(r.content, media_type=r.headers.get("content-type", "image/jpeg"),
                        headers={"Cache-Control": "max-age=86400"})

    @app.get("/room_state")
    def room_state():
        # public room state relayed for this agent's phone, so the phone only ever talks to its own agent
        if not logic.orch_url:
            raise HTTPException(503, "not connected to a room yet")
        try:
            return httpx.get(f"{logic.orch_url}/state", timeout=5).json()
        except httpx.HTTPError as e:
            raise HTTPException(502, f"room unreachable: {e}")

    def owner(token):
        try:
            logic.check_owner(token)
        except PermissionError as e:
            raise HTTPException(403, str(e))

    @app.post("/claim")
    def claim(body: dict = Body(default={})):
        try:
            return logic.claim(body.get("token"))
        except PermissionError as e:
            raise HTTPException(403, str(e))

    @app.get("/me")
    def me(x_owner_token: str | None = Header(default=None)):
        owner(x_owner_token)
        return logic.me()

    @app.post("/auction/override")
    def override(body: dict = Body(...), x_owner_token: str | None = Header(default=None)):
        owner(x_owner_token)
        try:
            return logic.override(body["item_id"], body.get("action", "drop"), body.get("amount"))
        except ValueError as e:
            raise HTTPException(400, str(e))

    @app.post("/prefs")
    def prefs(body: dict = Body(...), x_owner_token: str | None = Header(default=None)):
        owner(x_owner_token)
        try:
            return logic.set_prefs(body)
        except ValueError as e:
            raise HTTPException(400, str(e))

    @app.get("/demo_prefs")
    def demo_prefs(x_owner_token: str | None = Header(default=None)):
        # For the form's auto-fill button: the participant's own demo ratings.
        owner(x_owner_token)
        d = logic.demo_prefs()
        if d is None:
            raise HTTPException(404, "no demo ratings")
        return d.model_dump()

    @app.post("/demo_fill")
    def demo_fill():
        try:
            return logic.demo_fill()
        except ValueError as e:
            raise HTTPException(404, str(e))

    @app.get("/interest")
    def interest():
        return logic.interest()

    @app.post("/negotiate")
    def negotiate(body: dict = Body(...)):
        return logic.negotiate(body)

    @app.post("/auction/start")
    def auction_start(body: dict = Body(...)):
        return logic.auction_start(body)

    @app.post("/auction/tick")
    def auction_tick(body: dict = Body(...)):
        return logic.auction_tick(body["item_id"], float(body["price"]))

    @app.post("/attest")
    def attest(body: dict = Body(...)):
        return logic.attest(body["outcomes"], body["cash"])

    @app.post("/unlock")
    def unlock():
        return logic.unlock()

    @app.get("/reveal")
    def reveal():
        try:
            return logic.reveal()
        except PermissionError as e:
            raise HTTPException(403, str(e))

    return app


app = create_app(AgentLogic(os.environ.get("PARTICIPANT_ID")))
