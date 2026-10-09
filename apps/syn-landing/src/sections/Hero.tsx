import { useEffect, useMemo } from "react";
import { CITY_TONE_FILL, S_MARK_FACES, extrudeColors, isoCity, sMark } from "@syn137/skyline-core/geometry";
import GlassCard from "../components/GlassCard";
import HarnessChip from "../components/HarnessChip";
import InstallTerminal from "../components/InstallTerminal";
import { loadElement, useElement } from "../components/useElement";
import { useMedia } from "../components/useMedia";
import { HERO } from "../data/copy";
import { CITY_DESKTOP, CITY_MAX_SESSIONS, CITY_PHONE, HERO_CARDS, HERO_STATS, cityDays, type CityLayout } from "../data/sample/hero";
import "../components/PillarHeader.css";
import "./Hero.css";

const loadCity = () => import("@syn137/skyline-svelte-v5/elements/iso-city");
const loadMark = () => import("@syn137/skyline-svelte-v5/elements/s-mark");

const MARK = sMark(64);
const FACES = {
  run: extrudeColors(CITY_TONE_FILL.run),
  live: extrudeColors(CITY_TONE_FILL.live),
  failed: extrudeColors(CITY_TONE_FILL.failed),
  errored: extrudeColors(CITY_TONE_FILL.errored),
};

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
    () => isoCity(cityDays(layout), { ...layout, maxSessions: CITY_MAX_SESSIONS }),
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
        const f = FACES[b.tone];
        return (
          <g key={b.index} style={{ opacity: b.opacity }}>
            <polygon points={b.left} style={{ fill: f.front }} />
            <polygon points={b.right} style={{ fill: f.side }} />
            <polygon points={b.top} style={{ fill: f.top }} />
          </g>
        );
      })}
    </svg>
  );
}

function City({ layout }: { layout: CityLayout }) {
  const ready = useElement("sky-iso-city", loadCity, "idle");
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
      animate
      drift
    >
      <sky-s-mark slot="overlay" className="hero__mark" animate label={HERO.markLabel}>
        <MarkArt />
      </sky-s-mark>
    </sky-iso-city>
  );
}

/** Section 1, "Agent work that compounds." (v4 Landing and PhoneLanding boards). */
export default function Hero() {
  const wide = useMedia("(min-width: 48rem)");
  const cards = useMedia("(min-width: 64rem)");
  const { run, phases, trend } = HERO_CARDS;

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
          <InstallTerminal typing />
          <span className="hero__note">{HERO.installNote}</span>
        </div>
      </div>

      <div className="hero__stage">
        <City layout={wide ? CITY_DESKTOP : CITY_PHONE} />
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
      </div>

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
