FROM ubuntu:24.04

ENV NVM_DIR=/root/.nvm

RUN apt-get update \
    && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
        ca-certificates \
        curl \
        git \
        xz-utils \
        python3 \
        python3-pip \
    && rm -rf /var/lib/apt/lists/*

# Install Node.js and OpenClaw
RUN curl -o- https://raw.githubusercontent.com/nvm-sh/nvm/v0.40.1/install.sh | bash \
    && . "$NVM_DIR/nvm.sh" \
    && nvm install 20 \
    && nvm use 20 \
    && nvm alias default 20 \
    && npm config set registry https://registry.npmmirror.com/ \
    && npm install -g --ignore-scripts --no-audit openclaw@latest \
    && ln -s "$(command -v node)" /usr/local/bin/node \
    && ln -s "$(command -v npm)" /usr/local/bin/npm \
    && ln -s "$(command -v npx)" /usr/local/bin/npx \
    && ln -s "$(command -v openclaw)" /usr/local/bin/openclaw \
    && openclaw --version

# Install Python dependencies for grading
RUN pip install --no-cache-dir openai>=1.0.0 pyyaml>=6.0.1 anthropic>=0.20.0

# Copy skills into the container at /skills so Harbor can distribute them
# to OpenClaw's native skills directory via the skills_dir config.
COPY skills/ /skills/

WORKDIR /app
