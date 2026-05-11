FROM python:3.12-slim

# Install base dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    git \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# Install common Python packages
RUN pip install --no-cache-dir \
    pyyaml \
    requests \
    numpy \
    pandas

WORKDIR /workspace

# Copy fixtures if directory exists (fixtures are optional for Claw-Eval tasks)
# COPY fixtures/ /workspace/fixtures/

CMD ["/bin/bash"]
