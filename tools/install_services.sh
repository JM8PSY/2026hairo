#!/bin/bash
# SPDX-FileCopyrightText: 2026 旭川工業高等専門学校 最先端テクノロジー同好会
# SPDX-License-Identifier: GPL-3.0-or-later

# systemd ユニットを入れる（有効化はしない。自動起動したいときは表示されるコマンドを実行する）
# 使い方: sudo ./tools/install_services.sh parent|child
set -euo pipefail
ROLE="${1:-}"
case "$ROLE" in
  parent) UNITS=(parent/systemd/hairo-web.service parent/systemd/hairo-video.service) ;;
  child)  UNITS=(child/systemd/hairo-child.service) ;;
  *) echo "usage: sudo $0 parent|child" >&2; exit 2 ;;
esac
[ "$(id -u)" -eq 0 ] || { echo "sudo で実行してください" >&2; exit 1; }
REPO="$(cd "$(dirname "$0")/.." && pwd)"
USER_NAME="${SUDO_USER:?SUDO_USER が必要です（sudo 経由で実行）}"
for u in "${UNITS[@]}"; do
  name="$(basename "$u")"
  sed -e "s|@USER@|$USER_NAME|g" -e "s|@REPO@|$REPO|g" "$REPO/$u" > "/etc/systemd/system/$name"
  echo "installed /etc/systemd/system/$name"
done
systemctl daemon-reload
echo "起動:     sudo systemctl start ${UNITS[*]##*/}"
echo "自動起動: sudo systemctl enable ${UNITS[*]##*/}"
