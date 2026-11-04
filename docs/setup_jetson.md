# 親機 Jetson の環境構築

対象：Jetson Orin Nano Developer Kit Super、JetPack 7.2.1（Ubuntu 24.04）

## 手順

```bash
git clone https://github.com/JM8PSY/2026hairo.git
cd 2026hairo
sudo ./tools/setup_jetson.sh      # ROS 2 Jazzy・PlatformIO・udev ルールなど
# ログインし直す（dialout グループの反映）
make test                         # 単体テストが通ることを確認
```

オプション：`--no-ros`（ROS 2 を入れない）、`--no-pio`（PlatformIO を入れない）。何度実行してもよい。

## スクリプトが入れるもの

| 種類 | 内容 |
|------|------|
| 基本 | build-essential, cmake, git, python3-aiohttp, pipx, v4l-utils, ffmpeg |
| ROS 2 Jazzy | ros-base, ros-dev-tools, slam_toolbox, robot_localization, tf2_tools |
| ROS 2（任意） | realsense2_camera, rosbag2 mcap（入らなくても続行） |
| その他 | PlatformIO（pipx）、dialout グループ、`parent/udev/*.rules` |

## 常駐させる（systemd）

```bash
sudo ./tools/install_services.sh parent   # /etc/systemd/system/hairo-web.service を入れる（有効化はしない）
sudo systemctl start hairo-web            # 手動で起動
sudo systemctl enable hairo-web           # 起動時に自動で立ち上げる場合
journalctl -u hairo-web -f                # ログ
```

子機（Raspberry Pi）では `sudo ./tools/install_services.sh child`（`hairo-child.service`）。

## まだ手作業が要るもの

- **udev ルールのシリアル番号**：`parent/udev/99-robot.rules` の `CHANGE_ME_*` を実機の値に書き換える（YD-LiDAR はシリアル番号が 0001 で識別できないため、USB ポートの位置で設定済み。挿すポートを変えたら書き換える）。
- **電源モード**：`sudo nvpmodel -q` で確認し、MAXN 系に設定してから `sudo jetson_clocks`。
- **YD-LiDAR**：`YDLidar-SDK` と `ydlidar_ros2_driver` はソースからビルドする（sudo 不要）。

  ```bash
  ./tools/build_ydlidar.sh
  ```

- **2D SLAM**（YD-LiDAR + `slam_toolbox`）：

  ```bash
  cd parent/ros2_ws
  colcon build --packages-select bringup
  source install/setup.bash
  ros2 launch bringup lidar_slam.launch.py
  ```

  オドメトリの方式が未定のため、`odom → base_link` は固定（仮）で、スキャンマッチングだけで自己位置を求める。
- **RealSense**：apt の `realsense2_camera` で D455 が認識されない場合は、librealsense を `-DFORCE_RSUSB_BACKEND=ON` でソースビルドする。

## 検証

このスクリプトは Mac（arm64）の Docker で `ubuntu:24.04` を使って動作確認している（Jetson 固有の手順は飛ばされる）：

```bash
make test-setup
```
