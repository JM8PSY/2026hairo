// SPDX-FileCopyrightText: 2026 旭川工業高等専門学校 最先端テクノロジー同好会
// SPDX-License-Identifier: GPL-3.0-or-later

// ESP32 シミュレータ：仮想シリアル（pty）上で motor_core を動かし、実機の ESP32 のふりをする。
// 使い方: ./motor_sim parent|child [--link PATH]
//   起動すると pty のパスを1行目に表示する（--link を付けるとそのパスにシンボリックリンクを張る）。
//   上位プログラムはそのパスを /dev/robot_mcu の代わりに開けばよい。
//   標準入力に "limit <hex>" を入れるとリミット入力を、"fault" で I2C 故障を模擬する。
#include <fcntl.h>
#include <poll.h>
#include <termios.h>
#include <unistd.h>

#include <chrono>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <string>

#if defined(__APPLE__)
#include <util.h>
#else
#include <pty.h>
#endif

#include "board_config.h"
#include "motor_core.h"
#include "proto.h"

static uint32_t now_ms() {
  using namespace std::chrono;
  static const auto t0 = steady_clock::now();
  return static_cast<uint32_t>(duration_cast<milliseconds>(steady_clock::now() - t0).count());
}

static void write_all(int fd, const uint8_t* p, size_t n) {
  while (n > 0) {
    ssize_t w = write(fd, p, n);
    if (w <= 0) return;  // 相手が開いていない間は捨てる
    p += w;
    n -= static_cast<size_t>(w);
  }
}

int main(int argc, char** argv) {
  if (argc < 2 || (strcmp(argv[1], "parent") && strcmp(argv[1], "child"))) {
    std::fprintf(stderr, "usage: %s parent|child [--link PATH]\n", argv[0]);
    return 2;
  }
  const motor_core::BoardConfig& cfg = strcmp(argv[1], "parent") == 0 ? board::kParent : board::kChild;
  const char* link = (argc >= 4 && strcmp(argv[2], "--link") == 0) ? argv[3] : nullptr;

  int master, slave;
  char name[256];
  if (openpty(&master, &slave, name, nullptr, nullptr) < 0) {
    perror("openpty");
    return 1;
  }
  termios tio;
  tcgetattr(slave, &tio);
  cfmakeraw(&tio);
  tcsetattr(slave, TCSANOW, &tio);
  fcntl(master, F_SETFL, fcntl(master, F_GETFL) | O_NONBLOCK);
  if (link) {
    unlink(link);
    if (symlink(name, link) < 0) perror("symlink");
  }
  std::printf("%s\n", name);
  std::fflush(stdout);

  motor_core::Controller c(cfg);
  proto::Parser parser;
  uint8_t seq = 0;
  uint16_t limits = 0;
  uint32_t last_status = 0;
  uint8_t out[proto::MAX_FRAME];

  // 起動時に INFO を出す（実機と同じ）
  write_all(master, out, c.build_info(seq++, out, sizeof(out)));

  for (;;) {
    pollfd fds[2] = {{master, POLLIN, 0}, {STDIN_FILENO, POLLIN, 0}};
    poll(fds, 2, 5);
    if (fds[0].revents & POLLIN) {
      uint8_t buf[256];
      ssize_t n = read(master, buf, sizeof(buf));
      for (ssize_t i = 0; i < n; ++i) {
        if (!parser.feed(buf[i])) continue;
        size_t r = c.on_frame(parser.frame(), now_ms(), out, sizeof(out));
        if (r) write_all(master, out, r);
      }
    }
    if (fds[1].revents & POLLIN) {
      char line[128];
      if (!fgets(line, sizeof(line), stdin)) {
        fds[1].fd = -1;  // stdin が閉じても続ける
      } else if (strncmp(line, "limit ", 6) == 0) {
        limits = static_cast<uint16_t>(strtoul(line + 6, nullptr, 16));
      } else if (strncmp(line, "fault", 5) == 0) {
        c.set_fault(motor_core::FAULT_I2C);
      }
    }
    const uint32_t t = now_ms();
    c.tick(t, limits);
    if (c.take_reinit_request()) {
      // 実機ではここで PCA9685 を再初期化する。シミュレータでは常に成功
    }
    if (t - last_status >= 50) {  // STATUS 20Hz
      last_status = t;
      write_all(master, out, c.build_status(seq++, parser.errors(), out, sizeof(out)));
    }
  }
}
