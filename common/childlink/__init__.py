# SPDX-FileCopyrightText: 2026 旭川工業高等専門学校 最先端テクノロジー同好会
# SPDX-License-Identifier: GPL-3.0-or-later

"""親機 ⇔ 子機 UDP 通信。標準ライブラリのみ。"""
from . import proto
from .child import ChildController
from .parent import ChildClient

__all__ = ["proto", "ChildController", "ChildClient"]
