"""
HappyRobot Inbound Carrier Sales API
Freight brokerage AI automation backend
"""

from fastapi import FastAPI, HTTPException, Depends, Header, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import APIKeyHeader
from pydantic import BaseModel
from typing import Optional, List
import json
import os
import uuid
import httpx
from datetime import datetime
from enum import Enum

# ── Config ─────────────────────────────────────────────────────────────────────
API_KEY = os.getenv("API_KEY", "hr-secret-key-2026")
DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "data")
FMCSA_API_KEY = os.getenv("FMCSA_API_KEY", "")   # real key injected via env

app = FastAPI(
    title="HappyRobot Carrier Sales API",
    description="Inbound carrier load sales automation for freight brokerages",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Auth ────────────────────────────────────────────────────────────────────────
api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)

async def require_api_key(x_api_key: str = Depends(api_key_header)):
    if x_api_key != API_KEY:
        raise HTTPException(status_code=401, detail="Invalid or missing API key")
    return x_api_key

# ── Helpers ─────────────────────────────────────────────────────────────────────
def load_json(filename: str):
    path = os.path.join(DATA_DIR, filename)
    with open(path, "r") as f:
        return json.load(f)

def save_json(filename: str, data):
    path = os.path.join(DATA_DIR, filename)
    with open(path, "w") as f:
        json.dump(data, f, indent=2)

# ── Enums ────────────────────────────────────────────────────────────────────────
class CallOutcome(str, Enum):
    BOOKED = "BOOKED"
    NO_DEAL = "NO_DEAL"
    CARRIER_DECLINED = "CARRIER_DECLINED"
    FMCSA_REJECTED = "FMCSA_REJECTED"
    TRANSFERRED = "TRANSFERRED"
    ABANDONED = "ABANDONED"

class Sentiment(str, Enum):
    POSITIVE = "POSITIVE"
    NEUTRAL = "NEUTRAL"
    NEGATIVE = "NEGATIVE"

# ── Pydantic Models ──────────────────────────────────────────────────────────────
class CounterOffer(BaseModel):
    offered_rate: float
    round_number: int  # 1, 2, or 3

class NegotiationResult(BaseModel):
    accepted: bool
    counter_rate: Optional[float] = None
    message: str
    max_rounds_reached: bool = False

class CallLog(BaseModel):
    mc_number: str
    carrier_name: str
    load_id: Optional[str] = None
    origin: Optional[str] = None
    destination: Optional[str] = None
    initial_rate: Optional[float] = None
    final_agreed_rate: Optional[float] = None
    counter_offers: List[float] = []
    num_negotiations: int = 0
    outcome: CallOutcome
    sentiment: Sentiment
    fmcsa_verified: bool
    duration_seconds: Optional[int] = None
    equipment_type: Optional[str] = None
    miles: Optional[float] = None

# ── Routes ───────────────────────────────────────────────────────────────────────

@app.get("/health")
async def health():
    return {"status": "ok", "timestamp": datetime.utcnow().isoformat()}


# ── FMCSA Verification ───────────────────────────────────────────────────────────
@app.get("/verify-carrier/{mc_number}", dependencies=[Depends(require_api_key)])
async def verify_carrier(mc_number: str):
    """
    Verify carrier eligibility via FMCSA API.
    Falls back to mock logic if no API key configured.
    """
    mc_clean = mc_number.upper().replace("MC", "").strip()

    if FMCSA_API_KEY:
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                url = (
                    f"https://mobile.fmcsa.dot.gov/qc/services/carriers/{mc_clean}"
                    f"?webKey={FMCSA_API_KEY}"
                )
                resp = await client.get(url)
                if resp.status_code == 200:
                    data = resp.json()
                    carrier = data.get("content", {}).get("carrier", {})
                    allowed_to_operate = carrier.get("allowedToOperate", "N")
                    return {
                        "mc_number": mc_number,
                        "verified": allowed_to_operate == "Y",
                        "carrier_name": carrier.get("legalName", "Unknown"),
                        "dot_number": carrier.get("dotNumber"),
                        "operating_status": carrier.get("carrierOperation", {}).get("carrierOperationDesc"),
                        "source": "FMCSA",
                    }
        except Exception as e:
            pass  # fall through to mock

    # Mock fallback: reject obviously bad MC numbers, accept the rest
    bad_patterns = ["000BAD", "INVALID", "FAKE", "000000"]
    is_bad = any(p in mc_clean.upper() for p in bad_patterns)

    return {
        "mc_number": mc_number,
        "verified": not is_bad,
        "carrier_name": "Carrier (Mock)" if not is_bad else "UNVERIFIED",
        "dot_number": f"DOT-{mc_clean}" if not is_bad else None,
        "operating_status": "AUTHORIZED FOR HIRE" if not is_bad else "NOT AUTHORIZED",
        "source": "MOCK",
    }


# ── Load Search ──────────────────────────────────────────────────────────────────
@app.get("/loads", dependencies=[Depends(require_api_key)])
async def search_loads(
    origin: Optional[str] = Query(None, description="Filter by origin city/state"),
    destination: Optional[str] = Query(None, description="Filter by destination city/state"),
    equipment_type: Optional[str] = Query(None, description="Filter by equipment type"),
    load_id: Optional[str] = Query(None, description="Get specific load by ID"),
):
    """Search available loads. Supports filtering by origin, destination, equipment type."""
    loads = load_json("loads.json")

    if load_id:
        match = next((l for l in loads if l["load_id"] == load_id), None)
        if not match:
            raise HTTPException(status_code=404, detail=f"Load {load_id} not found")
        return match

    if origin:
        loads = [l for l in loads if origin.lower() in l["origin"].lower()]
    if destination:
        loads = [l for l in loads if destination.lower() in l["destination"].lower()]
    if equipment_type:
        loads = [l for l in loads if equipment_type.lower() in l["equipment_type"].lower()]

    return {"loads": loads, "count": len(loads)}


# ── Negotiation Engine ────────────────────────────────────────────────────────────
@app.post("/negotiate", dependencies=[Depends(require_api_key)])
async def evaluate_counter_offer(offer: CounterOffer, load_id: str = Query(...)):
    """
    Evaluate a carrier's counter offer for a load.
    Rules:
      - Accept if carrier offers >= 95% of loadboard rate
      - Counter back if carrier offers 85–95% (split difference)
      - Reject (no deal) after 3 rounds or if offer < 85%
    """
    loads = load_json("loads.json")
    load = next((l for l in loads if l["load_id"] == load_id), None)
    if not load:
        raise HTTPException(status_code=404, detail="Load not found")

    board_rate = load["loadboard_rate"]
    offered = offer.offered_rate
    ratio = offered / board_rate

    if offer.round_number >= 3:
        if ratio >= 0.95:
            return NegotiationResult(
                accepted=True,
                message=f"Deal accepted at ${offered:,.2f}. Transferring to sales rep now.",
                max_rounds_reached=True,
            )
        return NegotiationResult(
            accepted=False,
            message=(
                f"We've reached our negotiation limit. "
                f"Our minimum is ${board_rate * 0.95:,.2f}. We're unable to proceed below that."
            ),
            max_rounds_reached=True,
        )

    if ratio >= 0.95:
        return NegotiationResult(
            accepted=True,
            message=f"Great, we have a deal at ${offered:,.2f}! Transferring to sales rep.",
        )
    elif ratio >= 0.85:
        counter = round((offered + board_rate) / 2, 2)
        return NegotiationResult(
            accepted=False,
            counter_rate=counter,
            message=(
                f"That's a bit below what we can do. "
                f"We can meet you at ${counter:,.2f} — does that work for you?"
            ),
        )
    else:
        return NegotiationResult(
            accepted=False,
            counter_rate=board_rate * 0.95,
            message=(
                f"We're too far apart at ${offered:,.2f}. "
                f"The best we can do is ${board_rate * 0.95:,.2f}. Can you work with that?"
            ),
        )


# ── Call Logging ─────────────────────────────────────────────────────────────────
@app.post("/calls", dependencies=[Depends(require_api_key)])
async def log_call(call: CallLog):
    """Log a completed call with outcome classification and sentiment."""
    logs = load_json("call_logs.json")
    record = call.dict()
    record["call_id"] = f"CALL-{str(uuid.uuid4())[:8].upper()}"
    record["timestamp"] = datetime.utcnow().isoformat()
    logs.append(record)
    save_json("call_logs.json", logs)
    return {"call_id": record["call_id"], "status": "logged"}


@app.get("/calls", dependencies=[Depends(require_api_key)])
async def get_calls(
    outcome: Optional[str] = None,
    sentiment: Optional[str] = None,
    mc_number: Optional[str] = None,
):
    """Retrieve call logs with optional filters."""
    logs = load_json("call_logs.json")
    if outcome:
        logs = [c for c in logs if c.get("outcome") == outcome.upper()]
    if sentiment:
        logs = [c for c in logs if c.get("sentiment") == sentiment.upper()]
    if mc_number:
        logs = [c for c in logs if c.get("mc_number") == mc_number]
    return {"calls": logs, "count": len(logs)}


# ── Metrics ──────────────────────────────────────────────────────────────────────
@app.get("/metrics", dependencies=[Depends(require_api_key)])
async def get_metrics():
    """Aggregate metrics for the dashboard."""
    logs = load_json("call_logs.json")

    total = len(logs)
    if total == 0:
        return {"total_calls": 0}

    booked = [c for c in logs if c.get("outcome") == "BOOKED"]
    no_deal = [c for c in logs if c.get("outcome") == "NO_DEAL"]
    declined = [c for c in logs if c.get("outcome") == "CARRIER_DECLINED"]
    rejected = [c for c in logs if c.get("outcome") == "FMCSA_REJECTED"]

    booked_rates = [c["final_agreed_rate"] for c in booked if c.get("final_agreed_rate")]
    board_rates = [c["initial_rate"] for c in booked if c.get("initial_rate")]
    durations = [c["duration_seconds"] for c in logs if c.get("duration_seconds")]

    rate_delta = 0.0
    if booked_rates and board_rates and len(booked_rates) == len(board_rates):
        deltas = [a - b for a, b in zip(booked_rates, board_rates)]
        rate_delta = sum(deltas) / len(deltas)

    sentiment_counts = {"POSITIVE": 0, "NEUTRAL": 0, "NEGATIVE": 0}
    for c in logs:
        s = c.get("sentiment", "NEUTRAL")
        sentiment_counts[s] = sentiment_counts.get(s, 0) + 1

    outcome_counts = {}
    for c in logs:
        o = c.get("outcome", "UNKNOWN")
        outcome_counts[o] = outcome_counts.get(o, 0) + 1

    negotiation_rounds = [c.get("num_negotiations", 0) for c in logs]

    equipment_breakdown = {}
    for c in logs:
        eq = c.get("equipment_type") or "Unknown"
        equipment_breakdown[eq] = equipment_breakdown.get(eq, 0) + 1

    # Revenue: sum of agreed rates on booked loads
    total_revenue = sum(booked_rates)

    # Rate per mile
    rpm_list = []
    for c in booked:
        rate = c.get("final_agreed_rate")
        miles = c.get("miles")
        if rate and miles:
            rpm_list.append(rate / miles)

    avg_rpm = sum(rpm_list) / len(rpm_list) if rpm_list else 0

    return {
        "total_calls": total,
        "booked": len(booked),
        "booking_rate_pct": round(len(booked) / total * 100, 1),
        "no_deal": len(no_deal),
        "carrier_declined": len(declined),
        "fmcsa_rejected": len(rejected),
        "total_revenue_booked": round(total_revenue, 2),
        "avg_agreed_rate": round(sum(booked_rates) / len(booked_rates), 2) if booked_rates else 0,
        "avg_rate_delta": round(rate_delta, 2),
        "avg_call_duration_sec": round(sum(durations) / len(durations), 1) if durations else 0,
        "avg_negotiation_rounds": round(sum(negotiation_rounds) / len(negotiation_rounds), 2),
        "avg_rate_per_mile": round(avg_rpm, 4),
        "sentiment_breakdown": sentiment_counts,
        "outcome_breakdown": outcome_counts,
        "equipment_breakdown": equipment_breakdown,
        "calls": logs,  # include raw calls for timeline
    }
