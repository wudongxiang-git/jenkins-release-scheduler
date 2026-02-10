#!/bin/bash
# 使用 nerdctl 构建镜像（与 containerd/nerdctl 环境一致，如 K8s 节点）
set -e
cd "$(dirname "$0")/.."
IMAGE_NAME="${IMAGE_NAME:-jenkins-release-scheduler}"
IMAGE_TAG="${IMAGE_TAG:-latest}"
nerdctl build -t "${IMAGE_NAME}:${IMAGE_TAG}" .
echo "Built: ${IMAGE_NAME}:${IMAGE_TAG}"
