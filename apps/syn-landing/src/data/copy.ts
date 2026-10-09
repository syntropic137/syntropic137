/**
 * Page copy and links (design/landing-plan.md, section 5: strings live here).
 * P5 holds the shell, nav and footer, from the v4 boards
 * (design/canvas/Landing.dc.html, PhoneLanding.dc.html); P6 and P7 add the
 * sections.
 */

export const REPO = "syntropic137/syntropic137";
export const GITHUB_URL = `https://github.com/${REPO}`;
export const DOCS_URL = "https://docs.syntropic137.com";
export const X_URL = "https://x.com/syntropic137";

export interface SiteLink {
  label: string;
  href: string;
}

/** True for links that leave syntropic137.com (they open in a new tab). */
export const isExternal = (href: string): boolean => /^https?:\/\//.test(href);

/**
 * Nav links, in the board's order. The in-page targets are today's sections
 * until P6 and P7 rebuild them; Evals points at the docs until P7 adds the
 * "04 Compounding improvement" section (#evals).
 */
export const NAV_LINKS: readonly SiteLink[] = [
  { label: "Workflows", href: "#how-it-works" },
  { label: "Harnesses", href: "#orchestrator" },
  { label: "Observability", href: "#observability" },
  { label: "Evals", href: `${DOCS_URL}/docs/guide/evals` },
  { label: "Docs", href: DOCS_URL },
];

export const NAV_GITHUB_LABEL = "Star on GitHub";
export const NAV_CTA: SiteLink = { label: "Get started", href: "#get-started" };
