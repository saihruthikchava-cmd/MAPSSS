"""WayWise chatbot — service feedback, hazard reports, and location help.

Drop-in module. Import it at the bottom of app.py like:
    import chatbot  # noqa: F401  (registers /api/chat)

It reuses the host app's db(), body(), err(), current_user(), jsonify,
HAZARD_TYPES and FEEDBACK_TYPES so the chatbot's writes land in the same
tables your dashboard already shows.
"""
import json
import os
import random
import urllib.request

from flask import jsonify, request

# Pull the shared pieces from the host app.
from app import (
    app, db, body, err, current_user, utc_now,
    HAZARD_TYPES, FEEDBACK_TYPES,
)


# ─────────────────────────────────────────────────────────────────────────────
# Small talk / classification
# ─────────────────────────────────────────────────────────────────────────────
GREETINGS = {"hi", "hello", "hey", "yo", "namaste", "good morning", "good evening", "hola"}
THANKS    = {"thanks", "thank you", "thx", "ty", "cheers", "thankyou"}
BYES      = {"bye", "goodbye", "see you", "cya", "see ya"}
HELP_WORDS = {"help", "menu", "options", "what can you do", "commands"}


def _classify(text: str) -> str:
    t = text.lower().strip().rstrip("!.?")
    if t in GREETINGS: return "greeting"
    if t in THANKS:    return "thanks"
    if t in BYES:      return "bye"
    if t in HELP_WORDS: return "help"
    return "other"


# ─────────────────────────────────────────────────────────────────────────────
# Location validation + suggestions
# ─────────────────────────────────────────────────────────────────────────────
def _looks_like_coords(text: str):
    """Return (lat, lon) if the text is 'lat, lon' form, else None."""
    import re
    m = re.fullmatch(r"\s*(-?\d+(?:\.\d+)?)\s*,\s*(-?\d+(?:\.\d+)?)\s*", text)
    if not m:
        return None
    lat, lon = float(m.group(1)), float(m.group(2))
    if -90 <= lat <= 90 and -180 <= lon <= 180:
        return lat, lon
    return None


def _nearby_landmarks(lat, lon, limit=4):
    """Best-effort reverse geocode to give the bot something human to say.
    Fails silently — the bot still works without internet."""
    try:
        url = (
            "https://nominatim.openstreetmap.org/reverse?format=json"
            f"&zoom=16&lat={lat}&lon={lon}"
        )
        req = urllib.request.Request(url, headers={"User-Agent": "WayWise/1.0"})
        with urllib.request.urlopen(req, timeout=6) as r:
            data = json.loads(r.read().decode())
        name = data.get("display_name", "").split(",")[0].strip()
        return name or None
    except Exception:
        return None


def _location_help_reply(text: str) -> str:
    """When a location looks wrong / unparseable, give practical help."""
    coords = _looks_like_coords(text)
    if coords:
        lat, lon = coords
        nearby = _nearby_landmarks(lat, lon)
        where = f"near {nearby}" if nearby else "at that spot"
        return (
            f"Got it — that's {lat:.5f}, {lon:.5f} ({where}).\n\n"
            "You can:\n"
            "• Tap the map there to drop a pin and report a hazard\n"
            "• Save it as a place from the Me tab\n"
            "• Use it as a route start or destination"
        )

    return (
        "I couldn't pin that location. A few ways to help me find it:\n\n"
        "• **Landmark** — try \"Central Library\" or \"Hostel Block A\"\n"
        "• **Area + city** — e.g. \"Gachibowli, Hyderabad\"\n"
        "• **Coordinates** — paste as `17.3850, 78.4867`\n"
        "• **On the map** — tap the map where you mean, then choose *Report a hazard here*\n\n"
        "Tell me which one you'd like, or paste a place name and I'll try again."
    )


# ─────────────────────────────────────────────────────────────────────────────
# Guided flows: feedback + hazard
# ─────────────────────────────────────────────────────────────────────────────
# The chat is stateless on the server — the frontend keeps flow state so
# multiple users/tabs never collide. This endpoint is the "finisher": it
# validates and inserts once the frontend says the flow is complete.

def _finish_feedback(payload: dict, user) -> str:
    category = str(payload.get("category", "")).strip()
    message  = str(payload.get("message", "")).strip()
    try:
        rating = int(payload.get("rating"))
    except (TypeError, ValueError):
        return "I need a star rating from 1 to 5 before I can save your feedback."

    if category not in FEEDBACK_TYPES:
        return f"Please pick one of: {', '.join(sorted(FEEDBACK_TYPES))}."
    if not 1 <= rating <= 5:
        return "Rating should be between 1 and 5 stars."
    if not message:
        return "Add a short message so the team knows what to fix."
    if len(message) > 1000:
        return "That's a bit long — please keep it under 1000 characters."

    with db() as conn:
        conn.execute(
            "INSERT INTO user_feedback(category,rating,message,created_at,user_id)"
            " VALUES (?,?,?,?,?)",
            (category, rating, message, utc_now(), user["id"] if user else None),
        )
    stars = "★" * rating + "☆" * (5 - rating)
    who = f" Thanks, {user['name'].split()[0]}!" if user else ""
    return f"Saved your feedback {stars} ({category}).{who} The team sees it in the dashboard — thank you!"


def _finish_hazard(payload: dict, user) -> str:
    kind = str(payload.get("type", "")).strip()
    desc = str(payload.get("description", "")).strip()
    try:
        lat = float(payload.get("lat"))
        lon = float(payload.get("lon"))
    except (TypeError, ValueError):
        return _location_help_reply(str(payload.get("location_text", "")))

    if kind not in HAZARD_TYPES:
        return f"That hazard type isn't recognised. Try one of: {', '.join(sorted(HAZARD_TYPES))}."
    if not (-90 <= lat <= 90 and -180 <= lon <= 180):
        return _location_help_reply(f"{lat}, {lon}")
    if len(desc) > 500:
        return "Keep the note under 500 characters, please."

    with db() as conn:
        conn.execute(
            "INSERT INTO hazard_reports(type,description,lat,lon,created_at,user_id)"
            " VALUES (?,?,?,?,?,?)",
            (kind, desc, lat, lon, utc_now(), user["id"] if user else None),
        )
    where = _nearby_landmarks(lat, lon) or f"{lat:.5f}, {lon:.5f}"
    return f"Reported: **{kind}** near {where}. Thanks for helping other students — it's on the map now."


# ─────────────────────────────────────────────────────────────────────────────
# Free-form Q&A (facts pulled from the live DB)
# ─────────────────────────────────────────────────────────────────────────────
def _bot_context(user) -> dict:
    ctx = {"user_name": None, "hazards": [], "places": [], "history": []}
    if not user:
        return ctx
    ctx["user_name"] = user["name"].split(" ")[0]
    with db() as conn:
        ctx["places"] = [dict(r) for r in conn.execute(
            "SELECT label FROM saved_places WHERE user_id=? ORDER BY id DESC LIMIT 5",
            (user["id"],)).fetchall()]
        ctx["history"] = [dict(r) for r in conn.execute(
            "SELECT origin,destination,mode FROM route_history WHERE user_id=? ORDER BY id DESC LIMIT 3",
            (user["id"],)).fetchall()]
    with db() as conn:
        ctx["hazards"] = [dict(r) for r in conn.execute(
            "SELECT type,description FROM hazard_reports ORDER BY id DESC LIMIT 5"
        ).fetchall()]
    return ctx


def _rule_reply(text: str, ctx: dict) -> str:
    t = text.lower()
    intent = _classify(t)

    if intent == "greeting":
        who = f", {ctx['user_name']}" if ctx.get("user_name") else ""
        return (
            f"Hi{who}! 👋 I'm WayWise Assistant. I can:\n"
            "• Take your **feedback** on WayWise\n"
            "• File a **hazard report** for you\n"
            "• Help when a **location isn't found**\n"
            "• Answer questions about routes & saved places\n\n"
            "What would you like to do?"
        )
    if intent == "thanks":
        return "You're welcome! Stay safe out there. 🛡️"
    if intent == "bye":
        return "Goodbye! Plan your route and stay aware. 👋"
    if intent == "help":
        return (
            "Here's what I can do:\n"
            "• **Send feedback** — tell me how WayWise is working\n"
            "• **Report a hazard** — poor lighting, waterlogging, unsafe spots\n"
            "• **Find places** — if a search fails, I'll suggest ways to pin it\n"
            "• **Safety tips** — quick advice for walking at night\n\n"
            "Just type what you need."
        )

    # Feedback hints
    if any(w in t for w in ["feedback", "suggest", "bug", "improve", "complain", "review", "rating"]):
        return (
            "I can take your feedback right here. Tell me:\n"
            "1) A **rating 1–5** ⭐\n"
            "2) The **type** (Suggestion / Bug report / Route feedback / Map feedback / Other)\n"
            "3) A short **message**\n\n"
            "Or tap **Send feedback** below and I'll walk you through it."
        )

    # Hazard hints
    if any(w in t for w in ["hazard", "danger", "unsafe", "waterlog", "lighting", "accident", "obstruction"]):
        return (
            "I can file a hazard report for you. I'll need:\n"
            "• The **type** (Poor lighting, Waterlogging, Accident spot, Road damage, Isolated area, Unsafe crossing, Other)\n"
            "• A short **note**\n"
            "• A **location** — a place name, landmark, or `lat, lon`\n\n"
            "Or tap **Report a hazard** below."
        )

    # Location trouble
    if any(w in t for w in ["location", "not found", "can't find", "cannot find", "wrong place", "invalid", "no results"]):
        return _location_help_reply(text)

    # Saved places
    if any(w in t for w in ["saved", "my places", "hostel", "library", "canteen"]):
        places = ctx.get("places") or []
        if not places:
            return "No saved places yet. Add them in the **Me** tab and they'll show as quick picks on the Route tab."
        return "Your saved places: " + ", ".join(p["label"] for p in places) + "."

    # History
    if any(w in t for w in ["recent", "history", "last trip"]):
        hist = ctx.get("history") or []
        if not hist:
            return "No recent trips yet — plan one from the **Route** tab."
        return "Recent trips:\n" + "\n".join(
            f"• {h['origin']} → {h['destination']} ({h['mode']})" for h in hist)

    # Routes
    if any(w in t for w in ["route", "directions", "navigate", "walk", "drive", "bike", "cycle"]):
        return (
            "To plan a route:\n"
            "1) Open the **Route** tab\n"
            "2) Pick Walk / Bike / Drive\n"
            "3) Enter start and destination\n"
            "4) Tap *Find my route* — I'll rank options and flag hazards nearby."
        )

    # Safety
    if any(w in t for w in ["safe", "safety", "tips", "night", "alone"]):
        return random.choice([
            "Safety tips:\n• Share your live location on late trips\n• Stick to lit, busy routes after dark\n• Keep your phone charged, one ear free\n• Trust your gut — if a route feels wrong, take another",
            "A few that help:\n• Prefer main roads over shortcuts at night\n• Check **Nearby** for reports along your route\n• Tell someone your ETA\n• Avoid isolated stretches even if they're faster",
        ])

    # SOS
    if any(w in t for w in ["emergency", "sos", "help me now", "danger now"]):
        return ("⚠️ If you're in immediate danger, call your local emergency number now. "
                "WayWise is a planning tool, not a live emergency service.")

    # Fallback
    return (
        "I'm not sure about that one. Try:\n"
        "• *Send feedback*\n"
        "• *Report a hazard*\n"
        "• *Help me find a location*\n"
        "• *Safety tips*\n\n"
        "Or type **help** to see the menu."
    )


def _llm_reply(text: str, ctx: dict):
    """Optional LLM path. Set WAYWISE_LLM_URL + WAYWISE_LLM_KEY to enable."""
    url = os.environ.get("WAYWISE_LLM_URL")
    key = os.environ.get("WAYWISE_LLM_KEY")
    if not url or not key:
        return None
    system = (
        "You are WayWise Assistant, a helpful safety-aware bot for students. "
        "You can take feedback and hazard reports; the frontend will send a "
        "finished payload when the user completes a flow. For free-form chat, "
        "answer in under 90 words and never invent hazard reports or routes."
    )
    context_lines = [f"User: {ctx.get('user_name') or 'guest'}"]
    if ctx.get("hazards"):
        context_lines.append("Recent hazards: " + "; ".join(h["type"] for h in ctx["hazards"][:5]))
    if ctx.get("places"):
        context_lines.append("Saved places: " + ", ".join(p["label"] for p in ctx["places"]))
    if ctx.get("history"):
        context_lines.append("Recent trips: " + "; ".join(
            f"{h['origin']}→{h['destination']}" for h in ctx["history"]))

    payload = json.dumps({
        "model": os.environ.get("WAYWISE_LLM_MODEL", "gpt-4o-mini"),
        "messages": [
            {"role": "system", "content": system},
            {"role": "system", "content": "Context:\n" + "\n".join(context_lines)},
            {"role": "user",   "content": text},
        ],
        "max_tokens": 220,
        "temperature": 0.6,
    }).encode()

    req = urllib.request.Request(url, data=payload, method="POST", headers={
        "Content-Type": "application/json",
        "Authorization": f"Bearer {key}",
    })
    try:
        with urllib.request.urlopen(req, timeout=12) as r:
            data = json.loads(r.read().decode())
        return data["choices"][0]["message"]["content"].strip()
    except Exception as e:
        print(f"[chat] LLM failed: {e}")
        return None


# ─────────────────────────────────────────────────────────────────────────────
# API
# ─────────────────────────────────────────────────────────────────────────────
@app.post("/api/chat")
def chat():
    """
    Body:
        { "message": "...", "flow": null | "feedback" | "hazard", "payload": {...} }

    If `flow` is set and `payload` contains the collected fields, the bot
    finalises the insert (feedback / hazard). Otherwise it's a free-form chat.
    """
    d = body() or {}
    flow = d.get("flow")
    payload = d.get("payload") or {}
    text = str(d.get("message", "")).strip()

    user = current_user()

    # Guided finishes
    if flow == "feedback":
        reply = _finish_feedback(payload, user)
        return jsonify({"reply": reply, "done": True, "flow": "feedback"})
    if flow == "hazard":
        reply = _finish_hazard(payload, user)
        return jsonify({"reply": reply, "done": True, "flow": "hazard"})

    # Free-form chat
    if not text:
        return err("Message can't be empty.")
    if len(text) > 500:
        return err("Message must be 500 characters or fewer.")

    ctx = _bot_context(user)
    reply = _llm_reply(text, ctx) or _rule_reply(text, ctx)
    return jsonify({"reply": reply, "source": "llm" if os.environ.get("WAYWISE_LLM_URL") else "rules"})


@app.get("/api/chat/schema")
def chat_schema():
    """Frontend uses this to build the guided-flow forms (dropdowns, etc.)."""
    return jsonify({
        "hazard_types": sorted(HAZARD_TYPES),
        "feedback_types": sorted(FEEDBACK_TYPES),
        "feedback_categories": ["Suggestion", "Bug report", "Route feedback", "Map feedback", "Other"],
    })