import type { HeroSummary } from "../api/types";

export const norm = (s: string) => s.toLowerCase().replace(/[^a-z0-9]/g, "");

/** Client-side hero search, mirroring the server: aliases, prefixes, word starts, initials, substrings. */
export function searchHeroes<T extends HeroSummary>(heroes: readonly T[], query: string, limit = 12): T[] {
  const q = norm(query);
  if (!q) return [];
  const scored: [T, number][] = [];
  for (const h of heroes) {
    const name = norm(h.name);
    const key = norm(h.key);
    const words = h.name.split(/[\s\-']+/).map(norm).filter(Boolean);
    const initials = words.map((w) => w[0]).join("");
    const aliases = h.aliases.map(norm);
    let score = 0;
    if (aliases.includes(q) || q === name || q === key || q === String(h.id)) score = 100;
    else if (name.startsWith(q) || key.startsWith(q)) score = 80;
    else if (words.some((w) => w.startsWith(q))) score = 70;
    else if (q.length >= 2 && aliases.some((a) => a.startsWith(q))) score = 65;
    else if (q.length >= 2 && initials.startsWith(q)) score = 60;
    else if (name.includes(q)) score = 50;
    if (score) scored.push([h, score]);
  }
  scored.sort((a, b) => b[1] - a[1] || a[0].name.localeCompare(b[0].name));
  return scored.slice(0, limit).map(([h]) => h);
}
