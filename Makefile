# SPDX-FileCopyrightText: 2026 旭川工業高等専門学校 最先端テクノロジー同好会
# SPDX-License-Identifier: GPL-3.0-or-later

# 実機なしで回すテスト。Mac と Jetson の両方で通ること。
.PHONY: test test-fw test-py test-web test-docker test-setup clean

test: test-fw test-py test-web

test-fw:
	$(MAKE) -C firmware/motor_esp32/test_host test

test-py:
	python3 -m unittest discover -s common -t common
	python3 -m unittest discover -s parent/server -t parent/server

# Web UI の入力変換（node があるときだけ。Jetson には node を入れていないのでスキップされる）
test-web:
	@if command -v node >/dev/null; then node --test web/tests/*.test.mjs; else echo "node が無いので Web UI のテストをスキップ"; fi

# Ubuntu 24.04（apt の python3-aiohttp 入り）で make test を回す。Mac に aiohttp が無くても Web サーバーまでテストできる
test-docker:
	docker build -q -t hairo-test -f tools/docker/test.Dockerfile tools/docker >/dev/null
	docker run --rm -v "$(CURDIR)":/src:ro hairo-test bash -c \
	  'cp -r /src /repo && cd /repo && make clean >/dev/null && make test'

# tools/setup_jetson.sh を arm64 の Ubuntu 24.04 コンテナで実行する（Docker が必要、数分かかる）
test-setup:
	docker run --rm --platform linux/arm64 -v "$(CURDIR)":/repo:ro ubuntu:24.04 bash -c '\
	  set -e; apt-get update -qq && apt-get install -y -qq sudo >/dev/null; \
	  useradd -m -s /bin/bash jetson; \
	  cd /repo; \
	  SUDO_USER=jetson ./tools/setup_jetson.sh && \
	  sudo -u jetson -i bash -c "source /opt/ros/jazzy/setup.bash && ros2 pkg list | grep -E \"^(slam_toolbox|robot_localization)$$\" && ~/.local/bin/pio --version"'

clean:
	$(MAKE) -C firmware/motor_esp32/test_host clean
