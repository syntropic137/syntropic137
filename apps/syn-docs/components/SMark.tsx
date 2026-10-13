/**
 * The Syntropic137 S mark as inline SVG, coloured by Skyline tokens.
 *
 * Geometry is design/brand/s-mark.svg (viewBox 147 x 308): isometric cubes in
 * one vertical plane, blue on top, one glass cube, dark below. Swap for
 * skyline-core's sMark() or <sky-s-mark> once the elements build lands.
 */

type CubeKind = 'dark' | 'blue' | 'glass';

/** [left x, top-face y, kind], in s-mark.svg's paint order. */
const CUBES: ReadonlyArray<readonly [number, number, CubeKind]> = [
  [4, 184, 'dark'],
  [4, 104, 'dark'],
  [4, 64, 'blue'],
  [4, 24, 'blue'],
  [38.6, 204, 'dark'],
  [38.6, 124, 'dark'],
  [38.6, 44, 'blue'],
  [73.3, 224, 'dark'],
  [73.3, 184, 'dark'],
  [73.3, 144, 'dark'],
  [73.3, 64, 'glass'],
];

const W = 34.65; // half the cube's width
const H = 20; // half the top face's height

const FACES: Record<CubeKind, { left: string; right: string; top: string; edge?: string }> = {
  dark: {
    left: 'var(--sky-color-cube-dark-left)',
    right: 'var(--sky-color-cube-dark-right)',
    top: 'var(--sky-color-cube-dark-top)',
    edge: 'var(--sky-color-cube-edge)',
  },
  blue: {
    left: 'var(--sky-face-front)',
    right: 'var(--sky-face-side)',
    top: 'var(--sky-face-top)',
  },
  glass: {
    left: 'var(--sky-cube-glass-left)',
    right: 'var(--sky-cube-glass-right)',
    top: 'var(--sky-color-cube-glass-edge)',
    edge: 'var(--sky-color-cube-glass-edge)',
  },
};

const pts = (p: ReadonlyArray<readonly [number, number]>) =>
  p.map(([x, y]) => `${x.toFixed(1)},${y.toFixed(1)}`).join(' ');

export function SMark({ className, title = 'Syntropic137' }: { className?: string; title?: string | null }) {
  return (
    <svg
      viewBox="0 0 147 308"
      className={className}
      role={title ? 'img' : undefined}
      aria-label={title ?? undefined}
      aria-hidden={title ? undefined : true}
      focusable="false"
    >
      {CUBES.map(([x, y, kind], i) => {
        const f = FACES[kind];
        const stroke = f.edge ? { stroke: f.edge, strokeWidth: 1 } : {};
        return (
          <g key={i}>
            <polygon
              points={pts([[x, y + H], [x + W, y + 2 * H], [x + W, y + 4 * H], [x, y + 3 * H]])}
              style={{ fill: f.left }}
              {...stroke}
            />
            <polygon
              points={pts([[x + W, y + 2 * H], [x + 2 * W, y + H], [x + 2 * W, y + 3 * H], [x + W, y + 4 * H]])}
              style={{ fill: f.right }}
              {...stroke}
            />
            <polygon
              points={pts([[x + W, y], [x + 2 * W, y + H], [x + W, y + 2 * H], [x, y + H]])}
              style={{ fill: f.top }}
              {...stroke}
            />
          </g>
        );
      })}
    </svg>
  );
}

/** "Syntropic137" in the brand face, 137 in the accent. */
export function Wordmark({ className }: { className?: string }) {
  return (
    <span className={`syn-wordmark ${className ?? ''}`}>
      Syntropic<span className="syn-wordmark__num">137</span>
    </span>
  );
}
