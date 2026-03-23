'use client';

import { useEffect, useState } from 'react';

export const DARK_COLORS = {
  agent: '#38BDF8',    // sky-400
  command: '#7DD3FC',  // sky-300
  skill: '#0EA5E9',    // sky-500
  tool: '#BAE6FD',     // sky-200
  hook: '#A1A1AA',     // zinc-400
  line: '#38BDF8',
  particle: '#7DD3FC',
  coreOuter: '#38BDF8',
  coreMiddle: '#0EA5E9',
  coreInner: '#7DD3FC',
  ring1: '#38BDF8',
  ring2: '#0EA5E9',
};

export const LIGHT_COLORS = {
  agent: '#0284C7',    // sky-600
  command: '#0369A1',  // sky-700
  skill: '#0EA5E9',    // sky-500
  tool: '#38BDF8',     // sky-400
  hook: '#71717A',     // zinc-500
  line: '#0EA5E9',
  particle: '#0284C7',
  coreOuter: '#0EA5E9',
  coreMiddle: '#0284C7',
  coreInner: '#0369A1',
  ring1: '#0EA5E9',
  ring2: '#0284C7',
};

export function useTheme() {
  const [isDark, setIsDark] = useState(true);

  useEffect(() => {
    const checkTheme = () => {
      setIsDark(document.documentElement.classList.contains('dark'));
    };

    checkTheme();

    const observer = new MutationObserver(checkTheme);
    observer.observe(document.documentElement, {
      attributes: true,
      attributeFilter: ['class'],
    });

    return () => observer.disconnect();
  }, []);

  return isDark;
}
