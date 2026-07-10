# =============================================================
#  ReliefOps — Flask Backend
#  Disaster Supply Distribution Planner
#  B.Tech Project
#
#  Run:  python app.py
#  URL:  http://localhost:5000
# =============================================================

from flask import Flask, request, jsonify, render_template
from flask_sqlalchemy import SQLAlchemy
from datetime import datetime
import os
import random

# ── App & DB setup ────────────────────────────────────────────
app = Flask(__name__)
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///reliefops.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['SECRET_KEY'] = 'reliefops-secret-2024'

db = SQLAlchemy(app)


# =============================================================
#  DATABASE MODELS
# =============================================================

class DistributionPlan(db.Model):
    """
    One record per run of the distribution algorithm.
    Stores the inventory snapshot and links to per-region results.
    """
    __tablename__ = 'distribution_plan'

    id           = db.Column(db.Integer, primary_key=True)
    created_at   = db.Column(db.DateTime, default=datetime.utcnow)
    label        = db.Column(db.String(120), default='')   # optional user label
    water_total  = db.Column(db.Integer, nullable=False)
    food_total   = db.Column(db.Integer, nullable=False)
    med_total    = db.Column(db.Integer, nullable=False)
    water_used   = db.Column(db.Integer, default=0)
    food_used    = db.Column(db.Integer, default=0)
    med_used     = db.Column(db.Integer, default=0)

    # Relationship: one plan → many region results
    regions = db.relationship(
        'RegionResult',
        backref='plan',
        lazy=True,
        cascade='all, delete-orphan'
    )

    def summary(self):
        """Returns a lightweight dict for the history list."""
        return {
            'id':           self.id,
            'created_at':   self.created_at.strftime('%d %b %Y, %H:%M'),
            'label':        self.label,
            'inventory': {
                'water': self.water_total,
                'food':  self.food_total,
                'med':   self.med_total,
            },
            'used': {
                'water': self.water_used,
                'food':  self.food_used,
                'med':   self.med_used,
            },
            'region_count': len(self.regions),
            'satisfied':    sum(1 for r in self.regions if r.status == 'full'),
            'partial':      sum(1 for r in self.regions if r.status == 'partial'),
            'unsatisfied':  sum(1 for r in self.regions if r.status == 'none'),
        }


class RegionResult(db.Model):
    """
    One record per region in a distribution plan.
    Stores both what was requested and what was allocated.
    """
    __tablename__ = 'region_result'

    id          = db.Column(db.Integer, primary_key=True)
    plan_id     = db.Column(db.Integer,
                            db.ForeignKey('distribution_plan.id'),
                            nullable=False)
    rank        = db.Column(db.Integer)
    name        = db.Column(db.String(120), nullable=False)
    priority    = db.Column(db.Integer)
    population  = db.Column(db.Integer)
    score       = db.Column(db.Integer)

    # Requested quantities
    req_water   = db.Column(db.Integer)
    req_food    = db.Column(db.Integer)
    req_med     = db.Column(db.Integer)

    # Allocated quantities
    alloc_water = db.Column(db.Integer)
    alloc_food  = db.Column(db.Integer)
    alloc_med   = db.Column(db.Integer)

    # full | partial | none
    status      = db.Column(db.String(20))

    def to_dict(self):
        return {
            'rank':       self.rank,
            'name':       self.name,
            'priority':   self.priority,
            'population': self.population,
            'score':      self.score,
            'water':      self.req_water,
            'food':       self.req_food,
            'med':        self.req_med,
            'allocWater': self.alloc_water,
            'allocFood':  self.alloc_food,
            'allocMed':   self.alloc_med,
            'status':     self.status,
        }


# =============================================================
#  IMPROVED GREEDY ALLOCATION ALGORITHM  
#  Score = (Priority × Population) / Total Resources Requested
# =============================================================

def greedy_allocate(regions, inv):
    for r in regions:
        # 1. Calculate the "Value" (Impact)
        impact = r['priority'] * r['population']
        
        # 2. Calculate the "Weight" (Total resources requested)
        total_requested = r['water'] + r['food'] + r['med']
        
        # 3. Calculate the precise Ratio (Score)
        if total_requested == 0:
            r['score'] = 0  # Prevent division by zero
        else:
            # We round it to 2 decimal places so it looks clean in your frontend table
            r['score'] = round(impact / total_requested, 2)

    # Sort descending by the new ratio score
    regions.sort(key=lambda r: (-r['score'], -r['priority'], r['name']))

    rem = {
        'water': inv['water'],
        'food':  inv['food'],
        'med':   inv['med'],
    }

    results = []
    for idx, r in enumerate(regions):
        gw = min(r['water'], rem['water'])
        gf = min(r['food'],  rem['food'])
        gm = min(r['med'],   rem['med'])

        rem['water'] -= gw
        rem['food']  -= gf
        rem['med']   -= gm

        fully_met     = (gw == r['water'] and gf == r['food'] and gm == r['med'])
        nothing_given = (gw == 0 and gf == 0 and gm == 0)
        status = 'full' if fully_met else ('none' if nothing_given else 'partial')

        results.append({
            **r,
            'rank':       idx + 1,
            'allocWater': gw,
            'allocFood':  gf,
            'allocMed':   gm,
            'status':     status,
        })

    return results


# =============================================================
#  ROUTES — Pages
# =============================================================

@app.route('/')
def index():
    """Serve the main single-page frontend."""
    return render_template('index.html')


# =============================================================
#  ROUTES — API  (JSON in / JSON out)
# =============================================================

@app.route('/api/run', methods=['POST'])
def api_run():
    """
    POST /api/run
    Body (JSON):
    {
        "label":   "Operation Flood Relief",   // optional
        "water":   100,
        "food":    80,
        "med":     40,
        "regions": [
            { "name": "Region_A", "priority": 5, "population": 10000,
              "water": 50, "food": 40, "med": 20 },
            ...
        ]
    }

    Response (JSON):
    {
        "plan_id": 3,
        "results": [ ... ]
    }
    """
    data = request.get_json(silent=True)
    if not data:
        return jsonify({'error': 'Invalid JSON body'}), 400

    # ── Validate inventory ────────────────────────────────────
    try:
        inv = {
            'water': int(data['water']),
            'food':  int(data['food']),
            'med':   int(data['med']),
        }
    except (KeyError, ValueError, TypeError):
        return jsonify({'error': 'Missing or invalid inventory fields (water, food, med)'}), 400

    if any(v < 0 for v in inv.values()):
        return jsonify({'error': 'Inventory values must be non-negative'}), 400

    if all(v == 0 for v in inv.values()):
        return jsonify({'error': 'All inventory values are 0 — nothing to distribute'}), 400

    # ── Validate regions ──────────────────────────────────────
    raw_regions = data.get('regions', [])
    if not raw_regions or not isinstance(raw_regions, list):
        return jsonify({'error': 'No region data provided'}), 400

    regions = []
    for i, r in enumerate(raw_regions):
        try:
            regions.append({
                'name':       str(r['name']).strip(),
                'priority':   int(r['priority']),
                'population': int(r['population']),
                'water':      int(r['water']),
                'food':       int(r['food']),
                'med':        int(r['med']),
            })
        except (KeyError, ValueError, TypeError):
            return jsonify({'error': f'Invalid data in region row {i+1}'}), 400

    # ── Run algorithm ─────────────────────────────────────────
    results = greedy_allocate(regions, inv)

    # ── Calculate totals used ─────────────────────────────────
    water_used = sum(r['allocWater'] for r in results)
    food_used  = sum(r['allocFood']  for r in results)
    med_used   = sum(r['allocMed']   for r in results)

    # ── Persist to database ───────────────────────────────────
    plan = DistributionPlan(
        label       = str(data.get('label', '')).strip(),
        water_total = inv['water'],
        food_total  = inv['food'],
        med_total   = inv['med'],
        water_used  = water_used,
        food_used   = food_used,
        med_used    = med_used,
    )
    db.session.add(plan)
    db.session.flush()   # assigns plan.id before commit

    for r in results:
        db.session.add(RegionResult(
            plan_id     = plan.id,
            rank        = r['rank'],
            name        = r['name'],
            priority    = r['priority'],
            population  = r['population'],
            score       = r['score'],
            req_water   = r['water'],
            req_food    = r['food'],
            req_med     = r['med'],
            alloc_water = r['allocWater'],
            alloc_food  = r['allocFood'],
            alloc_med   = r['allocMed'],
            status      = r['status'],
        ))

    db.session.commit()

    return jsonify({
        'plan_id': plan.id,
        'results': results,
    }), 201


@app.route('/api/history', methods=['GET'])
def api_history():
    """
    GET /api/history
    Returns a list of all past distribution plans (summary only).
    """
    plans = DistributionPlan.query.order_by(
                DistributionPlan.created_at.desc()).all()
    return jsonify([p.summary() for p in plans])


@app.route('/api/history/<int:plan_id>', methods=['GET'])
def api_get_plan(plan_id):
    """
    GET /api/history/<plan_id>
    Returns full detail (inventory + all region rows) for one plan.
    """
    plan = db.session.get(DistributionPlan, plan_id)
    if plan is None:
        return jsonify({'error': 'Plan not found'}), 404

    return jsonify({
        **plan.summary(),
        'results': [r.to_dict() for r in plan.regions],
    })


@app.route('/api/history/<int:plan_id>', methods=['DELETE'])
def api_delete_plan(plan_id):
    """
    DELETE /api/history/<plan_id>
    Permanently removes a plan and all its region rows.
    """
    plan = db.session.get(DistributionPlan, plan_id)
    if plan is None:
        return jsonify({'error': 'Plan not found'}), 404

    db.session.delete(plan)
    db.session.commit()
    return jsonify({'message': f'Plan {plan_id} deleted successfully'})


@app.route('/api/stats', methods=['GET'])
def api_stats():
    """
    GET /api/stats
    Returns aggregate statistics across all plans.
    Useful for a dashboard overview.
    """
    total_plans   = DistributionPlan.query.count()
    total_regions = RegionResult.query.count()
    satisfied     = RegionResult.query.filter_by(status='full').count()
    partial       = RegionResult.query.filter_by(status='partial').count()
    unsatisfied   = RegionResult.query.filter_by(status='none').count()

    return jsonify({
        'total_plans':   total_plans,
        'total_regions': total_regions,
        'satisfied':     satisfied,
        'partial':       partial,
        'unsatisfied':   unsatisfied,
    })

@app.route('/api/generate', methods=['GET'])
def api_generate():
    """
    GET /api/generate?count=100
    Generates a random dataset of regions using Python and returns it as plain text.
    """
    # Get the count from the URL, default to 100 if not provided
    count = request.args.get('count', default=100, type=int)
    lines = []
    
    for i in range(1, count + 1):
        name = f"Region_{i}"
        priority = random.randint(1, 5)
        population = random.randint(1000, 50000)
        water = random.randint(10, 200)
        food = random.randint(10, 150)
        med = random.randint(5, 80)
        
        # Format exactly as the frontend expects
        lines.append(f"{name}, {priority}, {population}, {water}, {food}, {med}")
        
    # Return the data as a plain text file string
    return '\n'.join(lines), 200, {'Content-Type': 'text/plain'}
# =============================================================
#  ENTRY POINT
# =============================================================

if __name__ == '__main__':
    with app.app_context():
        db.create_all()            # creates reliefops.db if not present
        print('Database ready.')
    app.run(debug=True, port=5000)
