# SKAM — Self-healing Kubernetes Autonomous Monitor

An autonomous chaos engineering and self-healing platform for microservices on Kubernetes. Implements a closed-loop system: **inject → detect → decide → recover** — entirely without human intervention.

## What It Does

SKAM deploys a realistic e-commerce microservice application, monitors it with ML-based anomaly detection, and autonomously heals failures:

1. **7 Go microservices** communicate via gRPC, fronted by an HTTP API gateway
2. **Prometheus** scrapes per-service metrics (RPS, error rate, latency percentiles, CPU, memory, restarts)
3. An **ML anomaly detector** runs Isolation Forest + LSTM Autoencoder ensemble scoring per service
4. A **decision engine** evaluates 6 self-healing policies against anomaly scores and triggers recovery actions (restart, scale, memory adjustment)
5. A **chaos engine** injects 6 fault types (pod kill, crash loop, CPU stress, memory pressure, network partition, latency injection)
6. A **React dashboard** visualizes everything in real-time via WebSocket

## Architecture

```
                    ┌─────────────────────────┐
                    │     React Dashboard      │
                    │   (topology, timeline,   │
                    │   chaos, metrics, log)   │
                    └────┬──────┬──────┬───────┘
                         │      │      │
              WebSocket  │  HTTP│      │HTTP
                         ▼      ▼      ▼
┌──────────────┐  ┌──────────┐  ┌─────────────┐
│ Chaos Engine │  │ Decision │  │   Anomaly   │
│  (6 faults)  │  │  Engine  │  │  Detector   │
│   FastAPI    │  │ FastAPI  │  │   FastAPI   │
└──────┬───────┘  └────┬─────┘  └──────┬──────┘
       │               │               │
       │  K8s API      │  polls /scores │  PromQL
       │               │               │
       ▼               ▼               ▼
┌──────────────────────────────────────────────┐
│              Kubernetes (k3d)                │
│                                              │
│  api-gw ─┬─ user-svc    ─┐                  │
│          ├─ product-svc   │  PostgreSQL      │
│          ├─ order-svc  ───┤  Redis           │
│          ├─ cart-svc      │  Prometheus      │
│          ├─ payment-svc ──┘  Loki + Grafana  │
│          └─ notif-svc                        │
└──────────────────────────────────────────────┘
```

## Prerequisites

- Docker
- k3d v5+
- kubectl
- Helm 3
- Go 1.22+
- Python 3.11+
- Node.js 20+
- protoc + Go gRPC plugins

Run `bash setup.sh` to check and install missing tools.

## Quick Start

```bash
# 1. Create k3d cluster with local registry
make cluster-up

# 2. Generate gRPC stubs from .proto files
make proto

# 3. Build all containers (services + platform + dashboard)
make build

# 4. Deploy databases, services, platform, and dashboard
make deploy

# 5. Port-forward the dashboard
make dashboard
# Open http://localhost:3000

# 6. Generate traffic and run demos
pip install -r scripts/requirements.txt
make load-test &
make chaos-demo
```

## Services

| Service | Type | Port | Storage | Role |
|---------|------|------|---------|------|
| API Gateway | HTTP | `:8080` | — | chi router, gRPC proxy to all backends |
| User Service | gRPC | `:50051` | PostgreSQL | User CRUD, authentication |
| Product Service | gRPC | `:50052` | PostgreSQL | Product catalog |
| Order Service | gRPC | `:50053` | PG + Redis | Order processing pipeline |
| Cart Service | gRPC | `:50054` | Redis | Session-based shopping cart |
| Payment Service | gRPC | `:50055` | Stateless | Payment simulation |
| Notification Service | gRPC | `:50056` | Redis | Async event notifications |

## Platform Components

### Chaos Engine (port 8000)

FastAPI service that injects faults into Kubernetes workloads:

| Fault Type | What It Does |
|------------|-------------|
| `pod_kill` | Deletes random pods matching a label selector |
| `pod_crashloop` | Corrupts deployment image to force CrashLoopBackOff |
| `cpu_stress` | Spins up a CPU stress Job on target nodes |
| `memory_pressure` | Reduces memory limits to trigger OOMKill |
| `network_partition` | Creates NetworkPolicy to block ingress |
| `latency_injection` | Uses tc netem via exec to add network delay |

All faults save rollback state and clean up automatically after `duration_seconds`.

### Anomaly Detector (port 8001)

ML pipeline that scores each service every 15 seconds:

- **Feature extraction**: 8 metrics per service from Prometheus (request rate, error ratio, latency p50/p99, CPU usage/zscore, memory, restarts)
- **Isolation Forest**: Per-service sklearn model, 5-round warmup, 100 estimators
- **LSTM Autoencoder**: Per-service PyTorch model, 10-step sliding window, reconstruction error scoring
- **Ensemble**: Weighted average (0.4 IF + 0.6 LSTM), threshold at 0.7

### Decision Engine (port 8002)

Policy-based autonomous recovery:

| Policy | Trigger | Action |
|--------|---------|--------|
| `service_down_restart` | Score > 0.8 + high restart count | Rollout restart |
| `high_error_rate_scale` | Score > 0.7 + error ratio > 10% | Scale up replicas |
| `latency_spike_restart` | Score > 0.7 + p99 > 2s | Rollout restart |
| `cpu_overload_scale` | Score > 0.7 + CPU zscore > 2 | Scale up replicas |
| `memory_pressure_adjust` | Score > 0.7 + memory > 200MB | Increase memory limit |
| `crashloop_restart` | Score > 0.6 + restarts > 3 | Rollout restart |

Safety mechanisms:
- **Cooldown**: 120s per service after each action
- **Circuit breaker**: Max 3 actions per 10-minute window
- **Risk tiers**: Services classified as critical/standard/peripheral

### Dashboard (port 3000)

React SPA with nginx reverse proxy:

- **Topology**: SVG service map with real-time anomaly indicators + per-service metric cards
- **Timeline**: Recharts AreaChart showing anomaly score history with 0.7 threshold line
- **Chaos**: Fault injection panel with 6 buttons, target/duration selectors, experiment log
- **Metrics**: Model comparison BarChart (IF vs LSTM vs Ensemble) + feature breakdown table
- **Events**: Live WebSocket stream of recovery actions from the decision engine

## Scripts

```bash
# Steady load at 20 req/s for 2 minutes
python scripts/load_generator.py

# Burst pattern (5 cycles of 100rps/15s + 10rps/30s)
python scripts/load_generator.py --burst

# Custom load
python scripts/load_generator.py --rps 50 --duration 300

# Run individual demo scenarios
python scripts/demo_scenarios.py scenario1    # Pod kill + auto restart
python scripts/demo_scenarios.py scenario2    # Latency injection + scale up
python scripts/demo_scenarios.py scenario3    # Memory pressure + limit adjustment
python scripts/demo_scenarios.py scenario4    # CPU stress + horizontal scaling
python scripts/demo_scenarios.py scenario5    # Multi-fault concurrent healing

# Run all scenarios
python scripts/demo_scenarios.py all
```

## Project Structure

```
skam/
├── services/                    # 7 Go microservices
│   ├── api-gateway/             #   HTTP → gRPC proxy
│   ├── user-service/            #   User management
│   ├── product-service/         #   Product catalog
│   ├── order-service/           #   Order processing
│   ├── cart-service/            #   Shopping cart
│   ├── payment-service/         #   Payments
│   └── notification-service/    #   Notifications
├── platform/
│   ├── chaos-engine/            # Fault injection (FastAPI)
│   ├── anomaly-detector/        # ML scoring (FastAPI)
│   ├── decision-engine/         # Policy engine (FastAPI)
│   └── dashboard/               # React + Vite + nginx
├── proto/                       # Shared .proto definitions
├── k8s/
│   ├── cluster/                 # k3d cluster config
│   ├── infrastructure/          # Prometheus, Loki, Grafana values
│   ├── microservices/           # Service deployments + DB
│   ├── platform/                # Platform deployments
│   └── rbac/                    # ServiceAccounts + RBAC
├── scripts/
│   ├── load_generator.py        # Async traffic generator
│   └── demo_scenarios.py        # 5 end-to-end demo scripts
├── Makefile                     # Build + deploy automation
├── setup.sh                     # Prerequisite installer
└── requirements.txt             # Python deps for platform
```

## Tech Stack

| Layer | Technology |
|-------|-----------|
| Application | Go 1.22, chi, gRPC, zerolog |
| ML/Platform | Python 3.11, FastAPI, scikit-learn, PyTorch, Prometheus client |
| Frontend | React 18, Vite, Recharts, D3.js |
| Infrastructure | k3d (K3s), Docker, Helm 3 |
| Databases | PostgreSQL 15, Redis 7 |
| Observability | Prometheus, Loki, Grafana |

## Make Targets

| Target | Description |
|--------|-------------|
| `make cluster-up` | Create k3d cluster + deploy monitoring stack |
| `make cluster-down` | Delete cluster |
| `make proto` | Compile .proto files to Go stubs |
| `make build` | Build all Docker images and push to local registry |
| `make deploy` | Deploy databases, services, platform, dashboard |
| `make load-test` | Run the load generator |
| `make chaos-demo` | Run all 5 demo scenarios |
| `make dashboard` | Port-forward dashboard to localhost:3000 |
| `make grafana` | Port-forward Grafana to localhost:3001 |
| `make logs` | Tail all pod logs |
| `make clean` | Remove local Docker images |

## License

MIT
