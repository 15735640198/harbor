#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

WILDCLAWBENCH_BASE_IMAGE="${WILDCLAWBENCH_BASE_IMAGE:-wildclawbench-ubuntu:v1.3}"
OPENCLAW_VERSION="${OPENCLAW_VERSION:-2026.5.27}"
IMAGE_TAG="${IMAGE_TAG:-wildclawbench-ubuntu-openclaw:${OPENCLAW_VERSION}}"
PLATFORM="${PLATFORM:-linux/amd64}"
BUILD_HTTP_PROXY="${BUILD_HTTP_PROXY:-}"
BUILD_HTTPS_PROXY="${BUILD_HTTPS_PROXY:-}"

docker build \
  --platform "${PLATFORM}" \
  --build-arg "WILDCLAWBENCH_BASE_IMAGE=${WILDCLAWBENCH_BASE_IMAGE}" \
  --build-arg "OPENCLAW_VERSION=${OPENCLAW_VERSION}" \
  --build-arg "BUILD_HTTP_PROXY=${BUILD_HTTP_PROXY}" \
  --build-arg "BUILD_HTTPS_PROXY=${BUILD_HTTPS_PROXY}" \
  -t "${IMAGE_TAG}" \
  "${SCRIPT_DIR}"

docker image inspect "${IMAGE_TAG}" --format '{{.RepoTags}}'
