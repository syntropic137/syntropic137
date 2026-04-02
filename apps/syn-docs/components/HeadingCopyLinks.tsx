'use client';

import { useEffect } from 'react';
import { usePathname } from 'next/navigation';

// Clipboard icon SVG (Lucide "clipboard-copy", 14x14)
const COPY_ICON = `<svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="8" y="2" width="8" height="4" rx="1" ry="1"/><path d="M16 4h2a2 2 0 0 1 2 2v14a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2V6a2 2 0 0 1 2-2h2"/></svg>`;

// Check icon SVG (Lucide "check", 14x14)
const CHECK_ICON = `<svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="20 6 9 17 4 12"/></svg>`;

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

function handleHeadingClick(e: MouseEvent) {
  const heading = (e.target as HTMLElement).closest('h1, h2, h3, h4, h5, h6');
  if (!heading) return;

  const svg = heading.querySelector('svg.lucide-link') as HTMLElement | null;
  if (!svg) return;

  const clickedEl = e.target as HTMLElement;
  const isIcon = clickedEl === svg || svg.contains(clickedEl);
  const isAnchor = clickedEl.closest('a[href^="#"]');

  if (!isIcon && !isAnchor) return;

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

function handleCodeClick(e: MouseEvent) {
  const target = e.target as HTMLElement;
  if (target.closest('button')) return;

  // Find the .line span (Shiki renders each line as span.line)
  const lineSpan = target.closest('.line') as HTMLElement | null;
  if (!lineSpan) return;
  if (!lineSpan.closest('pre')) return;

  // Skip if user is selecting text
  const selection = window.getSelection();
  if (selection && selection.toString().length > 0) return;

  const text = lineSpan.textContent?.trim();
  if (!text) return;

  navigator.clipboard.writeText(text);
  showTooltip('Line copied!', null, e.clientX, e.clientY);

  // Flash the line and swap icon to checkmark
  lineSpan.classList.add('line-copied');
  const icon = lineSpan.querySelector('.line-copy-icon');
  if (icon) icon.innerHTML = CHECK_ICON;

  setTimeout(() => {
    lineSpan.classList.remove('line-copied');
    if (icon) icon.innerHTML = COPY_ICON;
  }, 1200);
}

/** Inject a copy icon into each .line span in code blocks. */
function injectLineCopyIcons() {
  const lines = document.querySelectorAll('pre code .line');
  lines.forEach((line) => {
    // Skip if already injected
    if (line.querySelector('.line-copy-icon')) return;
    const icon = document.createElement('span');
    icon.className = 'line-copy-icon';
    icon.innerHTML = COPY_ICON;
    icon.setAttribute('aria-hidden', 'true');
    line.appendChild(icon);
  });
}

export function HeadingCopyLinks() {
  const pathname = usePathname();

  useEffect(() => {
    document.addEventListener('click', handleHeadingClick);
    document.addEventListener('click', handleCodeClick);
    return () => {
      document.removeEventListener('click', handleHeadingClick);
      document.removeEventListener('click', handleCodeClick);
    };
  }, []);

  // Re-inject icons on route change (Next.js client navigation)
  useEffect(() => {
    // Small delay to let hydration/rendering complete
    const timer = setTimeout(injectLineCopyIcons, 100);
    return () => clearTimeout(timer);
  }, [pathname]);

  return null;
}
