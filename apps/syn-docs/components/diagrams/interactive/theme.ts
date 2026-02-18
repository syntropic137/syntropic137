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

// SR-71 palette mapped to hex — matches DiagramPrimitives color mapping
const darkColors: Record<ColorVariant, ColorPalette> = {
  indigo: {
    bg: 'rgba(14, 165, 233, 0.12)',
    bgHover: 'rgba(14, 165, 233, 0.20)',
    border: 'rgba(56, 189, 248, 0.25)',
    icon: '#38bdf8',
    text: '#7dd3fc',
    glow: 'rgba(14, 165, 233, 0.3)',
    groupBg: 'rgba(14, 165, 233, 0.06)',
    groupBorder: 'rgba(56, 189, 248, 0.15)',
  },
  purple: {
    bg: 'rgba(59, 130, 246, 0.12)',
    bgHover: 'rgba(59, 130, 246, 0.20)',
    border: 'rgba(96, 165, 250, 0.25)',
    icon: '#60a5fa',
    text: '#93bbfd',
    glow: 'rgba(59, 130, 246, 0.3)',
    groupBg: 'rgba(59, 130, 246, 0.06)',
    groupBorder: 'rgba(96, 165, 250, 0.15)',
  },
  pink: {
    bg: 'rgba(244, 63, 94, 0.10)',
    bgHover: 'rgba(244, 63, 94, 0.18)',
    border: 'rgba(251, 113, 133, 0.20)',
    icon: '#fb7185',
    text: '#fda4af',
    glow: 'rgba(244, 63, 94, 0.3)',
    groupBg: 'rgba(244, 63, 94, 0.05)',
    groupBorder: 'rgba(251, 113, 133, 0.12)',
  },
  cyan: {
    bg: 'rgba(6, 182, 212, 0.12)',
    bgHover: 'rgba(6, 182, 212, 0.20)',
    border: 'rgba(34, 211, 238, 0.25)',
    icon: '#22d3ee',
    text: '#67e8f9',
    glow: 'rgba(6, 182, 212, 0.3)',
    groupBg: 'rgba(6, 182, 212, 0.06)',
    groupBorder: 'rgba(34, 211, 238, 0.15)',
  },
  slate: {
    bg: 'rgba(113, 113, 122, 0.12)',
    bgHover: 'rgba(113, 113, 122, 0.20)',
    border: 'rgba(161, 161, 170, 0.25)',
    icon: '#a1a1aa',
    text: '#d4d4d8',
    glow: 'rgba(113, 113, 122, 0.3)',
    groupBg: 'rgba(113, 113, 122, 0.06)',
    groupBorder: 'rgba(161, 161, 170, 0.15)',
  },
  emerald: {
    bg: 'rgba(20, 184, 166, 0.12)',
    bgHover: 'rgba(20, 184, 166, 0.20)',
    border: 'rgba(45, 212, 191, 0.25)',
    icon: '#2dd4bf',
    text: '#5eead4',
    glow: 'rgba(20, 184, 166, 0.3)',
    groupBg: 'rgba(20, 184, 166, 0.06)',
    groupBorder: 'rgba(45, 212, 191, 0.15)',
  },
  amber: {
    bg: 'rgba(245, 158, 11, 0.10)',
    bgHover: 'rgba(245, 158, 11, 0.18)',
    border: 'rgba(251, 191, 36, 0.20)',
    icon: '#fbbf24',
    text: '#fcd34d',
    glow: 'rgba(245, 158, 11, 0.3)',
    groupBg: 'rgba(245, 158, 11, 0.05)',
    groupBorder: 'rgba(251, 191, 36, 0.12)',
  },
};

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
  return isDark ? 'rgba(161, 161, 170, 0.4)' : 'rgba(113, 113, 122, 0.35)';
}

export function getEdgeLabelColor(isDark: boolean): string {
  return isDark ? '#a1a1aa' : '#71717a';
}

export function getBackgroundColor(isDark: boolean): string {
  return isDark ? 'rgba(9, 9, 11, 0.5)' : 'rgba(250, 250, 250, 0.5)';
}

export function getDotColor(isDark: boolean): string {
  return isDark ? 'rgba(161, 161, 170, 0.12)' : 'rgba(113, 113, 122, 0.10)';
}
