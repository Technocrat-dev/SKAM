#!/bin/bash
set -e

echo "=== SKAM Platform Setup ==="

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

check_cmd() {
    if command -v "$1" &> /dev/null; then
        echo -e "${GREEN}✓${NC} $1 found: $(command -v $1)"
        return 0
    else
        echo -e "${RED}✗${NC} $1 not found"
        return 1
    fi
}

echo ""
echo "--- Checking prerequisites ---"

# Docker
if check_cmd docker; then
    docker info > /dev/null 2>&1 || { echo -e "${RED}Docker is not running! Start Docker Desktop.${NC}"; exit 1; }
else
    echo -e "${YELLOW}Install Docker Desktop: https://docs.docker.com/desktop/${NC}"
    exit 1
fi

# kubectl
if ! check_cmd kubectl; then
    echo "Installing kubectl..."
    curl -LO "https://dl.k8s.io/release/$(curl -Ls https://dl.k8s.io/release/stable.txt)/bin/linux/amd64/kubectl"
    chmod +x kubectl && sudo mv kubectl /usr/local/bin/
fi

# k3d
if ! check_cmd k3d; then
    echo "Installing k3d..."
    curl -s https://raw.githubusercontent.com/k3d-io/k3d/main/install.sh | bash
fi

# Helm
if ! check_cmd helm; then
    echo "Installing Helm..."
    curl https://raw.githubusercontent.com/helm/helm/main/scripts/get-helm-3 | bash
fi

# Go
if ! check_cmd go; then
    echo -e "${YELLOW}Install Go 1.22+: https://go.dev/dl/${NC}"
    exit 1
fi

# Python
if check_cmd python3; then
    PYTHON=python3
elif check_cmd python; then
    PYTHON=python
else
    echo -e "${YELLOW}Install Python 3.11+: https://python.org/downloads/${NC}"
    exit 1
fi

# Node.js
if ! check_cmd node; then
    echo -e "${YELLOW}Install Node.js 20+: https://nodejs.org/${NC}"
    exit 1
fi

# protoc
if ! check_cmd protoc; then
    echo -e "${YELLOW}Install protoc: https://grpc.io/docs/protoc-installation/${NC}"
    echo "  Ubuntu: sudo apt install -y protobuf-compiler"
    echo "  Mac: brew install protobuf"
fi

# Python venv
echo ""
echo "--- Setting up Python virtual environment ---"
$PYTHON -m venv .venv 2>/dev/null || true
source .venv/bin/activate 2>/dev/null || . .venv/Scripts/activate 2>/dev/null
pip install -r requirements.txt

# Go protobuf plugins
echo ""
echo "--- Installing Go protobuf plugins ---"
go install google.golang.org/protobuf/cmd/protoc-gen-go@latest
go install google.golang.org/grpc/cmd/protoc-gen-go-grpc@latest

echo ""
echo -e "${GREEN}=== Setup complete! ===${NC}"
echo "Next: run 'make cluster-up' to create the k3d cluster"
