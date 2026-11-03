"""基板ごとのモーター名（firmware/motor_esp32/include/board_config.h と同じ並び）。"""
from . import proto

MOTOR_NAMES = {
    proto.BOARD_ID_PARENT: ["P1", "P2", "P3", "P4", "P5", "P6", "P7", "P8", "P9"],
    proto.BOARD_ID_CHILD: ["C1", "C2", "C3"],
}

BOARD_IDS = {"parent": proto.BOARD_ID_PARENT, "child": proto.BOARD_ID_CHILD}
