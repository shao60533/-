#!/usr/bin/env bash
# One-shot deploy to Tencent Cloud Lightweight.
# Usage: ./deploy/tencent/deploy.sh [user@host]
#   Defaults to ubuntu@101.35.248.128

set -euo pipefail

TARGET="${1:-ubuntu@101.35.248.128}"
REMOTE_DIR="/opt/stock-trading-system"
LOCAL_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"

echo "==> Target: $TARGET"
echo "==> Local root: $LOCAL_ROOT"
echo "==> Remote dir: $REMOTE_DIR"

# 1. Bootstrap remote (Docker + dirs + permissions) on first run
echo "==> Bootstrapping remote host..."
ssh "$TARGET" 'bash -s' <<'REMOTE_BOOTSTRAP'
set -euo pipefail

# Install Docker + compose plugin if missing
if ! command -v docker >/dev/null 2>&1; then
  echo "Installing Docker..."
  sudo apt-get update -y
  sudo apt-get install -y ca-certificates curl gnupg
  sudo install -m 0755 -d /etc/apt/keyrings
  curl -fsSL https://mirrors.aliyun.com/docker-ce/linux/ubuntu/gpg \
    | sudo gpg --dearmor -o /etc/apt/keyrings/docker.gpg
  sudo chmod a+r /etc/apt/keyrings/docker.gpg
  echo \
    "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] \
      https://mirrors.aliyun.com/docker-ce/linux/ubuntu $(. /etc/os-release && echo $VERSION_CODENAME) stable" \
    | sudo tee /etc/apt/sources.list.d/docker.list >/dev/null
  sudo apt-get update -y
  sudo apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
fi

# Join ubuntu to docker group (effective next login)
if ! getent group docker | grep -q "\bubuntu\b"; then
  sudo usermod -aG docker ubuntu
fi

# Prepare dirs
sudo mkdir -p /opt/stock-trading-system/data
sudo chown -R ubuntu:ubuntu /opt/stock-trading-system

# Registry mirror (accelerates Docker Hub pulls from China)
if [ ! -f /etc/docker/daemon.json ] || ! grep -q registry-mirrors /etc/docker/daemon.json; then
  echo '{"registry-mirrors":["https://docker.1ms.run","https://hub.rat.dev","https://dockerproxy.com"]}' \
    | sudo tee /etc/docker/daemon.json >/dev/null
  sudo systemctl restart docker
fi

echo "Bootstrap OK"
REMOTE_BOOTSTRAP

# 2. Sync source tree (exclude gitignored and local-only stuff)
echo "==> Syncing source..."
rsync -az --delete \
  --exclude='.git/' \
  --exclude='.venv/' \
  --exclude='__pycache__/' \
  --exclude='*.pyc' \
  --exclude='data/' \
  --exclude='*.db' \
  --exclude='*.db-*' \
  --exclude='reports_output/' \
  --exclude='eval_results/' \
  --exclude='.rollback_backup_*/' \
  --exclude='.pytest_cache/' \
  --exclude='build/' \
  --exclude='*.egg-info/' \
  --exclude='deploy/tencent/.env' \
  "$LOCAL_ROOT/" "$TARGET:$REMOTE_DIR/"

# 3. Ensure .env exists (copy template if not)
echo "==> Checking .env on remote..."
ssh "$TARGET" bash -c '"
  cd /opt/stock-trading-system/deploy/tencent
  if [ ! -f .env ]; then
    echo \"NO .env FOUND — copying .env.example. You MUST edit it before first run.\"
    cp .env.example .env
    chmod 600 .env
    exit 2
  fi
  echo \".env OK\"
"'

# 4. Build + up
echo "==> Building + starting Docker service..."
ssh "$TARGET" bash -c '"
  cd /opt/stock-trading-system/deploy/tencent
  # use sg docker so we do not need to re-login for group membership
  sg docker -c \"docker compose build && docker compose up -d\"
"'

echo ""
echo "==> Deployed. Wait ~60s for warm-up, then:"
echo "    curl http://101.35.248.128:5000/api/health"
