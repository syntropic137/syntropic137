import { useEffect } from "react";
import { sMark, S_MARK_FACES } from "@syn137/skyline-core/geometry";

/** The brand S in cubes, same geometry and faces as Skyline's SMark pattern. */
const MARK = sMark(40);

let elementModule: Promise<unknown> | null = null;

/**
 * Registers <sky-s-mark> once, after first paint: the element pulls in the
 * shared Svelte runtime chunk, which nothing needs for the first render.
 */
function loadElement(): void {
  if (elementModule) return;
  const load = () => {
    elementModule ??= import("@syn137/skyline-svelte-v5/elements/s-mark");
  };
  if ("requestIdleCallback" in window) window.requestIdleCallback(load);
  else setTimeout(load, 1);
}

interface SMarkProps {
  /** Width in px; the height follows the mark's aspect ratio. */
  size: number;
  /** Accessible name; "" makes the mark decorative (next to the wordmark). */
  label?: string;
}

/**
 * <sky-s-mark> with a static light-DOM fallback: the same SVG, drawn from
 * skyline-core's sMark() with token fills, so the S shows before (and
 * without) the element's script. The upgraded element renders into its
 * shadow root and the fallback is no longer shown.
 */
export default function SMark({ size, label = "Syntropic137" }: SMarkProps) {
  useEffect(loadElement, []);
  const decorative = label === "";
  return (
    <sky-s-mark className="s-mark" size={size} label={label} style={{ width: size }}>
      <svg
        className="s-mark__fallback"
        viewBox={MARK.viewBox}
        width={size}
        role={decorative ? undefined : "img"}
        aria-label={decorative ? undefined : label}
        aria-hidden={decorative ? true : undefined}
        focusable="false"
      >
        {MARK.cubes.map((c) => {
          const f = S_MARK_FACES[c.tone];
          return (
            <g key={c.order} style={{ stroke: f.stroke ?? undefined }}>
              <polygon points={c.left} style={{ fill: f.left }} />
              <polygon points={c.right} style={{ fill: f.right }} />
              <polygon points={c.top} style={{ fill: f.top }} />
            </g>
          );
        })}
      </svg>
    </sky-s-mark>
  );
}
