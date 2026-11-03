# 実機なしで回すテスト。Mac と Jetson の両方で通ること。
.PHONY: test test-fw test-py test-setup clean

test: test-fw test-py

test-fw:
	$(MAKE) -C firmware/motor_esp32/test_host test

test-py:
	python3 -m unittest discover -s common -t common
	python3 -m unittest discover -s parent/server -t parent/server

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
