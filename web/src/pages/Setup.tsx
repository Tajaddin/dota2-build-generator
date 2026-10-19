import { useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api/client";
import { useDataStatus, useGsiStatus, useRecordings, useSettings } from "../api/hooks";
import type { LiveSnapshot } from "../api/types";
import { Bar, ErrorBox, Loading } from "../components/common";
import { dateTime } from "../lib/format";

function Gsi({ live }: { live: LiveSnapshot | null }) {
  const [path, setPath] = useState("");
  const { data: st, refetch } = useGsiStatus(path || undefined);
  const { data: settings } = useSettings();
  const [msg, setMsg] = useState<string>("");
  const [error, setError] = useState<unknown>(null);
  const act = async (what: "install" | "remove") => {
    setError(null);
    try {
      const res = await api.post<{ path?: string; removed?: boolean }>(`/api/gsi/${what}`, { path: path || null });
      setMsg(what === "install" ? `Written to ${res.path}. Restart Dota 2 if it is open.` : res.removed ? "Removed." : "There was nothing to remove.");
      void refetch();
    } catch (e) {
      setError(e);
    }
  };
  const gotPackets = (st?.connection.packets ?? 0) > 0 && st?.connection.source === "game";
  return (
    <section className="panel">
      <h2>Connect Dota 2</h2>
      {!st ? (
        <Loading what="the setup status" />
      ) : (
        <ol className="steps">
          <li className={st.dota_found ? "done" : ""}>
            <h3>Find Dota 2</h3>
            {st.dota_found ? (
              <p className="small">Found at {st.dota_path}.</p>
            ) : (
              <p className="small">Not found through Steam's library list. Paste the path of the "dota 2 beta" folder:</p>
            )}
            <input className="input" style={{ width: "100%" }} value={path} onChange={(e) => setPath(e.target.value)} placeholder="D:\SteamLibrary\steamapps\common\dota 2 beta" aria-label="Dota 2 folder" />
          </li>
          <li className={st.installed && st.current ? "done" : ""}>
            <h3>Install the Game State Integration config</h3>
            <p className="small">
              This writes one file, <code>gamestate_integration_d2bg.cfg</code>, into Dota's <code>cfg\gamestate_integration</code>{" "}
              folder. It is Valve's own way of letting a program listen to the game; nothing else is changed. See{" "}
              <a href="https://github.com/Tajaddin/dota2-build-generator/blob/main/docs/SAFETY.md" target="_blank" rel="noreferrer">
                SAFETY.md
              </a>
              .
            </p>
            <div className="row">
              <button className="btn primary" type="button" disabled={!st.dota_found && !path} onClick={() => void act("install")}>
                {st.installed ? (st.current ? "Reinstall" : "Update the config") : "Install"}
              </button>
              {st.installed && (
                <button className="btn danger" type="button" onClick={() => void act("remove")}>
                  Remove
                </button>
              )}
              <span className="small muted">{msg}</span>
            </div>
            <ErrorBox error={error} />
          </li>
          <li className={gotPackets ? "done" : ""}>
            <h3>Start Dota 2 and wait for the first update</h3>
            {gotPackets ? (
              <p className="small good">Receiving data: {st.connection.packets} updates so far. You are set.</p>
            ) : (
              <p className="small">
                Nothing received yet. Updates start once Dota is running. If nothing arrives after a minute, add{" "}
                <code>{st.launch_option_hint}</code> to Dota's launch options in Steam yourself (Library, Dota 2, Properties,
                Launch options). The app never edits your launch options.
              </p>
            )}
          </li>
          <li className={settings?.account_id ? "done" : ""}>
            <h3>Your account</h3>
            <p className="small">
              {settings?.account_id ? (
                <>Account {settings.account_id}. Your profile and post-game reviews use it.</>
              ) : (
                <>
                  Filled in from your first game, or type it in <Link to="/settings">Settings</Link>.
                </>
              )}
            </p>
          </li>
        </ol>
      )}
      {live?.connection.blocks.length ? (
        <p className="source">Data blocks the game has sent: {live.connection.blocks.join(", ")}.</p>
      ) : null}
    </section>
  );
}

function Data() {
  const [poll, setPoll] = useState(false);
  const { data, refetch } = useDataStatus(poll);
  const [error, setError] = useState<unknown>(null);
  const running = data?.refresh.running ?? false;
  if (poll && data && !running) setPoll(false);
  const start = async (steps?: string[]) => {
    setError(null);
    try {
      await api.post("/api/data/refresh", { steps });
      setPoll(true);
      void refetch();
    } catch (e) {
      setError(e);
    }
  };
  if (!data) return <Loading what="data status" />;
  const prog = data.refresh.progress;
  return (
    <section className="panel">
      <h2>Data</h2>
      <p className="small">
        The app ships with a snapshot so it works offline. Refreshing pulls the latest numbers from OpenDota: about 650 requests and
        15 minutes for everything. The free limit is about 3,000 requests a day.
      </p>
      <p className="small">
        OpenDota requests today: <strong>{data.usage.requests_today}</strong>
        {data.usage.remaining_day !== null ? `, ${data.usage.remaining_day} left today` : ""}
        {data.usage.has_api_key ? " (with your API key)" : ""}.
      </p>
      <div className="row">
        <button className="btn primary" type="button" disabled={running} onClick={() => void start()}>
          Refresh everything
        </button>
        <button className="btn" type="button" disabled={running} onClick={() => void start(["constants", "hero_stats"])}>
          Quick refresh (meta only)
        </button>
      </div>
      <ErrorBox error={error} />
      {running && prog.step && (
        <div style={{ marginTop: "0.75rem" }}>
          <p className="small">
            {prog.step}: {prog.message} ({prog.done}/{prog.total})
          </p>
          <Bar value={(prog.done ?? 0) / Math.max(prog.total ?? 1, 1)} label="Refresh progress" />
        </div>
      )}
      {data.refresh.error && <div className="error">Refresh stopped: {data.refresh.error}</div>}
      {data.refresh.results.length > 0 && (
        <p className="small muted">
          Last refresh: {data.refresh.results.map((r) => `${r.step} ${r.rows} rows, ${r.calls} calls`).join("; ")}.
        </p>
      )}
      <table style={{ marginTop: "0.75rem" }}>
        <thead>
          <tr>
            <th>File</th>
            <th>From</th>
            <th>Updated</th>
            <th className="num">Rows</th>
          </tr>
        </thead>
        <tbody>
          {Object.entries(data.files).map(([name, f]) => (
            <tr key={name}>
              <td className="small">{name}</td>
              <td className="small muted" title={f.source}>
                {f.present ? `${f.location === "refreshed" ? "Your refresh" : "Shipped snapshot"}: ${f.source ?? ""}` : "Missing"}
              </td>
              <td className="small">{dateTime(f.generated_at)}</td>
              <td className="num small">{f.rows?.toLocaleString() ?? "–"}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </section>
  );
}

function Recordings() {
  const { data } = useRecordings();
  const [error, setError] = useState<unknown>(null);
  const play = async (name: string) => {
    try {
      await api.post("/api/replay", { name, speed: 8 });
    } catch (e) {
      setError(e);
    }
  };
  return (
    <section className="panel">
      <h2>Recordings and demo</h2>
      <p className="small">
        Every game is recorded on this computer so you can replay it into the Live page. Turn this off in Settings.
      </p>
      <button className="btn" type="button" onClick={() => void api.post("/api/demo", { hero: "juggernaut", speed: 8 })}>
        Play the demo match
      </button>
      <ErrorBox error={error} />
      <table style={{ marginTop: "0.75rem" }}>
        <tbody>
          {(data ?? []).map((r) => (
            <tr key={r.name}>
              <td className="small">{r.name}</td>
              <td className="small muted">{dateTime(r.modified)}</td>
              <td className="num small">{Math.round(r.bytes / 1024)} KB</td>
              <td>
                <button className="btn small" type="button" onClick={() => void play(r.name)}>
                  Replay at 8×
                </button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      {data && !data.length && <p className="small muted">No recordings yet.</p>}
    </section>
  );
}

export function SetupPage({ live }: { live: LiveSnapshot | null }) {
  return (
    <>
      <div className="page-head">
        <div>
          <h1>Setup</h1>
          <p>Connect the game once, keep the data fresh, and replay past games.</p>
        </div>
      </div>
      <div className="stack">
        <div className="grid cols-2">
          <Gsi live={live} />
          <Recordings />
        </div>
        <Data />
      </div>
    </>
  );
}
