#!/bin/bash
# 使用 nerdctl 运行容器（需先设置环境变量或修改下方变量）
set -e
IMAGE_NAME="${IMAGE_NAME:-jenkins-release-scheduler}"
IMAGE_TAG="${IMAGE_TAG:-latest}"
CONTAINER_NAME="${CONTAINER_NAME:-jenkins-release-scheduler}"
DATA_DIR="${DATA_DIR:-./data}"

mkdir -p "$DATA_DIR"

nerdctl run -d \
  --name "$CONTAINER_NAME" \
  -p 5000:5000 \
  -v "$(cd "$DATA_DIR" && pwd):/data" \
  -e JENKINS_URL="${JENKINS_URL:-http://jenkins:8080}" \
  -e JENKINS_API_TOKEN="${JENKINS_API_TOKEN}" \
  -e JENKINS_USERNAME="${JENKINS_USERNAME:-}" \
  -e FEISHU_WEBHOOK_URL="${FEISHU_WEBHOOK_URL:-}" \
  -e APP_BASE_URL="${APP_BASE_URL:-}" \
  -e TZ=Asia/Shanghai \
  -e DATABASE_PATH=/data/release_plans.db \
  "${IMAGE_NAME}:${IMAGE_TAG}"

echo "Container $CONTAINER_NAME started. Web: http://localhost:5000"
