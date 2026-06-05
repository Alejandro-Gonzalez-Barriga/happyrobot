# HappyRobot — Inbound Carrier Sales Automation

End-to-end AI voice agent for freight brokerage inbound carrier load sales.  
Built for the HappyRobot FDE Technical Challenge.

---

## What This Is

A full-stack proof of concept that automates inbound calls from trucking carriers:

1. **Voice Agent** (HappyRobot platform) — greets carriers, verifies FMCSA compliance, searches loads, pitches details, negotiates pricing (up to 3 rounds), and books the load
2. **Backend API** (FastAPI/Python) — load data, FMCSA verification, negotiation engine, call logging
3. **Analytics Dashboard** (HTML/Nginx) — real-time metrics: booking rate, revenue, sentiment, outcomes, rate negotiation performance
4. **Docker Compose** — single-command local deployment

---

## Quick Start

```bash
git clone <your-repo-url>
cd happyrobot

# 1. Configure environment
cp .env.example .env
# Edit .env: set API_KEY and optionally FMCSA_API_KEY

# 2. Run everything
docker-compose up --build

# API:       http://localhost:8000
# Dashboard: http://localhost:3000
# API Docs:  http://localhost:8000/docs
```

---

## API Endpoints

All endpoints require `X-API-Key: <your-key>` header.

| Endpoint | Method | Description |
|---|---|---|
| `/health` | GET | Health check |
| `/verify-carrier/{mc_number}` | GET | FMCSA carrier verification |
| `/loads` | GET | Search loads (filter: origin, destination, equipment_type, load_id) |
| `/negotiate` | POST | Evaluate counter-offer for a load |
| `/calls` | POST | Log a completed call |
| `/calls` | GET | Retrieve call logs |
| `/metrics` | GET | Aggregated dashboard metrics |

Full interactive docs: `http://localhost:8000/docs`

---

## Environment Variables

| Variable | Required | Default | Description |
|---|---|---|---|
| `API_KEY` | Yes | `hr-secret-key-2026` | API authentication key |
| `FMCSA_API_KEY` | No | _(empty)_ | FMCSA web key — uses mock logic if blank |

---

## FMCSA Verification

- With a real key: calls `https://mobile.fmcsa.dot.gov/qc/services/carriers/{mc}`
- Without a key: mock logic rejects MC numbers containing `000BAD`, `INVALID`, `FAKE`, `000000`
- Get a free FMCSA key at: https://mobile.fmcsa.dot.gov/developer/home.page

---

## Negotiation Logic

| Carrier Offer | System Action |
|---|---|
| ≥ 95% of board rate | Accept — book the load |
| 85–94% of board rate | Counter at midpoint between offer and board rate |
| < 85% of board rate | Counter at 95% floor with urgency signal |
| Round 3 reached | Final decision — accept if ≥ 95%, else close |

---

## Dashboard

Open `http://localhost:3000` (or `dashboard/index.html` directly in a browser).

Enter the API URL and key, then click **Load**. The dashboard loads with demo data by default if the API is unreachable.

---

## Cloud Deployment (Railway / Fly.io / Render)

```bash
# Build and push image
docker build -t happyrobot-api .
docker tag happyrobot-api registry.railway.app/<your-project>/happyrobot-api:latest
docker push registry.railway.app/<your-project>/happyrobot-api:latest

# Set env vars in the cloud dashboard:
#   API_KEY=<strong-random-key>
#   FMCSA_API_KEY=<your-key>

# Deploy dashboard to Netlify/Vercel:
# Drag & drop the /dashboard folder, or connect the repo
```

For HTTPS in production, Railway/Render/Fly.io provide automatic TLS. No extra config needed.

---

## Project Structure

```
happyrobot/
├── app/
│   └── main.py              # FastAPI application
├── dashboard/
│   └── index.html           # Metrics dashboard
├── data/
│   ├── loads.json           # Load inventory
│   └── call_logs.json       # Persisted call records
├── Dockerfile
├── docker-compose.yml
├── requirements.txt
├── .env.example
└── README.md
```

---

## HappyRobot Agent Configuration

In the HappyRobot platform, configure the inbound workflow to call these API endpoints:

1. **Carrier Greeting** → collect name, company, MC number
2. **FMCSA Check** → `GET /verify-carrier/{mc_number}` — terminate call if `verified: false`
3. **Load Search** → `GET /loads?origin=...&equipment_type=...`
4. **Pitch Load** — present load details from the response
5. **Negotiation Loop** → `POST /negotiate?load_id=...` with carrier's counter-offer
6. **Book & Transfer** — mock transfer message on acceptance
7. **Log Call** → `POST /calls` with outcome, sentiment, extracted data

Use the web call trigger feature (no phone number purchase needed).
