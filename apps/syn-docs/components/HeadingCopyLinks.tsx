'use client';

import { useEffect } from 'react';

function showTooltip(text: string, anchorEl: HTMLElement | null, x?: number, y?: number) {
  const tooltip = document.createElement('span');
  tooltip.textContent = text;
  tooltip.style.cssText =
    'position:fixed;z-index:9999;padding:4px 12px;border-radius:6px;font-size:12px;font-weight:500;color:#4d80ff;background:#0f0f1a;border:1px solid rgba(77,128,255,0.25);box-shadow:0 4px 12px rgba(0,0,0,0.4);white-space:nowrap;pointer-events:none;transition:opacity 0.15s;';
  document.body.appendChild(tooltip);

  if (anchorEl) {
    const rect = anchorEl.getBoundingClientRect();
    tooltip.style.left = `${rect.left + rect.width / 2 - tooltip.offsetWidth / 2}px`;
    tooltip.style.top = `${rect.top - tooltip.offsetHeight - 6}px`;
  } else if (x !== undefined && y !== undefined) {
    tooltip.style.left = `${x - tooltip.offsetWidth / 2}px`;
    tooltip.style.top = `${y - tooltip.offsetHeight - 10}px`;
  }

  setTimeout(() => {
    tooltip.style.opacity = '0';
    setTimeout(() => tooltip.remove(), 150);
  }, 1200);
}

export function HeadingCopyLinks() {
  useEffect(() => {
    function handleHeadingClick(e: MouseEvent) {
      const heading = (e.target as HTMLElement).closest('h1, h2, h3, h4, h5, h6');
      if (!heading) return;

      const svg = heading.querySelector('svg.lucide-link') as HTMLElement | null;
      if (!svg) return;

      const clickedEl = e.target as HTMLElement;
      const isIcon = clickedEl === svg || svg.contains(clickedEl);
      const isAnchor = clickedEl.closest('a[href^="#"]');

      if (isIcon || isAnchor) {
        e.preventDefault();
        const id = heading.id;
        if (!id) return;
        const url = `${window.location.origin}${window.location.pathname}#${id}`;
        navigator.clipboard.writeText(url);

        svg.classList.add('!opacity-100', '!text-fd-primary');
        showTooltip('Copied!', svg);

        setTimeout(() => {
          svg.classList.remove('!opacity-100', '!text-fd-primary');
        }, 1500);
      }
    }

    function handleCodeClick(e: MouseEvent) {
      const target = e.target as HTMLElement;
      const pre = target.closest('pre');
      if (!pre) return;
      if (target.closest('button')) return;

      const code = pre.querySelector('code');
      if (!code) return;

      const codeRect = code.getBoundingClientRect();
      const lineHeight = parseFloat(getComputedStyle(code).lineHeight) || 20;
      const clickY = e.clientY - codeRect.top + code.scrollTop;
      const lineIndex = Math.floor(clickY / lineHeight);

      const lines = code.textContent?.split('\n') ?? [];
      const line = lines[lineIndex]?.trim();
      if (!line) return;

      navigator.clipboard.writeText(line);
      showTooltip('Copied!', null, e.clientX, e.clientY);

      pre.style.outline = '1px solid rgba(77, 128, 255, 0.25)';
      setTimeout(() => { pre.style.outline = ''; }, 1200);
    }

    document.addEventListener('click', handleHeadingClick);
    document.addEventListener('click', handleCodeClick);
    return () => {
      document.removeEventListener('click', handleHeadingClick);
      document.removeEventListener('click', handleCodeClick);
    };
  }, []);

  return null;
}
