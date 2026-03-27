# SKAM — Autonomous Chaos Engineering & Self-Healing Platform

A closed-loop chaos engineering and self-healing platform for microservices on Kubernetes.

**Core loop**: `inject → detect → decide → recover`

## Architecture

- **6 Custom Go Microservices** with gRPC inter-service communication and chi HTTP gateway
- **Python Platform**: Chaos Engine (6 fault types) + ML Anomaly Detector (Isolation Forest + LSTM) + Decision Engine
- **React Dashboard**: D3.js service topology map with WebSocket streaming
- **Observability**: Prometheus + Loki + Grafana (backup)
- **Infrastructure**: k3d (K3s in Docker), PostgreSQL, Redis

## Quick Start

```bash
# 1. Check prerequisites
bash setup.sh

# 2. Create cluster + deploy observability
make cluster-up

# 3. Generate protobuf stubs
make proto

# 4. Build and deploy everything
make build
make deploy

# 5. Run demo
make load-test &
make chaos-demo
make dashboard
```

## Services

| Service | Port | DB | Description |
|---------|------|----|-------------|
| API Gateway | `:8080` HTTP | — | chi router → gRPC proxy |
| User Service | `:50051` gRPC | PostgreSQL | User CRUD + auth |
| Product Service | `:50052` gRPC | PostgreSQL | Product catalog |
| Order Service | `:50053` gRPC | PG + Redis | Order processing |
| Cart Service | `:50054` gRPC | Redis | Shopping cart |
| Payment Service | `:50055` gRPC | Stateless | Payment simulation |
| Notification Service | `:50056` gRPC | Redis | Async notifications |

## Project Structure

```
skam/
├── services/          # 7 Go microservices
├── platform/          # Python: chaos engine, ML detector, decision engine
├── dashboard/         # React + D3.js real-time UI
├── proto/             # Shared .proto definitions
├── k8s/               # K8s manifests, Helm values, RBAC
├── scripts/           # Load generator + demo scenarios
├── Makefile           # One-command automation
└── setup.sh           # Prerequisite installer
```

## Tech Stack

Go 1.22 · Python 3.11 · React 18 · gRPC · chi · PostgreSQL 15 · Redis 7 · k3d · Prometheus · Loki · Grafana · scikit-learn · PyTorch · D3.js

## License

MIT
