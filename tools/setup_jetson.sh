#!/bin/bash
# 親機 Jetson（JetPack 7 / Ubuntu 24.04）の開発環境を構築する。
# 使い方（clone したリポジトリ直下で）: sudo ./tools/setup_jetson.sh [--no-ros] [--no-pio]
# 何度実行しても同じ結果になるように書く（済んでいる手順は飛ばす）。
set -euo pipefail

ROS_DISTRO=jazzy
WITH_ROS=1
WITH_PIO=1
for arg in "$@"; do
  case "$arg" in
    --no-ros) WITH_ROS=0 ;;
    --no-pio) WITH_PIO=0 ;;
    -h|--help) sed -n '2,4p' "$0"; exit 0 ;;
    *) echo "unknown option: $arg" >&2; exit 2 ;;
  esac
done

REPO_DIR="$(cd "$(dirname "$0")/.." && pwd)"
log()  { echo -e "\n\033[1;32m==> $*\033[0m"; }
warn() { echo -e "\033[1;33m[warn] $*\033[0m" >&2; }

if [ "$(id -u)" -ne 0 ]; then
  echo "sudo で実行してください: sudo $0 $*" >&2
  exit 1
fi
DEV_USER="${SUDO_USER:-}"
if [ -z "$DEV_USER" ] || [ "$DEV_USER" = root ]; then
  warn "SUDO_USER が分からないため、ユーザー単位の設定（dialout・PlatformIO）は飛ばします"
  DEV_USER=""
fi

. /etc/os-release
if [ "${VERSION_ID:-}" != "24.04" ]; then
  echo "Ubuntu 24.04 専用です（この環境: ${PRETTY_NAME:-unknown}）" >&2
  exit 1
fi
IS_JETSON=0
[ -f /etc/nv_tegra_release ] && IS_JETSON=1
[ "$IS_JETSON" -eq 1 ] || warn "Jetson ではありません。Jetson 固有の手順は飛ばします"

export DEBIAN_FRONTEND=noninteractive

log "基本パッケージ"
apt-get update
apt-get install -y --no-install-recommends \
  build-essential cmake git curl ca-certificates gnupg locales \
  software-properties-common \
  python3 python3-venv python3-pip pipx python3-aiohttp \
  v4l-utils ffmpeg usbutils udev

log "ロケール（UTF-8）"
locale-gen en_US.UTF-8 >/dev/null
update-locale LANG=en_US.UTF-8

if [ "$WITH_ROS" -eq 1 ]; then
  log "ROS 2 ${ROS_DISTRO} の apt リポジトリ"
  add-apt-repository -y universe
  if ! dpkg -s ros2-apt-source >/dev/null 2>&1; then
    ver=$(curl -fsSL https://api.github.com/repos/ros-infrastructure/ros-apt-source/releases/latest \
          | grep -F '"tag_name"' | awk -F'"' '{print $4}')
    [ -n "$ver" ] || { echo "ros-apt-source の版が取得できません（ネット接続を確認）" >&2; exit 1; }
    tmp=$(mktemp -d)
    curl -fsSL -o "$tmp/ros2-apt-source.deb" \
      "https://github.com/ros-infrastructure/ros-apt-source/releases/download/${ver}/ros2-apt-source_${ver}.${VERSION_CODENAME}_all.deb"
    apt-get install -y "$tmp/ros2-apt-source.deb"
    rm -rf "$tmp"
  fi
  apt-get update

  log "ROS 2 ${ROS_DISTRO} 本体"
  apt-get install -y \
    ros-${ROS_DISTRO}-ros-base ros-dev-tools \
    ros-${ROS_DISTRO}-slam-toolbox \
    ros-${ROS_DISTRO}-robot-localization \
    ros-${ROS_DISTRO}-tf2-tools

  # 無くても開発は始められるもの。入らなければ警告だけ出して続ける
  log "ROS 2 追加パッケージ（任意）"
  for pkg in ros-${ROS_DISTRO}-realsense2-camera ros-${ROS_DISTRO}-rosbag2-storage-mcap; do
    apt-get install -y "$pkg" || warn "$pkg が入りませんでした"
  done

  log "rosdep"
  [ -f /etc/ros/rosdep/sources.list.d/20-default.list ] || rosdep init
  if [ -n "$DEV_USER" ]; then
    sudo -u "$DEV_USER" -H rosdep update
    bashrc="$(getent passwd "$DEV_USER" | cut -d: -f6)/.bashrc"
    line="source /opt/ros/${ROS_DISTRO}/setup.bash"
    grep -qxF "$line" "$bashrc" 2>/dev/null || echo "$line" >> "$bashrc"
  fi
fi

if [ -n "$DEV_USER" ]; then
  log "シリアルポートの権限（dialout）"
  usermod -aG dialout "$DEV_USER"

  if [ "$WITH_PIO" -eq 1 ]; then
    log "PlatformIO（pipx、ユーザー ${DEV_USER}）"
    sudo -u "$DEV_USER" -H pipx install platformio || sudo -u "$DEV_USER" -H pipx upgrade platformio
    sudo -u "$DEV_USER" -H pipx ensurepath
  fi
fi

log "udev ルール"
for f in "$REPO_DIR"/parent/udev/*.rules; do
  [ -e "$f" ] || continue
  install -m 0644 "$f" /etc/udev/rules.d/
  echo "  $(basename "$f")"
done
if command -v udevadm >/dev/null && [ -d /run/udev ]; then
  udevadm control --reload-rules && udevadm trigger || warn "udev の再読み込みに失敗しました"
fi

if [ "$IS_JETSON" -eq 1 ]; then
  log "Jetson の状態"
  nvpmodel -q 2>/dev/null || true
  echo "最大性能にするには: sudo nvpmodel -m <MAXN の番号> && sudo jetson_clocks"
fi

log "完了"
[ -n "$DEV_USER" ] && echo "dialout グループを反映するため、一度ログインし直してください。"
