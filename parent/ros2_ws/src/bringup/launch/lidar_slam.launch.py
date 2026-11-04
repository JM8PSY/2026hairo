# SPDX-FileCopyrightText: 2026 旭川工業高等専門学校 最先端テクノロジー同好会
# SPDX-License-Identifier: GPL-3.0-or-later

# YD-LiDAR + slam_toolbox で 2D 地図を作る（CLAUDE.md §7）
import os

from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import IncludeLaunchDescription
from launch.launch_description_sources import PythonLaunchDescriptionSource
from launch_ros.actions import Node


def static_tf(parent, child):
    return Node(
        package="tf2_ros",
        executable="static_transform_publisher",
        name=f"tf_{parent}_{child}",
        arguments=["--frame-id", parent, "--child-frame-id", child],
    )


def generate_launch_description():
    config = os.path.join(get_package_share_directory("bringup"), "config")
    slam_launch = os.path.join(
        get_package_share_directory("slam_toolbox"), "launch", "online_async_launch.py")
    return LaunchDescription([
        Node(
            package="ydlidar_ros2_driver",
            executable="ydlidar_ros2_driver_node",
            name="ydlidar_ros2_driver_node",
            output="screen",
            parameters=[os.path.join(config, "ydlidar_x4_pro.yaml")],
        ),
        # 機体寸法が決まるまで仮の値（原点に一致）。CLAUDE.md §7 の寸法表で置き換える
        static_tf("base_link", "laser_frame"),
        # オドメトリの方式が決まるまでの仮置き。スキャンマッチングだけで自己位置を求める
        static_tf("odom", "base_link"),
        IncludeLaunchDescription(
            PythonLaunchDescriptionSource(slam_launch),
            launch_arguments={
                "use_sim_time": "false",
                "slam_params_file": os.path.join(config, "slam_toolbox.yaml"),
            }.items(),
        ),
    ])
