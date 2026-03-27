SHELL := /bin/bash
.PHONY: all cluster-up cluster-down build deploy proto load-test chaos-demo dashboard grafana logs clean status

REGISTRY := k3d-skam-registry:5111
NAMESPACE := default
MONITORING_NS := monitoring

# ─── Cluster ───────────────────────────────────────────────
cluster-up:
	k3d cluster create --config k8s/cluster/k3d-config.yaml
	@echo "Waiting for cluster to be ready..."
	kubectl wait --for=condition=Ready nodes --all --timeout=120s
	@$(MAKE) infra-deploy

cluster-down:
	k3d cluster delete skam

# ─── Infrastructure ───────────────────────────────────────
infra-deploy:
	helm repo add prometheus-community https://prometheus-community.github.io/helm-charts || true
	helm repo add grafana https://grafana.github.io/helm-charts || true
	helm repo update
	kubectl create namespace $(MONITORING_NS) --dry-run=client -o yaml | kubectl apply -f -
	helm upgrade --install prometheus prometheus-community/kube-prometheus-stack \
		-n $(MONITORING_NS) -f k8s/infrastructure/prometheus-values.yaml --wait
	helm upgrade --install loki grafana/loki-stack \
		-n $(MONITORING_NS) --set promtail.enabled=true \
		-f k8s/infrastructure/loki-values.yaml --wait
	kubectl apply -f k8s/infrastructure/prometheus-rules.yaml
	kubectl create configmap grafana-dashboards -n $(MONITORING_NS) \
		--from-file=k8s/infrastructure/grafana-dashboards/ \
		--dry-run=client -o yaml | kubectl apply -f -
	kubectl label configmap grafana-dashboards -n $(MONITORING_NS) grafana_dashboard=1 --overwrite
	kubectl apply -f k8s/rbac/

# ─── Protobuf ─────────────────────────────────────────────
proto:
	@echo "Compiling proto files..."
	@for p in proto/*.proto; do \
		protoc --go_out=. --go-grpc_out=. $$p; \
	done

# ─── Build ─────────────────────────────────────────────────
SERVICES := api-gateway user-service product-service order-service cart-service payment-service notification-service
PLATFORM := chaos-engine anomaly-detector decision-engine

build: build-services build-platform build-dashboard

build-services:
	@for svc in $(SERVICES); do \
		echo "Building $$svc..."; \
		docker build -t $(REGISTRY)/$$svc:latest services/$$svc/; \
		docker push $(REGISTRY)/$$svc:latest; \
	done

build-platform:
	@for svc in $(PLATFORM); do \
		echo "Building $$svc..."; \
		docker build -t $(REGISTRY)/$$svc:latest platform/$$svc/; \
		docker push $(REGISTRY)/$$svc:latest; \
	done

build-dashboard:
	docker build -t $(REGISTRY)/dashboard:latest platform/dashboard/
	docker push $(REGISTRY)/dashboard:latest

# ─── Deploy ────────────────────────────────────────────────
deploy: deploy-db deploy-services deploy-platform deploy-dashboard

deploy-db:
	kubectl apply -f k8s/microservices/postgres-deployment.yaml
	kubectl apply -f k8s/microservices/redis-deployment.yaml
	kubectl wait --for=condition=Ready pod -l app=postgres --timeout=120s
	kubectl wait --for=condition=Ready pod -l app=redis --timeout=120s

deploy-services:
	@for svc in $(SERVICES); do \
		kubectl apply -f k8s/microservices/$$svc.yaml; \
	done

deploy-platform:
	@for svc in $(PLATFORM); do \
		kubectl apply -f k8s/platform/$$svc.yaml; \
	done

deploy-dashboard:
	kubectl apply -f k8s/platform/dashboard.yaml

# ─── Operations ────────────────────────────────────────────
load-test:
	python scripts/load_generator.py

chaos-demo:
	python scripts/demo_scenarios.py all

dashboard:
	@echo "Opening dashboard at http://localhost:3000"
	kubectl port-forward svc/dashboard 3000:3000 &

grafana:
	@echo "Opening Grafana at http://localhost:3001"
	kubectl port-forward -n $(MONITORING_NS) svc/prometheus-grafana 3001:80 &

logs:
	kubectl logs -f -l app --all-containers --max-log-requests=20

clean:
	@for svc in $(SERVICES) $(PLATFORM) dashboard; do \
		docker rmi $(REGISTRY)/$$svc:latest 2>/dev/null || true; \
	done
