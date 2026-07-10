╔══════════════════════════════════════════════════════╗
║  ReliefOps — Disaster Supply Distribution Planner   ║
║  B.Tech Project  |  Flask + SQLite Backend          ║
╚══════════════════════════════════════════════════════╝

PROJECT STRUCTURE
─────────────────
reliefops/
├── app.py                 ← Flask server + API + algorithm
├── requirements.txt       ← Python dependencies
├── README.txt             ← This file
├── reliefops.db           ← SQLite DB (auto-created on first run)
└── templates/
    └── index.html         ← Full frontend (HTML/CSS/JS)

SETUP — run these commands once
────────────────────────────────
  pip install -r requirements.txt

RUN
───
  python app.py
  Then open:  http://localhost:5000

API ENDPOINTS
─────────────
  POST   /api/run                → Run algorithm + save plan to DB
  GET    /api/history            → List all saved plans
  GET    /api/history/<id>       → Full detail of one plan
  DELETE /api/history/<id>       → Delete a plan permanently
  GET    /api/stats              → Aggregate statistics

DATASET FORMAT  (.txt file)
───────────────────────────
  One region per line, comma-separated, no header row:
  RegionName, Priority(1-5), Population, Water, Food, MedKits

  Example:
  Region_A, 5, 10000, 50, 40, 20
  Region_B, 3, 5000,  20, 20, 10
  Region_C, 1, 2000,  10, 10,  5
  Region_D, 4, 8000,  40, 35, 15

ALGORITHM
─────────
  Greedy allocation: Score = Priority × Population
  Regions are sorted descending by score and served in order.
  Partial allocations are made when inventory runs low.
