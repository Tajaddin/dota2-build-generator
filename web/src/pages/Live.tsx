import { useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api/client";
import { useSettings } from "../api/hooks";
import type { LiveSnapshot } from "../api/types";
import { ClockRail } from "../components/ClockRail";
import { Bar, ErrorBox, HeroChip, ItemIcon, LineChart, Portrait } from "../components/common";
import { clock, gold, pct, percentileText } from "../lib/format";
import { useHotkeys } from "../lib/hotkeys";
import { setVoice, useSpeakAlerts, voiceUnlocked } from "../lib/voice";

export interface LiveState {
  snap: LiveSnapshot | null;
  online: boolean;
}

const PHASES: Record<string, string> = {
  waiting: "Waiting for Dota",
  menu: "In the menus",
  loading: "Loading",
  hero_selection: "Hero selection",
  strategy: "Strategy time",
  showcase: "Showcase",
  pre_game: "Pre-game",
  in_game: "In game",
  post_game: "Game over",
};

export function NoGame({ online }: { online: boolean }) {
  const [error, setError] = useState<unknown>(null);
  const start = async () => {
    try {
      await api.post("/api/demo", { hero: "juggernaut", speed: 8 });
    } catch (e) {
      setError(e);
    }
  };
  return (
    <div className="empty">
      <h2>No game yet</h2>
      {online ? (
        <p>
          When Dota 2 sends its first Game State Integration update, this page fills in: timers, your next item, skill
          reminders and the enemy draft. If you have not installed the GSI config, do that on <Link to="/setup">Setup</Link>.
        </p>
      ) : (
        <p>The app server is not answering. Start it with <code>.\run.cmd</code> and this page reconnects by itself.</p>
      )}
      <div className="row">
        <button className="btn primary" type="button" onClick={start} disabled={!online}>
          Play a demo match
        </button>
        <Link className="btn" to="/setup">
          Set up GSI
        </Link>
      </div>
      <p className="small muted" style={{ marginTop: "0.75rem" }}>
        The demo replays a made-up match at 8× speed so you can see every live feature.
      </p>
      <ErrorBox error={error} />
    </div>
  );
}

function Marks({ snap }: { snap: LiveSnapshot }) {
  const mark = (what: string) => api.post("/api/live/mark", { what });
  const keys = useMemo(() => ({ r: () => void mark("roshan"), t: () => void mark("tormentor"), a: () => void mark("aegis") }), []);
  useHotkeys(keys);
  return (
    <div className="row" style={{ marginTop: "1rem" }}>
      <button className="btn" type="button" onClick={() => mark("roshan")} title="Shortcut R">
        Roshan killed
      </button>
      <button className="btn" type="button" onClick={() => mark("aegis")} title="Shortcut A">
        Aegis taken
      </button>
      <button className="btn" type="button" onClick={() => mark("tormentor")} title="Shortcut T">
        Tormentor killed
      </button>
      {snap.timers?.some((t) => t.id === "roshan" && t.status !== "alive") && (
        <button className="btn" type="button" onClick={() => mark("clear_roshan")}>
          Clear Roshan
        </button>
      )}
    </div>
  );
}

export function TimerColumn({ snap, compact = false }: { snap: LiveSnapshot; compact?: boolean }) {
  return (
    <div>
      <div className="clockface">
        <span className="time" aria-label="Game clock">
          {clock(snap.clock)}
        </span>
        <span className="muted">
          {PHASES[snap.phase] ?? snap.phase}
          {snap.daytime === true ? ", day" : snap.daytime === false ? ", night" : ""}
          {snap.paused ? ", paused" : ""}
        </span>
      </div>
      {snap.score && (snap.score.radiant !== null || snap.score.dire !== null) && (
        <p className="small" style={{ margin: "0.35rem 0 0" }}>
          <span className="radiant">Radiant {snap.score.radiant ?? 0}</span>
          {"  "}
          <span className="dire">Dire {snap.score.dire ?? 0}</span>
          {snap.team ? <span className="muted"> (you are {snap.team})</span> : null}
        </p>
      )}
      {snap.clock !== null && snap.clock !== undefined && <ClockRail timers={snap.timers ?? []} now={snap.clock} />}
      {!compact && <Marks snap={snap} />}
      <p className="source">Timer rules for patch {snap.timer_patch}, from Valve's patch notes. Hover a timer for its source.</p>
    </div>
  );
}

export function NextItems({ snap }: { snap: LiveSnapshot }) {
  const items = snap.next_items ?? [];
  if (!items.length) return <p className="muted small">No build data for this hero yet.</p>;
  return (
    <div>
      {items.map((i, idx) => (
        <div className="next-item" key={i.item}>
          <ItemIcon itemKey={i.item} caption={idx === 0 ? "Next" : i.name} />
          <div>
            <div className="row" style={{ justifyContent: "space-between" }}>
              <strong>{i.name}</strong>
              <span className="gold">{i.remaining > 0 ? `${gold(i.remaining)} gold to go` : "Ready"}</span>
            </div>
            <Bar value={i.progress} gold label={`${i.name} progress`} />
            <div className="meta">
              {i.eta_seconds ? `About ${clock(i.eta_seconds)} at your GPM. ` : ""}
              {i.pro_median ? `Pros finish it at ${i.pro_median} (median).` : ""}
            </div>
          </div>
        </div>
      ))}
    </div>
  );
}

export function AlertList({ snap, limit = 30 }: { snap: LiveSnapshot; limit?: number }) {
  const alerts = (snap.alerts ?? []).slice(0, limit);
  if (!alerts.length) return <p className="muted small">Alerts show up here, and are read out if voice is on.</p>;
  return (
    <ul className="alerts" aria-live="polite">
      {alerts.map((a) => (
        <li key={a.id} className={a.kind}>
          <span className="t">{a.clock_text ?? ""}</span>
          <span className="x">{a.text}</span>
        </li>
      ))}
    </ul>
  );
}

function VoiceToggle() {
  const [on, setOn] = useState(voiceUnlocked());
  return (
    <button
      className="btn"
      type="button"
      aria-pressed={on}
      onClick={() => {
        setVoice(!on);
        setOn(!on);
      }}
    >
      {on ? "Voice on" : "Turn voice on"}
    </button>
  );
}

function HeroPanel({ snap }: { snap: LiveSnapshot }) {
  const h = snap.hero!;
  const s = snap.stats!;
  return (
    <section className="panel">
      <div className="hero-head">
        <Portrait hero={h.id} size={64} wide />
        <div>
          <h2>{h.name}</h2>
          <span className="muted">
            Level {h.level ?? "–"}
            {h.alive === false ? <span className="bad">, dead, back in {h.respawn_seconds ?? "?"}s</span> : null}
            {h.scepter ? ", Aghanim's Scepter" : ""}
            {h.shard ? ", Shard" : ""}
          </span>
        </div>
      </div>
      <div className="readouts" style={{ marginTop: "1rem" }}>
        <div className="readout">
          <b>
            {s.kills}/{s.deaths}/{s.assists}
          </b>
          <span>K/D/A{s.kill_participation !== null ? `, ${pct(s.kill_participation, 0)} of team kills` : ""}</span>
        </div>
        <div className="readout">
          <b>
            {s.last_hits}/{s.denies}
          </b>
          <span>Last hits / denies</span>
        </div>
        <div className="readout">
          <b>{s.gpm}</b>
          <span>GPM ({s.xpm} XPM)</span>
        </div>
        <div className="readout">
          <b className="gold">{gold(s.gold)}</b>
          <span>Gold ({gold(s.gold_reliable)} reliable)</span>
        </div>
        <div className="readout">
          <b>{gold(s.net_worth)}</b>
          <span>Net worth</span>
        </div>
        <div className="readout">
          <b className={s.buyback_cost && s.gold >= s.buyback_cost ? "good" : "bad"}>{gold(s.buyback_cost)}</b>
          <span>Buyback{s.buyback_cooldown ? `, cooldown ${clock(s.buyback_cooldown)}` : ""}</span>
        </div>
      </div>
      {snap.items && (
        <div className="order" style={{ marginTop: "1rem" }}>
          {[...snap.items.inventory, ...snap.items.backpack].map((i) => (
            <ItemIcon key={i.slot} itemKey={i.key} />
          ))}
          {snap.items.neutral ? <ItemIcon itemKey={snap.items.neutral} /> : null}
        </div>
      )}
    </section>
  );
}

function Pace({ snap }: { snap: LiveSnapshot }) {
  if (!snap.benchmarks?.length) return null;
  return (
    <section className="panel">
      <h3>Pace against this hero's public games</h3>
      {snap.lh_target && (
        <p>
          Last hits: <strong>{snap.lh_target.you}</strong>; the median player has about {snap.lh_target.now} by now and{" "}
          {snap.lh_target.at_10} by 10:00.
        </p>
      )}
      {snap.benchmarks.map((b) => (
        <div key={b.metric} style={{ marginBottom: "0.5rem" }}>
          <div className="row small" style={{ justifyContent: "space-between" }}>
            <span>
              {b.label}: {b.value}
            </span>
            <span className="muted">{percentileText(b.percentile)}</span>
          </div>
          <Bar value={b.percentile ?? 0} label={`${b.label} percentile`} />
        </div>
      ))}
      <p className="source">Percentiles from OpenDota benchmarks for this hero.</p>
    </section>
  );
}

function EnemyPanel({ snap }: { snap: LiveSnapshot }) {
  const enemies = snap.draft?.enemies ?? [];
  if (!enemies.length)
    return (
      <section className="panel">
        <h3>Enemy draft</h3>
        <p className="muted small">
          No enemy seen yet. Dota sends a player no enemy picks during the draft; after loading, each enemy appears here once you
          see them on the minimap. To plan earlier, type them on the <Link to="/draft">Draft</Link> page.
        </p>
      </section>
    );
  return (
    <section className="panel">
      <h3>Enemy draft and what to buy against it</h3>
      <div className="row" style={{ marginBottom: "0.75rem" }}>
        {enemies.map((e) => (
          <HeroChip key={e} hero={e} size={24} />
        ))}
      </div>
      {(snap.situational_items ?? []).map((rule) => (
        <div key={rule.id} style={{ marginBottom: "0.75rem" }}>
          <div className="small">
            <strong>{rule.reason}</strong> <span className="muted">({rule.heroes.join(", ")})</span>
          </div>
          <div className="order">
            {rule.items.map((i) => (
              <ItemIcon key={i.key} itemKey={i.key} owned={i.owned} />
            ))}
          </div>
        </div>
      ))}
    </section>
  );
}

function Spectating({ snap }: { snap: LiveSnapshot }) {
  if (!snap.players?.length) return null;
  return (
    <section className="panel">
      <h3>All players (spectating)</h3>
      <table>
        <thead>
          <tr>
            <th>Hero</th>
            <th className="num">K/D/A</th>
            <th className="num">LH</th>
            <th className="num">GPM</th>
            <th className="num">Net worth</th>
            <th>Items</th>
          </tr>
        </thead>
        <tbody>
          {snap.players.map((p) => (
            <tr key={`${p.team}${p.slot}`}>
              <td className={p.team}>{p.hero ? <HeroChip hero={p.hero} size={22} /> : p.name}</td>
              <td className="num">
                {p.kills}/{p.deaths}/{p.assists}
              </td>
              <td className="num">{p.last_hits}</td>
              <td className="num">{p.gpm}</td>
              <td className="num">{gold(p.net_worth)}</td>
              <td className="small muted">{p.items.map((i) => i.name).join(", ")}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </section>
  );
}

export function LivePage({ live }: { live: LiveState }) {
  const { snap, online } = live;
  const { data: settings } = useSettings();
  useSpeakAlerts(snap?.alerts, settings?.timers.voice ?? true);

  if (!snap || snap.phase === "waiting") {
    return (
      <>
        <div className="page-head">
          <h1>Live</h1>
        </div>
        <NoGame online={online} />
      </>
    );
  }
  return (
    <>
      <div className="page-head">
        <h1>Live</h1>
        <div className="row">
          {snap.demo && <span className="tag">Demo match, made-up numbers</span>}
          {snap.connection.source === "replay" && <span className="tag">Replaying a recording</span>}
          <VoiceToggle />
          {snap.connection.source !== "game" && (
            <button className="btn" type="button" onClick={() => api.post("/api/live/reset")}>
              Stop
            </button>
          )}
        </div>
      </div>
      <div className="live">
        <aside className="panel">
          <TimerColumn snap={snap} />
        </aside>
        <div className="stack">
          {snap.hero && snap.stats && <HeroPanel snap={snap} />}
          {snap.buyback_warning && <div className="note">{snap.buyback_warning}</div>}
          {snap.next_items && (
            <section className="panel">
              <h3>Next items</h3>
              <NextItems snap={snap} />
            </section>
          )}
          {snap.skills?.next && (snap.skills.unspent ?? 0) > 0 && (
            <div className="note">
              {snap.skills.unspent} skill point{snap.skills.unspent === 1 ? "" : "s"} to spend. Pros usually take{" "}
              <strong>{snap.skills.next.name}</strong> here ({pct(snap.skills.next.share, 0)} of pro games).
            </div>
          )}
          <div className="grid cols-2">
            <Pace snap={snap} />
            <EnemyPanel snap={snap} />
          </div>
          <section className="panel">
            <h3>Alerts</h3>
            <AlertList snap={snap} />
          </section>
          {(snap.series?.length ?? 0) > 1 && (
            <section className="panel">
              <h3>
                <span className="gold">Gold</span> and <span style={{ color: "var(--river)" }}>last hits</span> over the game
              </h3>
              <LineChart points={snap.series ?? []} series={[{ key: "gold", className: "gold" }, { key: "last_hits", className: "lh" }]} />
            </section>
          )}
          <Spectating snap={snap} />
        </div>
      </div>
    </>
  );
}
