"""
Mock API server backed by REAL TrainTicket Prometheus KPI data from Zenodo.

Loads CSV files from data/trainticket/ and replays them as live metrics.
Maps TrainTicket services → SKAM service names for the dashboard.

Run:  python scripts/mock_server.py
"""

import asyncio
import csv
import glob
import json
import math
import os
import random
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

app = FastAPI(title="SKAM Mock Server (Real Data)")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

# ─── Data Loading ──────────────────────────────

DATA_DIR = Path(__file__).resolve().parent.parent / "data" / "trainticket"
EXPERIMENT = "ts-auth-mongo_MongoDB_4.4.15_2022-07-27"

# Map a subset of TrainTicket services to SKAM's 7 services
SERVICE_MAP = {
    "ts-auth-service":         "api-gateway",
    "ts-user-service":         "user-service",
    "ts-order-service":        "product-service",
    "ts-travel-service":       "order-service",
    "ts-payment-service":      "payment-service",
    "ts-food-service":         "cart-service",
    "ts-notification-service": "notification-service",
}

# The anomalous service in this experiment (ts-auth-mongo version change)
ANOMALY_SERVICES = {"api-gateway", "product-service"}
# Timestamps where anomaly was observed (12:43 - 12:46 in the data)
ANOMALY_START_ROW = 21  # ~12:43
ANOMALY_END_ROW = 25    # ~12:46


def load_kpi_data():
    """Load all MicroRCA CSVs for the selected experiment."""
    kpi_dir = DATA_DIR / "anomalies_microservice_trainticket_version_configurations" / EXPERIMENT / "MicroRCA"

    if not kpi_dir.exists():
        print(f"[warn] KPI data not found at {kpi_dir}, using synthetic fallback")
        return None

    all_data = {}
    for src_name, skam_name in SERVICE_MAP.items():
        csv_path = kpi_dir / f"{src_name}_microRCA.csv"
        if not csv_path.exists():
            print(f"[warn] missing {csv_path}")
            continue

        rows = []
        with open(csv_path, "r") as f:
            reader = csv.DictReader(f)
            for row in reader:
                rows.append({
                    "timestamp": row["timestamp"],
                    "ctn_cpu": float(row["ctn_cpu"]),
                    "ctn_network": float(row["ctn_network"]),
                    "ctn_memory": float(row["ctn_memory"]),
                    "node_cpu": float(row["node_cpu"]),
                    "node_network": float(row["node_network"]),
                    "node_memory": float(row["node_memory"]),
                })
        all_data[skam_name] = rows
        print(f"  loaded {len(rows)} rows for {skam_name} <- {src_name}")

    return all_data


# ─── State ──────────────────────────────────────

kpi_data = {}       # service -> list of row dicts
row_index = 0       # current replay position (loops)
experiments = []
events = []
total_recoveries = 0
anomaly_overrides = {}  # service -> expiry timestamp (from chaos injection)
ws_clients = set()


def current_row(service):
    """Get current metric row for a service."""
    rows = kpi_data.get(service, [])
    if not rows:
        return None
    return rows[row_index % len(rows)]


def row_to_features(service, row):
    """Convert raw KPI row into SKAM feature format."""
    is_in_anomaly_window = ANOMALY_START_ROW <= (row_index % len(kpi_data.get(service, [1]))) <= ANOMALY_END_ROW
    is_chaos_anomaly = service in anomaly_overrides and anomaly_overrides[service] > time.time()
    is_anomalous = (is_in_anomaly_window and service in ANOMALY_SERVICES) or is_chaos_anomaly

    # Map real metrics to SKAM features
    cpu = row["ctn_cpu"]
    net = row["ctn_network"]
    mem = row["ctn_memory"]
    node_cpu = row["node_cpu"]

    # Derive SKAM-compatible features from real data
    # Use node_cpu as a proxy for request_rate (higher CPU = more requests)
    request_rate = node_cpu * 200 + random.uniform(-2, 2)

    # Error ratio: normally low, spikes during anomaly window
    if is_anomalous:
        error_ratio = 0.08 + cpu * 0.5 + random.uniform(0, 0.1)
    else:
        error_ratio = 0.005 + cpu * 0.02 + random.uniform(0, 0.005)

    # Latency from network metric
    latency_p50 = 0.01 + net * 1e5 + random.uniform(-0.002, 0.002)
    latency_p99 = latency_p50 * 3 + (1.5 if is_anomalous else 0) + random.uniform(-0.01, 0.01)

    # Memory in MB from container memory (raw is in bytes-ish, scale it)
    mem_mb = max(20, mem / 1000 + 30 + random.uniform(-5, 5))

    # CPU z-score
    cpu_zscore = (cpu - 0.005) / 0.003 if cpu > 0 else 0
    if is_anomalous:
        cpu_zscore = abs(cpu_zscore) + 1.5

    # Restart count
    restart_count = random.randint(2, 6) if is_anomalous else random.randint(0, 1)

    return {
        "request_rate": round(max(0.1, request_rate), 2),
        "error_ratio": round(min(1.0, max(0, error_ratio)), 4),
        "latency_p50": round(max(0.001, latency_p50), 4),
        "latency_p99": round(max(0.005, latency_p99), 4),
        "cpu_usage": round(cpu, 4),
        "cpu_zscore": round(cpu_zscore, 2),
        "memory_usage_mb": round(mem_mb, 1),
        "restart_count": restart_count,
    }


def make_score(service, features, is_anomaly):
    """Compute anomaly scores from features."""
    if is_anomaly:
        iso = round(0.55 + features["error_ratio"] * 2 + random.uniform(0, 0.15), 4)
        lstm = round(0.60 + features["cpu_usage"] * 5 + random.uniform(0, 0.15), 4)
    else:
        iso = round(0.05 + features["error_ratio"] * 3 + features["cpu_usage"] * 2 + random.uniform(0, 0.1), 4)
        lstm = round(0.03 + features["error_ratio"] * 2 + features["cpu_zscore"] * 0.02 + random.uniform(0, 0.08), 4)

    iso = min(1.0, max(0, iso))
    lstm = min(1.0, max(0, lstm))
    ensemble = round(0.4 * iso + 0.6 * lstm, 4)

    return {
        "service": service,
        "isoforest_score": iso,
        "lstm_score": lstm,
        "ensemble_score": ensemble,
        "is_anomaly": ensemble > 0.7,
        "features": features,
    }


def make_all_scores():
    """Build scores for all services using current replay position."""
    results = []
    for service in SERVICE_MAP.values():
        row = current_row(service)
        if not row:
            continue
        is_in_anomaly_window = ANOMALY_START_ROW <= (row_index % len(kpi_data.get(service, [1]))) <= ANOMALY_END_ROW
        is_chaos = service in anomaly_overrides and anomaly_overrides[service] > time.time()
        is_anomaly = (is_in_anomaly_window and service in ANOMALY_SERVICES) or is_chaos

        features = row_to_features(service, row)
        results.append(make_score(service, features, is_anomaly))
    return results


# ─── Anomaly Detector Endpoints ────────────────

@app.get("/anomaly/api/scores")
async def get_scores():
    return {"scores": make_all_scores(), "threshold": 0.7}

@app.get("/anomaly/api/status")
async def anomaly_status():
    anomaly_count = sum(1 for s in make_all_scores() if s["is_anomaly"])
    return {
        "running": True,
        "last_check": datetime.now(timezone.utc).isoformat(),
        "services_monitored": len(SERVICE_MAP),
        "total_anomalies": anomaly_count + total_recoveries,
    }


# ─── Decision Engine Endpoints ─────────────────

@app.get("/decision/api/status")
async def decision_status():
    now = time.time()
    return {
        "running": True,
        "policies_loaded": 6,
        "total_recoveries": total_recoveries,
        "services_in_cooldown": [s for s, t in anomaly_overrides.items() if t > now],
        "last_evaluation": datetime.now(timezone.utc).isoformat(),
    }

@app.get("/decision/api/events")
async def get_events(limit: int = 50):
    return {"events": events[-limit:], "total": len(events)}

@app.websocket("/decision/ws/events")
async def ws_events(ws: WebSocket):
    await ws.accept()
    ws_clients.add(ws)
    try:
        while True:
            await ws.receive_text()
    except WebSocketDisconnect:
        ws_clients.discard(ws)

async def broadcast(event):
    dead = set()
    for ws in ws_clients:
        try:
            await ws.send_text(json.dumps(event))
        except Exception:
            dead.add(ws)
    ws_clients.difference_update(dead)


# ─── Chaos Engine Endpoints ────────────────────

class ExpReq(BaseModel):
    name: str = ""
    fault_type: str
    target: dict
    duration_seconds: int = 30
    parameters: dict = {}

@app.post("/chaos/api/experiments")
async def create_experiment(req: ExpReq):
    global total_recoveries
    exp_id = str(uuid.uuid4())[:8]
    svc = req.target.get("label_selector", "").replace("app=", "")

    exp = {
        "id": exp_id,
        "name": req.name or f"{req.fault_type}-{exp_id}",
        "fault_type": req.fault_type,
        "target": req.target,
        "duration_seconds": req.duration_seconds,
        "status": "running",
        "started_at": datetime.now(timezone.utc).isoformat(),
    }
    experiments.append(exp)

    if svc in SERVICE_MAP.values():
        anomaly_overrides[svc] = time.time() + req.duration_seconds

    async def do_recovery():
        global total_recoveries
        await asyncio.sleep(random.uniform(6, 14))
        actions = ["rollout_restart", "scale_up", "increase_memory"]
        policies = ["service_down_restart", "high_error_rate_scale",
                     "latency_spike_restart", "cpu_overload_scale",
                     "memory_pressure_adjust", "crashloop_restart"]
        evt = {
            "id": str(uuid.uuid4())[:8],
            "service": svc,
            "action": random.choice(actions),
            "status": "completed",
            "risk_level": random.choice(["low", "medium", "high"]),
            "policy_matched": random.choice(policies),
            "duration_seconds": round(random.uniform(1, 8), 1),
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "error": None,
        }
        events.append(evt)
        total_recoveries += 1
        await broadcast(evt)

    asyncio.create_task(do_recovery())
    return exp


# ─── Background Tasks ──────────────────────────

async def advance_replay():
    """Advance the data replay cursor every 5 seconds."""
    global row_index
    while True:
        await asyncio.sleep(5)
        row_index += 1
        max_rows = max((len(rows) for rows in kpi_data.values()), default=35)
        if row_index >= max_rows:
            row_index = 0  # loop

async def auto_recovery_events():
    """Generate recovery events when anomalies are detected in the data."""
    global total_recoveries
    await asyncio.sleep(12)
    while True:
        scores = make_all_scores()
        for s in scores:
            if s["is_anomaly"] and random.random() < 0.4:
                actions = ["rollout_restart", "scale_up", "increase_memory"]
                policies = ["service_down_restart", "high_error_rate_scale",
                             "latency_spike_restart", "crashloop_restart"]
                evt = {
                    "id": str(uuid.uuid4())[:8],
                    "service": s["service"],
                    "action": random.choice(actions),
                    "status": random.choice(["completed", "completed", "failed"]),
                    "risk_level": "high" if s["ensemble_score"] > 0.85 else "medium",
                    "policy_matched": random.choice(policies),
                    "duration_seconds": round(random.uniform(0.5, 6), 1),
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "error": "k8s API timeout" if random.random() < 0.08 else None,
                }
                events.append(evt)
                if evt["status"] == "completed":
                    total_recoveries += 1
                await broadcast(evt)
        await asyncio.sleep(random.uniform(10, 20))


from contextlib import asynccontextmanager

@asynccontextmanager
async def lifespan(app):
    global kpi_data
    kpi_data = load_kpi_data() or {}

    if kpi_data:
        print(f"\n[mock] Loaded real KPI data for {len(kpi_data)} services from experiment: {EXPERIMENT}")
        print(f"[mock] Anomaly window: rows {ANOMALY_START_ROW}-{ANOMALY_END_ROW} on {ANOMALY_SERVICES}")
    else:
        print("[mock] No real data found — will return empty scores")

    t1 = asyncio.create_task(advance_replay())
    t2 = asyncio.create_task(auto_recovery_events())
    print(f"[mock] Server ready — replay advancing every 5s\n")
    yield
    t1.cancel()
    t2.cancel()

app.router.lifespan_context = lifespan


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=9000)
