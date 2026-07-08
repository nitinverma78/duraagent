FROM mcr.microsoft.com/devcontainers/python:1-3.11-bullseye

# Install uv for fast dependency management
RUN curl -LsSf https://astral.sh/uv/install.sh | sh
ENV PATH="/root/.cargo/bin:$PATH"

# Setup the workspace
WORKDIR /workspace
