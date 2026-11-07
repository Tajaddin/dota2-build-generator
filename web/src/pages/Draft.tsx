import { useEffect, useMemo, useRef, useState } from "react";
import { api } from "../api/client";
import { useDraft, useHeroes, useSettings } from "../api/hooks";
import type { DraftRequest, DraftResponse, HeroListRow, LiveSnapshot, RankBucket, Side, Suggestion, TeamReport } from "../api/types";
import { ErrorBox, HeroChip, ItemIcon, Portrait, Segmented, WinSplit, useHeroMap } from "../components/common";
import { HeroPicker } from "../components/HeroPicker";
import { BUCKETS, POSITION_NAMES, pct, pts } from "../lib/format";
import { useHotkeys } from "../lib/hotkeys";
import { mergeGameDraft, type BoardState } from "../lib/liveDraft";

type Target = "us" | "them" | "ban";

type DraftState = BoardState;

const EMPTY: DraftState = { us: [], them: [], bans: [], side: "radiant" };
const STORE = "d2bg.draft";

function load(): DraftState {
  try {
    const raw = localStorage.getItem(STORE);
    return raw ? { ...EMPTY, ...(JSON.parse(raw) as DraftState) } : EMPTY;
  } catch {
    return EMPTY;
  }
}

function Slots({ heroes, side, ours, positions, selected, onSelect, onRemove }: {
  heroes: number[];
  side: Side;
  ours: boolean;
  positions: Record<string, number> | undefined;
  selected: boolean;
  onSelect: () => void;
  onRemove: (h: number) => void;
}) {
  const heroMap = useHeroMap();
  return (
    <section className={`team ${side}${selected ? " selected" : ""}`} aria-label={`${side} picks`}>
      <header>
        <h2 className={side}>{side === "radiant" ? "Radiant" : "Dire"}</h2>
        <button type="button" className="btn small" onClick={onSelect} aria-pressed={selected}>
          {ours ? "Your team" : "Enemy team"}
          {selected ? ", adding here" : ""}
        </button>
      </header>
      <div className="slots">
        {Array.from({ length: 5 }, (_, i) => {
          const h = heroes[i];
          return h ? (
            <button key={h} type="button" className="slot filled" onClick={() => onRemove(h)} title="Remove">
              <Portrait hero={h} size={40} wide />
              <span>{heroMap.get(h)?.name}</span>
              {positions?.[String(h)] ? <span className="pos">pos {positions[String(h)]}</span> : null}
            </button>
          ) : (
            <button key={`empty${i}`} type="button" className="slot" onClick={onSelect}>
              <span className="muted small">{selected && i === heroes.length ? "Next pick goes here" : "Empty"}</span>
            </button>
          );
        })}
      </div>
    </section>
  );
}

function Why({ s }: { s: Suggestion }) {
  const heroMap = useHeroMap();
  const parts = [
    ...s.why.good_against.map((g) => `beats ${heroMap.get(g.hero)?.name ?? g.hero} ${pts(g.value)}`),
    ...s.why.with.map((g) => `with ${heroMap.get(g.hero)?.name ?? g.hero} ${pts(g.value)}`),
    ...s.why.bad_against.slice(0, 1).map((g) => `weak to ${heroMap.get(g.hero)?.name ?? g.hero} ${pts(g.value)}`),
  ];
  return <>{parts.join(", ") || "No matchup data against these picks yet"}</>;
}

function SuggestionTable({ rows, onCompare, compare }: { rows: Suggestion[]; onCompare: (h: number) => void; compare: number[] }) {
  if (!rows.length) return <p className="muted">Nothing fits these filters.</p>;
  return (
    <table className="suggest">
      <thead>
        <tr>
          <th>Hero</th>
          <th className="num">Score</th>
          <th>Positions</th>
          <th>Why</th>
          <th className="num" title="How hard its best counters beat it. Higher means pick it later.">Counter risk</th>
          <th />
        </tr>
      </thead>
      <tbody>
        {rows.map((s) => (
          <tr key={s.hero}>
            <td>
              <HeroChip hero={s.hero} size={26} />
            </td>
            <td className={`num ${s.score >= 0 ? "good" : "bad"}`}>{pts(s.score, 2)}</td>
            <td className="small">{s.positions.join(", ")}</td>
            <td className="why">
              <Why s={s} />
            </td>
            <td className="num small">{s.counterability.toFixed(1)}</td>
            <td>
              <button type="button" className="btn small" disabled={compare.includes(s.hero) || compare.length >= 3} onClick={() => onCompare(s.hero)}>
                Compare
              </button>
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

function TeamPanel({ title, report }: { title: string; report: TeamReport }) {
  if (!report.heroes.length) return null;
  return (
    <div>
      <h3>{title}</h3>
      {report.warnings.length ? (
        <ul className="small" style={{ paddingLeft: "1.1rem", margin: "0 0 0.5rem" }}>
          {report.warnings.map((w) => (
            <li key={w} className="bad">
              {w}
            </li>
          ))}
        </ul>
      ) : (
        <p className="small good">No gaps found.</p>
      )}
      <p className="small muted">
        Damage: {report.damage.magic} magic, {report.damage.physical} physical, {report.damage.pure} pure. {report.melee} melee,{" "}
        {report.ranged} ranged. Disables from {report.disablers.length ? report.disablers.join(", ") : "nobody"}.
      </p>
      <div className="row">
        {Object.entries(report.traits).map(([key, t]) => (
          <span key={key} className="tag" title={t.heroes.join(", ")}>
            {t.label} {t.heroes.length}
          </span>
        ))}
      </div>
    </div>
  );
}

function Results({ res, state, onCompare, compare, removeCompare }: {
  res: DraftResponse;
  state: DraftState;
  onCompare: (h: number) => void;
  compare: number[];
  removeCompare: (h: number) => void;
}) {
  const [tab, setTab] = useState("all");
  const heroMap = useHeroMap();
  const rows = tab === "all" ? res.suggestions : (res.by_position[tab] ?? []);
  const usLeft = state.side === "radiant";
  return (
    <div className="stack" style={{ marginTop: "1rem" }}>
      {res.win && (
        <section className="panel win-meter">
          <div className="labels">
            <span className={usLeft ? "radiant" : "dire"}>{usLeft ? `You ${pct(res.win.us)}` : `Them ${pct(res.win.them)}`}</span>
            <span className={usLeft ? "dire" : "radiant"}>{usLeft ? `Them ${pct(res.win.them)}` : `You ${pct(res.win.us)}`}</span>
          </div>
          <WinSplit left={usLeft ? res.win.us : res.win.them} label="Win probability" />
          <p className="source">
            Draft-only model; on held-out matches it picked the winner {pct(res.win.held_out_accuracy)} of the time. Skill and
            execution decide far more than this number.
          </p>
        </section>
      )}
      {res.notes.map((n) => (
        <div key={n} className="note">
          {n}
        </div>
      ))}
      <section className="panel">
        <h2>Picks for you</h2>
          <div className="tabs" role="tablist">
            {["all", "1", "2", "3", "4", "5"].map((t) => (
              <button key={t} type="button" role="tab" aria-selected={tab === t} onClick={() => setTab(t)} title={t === "all" ? "" : POSITION_NAMES[Number(t)]}>
                {t === "all" ? "Any position" : `Pos ${t}`}
              </button>
            ))}
          </div>
          <SuggestionTable rows={rows} onCompare={onCompare} compare={compare} />
          <p className="source">
            Score = average win-rate edge over their picks plus your synergy weight times the edge with your picks, in percentage
            points. {res.sample_matches.toLocaleString()} ranked matches, {res.source_week}, {BUCKETS.find((b) => b.value === res.bucket)?.label}.
          </p>
      </section>
      <div className="grid cols-2">
        <section className="panel">
          <h2>Bans</h2>
          <ul className="small" style={{ listStyle: "none", padding: 0, margin: 0 }}>
            {res.bans.slice(0, 8).map((b) => (
              <li key={b.hero} className="row" style={{ justifyContent: "space-between", padding: "0.2rem 0" }}>
                <HeroChip hero={b.hero} size={24} />
                <span className="muted">
                  {b.beats.length ? `beats ${b.beats.map((x) => heroMap.get(x.hero)?.name).join(", ")}, ` : ""}
                  {pct(b.wr)} win rate
                </span>
              </li>
            ))}
          </ul>
          {res.hot_counters.length > 0 && (
            <>
              <h3 style={{ marginTop: "1rem" }}>Counter two or more of their heroes</h3>
              <div className="row">
                {res.hot_counters.slice(0, 8).map((h) => (
                  <HeroChip key={h.hero} hero={h.hero} size={24} extra={<span className="muted small">×{h.enemies.length}</span>} />
                ))}
              </div>
            </>
          )}
        </section>
        {Object.keys(res.counters).length > 0 && (
          <section className="panel">
            <h2>What beats each enemy</h2>
            {Object.entries(res.counters).map(([enemy, list]) => (
              <div key={enemy} style={{ marginBottom: "0.6rem" }}>
                <HeroChip hero={Number(enemy)} size={26} />
                <div className="row small" style={{ marginTop: "0.3rem" }}>
                  {list.slice(0, 5).map((c) => (
                    <span key={c.hero} className="tag" title={`${pts(c.edge)} points`}>
                      {heroMap.get(c.hero)?.name}
                    </span>
                  ))}
                </div>
              </div>
            ))}
          </section>
        )}
      </div>
      {compare.length > 0 && (
        <section className="panel">
          <h2>Side by side</h2>
          <table>
            <thead>
              <tr>
                <th>Hero</th>
                <th className="num">Score</th>
                <th>Why</th>
                <th className="num">Counter risk</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {res.compare.map((s) => (
                <tr key={s.hero}>
                  <td>
                    <HeroChip hero={s.hero} size={26} />
                  </td>
                  <td className="num">{pts(s.score, 2)}</td>
                  <td className="small muted">
                    <Why s={s} />
                  </td>
                  <td className="num">{s.counterability.toFixed(1)}</td>
                  <td>
                    <button type="button" className="btn small" onClick={() => removeCompare(s.hero)}>
                      Remove
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </section>
      )}
      <div className="grid cols-2">
        <section className="panel">
          <TeamPanel title="Your team" report={res.ours} />
          <div style={{ height: "1rem" }} />
          <TeamPanel title="Their team" report={res.theirs} />
          {!res.ours.heroes.length && !res.theirs.heroes.length && <p className="muted">Pick heroes to see team gaps.</p>}
        </section>
        <section className="panel">
          <h2>Lanes</h2>
          {res.lanes.length ? (
            <table>
              <thead>
                <tr>
                  <th>Your lane</th>
                  <th>You</th>
                  <th>Them</th>
                  <th className="num">Edge</th>
                </tr>
              </thead>
              <tbody>
                {res.lanes.map((l) => (
                  <tr key={l.lane}>
                    <td>{l.lane === "safe" ? "Safe lane" : l.lane === "mid" ? "Mid" : "Off lane"}</td>
                    <td className="small">{l.ours.map((h) => heroMap.get(h)?.name).join(", ") || "–"}</td>
                    <td className="small">{l.theirs.map((h) => heroMap.get(h)?.name).join(", ") || "–"}</td>
                    <td className={`num ${l.advantage >= 0 ? "good" : "bad"}`} title={`${l.pairs_known} of ${l.pairs_total} pairs have data`}>
                      {pts(l.advantage)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          ) : (
            <p className="muted">Add heroes to both teams to see lanes. Positions are guessed from pro games; the numbers are a rough guide.</p>
          )}
        </section>
      </div>
      {res.items.length > 0 && (
        <section className="panel">
          <h2>Items to plan for against their draft</h2>
          <div className="grid cols-2">
            {res.items.map((rule) => (
              <div key={rule.id}>
                <p className="small" style={{ marginBottom: "0.3rem" }}>
                  <strong>{rule.reason}</strong> <span className="muted">({rule.heroes.join(", ")})</span>
                </p>
                <div className="order">
                  {rule.items.map((i) => (
                    <ItemIcon key={i.key} itemKey={i.key} />
                  ))}
                </div>
              </div>
            ))}
          </div>
        </section>
      )}
    </div>
  );
}

/** Says what came from the game so far, and plainly what Dota does not send a player. */
function GameStatus({ live }: { live: LiveSnapshot | null }) {
  const draft = live?.draft;
  if (!live || !draft || !live.connection.connected) {
    return (
      <p className="note" style={{ marginBottom: "1rem" }}>
        No game data right now. During a game your hero, your team and the bans fill in here by themselves. Dota does not send a
        player the other picks during the draft, so type those in.
      </p>
    );
  }
  const found = Object.values(draft.sources ?? {});
  return (
    <section className="panel" style={{ marginBottom: "1rem" }} aria-label="From the game">
      <p className="small" style={{ margin: 0 }}>
        <span className="dot on" />
        From the game{live.demo ? " (demo)" : ""}: {found.length ? found.join("; ") : "nothing yet; your hero appears once you pick"}.
      </p>
      {draft.note && (
        <p className="small muted" style={{ margin: "0.4rem 0 0" }}>
          {draft.note}
        </p>
      )}
    </section>
  );
}

export function DraftPage({ live }: { live: LiveSnapshot | null }) {
  const { data: heroes } = useHeroes();
  const { data: settings } = useSettings();
  const [state, setState] = useState<DraftState>(load);
  // Whatever the game sends (his hero and team, the bans, and after loading the minimap's heroes) fills
  // the board by itself; his own edits stay. Synced while rendering, React's pattern for outside data.
  const liveDraft = live?.draft;
  const liveKey = liveDraft
    ? JSON.stringify([live?.match_id, liveDraft.allies, liveDraft.enemies, liveDraft.bans, liveDraft.side])
    : null;
  const [syncedKey, setSyncedKey] = useState<string | null>(null);
  if (liveDraft && liveKey !== syncedKey) {
    setSyncedKey(liveKey);
    setState((s) => mergeGameDraft(s, liveDraft, live?.match_id ?? null));
  }
  const [history, setHistory] = useState<DraftState[]>([]);
  const [target, setTarget] = useState<Target>("them");
  const [bucket, setBucket] = useState<RankBucket | null>(null);
  const [weight, setWeight] = useState<number | null>(null);
  const [compare, setCompare] = useState<number[]>([]);
  const [paste, setPaste] = useState("");
  const [pasteMsg, setPasteMsg] = useState("");
  const search = useRef<HTMLInputElement>(null);

  useEffect(() => {
    try {
      localStorage.setItem(STORE, JSON.stringify(state));
    } catch {
      // the draft just won't survive a reload
    }
  }, [state]);

  const update = (next: DraftState) => {
    setHistory((h) => [...h.slice(-30), state]);
    setState(next);
  };
  const taken = useMemo(() => new Set([...state.us, ...state.them, ...state.bans]), [state]);

  const add = (h: HeroListRow) => {
    if (taken.has(h.id)) return;
    if (target === "ban") update({ ...state, bans: [...state.bans, h.id] });
    else if (target === "us" && state.us.length < 5) update({ ...state, us: [...state.us, h.id] });
    else if (target === "them" && state.them.length < 5) update({ ...state, them: [...state.them, h.id] });
  };
  const remove = (h: number) =>
    update({ ...state, us: state.us.filter((x) => x !== h), them: state.them.filter((x) => x !== h), bans: state.bans.filter((x) => x !== h) });

  const keys = useMemo(
    () => ({
      "/": () => search.current?.focus(),
      Tab: () => setTarget((t) => (t === "us" ? "them" : "us")),
      b: () => setTarget("ban"),
      Backspace: () => {
        const last = history[history.length - 1];
        if (!last) return;
        setState(last);
        setHistory(history.slice(0, -1));
      },
    }),
    [history],
  );
  useHotkeys(keys);

  const canFill = !!liveDraft && (liveDraft.allies.length > 0 || liveDraft.enemies.length > 0 || liveDraft.bans.length > 0);
  const fillFromGame = () => {
    if (!liveDraft) return;
    update(mergeGameDraft({ ...EMPTY }, liveDraft, live?.match_id ?? null));
  };

  const req: DraftRequest = {
    allies: state.us,
    enemies: state.them,
    bans: state.bans,
    side: state.side,
    rank_bucket: bucket ?? settings?.rank_bucket ?? "all",
    synergy_weight: weight ?? settings?.synergy_weight ?? 0.5,
    compare,
    n: 15,
  };
  const { data, error, isFetching } = useDraft(req, !!heroes);

  const copyText = () => {
    const name = (id: number) => heroes?.find((h) => h.id === id)?.name ?? String(id);
    const text = `Us: ${state.us.map(name).join(", ")}\nThem: ${state.them.map(name).join(", ")}${state.bans.length ? `\nBans: ${state.bans.map(name).join(", ")}` : ""}`;
    void navigator.clipboard?.writeText(text);
  };
  const applyPaste = async () => {
    const res = await api.post<{ heroes: HeroListRow[]; unknown: string[] }>("/api/heroes/parse", { text: paste });
    const ids = res.heroes.map((h) => h.id).filter((id) => !taken.has(id));
    if (target === "ban") update({ ...state, bans: [...state.bans, ...ids] });
    else if (target === "us") update({ ...state, us: [...state.us, ...ids].slice(0, 5) });
    else update({ ...state, them: [...state.them, ...ids].slice(0, 5) });
    setPasteMsg(res.unknown.length ? `Not recognised: ${res.unknown.join(", ")}` : `Added ${ids.length}`);
    setPaste("");
  };

  const ourSide = state.side;
  const radiantIsUs = ourSide === "radiant";
  return (
    <>
      <div className="page-head">
        <div>
          <h1>Draft</h1>
          <p>Your hero, your team and the bans fill in from the game by themselves. Type the other picks as they happen.</p>
        </div>
        <div className="row">
          {canFill && (
            <button className="btn primary" type="button" onClick={fillFromGame}>
              Reset to the game's draft
            </button>
          )}
          <button className="btn" type="button" onClick={() => update({ ...state, side: radiantIsUs ? "dire" : "radiant" })}>
            Swap sides
          </button>
          <button className="btn" type="button" onClick={copyText}>
            Copy as text
          </button>
          <button className="btn danger" type="button" onClick={() => update(EMPTY)}>
            Clear
          </button>
        </div>
      </div>
      <GameStatus live={live} />

      <div className="board">
        <Slots
          heroes={radiantIsUs ? state.us : state.them}
          side="radiant"
          ours={radiantIsUs}
          positions={radiantIsUs ? data?.positions.ours : data?.positions.theirs}
          selected={target === (radiantIsUs ? "us" : "them")}
          onSelect={() => setTarget(radiantIsUs ? "us" : "them")}
          onRemove={remove}
        />
        <div className="river" aria-hidden="true" />
        <Slots
          heroes={radiantIsUs ? state.them : state.us}
          side="dire"
          ours={!radiantIsUs}
          positions={radiantIsUs ? data?.positions.theirs : data?.positions.ours}
          selected={target === (radiantIsUs ? "them" : "us")}
          onSelect={() => setTarget(radiantIsUs ? "them" : "us")}
          onRemove={remove}
        />
      </div>
      <div className="bans" aria-label="Bans">
        <button type="button" className="btn small" aria-pressed={target === "ban"} onClick={() => setTarget("ban")}>
          {target === "ban" ? "Adding bans" : "Add bans"}
        </button>
        {state.bans.map((b) => (
          <button key={b} type="button" className="ban" onClick={() => remove(b)} title="Remove ban">
            <Portrait hero={b} size={30} />
          </button>
        ))}
      </div>

      <div className="row" style={{ marginTop: "1rem", justifyContent: "space-between" }}>
        <Segmented
          label="Rank bracket"
          value={(bucket ?? settings?.rank_bucket ?? "all") as RankBucket}
          options={BUCKETS.map((b) => ({ value: b.value as RankBucket, label: b.label }))}
          onChange={setBucket}
        />
        <label className="row small">
          Synergy weight
          <input
            type="range"
            min={0}
            max={1}
            step={0.05}
            value={weight ?? settings?.synergy_weight ?? 0.5}
            onChange={(e) => setWeight(Number(e.target.value))}
          />
          {(weight ?? settings?.synergy_weight ?? 0.5).toFixed(2)}
        </label>
      </div>

      {heroes && (
        <HeroPicker
          ref={search}
          heroes={heroes}
          taken={taken}
          onPick={add}
          onTab={() => setTarget((t) => (t === "us" ? "them" : "us"))}
          placeholder={`Add to ${target === "ban" ? "bans" : target === "us" ? "your team" : "the enemy team"}: type am, qop, pudge… then Enter (/ to focus, Tab to switch team)`}
        />
      )}
      <details style={{ marginTop: "0.75rem" }}>
        <summary className="small muted">Paste a list of heroes</summary>
        <div className="row" style={{ marginTop: "0.5rem" }}>
          <textarea className="input" rows={2} value={paste} onChange={(e) => setPaste(e.target.value)} placeholder="am, lion, cm" />
          <button className="btn" type="button" onClick={() => void applyPaste()} disabled={!paste.trim()}>
            Add to {target === "ban" ? "bans" : target === "us" ? "your team" : "enemy team"}
          </button>
          <span className="small muted">{pasteMsg}</span>
        </div>
      </details>

      <ErrorBox error={error} />
      {isFetching && !data ? <p className="muted">Working out suggestions…</p> : null}
      {data && (
        <Results
          res={data}
          state={state}
          compare={compare}
          onCompare={(h) => setCompare((c) => (c.includes(h) ? c : [...c, h].slice(0, 3)))}
          removeCompare={(h) => setCompare((c) => c.filter((x) => x !== h))}
        />
      )}
    </>
  );
}
