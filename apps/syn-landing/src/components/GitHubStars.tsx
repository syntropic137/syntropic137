import { useState, useEffect } from "react";
import { Star } from "lucide-react";

function formatStars(n: number): string {
  if (n >= 1000) return `${(n / 1000).toFixed(1).replace(/\.0$/, "")}k`;
  return String(n);
}

// Module-level cache: one fetch per repo per page load, shared across all instances.
// Guarded by VITE_GITHUB_STARS=true so CI/bots never hit the GitHub API.
const cache = new Map<string, Promise<number>>();

function fetchStars(repo: string): Promise<number> {
  if (!cache.has(repo)) {
    cache.set(
      repo,
      fetch(`https://api.github.com/repos/${repo}`)
        .then((r) => {
          if (!r.ok) throw new Error(`GitHub API ${r.status}`);
          return r.json() as Promise<{ stargazers_count: number }>;
        })
        .then((d) => d.stargazers_count),
    );
  }
  return cache.get(repo)!;
}

interface GitHubStarsProps {
  repo: string;
  size?: number;
}

export default function GitHubStars({ repo, size = 11 }: GitHubStarsProps) {
  const [stars, setStars] = useState<number | null>(null);

  useEffect(() => {
    if (import.meta.env.VITE_GITHUB_STARS !== "true") return;
    fetchStars(repo).then(setStars).catch(() => {});
  }, [repo]);

  if (stars === null) return null;

  return (
    <span
      style={{
        display: "inline-flex",
        alignItems: "center",
        gap: "3px",
        fontSize: "11px",
        color: "#f59e0b",
        fontWeight: 500,
      }}
    >
      <Star size={size} fill="#f59e0b" color="#f59e0b" />
      {formatStars(stars)}
    </span>
  );
}
