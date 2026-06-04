ARG WILDCLAWBENCH_BASE_IMAGE=wildclawbench-ubuntu:v1.3
FROM ${WILDCLAWBENCH_BASE_IMAGE}

ARG BUILD_HTTP_PROXY=
ARG BUILD_HTTPS_PROXY=
ARG OPENCLAW_VERSION=2026.5.27

ENV http_proxy=${BUILD_HTTP_PROXY} \
    https_proxy=${BUILD_HTTPS_PROXY} \
    HTTP_PROXY=${BUILD_HTTP_PROXY} \
    HTTPS_PROXY=${BUILD_HTTPS_PROXY} \
    all_proxy= \
    ALL_PROXY= \
    NPM_CONFIG_PROXY=${BUILD_HTTP_PROXY} \
    NPM_CONFIG_HTTPS_PROXY=${BUILD_HTTPS_PROXY} \
    NODE_COMPILE_CACHE=/var/tmp/openclaw-compile-cache \
    OPENCLAW_NO_RESPAWN=1

SHELL ["/bin/bash", "-o", "pipefail", "-c"]

RUN rm -rf /root/.openclaw \
    && mkdir -p /var/tmp/openclaw-compile-cache \
    && npm config delete proxy || true \
    && npm config delete https-proxy || true \
    && npm install -g --ignore-scripts --no-audit "openclaw@${OPENCLAW_VERSION}" \
    && ln -sf "$(command -v node)" /usr/local/bin/node \
    && ln -sf "$(command -v npm)" /usr/local/bin/npm \
    && ln -sf "$(command -v npx)" /usr/local/bin/npx \
    && ln -sf "$(command -v openclaw)" /usr/local/bin/openclaw \
    && openclaw --version | tee /usr/local/share/openclaw-version.txt
