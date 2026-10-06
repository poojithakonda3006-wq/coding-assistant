FROM python:3.12-slim

ENV DEBIAN_FRONTEND=noninteractive
RUN apt-get update \
    && apt-get install -y --no-install-recommends nodejs npm default-jdk gcc g++ \
    && npm install --global typescript \
    && python -m pip install --no-cache-dir pylint \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

RUN useradd --uid 10001 --no-create-home --shell /usr/sbin/nologin runner \
    && mkdir -p /workspace \
    && chown runner:runner /workspace

WORKDIR /workspace
USER 10001:10001
