FROM mcr.microsoft.com/devcontainers/python:1-3.11-bullseye

# Install uv globally by copying the binary from the official image
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

# Setup the workspace
WORKDIR /workspace
