# Jetson（Ubuntu 24.04）と同じ apt パッケージで `make test` を回すためのイメージ（ROS は入れない）
FROM ubuntu:24.04
RUN apt-get update && apt-get install -y --no-install-recommends \
      build-essential make python3 python3-aiohttp && rm -rf /var/lib/apt/lists/*
