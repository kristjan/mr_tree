// Mr Tree effects, ported from the CircuitPython app to plain C++.
//
// Pure C++ on purpose: this header pulls in no ESPHome types, only <cmath> and the
// generated tree_coords.h, so the math matches the originals and can be reasoned
// about in isolation. Each effect exposes a `*_step(now, params...)` that advances
// its state once per frame and a `*_color(i)` that returns the RGB for LED i.
//
// The ESPHome addressable_lambda does: <effect>_step(...);  then
//   for (i) it[i] = Color(<effect>_color(i));
//
// Power cap: every effect color is scaled by MAX_BRIGHT (0.30) so full-white output
// stays within the 5V/2.4A budget. color_correct at the light level backstops the
// base color (it does NOT reach these lambda writes — confirmed on hardware).
#pragma once
#include <cmath>
#include <cstdint>
#include <cstdlib>
#include <algorithm>
#include "tree_coords.h"

namespace tree {

struct RGB { uint8_t r, g, b; };

// Full-range output. The power cap is applied ONCE, at the light level, by
// color_correct: [30%,30%,30%] in mr_tree.yaml — ESPHome's ESPColorView::set_red()
// applies that correction to every effect pixel at write time (see esp_color_view.h),
// so capping again here would double-dim (0.30*0.30 = 9%). Keep at 1.0.
static constexpr float MAX_BRIGHT = 1.0f;
static constexpr int TRUNK_LED_COUNT = 36;   // cherry-blossom trunk split (by height)
static constexpr float TWO_PI = 6.28318530718f;

// ---------- helpers ----------------------------------------------------------

static inline float clampf(float v, float lo, float hi) { return v < lo ? lo : (v > hi ? hi : v); }
static inline float frac(float v) { v = fmodf(v, 1.0f); return v < 0 ? v + 1.0f : v; }
static inline float frand() { return (float) rand() / ((float) RAND_MAX + 1.0f); }
static inline float frand_range(float a, float b) { return a + (b - a) * frand(); }

// h,s,v in 0..1 -> RGB, already scaled by the power cap.
static inline RGB hsv(float h, float s, float v) {
  h = frac(h) * 6.0f;
  int i = (int) h;
  float f = h - i;
  float p = v * (1.0f - s);
  float q = v * (1.0f - s * f);
  float t = v * (1.0f - s * (1.0f - f));
  float r, g, b;
  switch (i % 6) {
    case 0: r = v; g = t; b = p; break;
    case 1: r = q; g = v; b = p; break;
    case 2: r = p; g = v; b = t; break;
    case 3: r = p; g = q; b = v; break;
    case 4: r = t; g = p; b = v; break;
    default: r = v; g = p; b = q; break;
  }
  return RGB{ (uint8_t)(r * 255.0f * MAX_BRIGHT), (uint8_t)(g * 255.0f * MAX_BRIGHT), (uint8_t)(b * 255.0f * MAX_BRIGHT) };
}

// Scale a raw 0-255 RGB triple by the power cap.
static inline RGB rgb_cap(float r, float g, float b) {
  return RGB{ (uint8_t)(r * MAX_BRIGHT), (uint8_t)(g * MAX_BRIGHT), (uint8_t)(b * MAX_BRIGHT) };
}

static inline float shortest(float delta) {   // hue wrap, shortest signed path
  if (delta > 0.5f) return delta - 1.0f;
  if (delta < -0.5f) return delta + 1.0f;
  return delta;
}

// ---------- geometry (computed once) -----------------------------------------

struct Geom {
  bool ready = false;
  float zmin, zmax, cx, cy;
  float znorm[TREE_NUM_LEDS];   // 0..1 by raw height
  float angle[TREE_NUM_LEDS];   // 0..1 around the x-y centroid
  bool is_trunk[TREE_NUM_LEDS]; // lowest TRUNK_LED_COUNT by height
  int branch_order[4];          // distinct branch seg ids (1..4) sorted by angle
  int n_branches = 0;
};
static Geom g_geom;

static void geom_init() {
  Geom &G = g_geom;
  if (G.ready) return;
  int n = TREE_NUM_LEDS;

  G.zmin = G.zmax = TREE_LEDS[0].z;
  double sx = 0, sy = 0;
  for (int i = 0; i < n; i++) {
    G.zmin = std::min(G.zmin, TREE_LEDS[i].z);
    G.zmax = std::max(G.zmax, TREE_LEDS[i].z);
    sx += TREE_LEDS[i].x;
    sy += TREE_LEDS[i].y;
  }
  G.cx = (float)(sx / n);
  G.cy = (float)(sy / n);
  float zspan = (G.zmax - G.zmin);
  if (zspan == 0) zspan = 1;

  for (int i = 0; i < n; i++) {
    G.znorm[i] = (TREE_LEDS[i].z - G.zmin) / zspan;
    G.angle[i] = frac(atan2f(TREE_LEDS[i].y - G.cy, TREE_LEDS[i].x - G.cx) / TWO_PI);
  }

  // Trunk = lowest TRUNK_LED_COUNT LEDs by height.
  int idx[TREE_NUM_LEDS];
  for (int i = 0; i < n; i++) idx[i] = i;
  std::sort(idx, idx + n, [](int a, int b) { return TREE_LEDS[a].z < TREE_LEDS[b].z; });
  for (int i = 0; i < n; i++) G.is_trunk[i] = false;
  for (int i = 0; i < TRUNK_LED_COUNT && i < n; i++) G.is_trunk[idx[i]] = true;

  // Branch seg ids (1..4) present, ordered by their centroid angle around (cx,cy).
  double bx[5] = {0}, by[5] = {0};
  int bc[5] = {0};
  for (int i = 0; i < n; i++) {
    int s = TREE_LEDS[i].seg;
    if (s >= 1 && s <= 4) { bx[s] += TREE_LEDS[i].x; by[s] += TREE_LEDS[i].y; bc[s]++; }
  }
  int order[4]; int m = 0;
  for (int s = 1; s <= 4; s++) if (bc[s] > 0) order[m++] = s;
  auto bang = [&](int s) { return atan2f((float)(by[s] / bc[s]) - G.cy, (float)(bx[s] / bc[s]) - G.cx); };
  std::sort(order, order + m, [&](int a, int b) { return bang(a) < bang(b); });
  for (int i = 0; i < m; i++) G.branch_order[i] = order[i];
  G.n_branches = m;

  srand(42);        // deterministic per-LED jitter for cherry_blossom / hue_shift
  G.ready = true;
}

// ---------- rainbow_cycle ----------------------------------------------------
// hue = znorm * bandwidth - phase, phase accumulated from a scroll frequency.

struct RainbowState { float phase = 0; float last = -1; };
static RainbowState g_rainbow;

// speed 0..1 -> frequency 0.1..2.0 cycles/s (matches Tree.set_speed for RainbowCycle).
static void rainbow_step(float now, float speed, float bandwidth) {
  geom_init();
  RainbowState &S = g_rainbow;
  if (S.last < 0) S.last = now;
  float dt = now - S.last; S.last = now;
  if (dt > 0.1f) dt = 0.1f;
  float freq = 0.1f + clampf(speed, 0, 1) * 1.9f;
  S.phase = frac(S.phase + freq * dt);
}
static RGB rainbow_color(int i, float bandwidth) {
  return hsv(frac(g_geom.znorm[i] * bandwidth - g_rainbow.phase), 1.0f, 1.0f);
}

// ---------- pinwheel ---------------------------------------------------------
// hue = angle * repeats + offset, offset accumulated from rotation speed.

struct PinwheelState { float offset = 0; float last = -1; };
static PinwheelState g_pinwheel;

static void pinwheel_step(float now, float rotation_speed) {
  geom_init();
  PinwheelState &S = g_pinwheel;
  if (S.last < 0) S.last = now;
  float dt = now - S.last; S.last = now;
  if (dt > 0.1f) dt = 0.1f;
  S.offset = frac(S.offset + (0.05f + clampf(rotation_speed, 0, 1) * 0.45f) * dt);
}
static RGB pinwheel_color(int i, int repeats) {
  return hsv(frac(g_geom.angle[i] * repeats + g_pinwheel.offset), 1.0f, 1.0f);
}

// ---------- cherry_blossom ---------------------------------------------------
// Brown trunk, warm-white branches, a pink_fraction subset twinkling white<->pink.

struct CherryState { float wt = 0; float last = -1; bool init = false; float rank[TREE_NUM_LEDS]; float phase[TREE_NUM_LEDS]; };
static CherryState g_cherry;

static void cherry_step(float now, float twinkle_speed) {
  geom_init();
  CherryState &S = g_cherry;
  if (!S.init) {
    for (int i = 0; i < TREE_NUM_LEDS; i++) { S.rank[i] = frand(); S.phase[i] = frand_range(0, TWO_PI); }
    S.init = true;
  }
  if (S.last < 0) S.last = now;
  float dt = now - S.last; S.last = now;
  if (dt > 0.1f) dt = 0.1f;
  float freq = 0.1f + clampf(twinkle_speed, 0, 1) * 0.5f;   // Hz
  S.wt = fmodf(S.wt + freq * TWO_PI * dt, TWO_PI);
}
static RGB cherry_color(int i, float pink_fraction) {
  const float TRUNK[3] = {90, 45, 18};
  const float BRANCH[3] = {255, 197, 143};
  const float PINK[3] = {255, 40, 110};
  if (g_geom.is_trunk[i]) return rgb_cap(TRUNK[0], TRUNK[1], TRUNK[2]);
  if (g_cherry.rank[i] < pink_fraction) {
    float osc = (sinf(g_cherry.wt + g_cherry.phase[i]) + 1.0f) * 0.5f;
    return rgb_cap(BRANCH[0] + (PINK[0] - BRANCH[0]) * osc,
                   BRANCH[1] + (PINK[1] - BRANCH[1]) * osc,
                   BRANCH[2] + (PINK[2] - BRANCH[2]) * osc);
  }
  return rgb_cap(BRANCH[0], BRANCH[1], BRANCH[2]);
}

// ---------- hue_shift --------------------------------------------------------
// Structural segments melt in place through hues; mode (1-5) sets the grouping.

struct HueShiftState {
  bool init = false;
  int mode = 0;
  int group_of[5];        // seg id -> group index
  int ngroups = 1;
  float anchor[5], frm[5], to[5], t0[5], dur[5];  // per group (<=5)
  float seg_disp[5];      // per seg id, the continuity layer
  float last = -1;
};
static HueShiftState g_hue;

static float hue_new_dur(float shift_speed) {
  float base = 9.0f - clampf(shift_speed, 0, 1) * 7.5f;
  return base * frand_range(0.7f, 1.3f);
}
static float hue_next(float h) {
  float off = frand_range(0.12f, 0.5f);
  if (frand() < 0.5f) off = -off;
  return frac(h + off);
}
static void hue_grouping(int mode, int *gv) {
  Geom &G = g_geom;
  for (int s = 0; s < 5; s++) gv[s] = 0;
  int *o = G.branch_order; int nb = G.n_branches;
  if (mode == 1 || nb == 0) return;
  if (mode == 2 || nb < 4) { for (int i = 0; i < nb; i++) gv[o[i]] = 1; return; }
  if (mode == 3) { gv[o[0]] = gv[o[2]] = 1; gv[o[1]] = gv[o[3]] = 2; }
  else if (mode == 4) { gv[o[0]] = gv[o[2]] = 1; gv[o[1]] = 2; gv[o[3]] = 3; }
  else { gv[o[0]] = 1; gv[o[1]] = 2; gv[o[2]] = 3; gv[o[3]] = 4; }
}
static void hue_set_mode(int mode, float now, bool seed) {
  HueShiftState &S = g_hue;
  mode = mode < 1 ? 1 : (mode > 5 ? 5 : mode);
  if (mode == S.mode && !seed) return;
  int gv[5]; hue_grouping(mode, gv);
  int ng = 0; for (int s = 0; s < 5; s++) ng = std::max(ng, gv[s] + 1);
  float anchor[5];
  if (seed) {
    float a[5]; for (int gi = 0; gi < ng; gi++) a[gi] = frand();
    for (int s = 0; s < 5; s++) S.seg_disp[s] = a[gv[s]];
    for (int gi = 0; gi < ng; gi++) anchor[gi] = a[gi];
  } else {
    bool set[5] = {false}; for (int gi = 0; gi < ng; gi++) anchor[gi] = -1;
    for (int s = 0; s < 5; s++) { int gi = gv[s]; if (!set[gi]) { anchor[gi] = S.seg_disp[s]; set[gi] = true; } }
    for (int gi = 0; gi < ng; gi++) if (anchor[gi] < 0) anchor[gi] = frand();
  }
  S.mode = mode; S.ngroups = ng;
  for (int s = 0; s < 5; s++) S.group_of[s] = gv[s];
  for (int gi = 0; gi < ng; gi++) {
    S.anchor[gi] = anchor[gi]; S.frm[gi] = anchor[gi]; S.to[gi] = hue_next(anchor[gi]);
    S.t0[gi] = now - frand_range(0.0f, 1.0f); S.dur[gi] = hue_new_dur(0.5f);
  }
}
static void hueshift_step(float now, float shift_speed, int mode) {
  geom_init();
  HueShiftState &S = g_hue;
  if (!S.init) { hue_set_mode(mode < 1 ? 1 : mode, now, true); S.init = true; S.last = now; }
  hue_set_mode(mode, now, false);        // re-groups only if the mode changed

  for (int gi = 0; gi < S.ngroups; gi++) {
    float dur = S.dur[gi];
    float p = dur > 0 ? (now - S.t0[gi]) / dur : 1.0f;
    if (p >= 1.0f) {
      S.frm[gi] = S.to[gi]; S.to[gi] = hue_next(S.frm[gi]);
      S.t0[gi] = now; S.dur[gi] = hue_new_dur(shift_speed); S.anchor[gi] = S.frm[gi];
    } else {
      float e = p * p * (3.0f - 2.0f * p);
      S.anchor[gi] = frac(S.frm[gi] + shortest(S.to[gi] - S.frm[gi]) * e);
    }
  }
  float dt = S.last < 0 ? 0 : now - S.last; S.last = now;
  float k = dt <= 0 ? 1.0f : 1.0f - expf(-dt / 0.35f);
  for (int s = 0; s < 5; s++) {
    float tgt = S.anchor[S.group_of[s]];
    S.seg_disp[s] = frac(S.seg_disp[s] + shortest(tgt - S.seg_disp[s]) * k);
  }
}
static RGB hueshift_color(int i) {
  return hsv(g_hue.seg_disp[TREE_LEDS[i].seg], 1.0f, 1.0f);
}

// ---------- boot / static fill ----------------------------------------------
// Static red->purple gradient by height (the CircuitPython boot rainbow_fill).

static RGB boot_color(int i) {
  geom_init();
  return hsv(g_geom.znorm[i] * 0.83f, 1.0f, 1.0f);
}

// ---------- timer ------------------------------------------------------------
// Fills bottom->top by remaining time, green->yellow->red, with a downward pulse
// wave over the filled region, a per-LED fade-out above the fill, and a rainbow
// completion celebration. Driven by start/pause/cancel from ESPHome buttons.

struct TimerState {
  bool running = false, paused = false;
  float start = 0, duration = 300, elapsed_at_pause = 0, pause_time = 0;
  float completion_start = -1;   // <0 = not celebrating
  float pulse_start = 0;
  bool was_lit[TREE_NUM_LEDS];
  float fade_start[TREE_NUM_LEDS];   // <0 = not fading
  bool inited = false;
};
static TimerState g_timer;

static void timer_reset_pixels() {
  for (int i = 0; i < TREE_NUM_LEDS; i++) { g_timer.was_lit[i] = false; g_timer.fade_start[i] = -1; }
}
static void timer_start(float now, float duration) {
  geom_init();
  TimerState &T = g_timer;
  if (duration > 0) T.duration = duration;
  T.start = now; T.running = true; T.paused = false; T.completion_start = -1;
  T.elapsed_at_pause = 0; T.pulse_start = now;
  timer_reset_pixels(); T.inited = true;
}
static void timer_pause(float now) {
  TimerState &T = g_timer;
  if (T.running && !T.paused) { T.paused = true; T.pause_time = now; T.elapsed_at_pause = now - T.start; }
}
static void timer_resume(float now) {
  TimerState &T = g_timer;
  if (T.paused) { T.start += (now - T.pause_time); T.paused = false; }
}
static void timer_cancel() {
  TimerState &T = g_timer;
  T.running = false; T.paused = false; T.completion_start = -1;
}
static void timer_set_duration(float duration) {
  if (!g_timer.running) g_timer.duration = duration;
}
static float timer_remaining(float now) {
  TimerState &T = g_timer;
  if (T.paused) return std::max(0.0f, T.duration - T.elapsed_at_pause);
  if (!T.running) return 0;
  return std::max(0.0f, T.duration - (now - T.start));
}
// state: 0 idle, 1 active, 2 paused
static int timer_state_code() {
  if (g_timer.paused) return 2;
  return g_timer.running ? 1 : 0;
}

// paint: call timer_step(now) first (advances completion/fade bookkeeping), then color.
static void timer_step(float now) {
  // fill/fade bookkeeping happens inside timer_color per-LED using `now`; step only
  // handles the running->completion transition so the celebration can begin.
  TimerState &T = g_timer;
  if (T.running && !T.paused) {
    if (timer_remaining(now) <= 0) { T.running = false; T.completion_start = now; }
  }
}

static RGB timer_color(int i, float now) {
  geom_init();
  TimerState &T = g_timer;
  float zmin = g_geom.zmin, zmax = g_geom.zmax, zrange = (zmax - zmin);
  if (zrange == 0) zrange = 1;
  float z = TREE_LEDS[i].z;

  if (!T.running) {
    if (T.completion_start >= 0) {
      // Rainbow celebration: wave up (2s) then hold full (1s), 3s loop.
      float elapsed = now - T.completion_start;
      float cyc = fmodf(elapsed, 3.0f);
      float wave_height = zmin + (cyc >= 2.0f ? zrange : (cyc * zrange / 2.0f));
      if (z <= wave_height) return hsv(0.5f + frac((z - zmin) / zrange * 0.83f), 1.0f, 1.0f);
      return RGB{0, 0, 0};
    }
    return RGB{0, 0, 0};
  }

  float remaining = timer_remaining(now);
  float progress = remaining / T.duration;
  float fill_height = zmin + zrange * progress;

  // Fade-out bookkeeping for LEDs that fall above the receding fill.
  float fade_duration = T.duration * 0.05f;
  float fade_b;
  if (z <= fill_height) {
    T.was_lit[i] = true; T.fade_start[i] = -1; fade_b = 1.0f;
  } else {
    if (T.was_lit[i]) { if (T.fade_start[i] < 0) T.fade_start[i] = now; T.was_lit[i] = false; }
    if (T.fade_start[i] >= 0) {
      float tsf = now - T.fade_start[i];
      if (tsf > fade_duration) { T.fade_start[i] = -1; fade_b = 0.0f; }
      else fade_b = (cosf(tsf / fade_duration * (float)M_PI) + 1.0f) / 2.0f;
    } else fade_b = 0.0f;
  }
  if (fade_b <= 0) return RGB{0, 0, 0};

  // Downward pulse wave over the filled region (2.5s: 1.5s sweep + 1s hold).
  float pulse_b = 1.0f;
  float wave_time = fmodf(now - T.pulse_start, 2.5f);
  if (wave_time <= 1.5f && z <= fill_height) {
    float wave_center = zmax - (wave_time / 1.5f * (zmax - zmin));
    float dist = fabsf(z - wave_center);
    float wave_width = (zmax - zmin) * 0.10f;
    if (dist <= wave_width) pulse_b = 1.0f - (cosf(dist / wave_width * (float)M_PI / 2.0f) * 0.7f);
  }

  // green(0.33)->yellow(0.17)->red(0.0) by progress.
  float hue;
  if (progress > 0.5f) hue = 0.17f + (progress - 0.5f) * 2.0f * 0.16f;
  else if (progress > 0.2f) hue = (progress - 0.2f) / 0.3f * 0.17f;
  else hue = 0.0f;
  RGB base = hsv(hue, 1.0f, 1.0f);
  float b = fade_b * pulse_b;
  return RGB{ (uint8_t)(base.r * b), (uint8_t)(base.g * b), (uint8_t)(base.b * b) };
}

}  // namespace tree
