// SPDX-FileCopyrightText: 2026 旭川工業高等専門学校 最先端テクノロジー同好会
// SPDX-License-Identifier: GPL-3.0-or-later

// VR ページの DOM・WebGL に依存しない部分（node --test で検査する）。行列は列優先。

// 正距円筒図を内側から見る球。画像の中央が正面（-Z）、u が増えると右（+X）、v = 0 が真上
export function makeSphere(radius, lonSegments, latSegments) {
  const vertices = [];
  const indices = [];
  for (let j = 0; j <= latSegments; j++) {
    const v = j / latSegments;
    const lat = (0.5 - v) * Math.PI;
    for (let i = 0; i <= lonSegments; i++) {
      const u = i / lonSegments;
      const lon = (u - 0.5) * 2 * Math.PI;
      vertices.push(
        radius * Math.cos(lat) * Math.sin(lon),
        radius * Math.sin(lat),
        -radius * Math.cos(lat) * Math.cos(lon),
        u,
        v,
      );
    }
  }
  const row = lonSegments + 1;
  for (let j = 0; j < latSegments; j++) {
    for (let i = 0; i < lonSegments; i++) {
      const a = j * row + i;
      indices.push(a, a + row, a + 1, a + 1, a + row, a + row + 1);
    }
  }
  return { vertices: new Float32Array(vertices), indices: new Uint32Array(indices) };
}

// 視界の正面に置く板（「映像なし」の表示用）。頭に固定する
export function makeQuad(width, height, z) {
  const x = width / 2;
  const y = height / 2;
  return {
    vertices: new Float32Array([
      -x, y, z, 0, 0,
      x, y, z, 1, 0,
      -x, -y, z, 0, 1,
      x, -y, z, 1, 1,
    ]),
    indices: new Uint32Array([0, 2, 1, 1, 2, 3]),
  };
}

// カメラは球の中心に固定なので、頭の移動は無視して回転だけ使う
export function rotationOnly(matrix) {
  const m = Float32Array.from(matrix);
  m[12] = 0;
  m[13] = 0;
  m[14] = 0;
  return m;
}

export function perspective(fovYDeg, aspect, near, far) {
  const f = 1 / Math.tan((fovYDeg * Math.PI) / 360);
  const m = new Float32Array(16);
  m[0] = f / aspect;
  m[5] = f;
  m[10] = (far + near) / (near - far);
  m[11] = -1;
  m[14] = (2 * far * near) / (near - far);
  return m;
}

export const IDENTITY = Float32Array.of(1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1);
