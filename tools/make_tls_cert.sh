#!/bin/bash
# SPDX-FileCopyrightText: 2026 旭川工業高等専門学校 最先端テクノロジー同好会
# SPDX-License-Identifier: GPL-3.0-or-later

# Meta Quest の WebXR に必要な HTTPS 用の自己署名証明書を作る（秘密鍵は git 管理外）。
# 親機の IP アドレスが変わったら作り直す。使い方: ./tools/make_tls_cert.sh
set -euo pipefail
REPO="$(cd "$(dirname "$0")/.." && pwd)"
DIR="$REPO/parent/config/tls"
mkdir -p "$DIR"
SAN="DNS:localhost,IP:127.0.0.1"
for ip in $(hostname -I 2>/dev/null); do
  case "$ip" in
    *:*) ;; # IPv6 は使わない
    *) SAN="$SAN,IP:$ip" ;;
  esac
done
openssl req -x509 -newkey rsa:2048 -nodes -days 3650 -subj "/CN=hairo-robot" \
  -addext "subjectAltName=$SAN" -keyout "$DIR/key.pem" -out "$DIR/cert.pem" 2>/dev/null
chmod 600 "$DIR/key.pem"
echo "作成しました: $DIR（$SAN）"
