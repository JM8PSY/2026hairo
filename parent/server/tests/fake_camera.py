# SPDX-FileCopyrightText: 2026 旭川工業高等専門学校 最先端テクノロジー同好会
# SPDX-License-Identifier: GPL-3.0-or-later

"""テスト用の偽カメラ：連結した JPEG を標準出力へ出す。  fake_camera.py FPS [枚数で終了]"""
import sys
import time

fps = float(sys.argv[1])
limit = int(sys.argv[2]) if len(sys.argv) > 2 else None
n = 0
while limit is None or n < limit:
    n += 1
    sys.stdout.buffer.write(b"\xff\xd8" + n.to_bytes(4, "big") + b"\xff\xd9")
    sys.stdout.buffer.flush()
    time.sleep(1.0 / fps)
