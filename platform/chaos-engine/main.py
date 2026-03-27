"""
SKAM Chaos Engine — FastAPI service for fault injection into K8s workloads.
Supports 6 fault types with automatic rollback tracking.
"""

import os
import uuid
import asyncio
from datetime import datetime, timezone
from typing import Optional
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from prometheus_client import Counter, Gauge, Histogram, make_asgi_app
from kubernetes import client, config

from faults.pod_kill import PodKillFault
from faults.pod_crashloop import PodCrashLoopFault
from faults.cpu_stress import CpuStressFault
from faults.memory_pressure import MemoryPressureFault
from faults.network_partition import NetworkPartitionFault
from faults.latency_injection import LatencyInjectionFault

# ─── Prometheus Metrics ──────────────────────────────────────

chaos_experiments_total = Counter(
    "chaos_experiments_total", "Total chaos experiments", ["fault_type", "status"]
)
chaos_experiments_active = Gauge(
    "chaos_experiments_active", "Currently active experiments"
)
chaos_experiment_duration = Histogram(
    "chaos_experiment_duration_seconds", "Experiment duration", ["fault_type"]
)

# ─── Kubernetes Client ───────────────────────────────────────

def init_k8s():
    """Initialize K8s client — in-cluster or kubeconfig."""
    try:
        config.load_incluster_config()
    except config.ConfigException:
        config.load_kube_config()
    return client.CoreV1Api(), client.AppsV1Api(), client.BatchV1Api(), client.NetworkingV1Api()

# ─── Data Models ─────────────────────────────────────────────

class ExperimentTarget(BaseModel):
    namespace: str = "default"
    label_selector: str  # e.g., "app=order-service"

class ExperimentCreate(BaseModel):
    name: str
    target: ExperimentTarget
    fault_type: str  # pod_kill, pod_crashloop, cpu_stress, memory_pressure, network_partition, latency_injection
    parameters: dict = Field(default_factory=dict)
    duration_seconds: int = 60

class Experiment(BaseModel):
    id: str
    name: str
    target: ExperimentTarget
    fault_type: str
    parameters: dict
    duration_seconds: int
    status: str  # pending, running, completed, rolled_back, failed
    started_at: Optional[str] = None
    ended_at: Optional[str] = None
    rollback_state: dict = Field(default_factory=dict)
    error: Optional[str] = None

# ─── App State ───────────────────────────────────────────────

experiments: dict[str, Experiment] = {}
fault_handlers = {}

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Initialize fault handlers on startup."""
    core_v1, apps_v1, batch_v1, networking_v1 = init_k8s()

    fault_handlers["pod_kill"] = PodKillFault(core_v1)
    fault_handlers["pod_crashloop"] = PodCrashLoopFault(core_v1, apps_v1)
    fault_handlers["cpu_stress"] = CpuStressFault(core_v1, batch_v1)
    fault_handlers["memory_pressure"] = MemoryPressureFault(core_v1, apps_v1)
    fault_handlers["network_partition"] = NetworkPartitionFault(networking_v1)
    fault_handlers["latency_injection"] = LatencyInjectionFault(core_v1)

    print("🔥 Chaos Engine initialized with 6 fault types")
    yield
    print("🔥 Chaos Engine shutting down")

# ─── FastAPI App ─────────────────────────────────────────────

app = FastAPI(
    title="SKAM Chaos Engine",
    description="Fault injection service for Kubernetes workloads",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Mount Prometheus metrics
metrics_app = make_asgi_app()
app.mount("/metrics", metrics_app)

# ─── Endpoints ───────────────────────────────────────────────

@app.get("/health")
async def health():
    return {"status": "healthy", "service": "chaos-engine", "active_experiments": len([e for e in experiments.values() if e.status == "running"])}


@app.get("/api/faults")
async def list_faults():
    """List available fault types with parameter descriptions."""
    return {
        "faults": [
            {
                "type": "pod_kill",
                "description": "Delete a random pod matching the label selector",
                "parameters": {"count": "Number of pods to kill (default: 1)"},
            },
            {
                "type": "pod_crashloop",
                "description": "Patch deployment to an invalid image causing CrashLoopBackOff",
                "parameters": {"image": "Invalid image name (default: invalid:latest)"},
            },
            {
                "type": "cpu_stress",
                "description": "Deploy a stress-ng job for CPU pressure",
                "parameters": {"cpu_cores": "Number of CPU cores to stress (default: 2)", "duration": "Stress duration in seconds"},
            },
            {
                "type": "memory_pressure",
                "description": "Reduce container memory limit to trigger OOMKill",
                "parameters": {"limit_mi": "Memory limit in Mi (default: 64)"},
            },
            {
                "type": "network_partition",
                "description": "Create a NetworkPolicy blocking all ingress to target",
                "parameters": {},
            },
            {
                "type": "latency_injection",
                "description": "Add network latency using tc netem via pod exec",
                "parameters": {"delay_ms": "Latency in milliseconds (default: 500)", "jitter_ms": "Jitter in ms (default: 100)"},
            },
        ]
    }


@app.post("/api/experiments", status_code=201)
async def create_experiment(req: ExperimentCreate):
    """Create and start a chaos experiment."""
    if req.fault_type not in fault_handlers:
        raise HTTPException(status_code=400, detail=f"Unknown fault type: {req.fault_type}")

    exp = Experiment(
        id=f"exp-{uuid.uuid4().hex[:8]}",
        name=req.name,
        target=req.target,
        fault_type=req.fault_type,
        parameters=req.parameters,
        duration_seconds=req.duration_seconds,
        status="pending",
    )
    experiments[exp.id] = exp

    # Start experiment asynchronously
    asyncio.create_task(_run_experiment(exp))

    chaos_experiments_total.labels(fault_type=req.fault_type, status="started").inc()
    chaos_experiments_active.inc()

    return exp


@app.get("/api/experiments")
async def list_experiments(status: Optional[str] = None):
    """List all experiments, optionally filtered by status."""
    exps = list(experiments.values())
    if status:
        exps = [e for e in exps if e.status == status]
    return {"experiments": exps, "total": len(exps)}


@app.get("/api/experiments/{experiment_id}")
async def get_experiment(experiment_id: str):
    """Get experiment details by ID."""
    exp = experiments.get(experiment_id)
    if not exp:
        raise HTTPException(status_code=404, detail="Experiment not found")
    return exp


@app.post("/api/experiments/{experiment_id}/stop")
async def stop_experiment(experiment_id: str):
    """Stop and rollback an active experiment."""
    exp = experiments.get(experiment_id)
    if not exp:
        raise HTTPException(status_code=404, detail="Experiment not found")
    if exp.status != "running":
        raise HTTPException(status_code=400, detail=f"Experiment is {exp.status}, not running")

    try:
        handler = fault_handlers[exp.fault_type]
        await handler.rollback(exp)
        exp.status = "rolled_back"
        exp.ended_at = datetime.now(timezone.utc).isoformat()
        chaos_experiments_active.dec()
        chaos_experiments_total.labels(fault_type=exp.fault_type, status="rolled_back").inc()
    except Exception as e:
        exp.error = str(e)
        exp.status = "failed"

    return exp


# ─── Experiment Runner ───────────────────────────────────────

async def _run_experiment(exp: Experiment):
    """Execute a chaos experiment: inject → wait → rollback."""
    handler = fault_handlers[exp.fault_type]

    try:
        # Inject fault
        exp.status = "running"
        exp.started_at = datetime.now(timezone.utc).isoformat()
        rollback_state = await handler.inject(exp)
        exp.rollback_state = rollback_state

        # Wait for experiment duration
        await asyncio.sleep(exp.duration_seconds)

        # Auto-rollback after duration
        if exp.status == "running":
            await handler.rollback(exp)
            exp.status = "completed"
            exp.ended_at = datetime.now(timezone.utc).isoformat()
            chaos_experiments_active.dec()
            chaos_experiments_total.labels(fault_type=exp.fault_type, status="completed").inc()
            chaos_experiment_duration.labels(fault_type=exp.fault_type).observe(exp.duration_seconds)

    except Exception as e:
        exp.status = "failed"
        exp.error = str(e)
        exp.ended_at = datetime.now(timezone.utc).isoformat()
        chaos_experiments_active.dec()
        chaos_experiments_total.labels(fault_type=exp.fault_type, status="failed").inc()
        print(f"❌ Experiment {exp.id} failed: {e}")
