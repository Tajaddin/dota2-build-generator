import { useState } from "react";
import { useParams } from "react-router-dom";
import { api } from "../api/client";
import { useBuild, useHero } from "../api/hooks";
import type { BuildResponse, HeroDetail, RankBucket } from "../api/types";
import { Bar, ErrorBox, HeroChip, ItemIcon, Loading, Portrait, Segmented } from "../components/common";
import { BUCKETS, MEDALS, POSITION_NAMES, date, pct, pts } from "../lib/format";

function BuildTab({ build }: { build: BuildResponse }) {
  const [copied, setCopied] = useState(false);
  const copy = async () => {
    const text = await api.get<string>(`/api/heroes/${build.hero.key}/build.txt`);
    await navigator.clipboard?.writeText(text);
    setCopied(true);
  };
  const talentsByLevel = [25, 20, 15, 10].map((lvl) => build.skills.talents.filter((t) => t.level === lvl));
  return (
    <div className="stack">
      {build.notes.map((n) => (
        <div key={n} className="note">
          {n}
        </div>
      ))}
      <section className="panel">
        <div className="row" style={{ justifyContent: "space-between" }}>
          <h2>Item build</h2>
          <button className="btn" type="button" onClick={() => void copy()}>
            {copied ? "Copied" : "Copy build as text"}
          </button>
        </div>
        {build.items.starting[0] && (
          <>
            <h3>Starting items</h3>
            <div className="order">
              {build.items.starting[0].items.map((i, idx) => (
                <ItemIcon key={`${i.key}${idx}`} itemKey={i.key} />
              ))}
            </div>
            <p className="small muted">
              In {build.items.starting[0].n} of {build.pro.games} pro games.
            </p>
          </>
        )}
        <h3>Core items, in the order pros finish them</h3>
        <div className="order">
          {build.items.order.map((o) => (
            <ItemIcon key={o.key} itemKey={o.key} caption={<>{o.name}<br /><span className="gold">{o.median}</span> <span>{pct(o.share, 0)}</span></>} />
          ))}
        </div>
        <p className="source">
          From {build.pro.games} pro games on this hero
          {build.pro.since ? ` since ${date(build.pro.since)}` : ""}: median minute of the first purchase, and the share of
          games that bought it. Components that are later finished into a bigger item are left out.
        </p>
      </section>
      <section className="panel">
        <h2>Skill order</h2>
        <div className="skill-row">
          {build.skills.by_level.slice(0, 18).map((s) => (
            <div key={s.pick} className="lv" title={`${s.name}: ${pct(s.share, 0)} of ${s.n} games`}>
              {s.img ? <img src={s.img} alt={s.name} /> : <span>{s.name}</span>}
              {s.pick}
            </div>
          ))}
        </div>
        {build.skills.orders[0] && (
          <p className="small muted" style={{ marginTop: "0.5rem" }}>
            Most common first ten points: {build.skills.orders[0].order.map((a) => a.name).join(", ")} ({build.skills.orders[0].n} games
            {build.skills.orders[0].win_rate !== null ? `, ${pct(build.skills.orders[0].win_rate, 0)} won` : ""}).
          </p>
        )}
        <h3>Talents</h3>
        <table>
          <tbody>
            {talentsByLevel.map((pair, i) =>
              pair.length ? (
                <tr key={i}>
                  <td className="num" style={{ width: "3rem" }}>
                    {pair[0]!.level}
                  </td>
                  {pair.map((t) => (
                    <td key={t.key} style={{ fontWeight: (t.share ?? 0) >= 0.5 ? 600 : 400 }}>
                      {t.name} <span className="muted small">{t.share === null ? "" : pct(t.share, 0)}</span>
                    </td>
                  ))}
                </tr>
              ) : null,
            )}
          </tbody>
        </table>
      </section>
      <div className="grid cols-2">
        {Object.entries(build.items.phases).map(([phase, rows]) =>
          rows.length ? (
            <section key={phase} className="panel">
              <h3>{{ start: "Bought before the horn", early: "Early game", mid: "Mid game", late: "Late game" }[phase] ?? phase}</h3>
              <div className="order">
                {rows.slice(0, 8).map((r) => (
                  <ItemIcon key={r.key} itemKey={r.key} caption={<>{r.name}<br />{pct(r.share, 0)}</>} />
                ))}
              </div>
            </section>
          ) : null,
        )}
      </div>
      {Object.keys(build.items.timing_win_rates).length > 0 && (
        <section className="panel">
          <h2>Win rate by item timing</h2>
          <table>
            <thead>
              <tr>
                <th>Item</th>
                <th>Win rate when bought before…</th>
              </tr>
            </thead>
            <tbody>
              {Object.values(build.items.timing_win_rates)
                .sort((a, b) => b.games - a.games)
                .slice(0, 10)
                .map((t) => (
                  <tr key={t.key}>
                    <td>{t.name}</td>
                    <td className="small">
                      {t.buckets
                        .filter((b) => b.games >= 10)
                        .map((b) => `${b.label}: ${pct(b.win_rate, 0)} (${b.games})`)
                        .join("   ")}
                    </td>
                  </tr>
                ))}
            </tbody>
          </table>
          <p className="source">OpenDota item timing scenarios (public matches). Buckets with fewer than 10 games are hidden.</p>
        </section>
      )}
    </div>
  );
}

function AbilitiesTab({ hero }: { hero: HeroDetail }) {
  return (
    <section className="panel">
      {hero.abilities
        .filter((a) => !a.hidden || a.desc)
        .map((a) => (
          <div key={a.key} className="ability">
            {a.img ? <img src={a.img} alt="" loading="lazy" /> : <span />}
            <div>
              <h3 style={{ marginBottom: "0.2rem" }}>
                {a.name} {a.hidden ? <span className="tag">from Aghanim's or a sub-ability</span> : null}
              </h3>
              <p className="small">{a.desc}</p>
              <p className="small muted">
                {[a.behavior.join(", "), a.dmg_type ? `${a.dmg_type} damage` : "", a.bkb_pierce ? "pierces spell immunity" : "",
                  a.cooldown ? `cooldown ${String(a.cooldown)}` : "", a.mana ? `mana ${String(a.mana)}` : ""]
                  .filter(Boolean)
                  .join("; ")}
              </p>
            </div>
          </div>
        ))}
      {hero.scepter?.desc && (
        <p>
          <strong>Aghanim's Scepter ({hero.scepter.skill}):</strong> {hero.scepter.desc}
        </p>
      )}
      {hero.shard?.desc && (
        <p>
          <strong>Aghanim's Shard ({hero.shard.skill}):</strong> {hero.shard.desc}
        </p>
      )}
      <h3>Traits found in the ability text</h3>
      <div className="row">
        {hero.traits.map((t) => (
          <span key={t.trait} className="tag" title={`From: ${t.evidence.join(", ")}`}>
            {t.label}
          </span>
        ))}
      </div>
    </section>
  );
}

function MatchupsTab({ hero }: { hero: HeroDetail }) {
  const list = (rows: { hero: number; value?: number; edge?: number }[]) => (
    <ul style={{ listStyle: "none", padding: 0, margin: 0 }}>
      {rows.map((r) => (
        <li key={r.hero} className="row" style={{ justifyContent: "space-between", padding: "0.2rem 0" }}>
          <HeroChip hero={r.hero} size={24} />
          <span className={(r.value ?? r.edge ?? 0) >= 0 ? "good" : "bad"}>{pts(r.value ?? r.edge ?? 0)}</span>
        </li>
      ))}
    </ul>
  );
  return (
    <div className="grid cols-3">
      <section className="panel">
        <h3>Good against</h3>
        {list(hero.best_against)}
      </section>
      <section className="panel">
        <h3>Countered by</h3>
        {list(hero.worst_against)}
      </section>
      <section className="panel">
        <h3>Best with</h3>
        {list(hero.best_with)}
      </section>
      <section className="panel">
        <h3>Similar matchup profile</h3>
        <ul style={{ listStyle: "none", padding: 0, margin: 0 }}>
          {hero.similar.map((s) => (
            <li key={s.hero} style={{ padding: "0.2rem 0" }}>
              <HeroChip hero={s.hero} size={24} />
            </li>
          ))}
        </ul>
        <p className="source">Heroes whose wins and losses against everyone else look most alike.</p>
      </section>
      <section className="panel" style={{ gridColumn: "span 2" }}>
        <p className="small muted">
          Win-rate edge in percentage points against or alongside each hero, smoothed toward the hero's own win rate; pairs seen in
          fewer than 50 games are left out. Counter risk {hero.counterability.toFixed(1)}: the mean edge of its ten strongest
          counters.
        </p>
      </section>
    </div>
  );
}

function NumbersTab({ hero }: { hero: HeroDetail }) {
  const brackets = hero.meta.brackets ?? {};
  const lanes = hero.lane_roles ?? {};
  const laneTotal = Object.values(lanes).reduce((s, [g]) => s + g, 0) || 1;
  return (
    <div className="grid cols-2">
      <section className="panel">
        <h3>Win rate by medal</h3>
        <table>
          <tbody>
            {MEDALS.map((m, i) => {
              const [p, w] = brackets[String(i + 1)] ?? [0, 0];
              return (
                <tr key={m}>
                  <td>{m}</td>
                  <td className="num">{p ? pct(w / p) : "–"}</td>
                  <td className="num muted small">{p.toLocaleString()} games</td>
                </tr>
              );
            })}
          </tbody>
        </table>
        {hero.meta.pro && (
          <p className="small muted">
            Pro: {hero.meta.pro[0]} picks, {hero.meta.pro[2]} bans, {hero.meta.pro[0] ? pct(hero.meta.pro[1] / hero.meta.pro[0]) : "–"} won.
          </p>
        )}
      </section>
      <section className="panel">
        <h3>Where it is played</h3>
        {hero.positions && (
          <>
            {Object.entries(hero.positions.shares).map(([p, s]) => (
              <div key={p} style={{ marginBottom: "0.4rem" }}>
                <div className="small row" style={{ justifyContent: "space-between" }}>
                  <span>
                    {p}. {POSITION_NAMES[Number(p)]}
                  </span>
                  <span>{pct(s, 0)}</span>
                </div>
                <Bar value={s} label={`Position ${p}`} />
              </div>
            ))}
            <p className="source">
              Source: {hero.positions.source}
              {hero.positions.games ? ` (${hero.positions.games} games)` : ""}.
            </p>
          </>
        )}
        {Object.keys(lanes).length > 0 && (
          <p className="small muted">
            Public games by lane:{" "}
            {Object.entries(lanes)
              .map(([lane, [g, w]]) => `${({ "1": "safe", "2": "mid", "3": "off", "4": "jungle" } as Record<string, string>)[lane] ?? lane} ${pct(g / laneTotal, 0)} (${pct(w / Math.max(g, 1), 0)} won)`)
              .join(", ")}
          </p>
        )}
      </section>
      {hero.benchmarks && (
        <section className="panel">
          <h3>Benchmarks (median and top 10%)</h3>
          <table>
            <tbody>
              {Object.entries(hero.benchmarks).map(([metric, points]) => {
                const med = points.find(([p]) => p === 0.5)?.[1];
                const top = points.find(([p]) => p === 0.9)?.[1];
                return (
                  <tr key={metric}>
                    <td>{metric.replace(/_/g, " ")}</td>
                    <td className="num">{med?.toFixed(metric.includes("per_min") && (med ?? 0) < 10 ? 2 : 0)}</td>
                    <td className="num muted">{top?.toFixed(metric.includes("per_min") && (top ?? 0) < 10 ? 2 : 0)}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </section>
      )}
      <section className="panel">
        <h3>Base stats</h3>
        <table>
          <tbody>
            {Object.entries(hero.stats)
              .filter(([, v]) => v !== null)
              .map(([k, v]) => (
                <tr key={k}>
                  <td>{k.replace(/_/g, " ")}</td>
                  <td className="num">{String(v)}</td>
                </tr>
              ))}
          </tbody>
        </table>
      </section>
    </div>
  );
}

export function HeroPage() {
  const { ref = "" } = useParams();
  const [bucket, setBucket] = useState<RankBucket | undefined>(undefined);
  const hero = useHero(ref, bucket);
  const build = useBuild(ref);
  const [tab, setTab] = useState("build");
  if (hero.error) return <ErrorBox error={hero.error} />;
  if (!hero.data) return <Loading what="the hero" />;
  const h = hero.data;
  const stats = h.bucket_stats;
  return (
    <>
      <div className="hero-title">
        <Portrait hero={h.id} size={84} wide />
        <div>
          <h1>{h.name}</h1>
          <p className="muted" style={{ margin: 0 }}>
            {h.roles.join(", ")}. {h.attack_type}. {stats ? `${pct(stats.wr)} win rate in ${stats.games.toLocaleString()} ranked games.` : ""}{" "}
            {h.aliases.length ? `Also called ${h.aliases.join(", ")}.` : ""}
          </p>
        </div>
      </div>
      <div className="tabs" role="tablist">
        {[
          ["build", "Build"],
          ["abilities", "Abilities"],
          ["matchups", "Matchups"],
          ["numbers", "Numbers"],
        ].map(([k, label]) => (
          <button key={k} type="button" role="tab" aria-selected={tab === k} onClick={() => setTab(k!)}>
            {label}
          </button>
        ))}
      </div>
      {tab === "build" && (build.data ? <BuildTab build={build.data} /> : <ErrorBox error={build.error} />)}
      {tab === "abilities" && <AbilitiesTab hero={h} />}
      {tab === "matchups" && (
        <>
          <div style={{ marginBottom: "1rem" }}>
            <Segmented label="Rank bracket" value={(bucket ?? h.bucket) as RankBucket} options={BUCKETS.map((b) => ({ value: b.value as RankBucket, label: b.label }))} onChange={setBucket} />
          </div>
          <MatchupsTab hero={h} />
        </>
      )}
      {tab === "numbers" && <NumbersTab hero={h} />}
    </>
  );
}
