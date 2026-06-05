"""
HappyRobot — Inbound Carrier Sales API
Acme Logistics · v1
"""

from fastapi import FastAPI, HTTPException, Depends, Header, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import APIKeyHeader
from pydantic import BaseModel
from typing import Optional, List
import os
import uuid
import httpx
import aiosqlite
from datetime import datetime
from enum import Enum
from contextlib import asynccontextmanager

# ── Config ────────────────────────────────────────────────────────────────────
API_KEY      = os.getenv("API_KEY", "hr-secret-key-2026")
FMCSA_KEY    = os.getenv("FMCSA_API_KEY", "")
DB_PATH      = os.getenv("DB_PATH", "/app/data/happyrobot.db")

# ── DB Init ───────────────────────────────────────────────────────────────────
async def init_db():
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS loads (
                load_id         TEXT PRIMARY KEY,
                origin          TEXT NOT NULL,
                destination     TEXT NOT NULL,
                pickup_datetime TEXT NOT NULL,
                delivery_datetime TEXT NOT NULL,
                equipment_type  TEXT NOT NULL,
                loadboard_rate  REAL NOT NULL,
                notes           TEXT,
                weight          REAL,
                commodity_type  TEXT,
                num_of_pieces   INTEGER,
                miles           REAL,
                dimensions      TEXT
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS call_logs (
                call_id             TEXT PRIMARY KEY,
                timestamp           TEXT NOT NULL,
                carrier_mc          TEXT,
                carrier_name        TEXT,
                load_id             TEXT,
                origin              TEXT,
                destination         TEXT,
                equipment_type      TEXT,
                miles               REAL,
                initial_rate        REAL,
                final_agreed_rate   REAL,
                counter_offers      TEXT,
                negotiation_rounds  INTEGER DEFAULT 0,
                outcome             TEXT,
                sentiment           TEXT,
                fmcsa_verified      INTEGER DEFAULT 0,
                duration_seconds    INTEGER,
                highlights          TEXT
            )
        """)
        # Seed loads if empty
        cur = await db.execute("SELECT COUNT(*) FROM loads")
        row = await cur.fetchone()
        if row[0] == 0:
            await db.executemany("""
                INSERT INTO loads VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
            """, SEED_LOADS)
        # Seed demo call logs if empty
        cur2 = await db.execute("SELECT COUNT(*) FROM call_logs")
        row2 = await cur2.fetchone()
        if row2[0] == 0:
            await db.executemany("""
                INSERT INTO call_logs VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """, SEED_CALLS)
        await db.commit()

@asynccontextmanager
async def lifespan(app: FastAPI):
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    await init_db()
    yield

# ── App ───────────────────────────────────────────────────────────────────────
app = FastAPI(
    title="HappyRobot Carrier Sales API",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Auth ──────────────────────────────────────────────────────────────────────
api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)

async def require_api_key(x_api_key: str = Depends(api_key_header)):
    if x_api_key != API_KEY:
        raise HTTPException(status_code=401, detail="Invalid or missing API key")
    return x_api_key

# ── Helpers ───────────────────────────────────────────────────────────────────
def row_to_load(row):
    keys = ["load_id","origin","destination","pickup_datetime","delivery_datetime",
            "equipment_type","loadboard_rate","notes","weight","commodity_type",
            "num_of_pieces","miles","dimensions"]
    return dict(zip(keys, row))

def row_to_call(row):
    keys = ["call_id","timestamp","carrier_mc","carrier_name","load_id","origin",
            "destination","equipment_type","miles","initial_rate","final_agreed_rate",
            "counter_offers","negotiation_rounds","outcome","sentiment",
            "fmcsa_verified","duration_seconds","highlights"]
    d = dict(zip(keys, row))
    # Parse stored comma-separated counter offers back to list
    co = d.get("counter_offers") or ""
    d["counter_offers"] = [float(x) for x in co.split(",") if x] if co else []
    d["fmcsa_verified"] = bool(d["fmcsa_verified"])
    return d

# ── Seed Data ─────────────────────────────────────────────────────────────────
SEED_LOADS = [
    ("LD-1001","Chicago, IL","Dallas, TX","2026-06-06T08:00:00","2026-06-07T18:00:00","Dry Van",2850.00,"No touch freight. Dock to dock.",42000,"General Merchandise",24,921,"48x102x96"),
    ("LD-1002","Los Angeles, CA","Phoenix, AZ","2026-06-07T07:00:00","2026-06-07T20:00:00","Reefer",1400.00,"Temperature: 34F. Produce load.",38000,"Produce",18,372,"48x102x96"),
    ("LD-1003","Atlanta, GA","Miami, FL","2026-06-06T10:00:00","2026-06-07T09:00:00","Flatbed",1950.00,"Tarps required. Steel coils.",44000,"Steel Coils",6,662,"48x102"),
    ("LD-1004","Houston, TX","Memphis, TN","2026-06-08T06:00:00","2026-06-09T14:00:00","Dry Van",1750.00,"Palletized. Team driver preferred.",36000,"Auto Parts",32,565,"48x102x96"),
    ("LD-1005","Seattle, WA","Denver, CO","2026-06-09T09:00:00","2026-06-10T17:00:00","Dry Van",3200.00,"Fragile electronics. Liftgate required.",28000,"Electronics",48,1321,"48x102x96"),
    ("LD-1006","Nashville, TN","Columbus, OH","2026-06-07T12:00:00","2026-06-08T08:00:00","Dry Van",1100.00,"Floor loaded. Residential delivery.",18000,"Furniture",15,330,"48x102x96"),
    ("LD-1007","Kansas City, MO","Minneapolis, MN","2026-06-10T07:00:00","2026-06-10T22:00:00","Reefer",1650.00,"Frozen food. Keep at -10F.",40000,"Frozen Food",22,440,"48x102x96"),
]

SEED_CALLS = [
    ("CALL-0001","2026-06-01T09:14:22","MC123456","Swift Transport LLC","LD-1001","Chicago, IL","Dallas, TX","Dry Van",921,2850.00,2950.00,"2650,2800,2950",3,"BOOKED","POSITIVE",1,187,"Carrier negotiated up from $2,650. Agreed at $2,950 after 3 rounds."),
    ("CALL-0002","2026-06-01T10:32:11","MC789012","Lone Star Freight","LD-1002","Los Angeles, CA","Phoenix, AZ","Reefer",372,1400.00,None,"1200,1100",2,"CARRIER_DECLINED","NEGATIVE",1,134,"Carrier kept pushing below floor rate. Call ended without deal."),
    ("CALL-0003","2026-06-01T11:05:44","MC000BAD","Unknown Carrier",None,None,None,None,None,None,None,"",0,"FMCSA_REJECTED","NEUTRAL",0,45,"MC number returned inactive status on FMCSA check. Call terminated."),
    ("CALL-0004","2026-06-02T08:22:09","MC345678","Mountain Pass Logistics","LD-1005","Seattle, WA","Denver, CO","Dry Van",1321,3200.00,3200.00,"",0,"BOOKED","POSITIVE",1,95,"Carrier accepted board rate immediately. No negotiation needed."),
    ("CALL-0005","2026-06-02T13:47:30","MC901234","Coastal Carriers Inc","LD-1003","Atlanta, GA","Miami, FL","Flatbed",662,1950.00,2050.00,"1800,2050",2,"BOOKED","POSITIVE",1,162,"Carrier countered at $1,800. Met in middle at $2,050."),
    ("CALL-0006","2026-06-03T09:10:05","MC567890","Heartland Haulers","LD-1004","Houston, TX","Memphis, TN","Dry Van",565,1750.00,None,"1500,1400,1350",3,"NO_DEAL","NEGATIVE",1,210,"3-round cap hit. Carrier never came close to floor rate."),
    ("CALL-0007","2026-06-03T14:55:18","MC112233","Midwest Express","LD-1006","Nashville, TN","Columbus, OH","Dry Van",330,1100.00,1150.00,"1050,1150",2,"BOOKED","NEUTRAL",1,143,"Standard negotiation. Closed $50 above board rate."),
    ("CALL-0008","2026-06-04T07:30:00","MC445566","Arctic Reefer Co","LD-1007","Kansas City, MO","Minneapolis, MN","Reefer",440,1650.00,1700.00,"1550,1700",2,"BOOKED","POSITIVE",1,155,"Carrier familiar with lane. Quick close at $1,700."),
]

# ═════════════════════════════════════════════════════════════════════════════
# ROUTES
# ═════════════════════════════════════════════════════════════════════════════

@app.get("/health")
async def health():
    return {"status": "ok", "timestamp": datetime.utcnow().isoformat()}


# ── Carrier Verification ──────────────────────────────────────────────────────
class VerifyRequest(BaseModel):
    mc_number: str

@app.post("/api/v1/carrier/verify", dependencies=[Depends(require_api_key)])
async def verify_carrier(body: VerifyRequest):
    """Verify carrier FMCSA eligibility by MC number."""
    mc_clean = body.mc_number.upper().replace("MC", "").strip()

    if FMCSA_KEY:
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                url = f"https://mobile.fmcsa.dot.gov/qc/services/carriers/{mc_clean}?webKey={FMCSA_KEY}"
                resp = await client.get(url)
                if resp.status_code == 200:
                    data = resp.json()
                    carrier = data.get("content", {}).get("carrier", {})
                    allowed = carrier.get("allowedToOperate", "N")
                    return {
                        "mc_number": body.mc_number,
                        "verified": allowed == "Y",
                        "carrier_name": carrier.get("legalName", "Unknown"),
                        "dot_number": carrier.get("dotNumber"),
                        "operating_status": carrier.get("carrierOperation", {}).get("carrierOperationDesc"),
                        "source": "FMCSA_LIVE",
                    }
        except Exception:
            pass  # fall through to mock

    # Mock: reject obvious bad MCs
    bad = any(p in mc_clean.upper() for p in ["000BAD", "INVALID", "FAKE", "000000"])
    return {
        "mc_number": body.mc_number,
        "verified": not bad,
        "carrier_name": "Carrier (Mock)" if not bad else "UNVERIFIED",
        "dot_number": f"DOT-{mc_clean}" if not bad else None,
        "operating_status": "AUTHORIZED FOR HIRE" if not bad else "NOT AUTHORIZED",
        "source": "MOCK",
    }


# ── Load Search ───────────────────────────────────────────────────────────────
class LoadSearchRequest(BaseModel):
    origin: Optional[str] = None
    destination: Optional[str] = None
    equipment_type: Optional[str] = None
    load_id: Optional[str] = None

@app.post("/api/v1/loads/search", dependencies=[Depends(require_api_key)])
async def search_loads(body: LoadSearchRequest):
    """Search available loads by criteria."""
    query = "SELECT * FROM loads WHERE 1=1"
    params = []

    if body.load_id:
        query += " AND load_id = ?"
        params.append(body.load_id)
    if body.origin:
        query += " AND LOWER(origin) LIKE ?"
        params.append(f"%{body.origin.lower()}%")
    if body.destination:
        query += " AND LOWER(destination) LIKE ?"
        params.append(f"%{body.destination.lower()}%")
    if body.equipment_type:
        query += " AND LOWER(equipment_type) LIKE ?"
        params.append(f"%{body.equipment_type.lower()}%")

    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(query, params)
        rows = await cur.fetchall()

    loads = [row_to_load(r) for r in rows]
    return {"loads": loads, "count": len(loads)}


# ── Negotiation ───────────────────────────────────────────────────────────────
class NegotiateRequest(BaseModel):
    load_id: str
    carrier_offer: float
    round_number: int  # 1, 2, or 3

@app.post("/api/v1/negotiate", dependencies=[Depends(require_api_key)])
async def negotiate(body: NegotiateRequest):
    """
    Evaluate a carrier counter-offer.
    Rules:
      >= 95% of board rate  → Accept
      85–94%                → Counter (split the difference)
      < 85%                 → Counter at 95% floor
      Round 3 cap           → Final decision, no more counters
    """
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute("SELECT loadboard_rate FROM loads WHERE load_id = ?", (body.load_id,))
        row = await cur.fetchone()

    if not row:
        raise HTTPException(status_code=404, detail=f"Load {body.load_id} not found")

    board_rate = row[0]
    offered    = body.carrier_offer
    ratio      = offered / board_rate
    floor      = round(board_rate * 0.95, 2)

    # Round 3 is final — accept or walk
    if body.round_number >= 3:
        if ratio >= 0.95:
            return {"accepted": True, "agreed_rate": offered, "round": body.round_number,
                    "message": f"Deal. We'll lock in ${offered:,.2f}. Transferring you to our sales rep now — hang tight.",
                    "final": True}
        return {"accepted": False, "agreed_rate": None, "round": body.round_number,
                "message": f"We've hit our limit on this one. Our floor is ${floor:,.2f} and we can't go below that. We'll have to pass this time.",
                "final": True}

    if ratio >= 0.95:
        return {"accepted": True, "agreed_rate": offered, "round": body.round_number,
                "message": f"You've got a deal at ${offered:,.2f}. Transferring you to our sales rep now — hang tight.",
                "final": True}
    elif ratio >= 0.85:
        counter = round((offered + board_rate) / 2, 2)
        return {"accepted": False, "counter_rate": counter, "round": body.round_number,
                "message": f"I hear you, but I can't go that low. How about we meet in the middle at ${counter:,.2f}?",
                "final": False}
    else:
        return {"accepted": False, "counter_rate": floor, "round": body.round_number,
                "message": f"That's quite a bit below what we need. The absolute best I can do is ${floor:,.2f} — does that work?",
                "final": False}


# ── Call Webhook ──────────────────────────────────────────────────────────────
class CallWebhookRequest(BaseModel):
    carrier_mc: str
    carrier_name: Optional[str] = None
    load_id: Optional[str] = None
    origin: Optional[str] = None
    destination: Optional[str] = None
    equipment_type: Optional[str] = None
    miles: Optional[float] = None
    initial_rate: Optional[float] = None
    final_agreed_rate: Optional[float] = None
    counter_offers: List[float] = []
    negotiation_rounds: int = 0
    outcome: str  # BOOKED | NO_DEAL | CARRIER_DECLINED | FMCSA_REJECTED | ABANDONED
    sentiment: str  # POSITIVE | NEUTRAL | NEGATIVE
    fmcsa_verified: bool = False
    duration_seconds: Optional[int] = None
    highlights: Optional[str] = None

@app.post("/api/v1/calls/webhook", dependencies=[Depends(require_api_key)])
async def call_webhook(body: CallWebhookRequest):
    """Post-call webhook — HappyRobot hits this when a call ends."""
    call_id = f"CALL-{str(uuid.uuid4())[:8].upper()}"
    timestamp = datetime.utcnow().isoformat()
    counter_str = ",".join(str(x) for x in body.counter_offers)

    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            INSERT INTO call_logs VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """, (
            call_id, timestamp, body.carrier_mc, body.carrier_name,
            body.load_id, body.origin, body.destination, body.equipment_type,
            body.miles, body.initial_rate, body.final_agreed_rate,
            counter_str, body.negotiation_rounds,
            body.outcome, body.sentiment,
            int(body.fmcsa_verified), body.duration_seconds, body.highlights
        ))
        await db.commit()

    return {"call_id": call_id, "status": "logged", "timestamp": timestamp}


# ── Call Log Read ─────────────────────────────────────────────────────────────
@app.get("/api/v1/calls", dependencies=[Depends(require_api_key)])
async def get_calls(
    outcome:    Optional[str] = None,
    sentiment:  Optional[str] = None,
    carrier_mc: Optional[str] = None,
    limit:      int = 100,
):
    query = "SELECT * FROM call_logs WHERE 1=1"
    params = []
    if outcome:    query += " AND outcome = ?";    params.append(outcome.upper())
    if sentiment:  query += " AND sentiment = ?";  params.append(sentiment.upper())
    if carrier_mc: query += " AND carrier_mc = ?"; params.append(carrier_mc)
    query += " ORDER BY timestamp DESC LIMIT ?"
    params.append(limit)

    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(query, params)
        rows = await cur.fetchall()

    return {"calls": [row_to_call(r) for r in rows], "count": len(rows)}


# ── Metrics ───────────────────────────────────────────────────────────────────
@app.get("/api/v1/metrics", dependencies=[Depends(require_api_key)])
async def get_metrics():
    """All aggregated metrics for the dashboard — single endpoint."""
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute("SELECT * FROM call_logs ORDER BY timestamp DESC")
        rows = await cur.fetchall()

    calls = [row_to_call(r) for r in rows]
    total = len(calls)
    if total == 0:
        return {"total_calls": 0}

    booked   = [c for c in calls if c["outcome"] == "BOOKED"]
    no_deal  = [c for c in calls if c["outcome"] == "NO_DEAL"]
    declined = [c for c in calls if c["outcome"] == "CARRIER_DECLINED"]
    rejected = [c for c in calls if c["outcome"] == "FMCSA_REJECTED"]

    booked_rates = [c["final_agreed_rate"] for c in booked if c["final_agreed_rate"]]
    board_rates  = [c["initial_rate"]      for c in booked if c["initial_rate"]]
    durations    = [c["duration_seconds"]  for c in calls  if c["duration_seconds"]]
    neg_rounds   = [c["negotiation_rounds"]for c in calls]

    # Rate delta (agreed vs board) for booked calls
    deltas = []
    for c in booked:
        if c["final_agreed_rate"] and c["initial_rate"]:
            deltas.append(c["final_agreed_rate"] - c["initial_rate"])
    avg_delta = round(sum(deltas) / len(deltas), 2) if deltas else 0

    # Revenue
    total_revenue = sum(booked_rates)

    # Rate per mile
    rpm_vals = []
    for c in booked:
        if c["final_agreed_rate"] and c["miles"]:
            rpm_vals.append(c["final_agreed_rate"] / c["miles"])
    avg_rpm = round(sum(rpm_vals) / len(rpm_vals), 4) if rpm_vals else 0

    # Breakdowns
    def breakdown(key, items=calls):
        d = {}
        for c in items:
            v = c.get(key) or "Unknown"
            d[v] = d.get(v, 0) + 1
        return d

    # Sentiment vs booking
    sent_booked = {}
    for c in booked:
        s = c["sentiment"] or "UNKNOWN"
        sent_booked[s] = sent_booked.get(s, 0) + 1

    # Funnel: where carriers drop off
    funnel = {
        "Inbound Calls":        total,
        "FMCSA Verified":       total - len(rejected),
        "Load Matched & Pitched": total - len(rejected) - sum(1 for c in calls if c["outcome"] == "NO_LOAD"),
        "Entered Negotiation":  len([c for c in calls if c["negotiation_rounds"] > 0 or c["outcome"] == "BOOKED"]),
        "Booked":               len(booked),
    }

    return {
        "total_calls":             total,
        "booked":                  len(booked),
        "no_deal":                 len(no_deal),
        "carrier_declined":        len(declined),
        "fmcsa_rejected":          len(rejected),
        "booking_rate_pct":        round(len(booked) / total * 100, 1),
        "total_revenue_booked":    round(total_revenue, 2),
        "avg_agreed_rate":         round(sum(booked_rates)/len(booked_rates), 2) if booked_rates else 0,
        "avg_rate_delta":          avg_delta,
        "avg_call_duration_sec":   round(sum(durations)/len(durations), 1) if durations else 0,
        "avg_negotiation_rounds":  round(sum(neg_rounds)/len(neg_rounds), 2),
        "avg_rate_per_mile":       avg_rpm,
        "sentiment_breakdown":     breakdown("sentiment"),
        "outcome_breakdown":       breakdown("outcome"),
        "equipment_breakdown":     breakdown("equipment_type"),
        "sentiment_vs_booked":     sent_booked,
        "funnel":                  funnel,
        "calls":                   calls,
    }