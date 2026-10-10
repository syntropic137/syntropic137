/**
 * Which hero visual ships (LANDING-MIGRATION-PLAN, decision "Hero visual, two layers"):
 * "render" is the Blender clip (handoffs/.../blender, build_hero.py --transparent),
 * "vector" is <sky-iso-city> with <sky-s-mark>.
 */
export type HeroMedia = "render" | "vector";
export const HERO_MEDIA: HeroMedia = "render";

/**
 * The rendered hero, transparent so the page background shows through. Alpha video
 * only plays as HEVC (Safari) or VP9 WebM (Chrome, Firefox, Edge); HEVC is listed
 * first because Safari also claims WebM but drops its alpha. The still is the
 * clip's last frame rendered at 4K: the clip plays once, then the still replaces
 * it so the resting hero is sharp on any screen. Reduced motion, or a refused
 * autoplay, shows only the still.
 */
export const HERO_RENDER = {
  /** Last frame at 4K, cut to these widths (hero-still-<w>.webp) for srcset. */
  stillWidths: [960, 1600, 2400, 3200],
  still: (w: number) => `/hero/hero-still-${w}.webp`,
  /** The stage is 150% of the viewport on phones, 112% from 48rem (Hero.css). */
  sizes: "(min-width: 48rem) 112vw, 150vw",
  /** Phones get the half-width clip (hero-sm.*). */
  phone: "(max-width: 47.99rem)",
  clip: (name: "hero" | "hero-sm", ext: "mov" | "webm") => `/hero/${name}.${ext}`,
  width: 1920,
  height: 1080,
} as const;
