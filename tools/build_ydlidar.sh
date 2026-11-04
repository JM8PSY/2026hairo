#!/bin/bash
# SPDX-FileCopyrightText: 2026 旭川工業高等専門学校 最先端テクノロジー同好会
# SPDX-License-Identifier: GPL-3.0-or-later

# YD-LiDAR の SDK と ROS 2 ドライバをソースからビルドする（sudo 不要・apt に無いため）。
# ソースは git 管理外。Jazzy 向けの公式ブランチが無いので humble ブランチを固定して使う。
# 実行後: source parent/ros2_ws/install/setup.bash
set -euo pipefail

SDK_COMMIT=e008f32ed7477c6351b49e2215f8fc5a797b8959
DRIVER_COMMIT=4ef70d3f32a85704ade0be54b214f3763b1ab3e8

REPO_DIR="$(cd "$(dirname "$0")/.." && pwd)"
WS="$REPO_DIR/parent/ros2_ws"
THIRD="$WS/third_party"
SDK_SRC="$THIRD/YDLidar-SDK"
SDK_PREFIX="$THIRD/sdk_install"
DRIVER_SRC="$WS/src/ydlidar_ros2_driver"

log() { echo "==> $*"; }

# fetch URL DIR COMMIT
fetch() {
  [ -d "$2/.git" ] || git clone "$1" "$2"
  git -C "$2" cat-file -e "$3^{commit}" 2>/dev/null || git -C "$2" fetch origin
  git -C "$2" checkout -q "$3"
}

mkdir -p "$THIRD"
log "ソースの取得"
fetch https://github.com/YDLIDAR/YDLidar-SDK.git "$SDK_SRC" "$SDK_COMMIT"
fetch https://github.com/YDLIDAR/ydlidar_ros2_driver.git "$DRIVER_SRC" "$DRIVER_COMMIT"

log "SDK のビルド"
cmake -S "$SDK_SRC" -B "$THIRD/sdk_build" \
  -DCMAKE_BUILD_TYPE=Release -DCMAKE_INSTALL_PREFIX="$SDK_PREFIX" \
  -DCMAKE_POSITION_INDEPENDENT_CODE=ON -DBUILD_EXAMPLES=OFF
cmake --build "$THIRD/sdk_build" -j"$(nproc)"
cmake --install "$THIRD/sdk_build"

log "ROS 2 ドライバのビルド"
# ROS の setup.bash は未定義変数を参照する
set +u
# shellcheck disable=SC1091
source /opt/ros/jazzy/setup.bash
set -u
cd "$WS"
# 上流の CMakeLists は C++14 指定だが、Jazzy の rclcpp は C++17 が必要。
# SDK の CMake 設定はライブラリの場所を渡さないので、リンカに直接教える。
colcon build --packages-select ydlidar_ros2_driver --cmake-args \
  -DCMAKE_BUILD_TYPE=Release -DCMAKE_CXX_STANDARD=17 \
  -DCMAKE_EXE_LINKER_FLAGS="-L$SDK_PREFIX/lib" \
  -DCMAKE_PREFIX_PATH="$SDK_PREFIX;$AMENT_PREFIX_PATH"

log "完了: source $WS/install/setup.bash"
