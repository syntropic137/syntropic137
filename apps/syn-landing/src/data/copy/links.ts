/** The /links page (link in bio, from the X profile): order is priority. */
import { DOCS_URL, GITHUB_URL, X_URL } from "../copy";

/** Stable ids for click analytics (data-link-id); never rename one. */
export type LinkId = "website" | "github" | "docs" | "canny" | "discussions" | "x" | "email";

export interface BioLink {
  id: LinkId;
  title: string;
  desc: string;
  href: string;
  /** featured: the one large card; primary: full cards; secondary: the grouped list. */
  tier: "featured" | "primary" | "secondary";
}

export const LINKS_PAGE = {
  documentTitle: "Syntropic137: links",
  tagline: "Agent work that compounds.",
  installNote: "Self-host in about five minutes. Node 18+ and Docker.",
  listLabel: "Syntropic137 links",
  newTab: "(opens in a new tab)",
  footer: "MIT licensed · Self-hosted",
} as const;

export const BIO_LINKS: readonly BioLink[] = [
  { id: "website", title: "Website", desc: "syntropic137.com", href: "/", tier: "featured" },
  { id: "github", title: "GitHub", desc: "Source code and releases", href: GITHUB_URL, tier: "primary" },
  { id: "docs", title: "Documentation", desc: "Guides, CLI and API reference", href: DOCS_URL, tier: "primary" },
  { id: "canny", title: "Request a feature", desc: "Suggest and vote on Canny", href: "https://syntropic137.canny.io/", tier: "secondary" },
  { id: "discussions", title: "GitHub Discussions", desc: "Questions and community help", href: `${GITHUB_URL}/discussions`, tier: "secondary" },
  { id: "x", title: "@syntropic137", desc: "Updates and announcements on X", href: X_URL, tier: "secondary" },
  { id: "email", title: "Email", desc: "hello@syntropic137.com", href: "mailto:hello@syntropic137.com", tier: "secondary" },
];
