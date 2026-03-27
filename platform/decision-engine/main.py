"""
SKAM Decision Engine — receives anomaly scores from the ML detector,
evaluates policy rules, and triggers self-healing actions.
Includes risk assessment, cooldown management, and WebSocket event stream.
"""

import os
import uuid
import asyncio
import logging
from datetime import datetime, timezone, timedelta
from typing import Optional
from contextlib import asynccontextmanager

import aiohttp
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from prometheus_client import Counter, Gauge, Histogram, make_asgi_app

from policies import PolicyEngine
from actions import ActionExecutor
from risk import RiskAssessor

# ─── Logging ─────────────────────────────────────────────────

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("decision-engine")

# ─── Prometheus Metrics ──────────────────────────────────────

recovery_actions_total = Counter(
    "recovery_actions_total", "Total recovery actions", ["service", "action", "result"]
)
recovery_duration = Histogram(
    "recovery_duration_seconds", "Time to execute recovery", ["action"],
    buckets=[0.5, 1, 2, 5, 10, 30, 60]
)
active_recoveries = Gauge("active_recoveries", "Currently active recoveries")
cooldown_active = Gauge("cooldown_active", "Services currently in cooldown", ["service"])

# ─── Configuration ───────────────────────────────────────────

ANOMALY_DETECTOR_URL = os.getenv("ANOMALY_DETECTOR_URL", "http://anomaly-detector:8001")
CHAOS_ENGINE_URL = os.getenv("CHAOS_ENGINE_URL", "http://chaos-engine:8000")
POLL_INTERVAL = int(os.getenv("POLL_INTERVAL", "10"))
COOLDOWN_SECONDS = int(os.getenv("COOLDOWN_SECONDS", "120"))

# ─── Data Models ─────────────────────────────────────────────

class RecoveryEvent(BaseModel):
    id: str
    timestamp: str
    service: str
    anomaly_score: float
    policy_matched: str
    action: str
    risk_level: str  # low, medium, high
    status: str  # pending, executing, completed, failed, blocked
    duration_seconds: Optional[float] = None
    error: Optional[str] = None

class EngineStatus(BaseModel):
    running: bool
    policies_loaded: int
    total_recoveries: int
    services_in_cooldown: list[str]
    last_evaluation: Optional[str]

# ─── App State ───────────────────────────────────────────────

event_log: list[RecoveryEvent] = []
active_websockets: list[WebSocket] = []
engine_running = False
total_recovery_count = 0
cooldowns: dict[str, datetime] = {}  # service → cooldown_expires_at
_session: Optional[aiohttp.ClientSession] = None

# ─── Components ──────────────────────────────────────────────

policy_engine = PolicyEngine()
action_executor = ActionExecutor()
risk_assessor = RiskAssessor()

# ─── FastAPI App ─────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    global engine_running, _session
    engine_running = True
    _session = aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=10))
    task = asyncio.create_task(decision_loop())
    logger.info("🧠 Decision Engine started — %d policies loaded", policy_engine.count())
    yield
    engine_running = False
    task.cancel()
    if _session:
        await _session.close()
    logger.info("🧠 Decision Engine stopped")

app = FastAPI(
    title="SKAM Decision Engine",
    description="Policy-driven self-healing engine",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])
app.mount("/metrics", make_asgi_app())

# ─── REST Endpoints ──────────────────────────────────────────

@app.get("/health")
async def health():
    return {"status": "healthy", "service": "decision-engine", "running": engine_running}


@app.get("/api/status")
async def get_status():
    active_cooldowns = [
        svc for svc, expires in cooldowns.items()
        if datetime.now(timezone.utc) < expires
    ]
    return EngineStatus(
        running=engine_running,
        policies_loaded=policy_engine.count(),
        total_recoveries=total_recovery_count,
        services_in_cooldown=active_cooldowns,
        last_evaluation=event_log[-1].timestamp if event_log else None,
    )


@app.get("/api/events")
async def get_events(limit: int = 50):
    """Get recent recovery events."""
    return {"events": event_log[-limit:], "total": len(event_log)}


@app.get("/api/policies")
async def get_policies():
    """Get all loaded policies."""
    return {"policies": policy_engine.list_policies()}


# ─── WebSocket Event Stream ─────────────────────────────────

@app.websocket("/ws/events")
async def websocket_events(websocket: WebSocket):
    """Real-time event stream for dashboard."""
    await websocket.accept()
    active_websockets.append(websocket)
    logger.info(f"WebSocket client connected ({len(active_websockets)} total)")
    try:
        while True:
            # Keep connection alive, clients just listen
            await websocket.receive_text()
    except WebSocketDisconnect:
        active_websockets.remove(websocket)
        logger.info(f"WebSocket client disconnected ({len(active_websockets)} total)")


async def broadcast_event(event: RecoveryEvent):
    """Broadcast an event to all connected WebSocket clients."""
    event_data = event.model_dump_json()
    disconnected = []
    for ws in active_websockets:
        try:
            await ws.send_text(event_data)
        except Exception:
            disconnected.append(ws)
    for ws in disconnected:
        active_websockets.remove(ws)


# ─── Decision Loop ──────────────────────────────────────────

async def decision_loop():
    """Main loop: poll anomaly scores → evaluate policies → trigger actions."""
    global total_recovery_count

    while engine_running:
        try:
            # 1. Fetch latest anomaly scores from ML detector
            scores = await _fetch_anomaly_scores()
            if not scores:
                await asyncio.sleep(POLL_INTERVAL)
                continue

            for score_data in scores:
                service = score_data.get("service", "")
                ensemble_score = score_data.get("ensemble_score", 0.0)
                is_anomaly = score_data.get("is_anomaly", False)

                if not is_anomaly:
                    continue

                # 2. Check cooldown
                if _is_in_cooldown(service):
                    logger.debug(f"⏳ {service} is in cooldown, skipping")
                    continue

                # 3. Evaluate policies
                matched_policy = policy_engine.evaluate(service, ensemble_score, score_data)
                if not matched_policy:
                    continue

                # 4. Risk assessment
                risk = risk_assessor.assess(service, matched_policy, ensemble_score)
                if risk == "blocked":
                    logger.warning(f"🚫 Action blocked for {service}: risk too high")
                    continue

                # 5. Create recovery event
                event = RecoveryEvent(
                    id=f"rec-{uuid.uuid4().hex[:8]}",
                    timestamp=datetime.now(timezone.utc).isoformat(),
                    service=service,
                    anomaly_score=ensemble_score,
                    policy_matched=matched_policy["name"],
                    action=matched_policy["action"],
                    risk_level=risk,
                    status="pending",
                )
                event_log.append(event)

                # Keep event log bounded
                if len(event_log) > 5000:
                    event_log[:] = event_log[-2500:]

                # 6. Execute recovery action
                asyncio.create_task(_execute_recovery(event, matched_policy))

            await asyncio.sleep(POLL_INTERVAL)

        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.error(f"Decision loop error: {e}")
            await asyncio.sleep(POLL_INTERVAL)


async def _fetch_anomaly_scores() -> list:
    """Fetch latest scores from the anomaly detector."""
    try:
        async with _session.get(f"{ANOMALY_DETECTOR_URL}/api/scores") as resp:
            if resp.status == 200:
                data = await resp.json()
                return data.get("scores", [])
    except Exception as e:
        logger.debug(f"Failed to fetch anomaly scores: {e}")
    return []


def _is_in_cooldown(service: str) -> bool:
    """Check if a service is in cooldown period."""
    if service not in cooldowns:
        return False
    return datetime.now(timezone.utc) < cooldowns[service]


def _set_cooldown(service: str):
    """Set cooldown for a service."""
    cooldowns[service] = datetime.now(timezone.utc) + timedelta(seconds=COOLDOWN_SECONDS)
    cooldown_active.labels(service=service).set(1)
    logger.info(f"⏳ Cooldown set for {service} ({COOLDOWN_SECONDS}s)")


async def _execute_recovery(event: RecoveryEvent, policy: dict):
    """Execute a recovery action and track its lifecycle."""
    global total_recovery_count
    import time

    start = time.time()
    event.status = "executing"
    active_recoveries.inc()
    await broadcast_event(event)

    try:
        await action_executor.execute(event.service, policy, _session)

        elapsed = time.time() - start
        event.status = "completed"
        event.duration_seconds = round(elapsed, 2)
        total_recovery_count += 1

        recovery_actions_total.labels(
            service=event.service, action=event.action, result="success"
        ).inc()
        recovery_duration.labels(action=event.action).observe(elapsed)

        logger.info(f"✅ Recovery completed for {event.service}: {event.action} ({elapsed:.1f}s)")

    except Exception as e:
        event.status = "failed"
        event.error = str(e)
        recovery_actions_total.labels(
            service=event.service, action=event.action, result="failure"
        ).inc()
        logger.error(f"❌ Recovery failed for {event.service}: {e}")

    finally:
        active_recoveries.dec()
        _set_cooldown(event.service)
        await broadcast_event(event)
