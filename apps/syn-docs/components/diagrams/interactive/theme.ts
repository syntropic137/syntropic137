import type { ColorVariant } from './types';

interface ColorPalette {
  bg: string;
  bgHover: string;
  border: string;
  icon: string;
  text: string;
  glow: string;
  groupBg: string;
  groupBorder: string;
}

// Dark mode: Skyline tokens. Each variant keeps its role (see the docs-fuma
// skill's colour table) and resolves to one Skyline hue; the rest of the
// palette is mixed from it, so the theme package stays the only place colour
// values live.
const darkTone: Record<ColorVariant, string> = {
  indigo: 'var(--ds-color-accent)', // primary services
  purple: 'var(--sky-color-data-3)', // secondary services
  pink: 'var(--sky-color-series-4)', // external, alerts
  cyan: 'var(--sky-color-data-1)', // data, streaming
  slate: 'var(--ds-color-text-subtle)', // infrastructure
  emerald: 'var(--ds-color-success)', // success, health
  amber: 'var(--ds-color-warning)', // warnings, config
};

const mix = (tone: string, pct: number, base = 'transparent') => `color-mix(in oklab, ${tone} ${pct}%, ${base})`;

const darkColors = Object.fromEntries(
  Object.entries(darkTone).map(([variant, tone]) => [
    variant,
    {
      bg: mix(tone, 12, 'var(--ds-color-surface)'),
      bgHover: mix(tone, 20, 'var(--ds-color-surface)'),
      border: mix(tone, 32),
      icon: tone,
      text: mix(tone, 40, 'var(--ds-color-fg)'),
      glow: mix(tone, 30),
      groupBg: mix(tone, 5),
      groupBorder: mix(tone, 20),
    },
  ]),
) as Record<ColorVariant, ColorPalette>;

const lightColors: Record<ColorVariant, ColorPalette> = {
  indigo: {
    bg: 'rgba(14, 165, 233, 0.08)',
    bgHover: 'rgba(14, 165, 233, 0.14)',
    border: 'rgba(14, 165, 233, 0.25)',
    icon: '#0ea5e9',
    text: '#0369a1',
    glow: 'rgba(14, 165, 233, 0.2)',
    groupBg: 'rgba(14, 165, 233, 0.04)',
    groupBorder: 'rgba(14, 165, 233, 0.15)',
  },
  purple: {
    bg: 'rgba(59, 130, 246, 0.08)',
    bgHover: 'rgba(59, 130, 246, 0.14)',
    border: 'rgba(59, 130, 246, 0.25)',
    icon: '#3b82f6',
    text: '#1d4ed8',
    glow: 'rgba(59, 130, 246, 0.2)',
    groupBg: 'rgba(59, 130, 246, 0.04)',
    groupBorder: 'rgba(59, 130, 246, 0.15)',
  },
  pink: {
    bg: 'rgba(244, 63, 94, 0.08)',
    bgHover: 'rgba(244, 63, 94, 0.14)',
    border: 'rgba(244, 63, 94, 0.20)',
    icon: '#f43f5e',
    text: '#be123c',
    glow: 'rgba(244, 63, 94, 0.2)',
    groupBg: 'rgba(244, 63, 94, 0.04)',
    groupBorder: 'rgba(244, 63, 94, 0.12)',
  },
  cyan: {
    bg: 'rgba(6, 182, 212, 0.08)',
    bgHover: 'rgba(6, 182, 212, 0.14)',
    border: 'rgba(6, 182, 212, 0.25)',
    icon: '#06b6d4',
    text: '#0e7490',
    glow: 'rgba(6, 182, 212, 0.2)',
    groupBg: 'rgba(6, 182, 212, 0.04)',
    groupBorder: 'rgba(6, 182, 212, 0.15)',
  },
  slate: {
    bg: 'rgba(113, 113, 122, 0.08)',
    bgHover: 'rgba(113, 113, 122, 0.14)',
    border: 'rgba(113, 113, 122, 0.25)',
    icon: '#71717a',
    text: '#3f3f46',
    glow: 'rgba(113, 113, 122, 0.2)',
    groupBg: 'rgba(113, 113, 122, 0.04)',
    groupBorder: 'rgba(113, 113, 122, 0.15)',
  },
  emerald: {
    bg: 'rgba(20, 184, 166, 0.08)',
    bgHover: 'rgba(20, 184, 166, 0.14)',
    border: 'rgba(20, 184, 166, 0.25)',
    icon: '#14b8a6',
    text: '#0f766e',
    glow: 'rgba(20, 184, 166, 0.2)',
    groupBg: 'rgba(20, 184, 166, 0.04)',
    groupBorder: 'rgba(20, 184, 166, 0.15)',
  },
  amber: {
    bg: 'rgba(245, 158, 11, 0.08)',
    bgHover: 'rgba(245, 158, 11, 0.14)',
    border: 'rgba(245, 158, 11, 0.20)',
    icon: '#f59e0b',
    text: '#b45309',
    glow: 'rgba(245, 158, 11, 0.2)',
    groupBg: 'rgba(245, 158, 11, 0.04)',
    groupBorder: 'rgba(245, 158, 11, 0.12)',
  },
};

export function getColors(color: ColorVariant, isDark: boolean): ColorPalette {
  return isDark ? darkColors[color] : lightColors[color];
}

export function getEdgeColor(isDark: boolean): string {
  return isDark ? 'var(--sky-color-border-hover)' : 'rgba(113, 113, 122, 0.35)';
}

export function getEdgeLabelColor(isDark: boolean): string {
  return isDark ? 'var(--ds-color-text-muted)' : '#71717a';
}

export function getBackgroundColor(isDark: boolean): string {
  return isDark ? 'var(--ds-color-bg)' : 'rgba(250, 250, 250, 0.5)';
}

export function getDotColor(isDark: boolean): string {
  return isDark ? 'color-mix(in oklab, var(--ds-color-text-muted) 14%, transparent)' : 'rgba(113, 113, 122, 0.10)';
}

export function getEdgeLabelBackground(isDark: boolean): string {
  return isDark ? 'var(--ds-color-surface-raised)' : 'rgba(244, 244, 245, 0.9)';
}

export function getSublabelColor(isDark: boolean): string {
  return isDark ? 'var(--ds-color-text-subtle)' : '#71717a';
}
