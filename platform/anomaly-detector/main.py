"""
SKAM ML Anomaly Detector — Collects metrics from Prometheus,
runs feature engineering, and scores anomalies using an
Isolation Forest + LSTM Autoencoder ensemble.
"""

import os
import time
import asyncio
import logging
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Optional

import numpy as np
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from prometheus_client import Gauge, Counter, Histogram, make_asgi_app

from collector import PrometheusCollector
from features import FeatureEngineer
from models.isolation_forest import IsolationForestDetector
from models.lstm_autoencoder import LSTMAutoencoder
from ensemble import EnsembleScorer

# ─── Logging ─────────────────────────────────────────────────

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("anomaly-detector")

# ─── Prometheus Metrics ──────────────────────────────────────

anomaly_score_gauge = Gauge(
    "anomaly_score", "Current anomaly score", ["service", "detector"]
)
anomalies_detected = Counter(
    "anomalies_detected_total", "Total anomalies detected", ["service", "detector"]
)
detection_latency = Histogram(
    "detection_latency_seconds", "Time to compute anomaly score",
    buckets=[0.01, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5]
)

# ─── Configuration ───────────────────────────────────────────

PROMETHEUS_URL = os.getenv("PROMETHEUS_URL", "http://prometheus-kube-prometheus-prometheus.monitoring.svc:9090")
DETECTION_INTERVAL = int(os.getenv("DETECTION_INTERVAL", "15"))
ANOMALY_THRESHOLD = float(os.getenv("ANOMALY_THRESHOLD", "0.7"))
SERVICES = ["api-gateway", "user-service", "product-service", "order-service", "cart-service", "payment-service", "notification-service"]

# ─── Data Models ─────────────────────────────────────────────

class AnomalyResult(BaseModel):
    service: str
    timestamp: str
    isoforest_score: float
    lstm_score: float
    ensemble_score: float
    is_anomaly: bool
    features: dict

class DetectorStatus(BaseModel):
    running: bool
    last_check: Optional[str]
    services_monitored: int
    total_anomalies: int

# ─── App State ───────────────────────────────────────────────

latest_results: dict[str, AnomalyResult] = {}
history: list[AnomalyResult] = []
detector_running = False
total_anomaly_count = 0

# ─── Per-Service ML Components ───────────────────────────────
# Each service gets its own model instances so training on one
# service's baseline doesn't pollute another's anomaly profile.

collector = PrometheusCollector(PROMETHEUS_URL)
feature_engineer = FeatureEngineer()
ensemble = EnsembleScorer(weights={"isoforest": 0.4, "lstm": 0.6})

# Per-service model registries
service_models: dict[str, dict] = {}

def get_models(service: str) -> dict:
    """Get or create per-service model instances."""
    if service not in service_models:
        service_models[service] = {
            "isoforest": IsolationForestDetector(),
            "lstm": LSTMAutoencoder(),
            "warmup_data": [],
            "warmup_rounds": 0,
        }
    return service_models[service]

# ─── FastAPI App ─────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    global detector_running
    detector_running = True
    # Initialize shared aiohttp session
    await collector.start_session()
    task = asyncio.create_task(detection_loop())
    logger.info("🧠 Anomaly Detector started — monitoring %d services", len(SERVICES))
    yield
    detector_running = False
    task.cancel()
    await collector.close_session()
    logger.info("🧠 Anomaly Detector stopped")

app = FastAPI(
    title="SKAM Anomaly Detector",
    description="ML-based anomaly detection for microservices",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])
app.mount("/metrics", make_asgi_app())

# ─── Endpoints ───────────────────────────────────────────────

@app.get("/health")
async def health():
    return {
        "status": "healthy",
        "service": "anomaly-detector",
        "detector_running": detector_running,
    }


@app.get("/api/status")
async def status():
    return DetectorStatus(
        running=detector_running,
        last_check=history[-1].timestamp if history else None,
        services_monitored=len(SERVICES),
        total_anomalies=total_anomaly_count,
    )


@app.get("/api/scores")
async def get_scores():
    """Get latest anomaly scores for all services."""
    return {"scores": list(latest_results.values()), "threshold": ANOMALY_THRESHOLD}


@app.get("/api/scores/{service}")
async def get_service_score(service: str):
    """Get latest anomaly score for a specific service."""
    result = latest_results.get(service)
    if not result:
        return {"error": f"No data for service: {service}"}
    return result


@app.get("/api/history")
async def get_history(limit: int = 100):
    """Get anomaly detection history."""
    return {"history": history[-limit:], "total": len(history)}


# ─── Detection Loop ─────────────────────────────────────────

async def detection_loop():
    """Main detection loop — runs every DETECTION_INTERVAL seconds."""
    global total_anomaly_count
    warmup_target = 5

    while detector_running:
        try:
            start = time.time()

            for service in SERVICES:
                try:
                    models = get_models(service)
                    iso = models["isoforest"]
                    ae = models["lstm"]

                    # 1. Collect raw metrics from Prometheus
                    raw_metrics = await collector.collect_service_metrics(service)
                    if not raw_metrics:
                        continue

                    # 2. Feature engineering
                    features = feature_engineer.extract(raw_metrics, service)

                    # Accumulate warmup data (per-service)
                    if models["warmup_rounds"] < warmup_target:
                        models["warmup_data"].append(features)
                        models["warmup_rounds"] += 1
                        continue

                    # Train on first run after warmup (per-service)
                    if models["warmup_rounds"] == warmup_target:
                        warmup_features = models["warmup_data"]
                        if warmup_features:
                            feature_matrix = np.array([list(f.values()) for f in warmup_features])
                            iso.fit(feature_matrix)
                            ae.fit(feature_matrix)
                            logger.info(f"✅ Models trained for {service} on {len(warmup_features)} samples")
                        models["warmup_rounds"] += 1  # Prevent re-training

                    # 3. Score with both models
                    feature_vec = np.array(list(features.values())).reshape(1, -1)

                    iso_score = iso.score(feature_vec)
                    lstm_score = ae.score(feature_vec)

                    # 4. Ensemble scoring
                    ens_score = ensemble.combine(iso_score, lstm_score)
                    is_anomaly = ens_score > ANOMALY_THRESHOLD

                    # 5. Record result
                    result = AnomalyResult(
                        service=service,
                        timestamp=datetime.now(timezone.utc).isoformat(),
                        isoforest_score=float(iso_score),
                        lstm_score=float(lstm_score),
                        ensemble_score=float(ens_score),
                        is_anomaly=is_anomaly,
                        features=features,
                    )

                    latest_results[service] = result
                    history.append(result)

                    # Keep history bounded
                    if len(history) > 10000:
                        history[:] = history[-5000:]

                    # 6. Update Prometheus metrics
                    anomaly_score_gauge.labels(service=service, detector="isoforest").set(iso_score)
                    anomaly_score_gauge.labels(service=service, detector="lstm").set(lstm_score)
                    anomaly_score_gauge.labels(service=service, detector="ensemble").set(ens_score)

                    if is_anomaly:
                        anomalies_detected.labels(service=service, detector="ensemble").inc()
                        total_anomaly_count += 1
                        logger.warning(f"🚨 ANOMALY on {service}: score={ens_score:.3f} (iso={iso_score:.3f}, lstm={lstm_score:.3f})")

                except Exception as e:
                    logger.error(f"Error processing {service}: {e}")

            elapsed = time.time() - start
            detection_latency.observe(elapsed)

            # Sleep until next interval
            sleep_time = max(0, DETECTION_INTERVAL - elapsed)
            await asyncio.sleep(sleep_time)

        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.error(f"Detection loop error: {e}")
            await asyncio.sleep(DETECTION_INTERVAL)
