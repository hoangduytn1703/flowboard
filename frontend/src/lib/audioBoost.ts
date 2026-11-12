/**
 * Loudness of a <video> / <audio> beyond 100 %. An element's own ``volume`` stops at 1, so the first time a gain
 * above 1 is asked for, the element's sound is routed through a Web Audio gain node (and stays there). At or below
 * 1 an element that was never boosted just uses ``volume``.
 */
let ctx: AudioContext | null = null;
const nodes = new WeakMap<HTMLMediaElement, GainNode>();

export function setGain(el: HTMLMediaElement | null | undefined, gain: number): void {
  if (!el) return;
  const g = Math.max(0, gain);
  let node = nodes.get(el);
  if (!node && g > 1) {
    try {
      const Ctx = window.AudioContext ?? (window as unknown as { webkitAudioContext?: typeof AudioContext }).webkitAudioContext;
      if (!Ctx) throw new Error("no Web Audio");
      ctx = ctx ?? new Ctx();
      node = ctx.createGain();
      ctx.createMediaElementSource(el).connect(node);
      node.connect(ctx.destination);
      nodes.set(el, node);
    } catch {
      node = undefined; // no Web Audio (or the element is already wired elsewhere): as loud as the element goes
    }
  }
  if (node) {
    el.volume = 1;
    node.gain.value = g;
    if (ctx && ctx.state === "suspended") void ctx.resume().catch(() => undefined);
  } else {
    el.volume = Math.min(1, g);
  }
}
