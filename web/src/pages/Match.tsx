import { useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { api } from "../api/client";
import { useMatch, usePostGame } from "../api/hooks";
import type { MatchReview, ReviewRow } from "../api/types";
import { Bar, ErrorBox, HeroChip, Loading } from "../components/common";
import { dateTime, gold, percentileText } from "../lib/format";

function Team({ rows, won, side }: { rows: ReviewRow[]; won: boolean; side: "radiant" | "dire" }) {
  return (
    <section className="panel">
      <h3 className={side}>
        {side === "radiant" ? "Radiant" : "Dire"} {won ? "won" : "lost"}
      </h3>
      <table>
        <thead>
          <tr>
            <th>Hero</th>
            <th className="num">K/D/A</th>
            <th className="num">LH/DN</th>
            <th className="num">GPM</th>
            <th className="num">Net worth</th>
            <th className="num">Damage</th>
            <th>Items</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => (
            <tr key={`${r.hero}${r.account_id}`}>
              <td>
                <HeroChip hero={r.hero} size={24} extra={r.name ? <span className="muted small">{r.name}</span> : null} />
              </td>
              <td className="num">
                {r.kills}/{r.deaths}/{r.assists}
              </td>
              <td className="num">
                {r.last_hits}/{r.denies}
              </td>
              <td className="num">{r.gpm}</td>
              <td className="num gold">{gold(r.net_worth)}</td>
              <td className="num">{gold(r.hero_damage)}</td>
              <td className="small muted">{r.items.map((i) => i.name).join(", ")}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </section>
  );
}

function Review({ m }: { m: MatchReview }) {
  const [parse, setParse] = useState("");
  const requestParse = async () => {
    try {
      await api.post(`/api/matches/${m.match_id}/parse`);
      setParse("Parse requested. OpenDota usually finishes within a few minutes; reload this page then.");
    } catch (e) {
      setParse(e instanceof Error ? e.message : String(e));
    }
  };
  return (
    <div className="stack">
      <p className="muted">
        Match {m.match_id}, {dateTime(m.start_time)}, {m.duration_text}. Score{" "}
        <span className="radiant">{m.score.radiant}</span> to <span className="dire">{m.score.dire}</span>.
      </p>
      {!m.parsed && (
        <div className="note">
          OpenDota has not parsed this replay, so item timings and laning numbers are missing.{" "}
          <button className="btn small" type="button" onClick={() => void requestParse()}>
            Request a parse
          </button>{" "}
          {parse}
        </div>
      )}
      {m.me && (
        <section className="panel">
          <h2>
            Your game: <span className={m.me.won ? "good" : "bad"}>{m.me.won ? "won" : "lost"}</span> on {m.me.row.hero_name}
          </h2>
          {m.notes.length > 0 && (
            <ul>
              {m.notes.map((n) => (
                <li key={n}>{n}</li>
              ))}
            </ul>
          )}
          <div className="grid cols-2">
            <div>
              <h3>Against other {m.me.row.hero_name} players</h3>
              {m.me.benchmarks.length ? (
                m.me.benchmarks.map((b) => (
                  <div key={b.metric} style={{ marginBottom: "0.45rem" }}>
                    <div className="small row" style={{ justifyContent: "space-between" }}>
                      <span>
                        {b.label}: {b.value}
                      </span>
                      <span className="muted">{percentileText(b.percentile)}</span>
                    </div>
                    <Bar value={b.percentile} label={b.label} />
                  </div>
                ))
              ) : (
                <p className="small muted">No benchmarks until the replay is parsed.</p>
              )}
            </div>
            <div>
              <h3>Item timings against pro medians</h3>
              {m.me.item_timings.length ? (
                <table>
                  <tbody>
                    {m.me.item_timings.map((t) => (
                      <tr key={t.item}>
                        <td>{t.name}</td>
                        <td className="num">{t.you}</td>
                        <td className="num muted">pros {t.pro_median}</td>
                        <td className={`num ${t.delta_seconds > 0 ? "bad" : "good"}`}>{t.delta_seconds > 0 ? `+${t.delta}` : t.delta}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              ) : (
                <p className="small muted">No item timings: the replay is not parsed, or none of your items are in the pro build data.</p>
              )}
            </div>
          </div>
        </section>
      )}
      <Team rows={m.radiant} won={m.radiant_win} side="radiant" />
      <Team rows={m.dire} won={!m.radiant_win} side="dire" />
    </div>
  );
}

export function MatchPage() {
  const params = useParams();
  const navigate = useNavigate();
  const id = params.id ? Number(params.id) : null;
  const [input, setInput] = useState(params.id ?? "");
  const { data, error, isFetching } = useMatch(id);
  const { data: jobs } = usePostGame();
  return (
    <>
      <div className="page-head">
        <div>
          <h1>Matches</h1>
          <p>Review any match OpenDota has: scoreboard, your numbers against other players of the hero, item timings against pros.</p>
        </div>
      </div>
      <div className="row" style={{ marginBottom: "1rem" }}>
        <input className="input" value={input} onChange={(e) => setInput(e.target.value.replace(/\D/g, ""))} onKeyDown={(e) => e.key === "Enter" && input && navigate(`/match/${input}`)} placeholder="Match ID" aria-label="Match ID" />
        <button className="btn primary" type="button" disabled={!input} onClick={() => navigate(`/match/${input}`)}>
          Open match
        </button>
      </div>
      {jobs && jobs.length > 0 && (
        <section className="panel" style={{ marginBottom: "1rem" }}>
          <h3>After your last games</h3>
          {jobs.map((j) => (
            <p key={j.match_id} className="small" style={{ margin: "0.2rem 0" }}>
              Match {j.match_id}:{" "}
              {j.status === "ready" ? <Link to={`/match/${j.match_id}`}>ready to review</Link> : j.status === "waiting" ? `waiting for OpenDota (check ${j.attempts})` : "OpenDota never had it; try the ID later"}
              {j.parse_requested ? ", parse requested" : ""}
            </p>
          ))}
        </section>
      )}
      <ErrorBox error={error} />
      {id && isFetching && !data && <Loading what={`match ${id}`} />}
      {data && <Review m={data} />}
    </>
  );
}
