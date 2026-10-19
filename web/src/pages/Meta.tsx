import { useState } from "react";
import { useMeta } from "../api/hooks";
import { ErrorBox, HeroChip, Loading, Segmented } from "../components/common";
import { MEDALS, POSITION_NAMES, dateTime, pct } from "../lib/format";

export function MetaPage() {
  const [source, setSource] = useState("bracket");
  const [bracket, setBracket] = useState<number | null>(null);
  const [position, setPosition] = useState<number | null>(null);
  const { data, error, isFetching } = useMeta(source, bracket, position);

  return (
    <>
      <div className="page-head">
        <div>
          <h1>Meta</h1>
          <p>Win rates on the current patch. Tiers are win-rate bands: the top tenth is S, the bottom fifth D.</p>
        </div>
      </div>
      <div className="stack" style={{ marginBottom: "1rem" }}>
        <Segmented
          label="Source"
          value={source}
          onChange={setSource}
          options={[
            { value: "bracket", label: "Public by medal" },
            { value: "matrix", label: "Ranked All Pick sample" },
            { value: "pro", label: "Pro" },
            { value: "turbo", label: "Turbo" },
          ]}
        />
        {source === "bracket" && (
          <Segmented
            label="Medal"
            value={bracket ?? 0}
            onChange={(v) => setBracket(v || null)}
            options={[{ value: 0, label: "All medals" }, ...MEDALS.map((m, i) => ({ value: i + 1, label: m }))]}
          />
        )}
        <Segmented
          label="Position"
          value={position ?? 0}
          onChange={(v) => setPosition(v || null)}
          options={[{ value: 0, label: "Any position" }, ...[1, 2, 3, 4, 5].map((p) => ({ value: p, label: POSITION_NAMES[p]! }))]}
        />
      </div>
      <ErrorBox error={error} />
      {!data && !error && <Loading what="the meta" />}
      {data && (
        <section className="panel" style={{ opacity: isFetching ? 0.6 : 1 }}>
          <table>
            <thead>
              <tr>
                <th>Tier</th>
                <th>Hero</th>
                <th className="num">Win rate</th>
                <th className="num">Games</th>
                <th className="num">Pick share</th>
                {source === "pro" && <th className="num">Bans</th>}
                <th>Positions</th>
              </tr>
            </thead>
            <tbody>
              {data.rows.map((r) => (
                <tr key={r.hero}>
                  <td className={`tier ${r.tier}`}>{r.tier}</td>
                  <td>
                    <HeroChip hero={r.hero} size={26} />
                  </td>
                  <td className="num">{pct(r.win_rate)}</td>
                  <td className="num">{r.picks.toLocaleString()}</td>
                  <td className="num muted">{pct(r.pick_share)}</td>
                  {source === "pro" && <td className="num">{r.bans}</td>}
                  <td className="small muted">{r.positions.join(", ")}</td>
                </tr>
              ))}
            </tbody>
          </table>
          <p className="source">
            {data.data_source ?? "OpenDota"}, updated {dateTime(data.generated_at)}. Heroes under 0.5% of picks are left out.
          </p>
        </section>
      )}
    </>
  );
}
