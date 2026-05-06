<template>
  <svg
    class="chika-mark"
    :class="[`s-${state}`]"
    viewBox="-60 -60 120 120"
    :style="{ width: `${size}px`, height: `${size}px` }"
    aria-hidden="true"
  >
    <g class="petals">
      <g
        v-for="(angle, i) in ANGLES"
        :key="i"
        :class="`petal-wrap petal-wrap-${i}`"
        :transform="`rotate(${angle})`"
      >
        <path :d="PETAL_D" class="petal" />
      </g>
      <circle class="hub-dot" cx="0" cy="0" r="3.2" />
    </g>
  </svg>
</template>

<script setup>
// chika brand mark — three architectural leaves at 120° intervals,
// stroke-only, with a centre anchor dot.  See mark-mock.html for the
// design rationale + animation math.
//
// Props
//   size:  rendered width/height in px  (default 28)
//   state: "idle" | "thinking" | "streaming" | "success" | "intro"
//
// State semantics
//   idle       — subtle prime-ratio breath, never resyncs
//   thinking   — leaves periodically unfurl in place; mostly still
//   streaming  — sin-wave on stroke-opacity & stroke-width
//   success    — one-shot cascade pop (90 ms stagger)
//   intro      — one-shot rotateY-flip + scale-up (130 ms stagger)
defineProps({
  size: { type: Number, default: 28 },
  state: { type: String, default: 'idle' },
})

const PETAL_D = 'M 0,-58 C 13,-44 19,-22 0,-6 C -19,-22 -13,-44 0,-58 Z'
const ANGLES = [0, 120, 240]
</script>

<style scoped>
.chika-mark {
  display: block;
  overflow: visible;
}

.chika-mark .petal {
  fill: none;
  stroke: var(--mark-stroke, #b3bdff);
  stroke-width: 3.4;
  stroke-linejoin: round;
  stroke-linecap: round;
  transform-origin: 50% 50%;
  transform-box: fill-box;
  vector-effect: non-scaling-stroke;
}
.chika-mark .hub-dot {
  fill: var(--mark-stroke, #b3bdff);
}
.chika-mark .petals {
  transform-origin: 50% 50%;
  transform-box: view-box;
}

/* ── IDLE — per-leaf prime-ratio breath ───────────────────────── */
.chika-mark.s-idle .petal {
  animation-name: chika-breath;
  animation-iteration-count: infinite;
  animation-timing-function: ease-in-out;
  animation-direction: alternate;
}
.chika-mark.s-idle .petal-wrap-0 .petal { animation-duration: 2.3s; --amp: 1.045; }
.chika-mark.s-idle .petal-wrap-1 .petal { animation-duration: 3.7s; --amp: 1.060; }
.chika-mark.s-idle .petal-wrap-2 .petal { animation-duration: 5.3s; --amp: 1.052; }
@keyframes chika-breath {
  0%   { transform: scale(1.000); }
  100% { transform: scale(var(--amp, 1.05)); }
}

/* ── THINKING — periodic unfurl gesture ───────────────────────── */
.chika-mark.s-thinking .petal {
  animation-name: chika-think-pulse;
  animation-iteration-count: infinite;
  animation-timing-function: cubic-bezier(0.16, 1.0, 0.3, 1);
}
.chika-mark.s-thinking .petal-wrap-0 .petal { animation-duration: 4.3s; animation-delay:  0.00s; }
.chika-mark.s-thinking .petal-wrap-1 .petal { animation-duration: 5.1s; animation-delay: -1.70s; }
.chika-mark.s-thinking .petal-wrap-2 .petal { animation-duration: 6.7s; animation-delay: -3.35s; }
@keyframes chika-think-pulse {
    0%  { transform: rotateY(180deg) scale(0); opacity: 0; }
   18%  { transform: rotateY(0deg)   scale(1); opacity: 1; }
   82%  { transform: rotateY(0deg)   scale(1); opacity: 1; }
  100%  { transform: rotateY(-180deg) scale(0); opacity: 0; }
}

/* ── STREAMING — sin wave on stroke-opacity + stroke-width ────── */
.chika-mark.s-streaming .petal {
  animation: chika-wave 1.6s linear infinite;
}
.chika-mark.s-streaming .petal-wrap-0 .petal { animation-delay:  0.000s; }
.chika-mark.s-streaming .petal-wrap-1 .petal { animation-delay: -0.533s; }
.chika-mark.s-streaming .petal-wrap-2 .petal { animation-delay: -1.067s; }
@keyframes chika-wave {
    0%   { stroke-opacity: 0.675; stroke-width: 2.6; }
    8.3% { stroke-opacity: 0.838; stroke-width: 3.1; }
   16.7% { stroke-opacity: 0.957; stroke-width: 3.5; }
   25.0% { stroke-opacity: 1.000; stroke-width: 3.6; }
   33.3% { stroke-opacity: 0.957; stroke-width: 3.5; }
   41.7% { stroke-opacity: 0.838; stroke-width: 3.1; }
   50.0% { stroke-opacity: 0.675; stroke-width: 2.6; }
   58.3% { stroke-opacity: 0.513; stroke-width: 2.1; }
   66.7% { stroke-opacity: 0.394; stroke-width: 1.7; }
   75.0% { stroke-opacity: 0.350; stroke-width: 1.6; }
   83.3% { stroke-opacity: 0.394; stroke-width: 1.7; }
   91.7% { stroke-opacity: 0.513; stroke-width: 2.1; }
  100%   { stroke-opacity: 0.675; stroke-width: 2.6; }
}

/* ── SUCCESS — radial cascade pop ─────────────────────────────── */
.chika-mark.s-success .petal {
  animation: chika-pop 700ms cubic-bezier(0.34, 1.56, 0.64, 1) 1 both;
}
.chika-mark.s-success .petal-wrap-0 .petal { animation-delay:    0ms; }
.chika-mark.s-success .petal-wrap-1 .petal { animation-delay:   90ms; }
.chika-mark.s-success .petal-wrap-2 .petal { animation-delay:  180ms; }
@keyframes chika-pop {
  0%   { transform: scale(1.000); }
  35%  { transform: scale(1.140); }
  65%  { transform: scale(0.955); }
  100% { transform: scale(1.000); }
}

/* ── INTRO — leaves unfurl in cascade ─────────────────────────── */
.chika-mark.s-intro .petal {
  animation: chika-unfurl 900ms cubic-bezier(0.16, 1.0, 0.3, 1) 1 both;
}
.chika-mark.s-intro .petal-wrap-0 .petal { animation-delay:   0ms; }
.chika-mark.s-intro .petal-wrap-1 .petal { animation-delay: 130ms; }
.chika-mark.s-intro .petal-wrap-2 .petal { animation-delay: 260ms; }
.chika-mark.s-intro .hub-dot {
  animation: chika-dot 700ms cubic-bezier(0.16, 1.0, 0.3, 1) 1 both;
  animation-delay: 100ms;
  transform-origin: 50% 50%;
  transform-box: view-box;
}
@keyframes chika-unfurl {
    0% { transform: rotateY(180deg) scale(0); opacity: 0; }
   35% { opacity: 1; }
  100% { transform: rotateY(0deg)   scale(1); opacity: 1; }
}
@keyframes chika-dot {
    0% { transform: scale(0); opacity: 0; }
  100% { transform: scale(1); opacity: 1; }
}
</style>
