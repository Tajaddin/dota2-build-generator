import { forwardRef, useMemo, useState } from "react";
import type { HeroListRow } from "../api/types";
import { searchHeroes } from "../lib/search";

interface Props {
  heroes: HeroListRow[];
  taken: Set<number>;
  onPick: (hero: HeroListRow) => void;
  placeholder?: string;
  onTab?: () => void;
}

/** Type to filter (aliases like "am", "qop" work), Enter takes the first match. */
export const HeroPicker = forwardRef<HTMLInputElement, Props>(function HeroPicker({ heroes, taken, onPick, placeholder, onTab }, ref) {
  const [query, setQuery] = useState("");
  const results = useMemo(() => {
    const list = query.trim() ? searchHeroes(heroes, query, 40) : [...heroes].sort((a, b) => a.name.localeCompare(b.name));
    return list;
  }, [heroes, query]);
  const firstFree = results.find((h) => !taken.has(h.id));

  return (
    <div className="picker">
      <input
        ref={ref}
        className="input"
        style={{ width: "100%" }}
        value={query}
        placeholder={placeholder ?? "Type a hero: am, qop, pudge… then Enter"}
        aria-label="Search heroes"
        onChange={(e) => setQuery(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === "Enter" && firstFree) {
            onPick(firstFree);
            setQuery("");
          }
          if (e.key === "Escape") setQuery("");
          if (e.key === "Tab" && onTab) {
            e.preventDefault();
            onTab();
          }
        }}
      />
      <div className="results" role="list">
        {results.map((h) => (
          <button
            key={h.id}
            type="button"
            role="listitem"
            className={`pick-tile${h === firstFree && query ? " first" : ""}`}
            disabled={taken.has(h.id)}
            onClick={() => {
              onPick(h);
              setQuery("");
            }}
            title={h.name}
          >
            {h.img ? <img src={h.img} alt="" loading="lazy" /> : null}
            <span>{h.name}</span>
          </button>
        ))}
      </div>
    </div>
  );
});
