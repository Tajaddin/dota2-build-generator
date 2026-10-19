import { useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { useHeroes } from "../api/hooks";
import { ErrorBox, Loading, Segmented } from "../components/common";
import { POSITION_NAMES } from "../lib/format";
import { searchHeroes } from "../lib/search";

const ATTRS = [
  { value: "str", label: "Strength" },
  { value: "agi", label: "Agility" },
  { value: "int", label: "Intelligence" },
  { value: "all", label: "Universal" },
];

export function HeroesPage() {
  const { data, error } = useHeroes();
  const [query, setQuery] = useState("");
  const [position, setPosition] = useState(0);
  const filtered = useMemo(() => {
    const list = data ?? [];
    const found = query.trim() ? searchHeroes(list, query, 200) : list;
    return position ? found.filter((h) => h.positions.includes(position)) : found;
  }, [data, query, position]);

  return (
    <>
      <div className="page-head">
        <div>
          <h1>Heroes</h1>
          <p>Builds, abilities, matchups and numbers for every hero on the current patch.</p>
        </div>
      </div>
      <div className="row" style={{ marginBottom: "1rem" }}>
        <input className="input" placeholder="Search: am, qop, storm…" value={query} onChange={(e) => setQuery(e.target.value)} aria-label="Search heroes" />
        <Segmented
          label="Position"
          value={position}
          onChange={setPosition}
          options={[{ value: 0, label: "Any position" }, ...[1, 2, 3, 4, 5].map((p) => ({ value: p, label: `${p}. ${POSITION_NAMES[p]}` }))]}
        />
      </div>
      <ErrorBox error={error} />
      {!data && !error && <Loading what="heroes" />}
      {ATTRS.map((attr) => {
        const group = filtered.filter((h) => h.primary_attr === attr.value).sort((a, b) => a.name.localeCompare(b.name));
        if (!group.length) return null;
        return (
          <section key={attr.value} className="attr-group">
            <h2>{attr.label}</h2>
            <div className="hero-grid">
              {group.map((h) => (
                <Link key={h.id} className="hero-card" to={`/heroes/${h.key}`}>
                  {h.img ? <img src={h.img} alt="" loading="lazy" /> : null}
                  <span>{h.name}</span>
                </Link>
              ))}
            </div>
          </section>
        );
      })}
    </>
  );
}
