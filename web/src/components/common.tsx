import { useMemo, type ReactNode } from "react";
import { Link } from "react-router-dom";
import { ApiError } from "../api/client";
import { useHeroes, useItems } from "../api/hooks";
import type { HeroListRow, ItemRow } from "../api/types";

export function useHeroMap(): Map<number, HeroListRow> {
  const { data } = useHeroes();
  return useMemo(() => new Map((data ?? []).map((h) => [h.id, h])), [data]);
}

export function useItemMap(): Map<string, ItemRow> {
  const { data } = useItems();
  return useMemo(() => new Map((data ?? []).map((i) => [i.key, i])), [data]);
}

function initials(name: string): string {
  return name
    .split(/[\s\-']+/)
    .map((w) => w[0])
    .join("")
    .slice(0, 2);
}

export function Portrait({ hero, size = 40, wide = false }: { hero: number | null | undefined; size?: number; wide?: boolean }) {
  const heroes = useHeroMap();
  const h = hero ? heroes.get(hero) : undefined;
  const w = wide ? Math.round(size * 1.78) : size;
  const src = wide ? h?.img : (h?.icon ?? h?.img);
  return (
    <span className="portrait" style={{ width: w, height: size, fontSize: size * 0.4 }} title={h?.name}>
      {src ? <img src={src} alt="" loading="lazy" /> : h ? initials(h.name) : "?"}
    </span>
  );
}

export function HeroChip({ hero, size = 28, link = true, extra }: { hero: number; size?: number; link?: boolean; extra?: ReactNode }) {
  const heroes = useHeroMap();
  const h = heroes.get(hero);
  const body = (
    <>
      <Portrait hero={hero} size={size} />
      <span>{h?.name ?? `Hero ${hero}`}</span>
      {extra}
    </>
  );
  return link && h ? (
    <Link className="hero-chip" to={`/heroes/${h.key}`}>
      {body}
    </Link>
  ) : (
    <span className="hero-chip">{body}</span>
  );
}

export function ItemIcon({ itemKey, caption, owned = false, link = true }: { itemKey: string; caption?: ReactNode; owned?: boolean; link?: boolean }) {
  const items = useItemMap();
  const item = items.get(itemKey);
  const name = item?.name ?? itemKey.replace(/_/g, " ");
  const body = (
    <>
      <span className="pic">{item?.img ? <img src={item.img} alt="" loading="lazy" /> : <span>{initials(name)}</span>}</span>
      <span>{caption ?? name}</span>
    </>
  );
  const cls = `item-icon${owned ? " owned" : ""}`;
  return link ? (
    <Link className={cls} to={`/items/${itemKey}`} title={name}>
      {body}
    </Link>
  ) : (
    <span className={cls} title={name}>
      {body}
    </span>
  );
}

export function Segmented<T extends string | number>({
  value,
  options,
  onChange,
  label,
}: {
  value: T;
  options: readonly { value: T; label: string }[];
  onChange: (v: T) => void;
  label: string;
}) {
  return (
    <div className="segmented" role="group" aria-label={label}>
      {options.map((o) => (
        <button key={String(o.value)} type="button" aria-pressed={o.value === value} onClick={() => onChange(o.value)}>
          {o.label}
        </button>
      ))}
    </div>
  );
}

export function ErrorBox({ error }: { error: unknown }) {
  if (!error) return null;
  const msg = error instanceof ApiError ? error.message : error instanceof Error ? error.message : String(error);
  return (
    <div className="error" role="alert">
      {msg}
    </div>
  );
}

export function Bar({ value, gold = false, label }: { value: number; gold?: boolean; label: string }) {
  const v = Math.max(0, Math.min(1, value));
  return (
    <div className={`bar${gold ? " gold" : ""}`} role="meter" aria-label={label} aria-valuemin={0} aria-valuemax={100} aria-valuenow={Math.round(v * 100)}>
      <i style={{ width: `${v * 100}%` }} />
    </div>
  );
}

/** Two-sided win probability, Radiant colour on the left. */
export function WinSplit({ left, label }: { left: number; label: string }) {
  return (
    <div className="split" role="meter" aria-label={label} aria-valuenow={Math.round(left * 100)} aria-valuemin={0} aria-valuemax={100}>
      <i style={{ width: `${left * 100}%` }} />
      <i style={{ width: `${(1 - left) * 100}%` }} />
    </div>
  );
}

/** A small line chart of one or two series over game time. */
export function LineChart({
  points,
  series,
}: {
  points: { t: number; [k: string]: number | null }[];
  series: { key: string; className: string }[];
}) {
  if (points.length < 2) return <p className="muted small">The chart fills in as the game goes on.</p>;
  const w = 600;
  const h = 128;
  const t0 = points[0]!.t;
  const t1 = points[points.length - 1]!.t || 1;
  const paths = series.map((s) => {
    const vals = points.map((p) => p[s.key] ?? 0);
    const max = Math.max(...vals, 1);
    const d = points
      .map((p, i) => {
        const x = ((p.t - t0) / Math.max(t1 - t0, 1)) * w;
        const y = h - ((vals[i] ?? 0) / max) * (h - 6) - 3;
        return `${i ? "L" : "M"}${x.toFixed(1)},${y.toFixed(1)}`;
      })
      .join("");
    return <path key={s.key} className={s.className} d={d} />;
  });
  return (
    <svg className="chart" viewBox={`0 0 ${w} ${h}`} preserveAspectRatio="none" role="img" aria-label="Gold and last hits over time">
      {paths}
    </svg>
  );
}

export function Loading({ what }: { what: string }) {
  return <p className="muted">Loading {what}…</p>;
}
