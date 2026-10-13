import { useEffect, useMemo, useRef, useState, type ReactNode, type RefObject } from "react";
import { S_MARK_FACES, cityBlockPaint, heroCity, sMark, type CityFill } from "@syn137/skyline-core/geometry";
import GlassCard from "../components/GlassCard";
import HarnessChip from "../components/HarnessChip";
import InstallTerminal from "../components/InstallTerminal";
import { loadElement, useElement } from "../components/useElement";
import { useInViewOnce } from "../components/useInView";
import { useMedia } from "../components/useMedia";
import { HERO } from "../data/copy";
import { HERO_MEDIA, HERO_RENDER } from "../data/heroMedia";
import { CITY_DESKTOP, CITY_MAX_SESSIONS, CITY_PHONE, HERO_CARDS, HERO_STATS, cityDays, type CityLayout } from "../data/sample/hero";
import "../components/PillarHeader.css";
import "./Hero.css";

const loadCity = () => import("@syn137/skyline-svelte-v5/elements/iso-city");
const loadMark = () => import("@syn137/skyline-svelte-v5/elements/s-mark");

const MARK = sMark(64);
/** Opaque blocks: quiet days darken instead of turning see-through (owner review; the board fades them). */
const FILL: CityFill = "solid";
/** If the city element has not loaded this long after the city came into view, show the static city. */
const LOAD_GRACE_MS = 2500;

/** The S in cubes as static SVG: <sky-s-mark>'s light-DOM fallback. */
function MarkArt() {
  return (
    <svg className="hero__mark-art" viewBox={MARK.viewBox} aria-hidden="true" focusable="false">
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
  );
}

/** The city as static SVG, same geometry as <sky-iso-city> (shown until the element is defined). */
function CityArt({ layout }: { layout: CityLayout }) {
  const city = useMemo(
    () => heroCity(cityDays(layout), { ...layout, maxSessions: CITY_MAX_SESSIONS }),
    [layout],
  );
  return (
    <svg className="hero__city-art" viewBox={city.viewBox} role="img" aria-label={HERO.cityLabel}>
      <defs>
        <radialGradient id="hero-city-glow" cx="55%" cy="55%" r="55%">
          <stop offset="0" className="hero__glow-in" />
          <stop offset="1" className="hero__glow-out" />
        </radialGradient>
      </defs>
      <ellipse cx={city.glow.cx} cy={city.glow.cy} rx={city.glow.rx} ry={city.glow.ry} fill="url(#hero-city-glow)" />
      <polygon className="hero__floor" points={city.floor} />
      {city.blocks.map((b) => {
        const f = cityBlockPaint(b.tone, b.opacity, FILL);
        return (
          <g key={b.index} style={f.opacity === 1 ? undefined : { opacity: f.opacity }}>
            <polygon points={b.left} style={{ fill: f.front }} />
            <polygon points={b.right} style={{ fill: f.side }} />
            <polygon points={b.top} style={{ fill: f.top }} />
          </g>
        );
      })}
    </svg>
  );
}

function City({ layout, ready, animate }: { layout: CityLayout; ready: boolean; animate: boolean }) {
  const days = useMemo(() => cityDays(layout), [layout]);
  useEffect(() => void loadElement("sky-s-mark", loadMark), []);

  if (!ready) {
    return (
      <div className="hero__city">
        <CityArt layout={layout} />
        <div className="hero__overlay">
          <div className="hero__mark" role="img" aria-label={HERO.markLabel}>
            <MarkArt />
          </div>
        </div>
      </div>
    );
  }
  return (
    <sky-iso-city
      key={layout.cols}
      className="hero__city"
      days={days}
      live={layout.live}
      failed={layout.failed}
      errored={layout.errored}
      cols={layout.cols}
      rows={layout.rows}
      cell={layout.cell}
      maxSessions={CITY_MAX_SESSIONS}
      label={HERO.cityLabel}
      fill={FILL}
      animate={animate}
      drift={animate}
    >
      <sky-s-mark slot="overlay" className="hero__mark" animate={animate} label={HERO.markLabel}>
        <MarkArt />
      </sky-s-mark>
    </sky-iso-city>
  );
}

/**
 * When the city entrance plays (owner review: so nobody misses it). With
 * motion allowed, the stage holds (data-hold: blocks and S hidden, every
 * motion.css class paused through --sky-motion-play) until the city is 40%
 * on screen and its element has loaded; then the blocks rise, the S drops
 * and the cards start to bob, once. With reduced motion nothing holds: the
 * static city shows at once. If the element is slow to load, the static
 * city shows after LOAD_GRACE_MS instead of an empty stage.
 */
function useCityEntrance(stage: RefObject<HTMLDivElement | null>) {
  const motion = useMedia("(prefers-reduced-motion: no-preference)");
  const ready = useElement("sky-iso-city", loadCity, "idle");
  const inView = useInViewOnce(stage, 0.4);
  const [late, setLate] = useState(false);

  useEffect(() => {
    if (!motion || !inView || ready) return;
    const id = window.setTimeout(() => setLate(true), LOAD_GRACE_MS);
    return () => window.clearTimeout(id);
  }, [motion, inView, ready]);

  const animate = motion && !late;
  return { ready, animate, hold: animate && !(inView && ready) };
}

/** The vector stage: <sky-iso-city> with <sky-s-mark>, or their static fallback. */
interface StageProps {
  wide: boolean;
  children: ReactNode;
}

function VectorStage({ wide, children }: StageProps) {
  const stage = useRef<HTMLDivElement>(null);
  const city = useCityEntrance(stage);
  return (
    <div ref={stage} className="hero__stage" data-hold={city.hold ? "" : undefined}>
      <City layout={wide ? CITY_DESKTOP : CITY_PHONE} ready={city.ready} animate={city.animate} />
      {children}
    </div>
  );
}

/**
 * The rendered stage: the Blender clip plays once when the stage is 40% on
 * screen, then the 4K still (its last frame) replaces it; no loop, for the
 * idle-CPU gate. Until it plays, data-hold hides it, so the finished scene
 * never flashes before the build. Reduced motion, or a refused autoplay,
 * shows only the still.
 */
function RenderStage({ children }: StageProps) {
  const stage = useRef<HTMLDivElement>(null);
  const video = useRef<HTMLVideoElement>(null);
  const motion = useMedia("(prefers-reduced-motion: no-preference)");
  const inView = useInViewOnce(stage, 0.4);
  const [ended, setEnded] = useState(false);

  useEffect(() => {
    if (motion && inView) void video.current?.play().catch(() => setEnded(true));
  }, [motion, inView]);

  const { stillWidths, still, sizes, phone, clip, width, height } = HERO_RENDER;
  const playing = motion && !ended;
  return (
    <div ref={stage} className="hero__stage hero__stage--render" data-hold={motion && !inView ? "" : undefined}>
      <img
        className="hero__render"
        src={still(stillWidths[1])}
        srcSet={stillWidths.map((w) => `${still(w)} ${w}w`).join(", ")}
        sizes={sizes}
        fetchPriority={playing ? "low" : "high"}
        width={width}
        height={height}
        alt={HERO.cityLabel}
        hidden={playing}
      />
      {playing && (
        <video
          ref={video}
          className="hero__render"
          width={width}
          height={height}
          muted
          playsInline
          preload="auto"
          aria-hidden="true"
          onEnded={() => setEnded(true)}
        >
          <source media={phone} src={clip("hero-sm", "mov")} type={'video/mp4; codecs="hvc1"'} />
          <source media={phone} src={clip("hero-sm", "webm")} type="video/webm" />
          <source src={clip("hero", "mov")} type={'video/mp4; codecs="hvc1"'} />
          <source src={clip("hero", "webm")} type="video/webm" />
        </video>
      )}
      {children}
    </div>
  );
}

/** Section 1, "Agent work that compounds." (v4 Landing and PhoneLanding boards). */
export default function Hero() {
  const wide = useMedia("(min-width: 48rem)");
  const cards = useMedia("(min-width: 64rem)");
  const { run, phases, trend } = HERO_CARDS;
  const Stage = HERO_MEDIA === "render" ? RenderStage : VectorStage;

  return (
    <section className="hero" aria-label="Hero">
      <div className="hero__grain" aria-hidden="true" />
      <div className="hero__copy">
        <a className="hero__badge" href={HERO.badge.href}>
          <span className="hero__badge-tag">{HERO.badge.tag}</span>
          {HERO.badge.text}
          <svg width="14" height="14" viewBox="0 0 16 16" aria-hidden="true" focusable="false">
            <path d="M3 8h10M9 4l4 4-4 4" />
          </svg>
        </a>
        <h1 className="hero__title glow-text">{HERO.title}</h1>
        <p className="hero__lede">{HERO.lede}</p>
        <div className="hero__install">
          <InstallTerminal caret />
          <span className="hero__note">{HERO.installNote}</span>
        </div>
      </div>

      <Stage wide={wide}>
        {cards && (
          <>
            <GlassCard className="hero__card hero__card--run" float="bob">
              <span className="hero__card-meta">
                <span className="live-dot" aria-hidden="true" />
                {run.meta}
              </span>
              <span className="hero__card-title">{run.title}</span>
              <span className="hero__card-detail">{run.detail}</span>
            </GlassCard>
            <GlassCard className="hero__card hero__card--phases" float="alt">
              <span className="hero__card-meta">{phases.meta}</span>
              <span className="hero__card-chips">
                {phases.chips.map((c, i) => (
                  <span key={c.label} className="hero__card-chip">
                    {i > 0 && (
                      <span className="hero__card-arrow" aria-hidden="true">
                        →
                      </span>
                    )}
                    <HarnessChip provider={c.provider} label={c.label} />
                  </span>
                ))}
              </span>
            </GlassCard>
            <GlassCard className="hero__card hero__card--trend" float="bob" delay={1.2}>
              <span className="hero__card-meta">{trend.meta}</span>
              <span className="hero__card-gains">
                {trend.gains.map((g, i) => [
                  i > 0 && (
                    <span key={`sep-${g}`} className="hero__card-sep" aria-hidden="true">
                      ·
                    </span>
                  ),
                  <span key={g} className="hero__card-gain">
                    {g}
                  </span>,
                ])}
              </span>
            </GlassCard>
          </>
        )}
      </Stage>

      <ul className="hero__stats">
        {HERO_STATS.map((s) => (
          <li key={s.label}>
            <span className="hero__stat-value">{s.value}</span>
            <span className="hero__stat-label">{s.label}</span>
          </li>
        ))}
      </ul>
      <div className="hero__fade" aria-hidden="true" />
    </section>
  );
}
