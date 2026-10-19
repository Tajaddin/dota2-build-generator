import { useEffect, useState } from "react";
import { api } from "../api/client";
import { useHeroes, useSaveSettings, useSettings, useVersion } from "../api/hooks";
import type { Settings } from "../api/types";
import { ErrorBox, HeroChip, Loading, Segmented } from "../components/common";
import { HeroPicker } from "../components/HeroPicker";
import { BUCKETS } from "../lib/format";

function HeroList({ label, ids, onChange }: { label: string; ids: number[]; onChange: (ids: number[]) => void }) {
  const { data: heroes } = useHeroes();
  const [open, setOpen] = useState(false);
  return (
    <div>
      <h3>{label}</h3>
      <div className="row">
        {ids.map((id) => (
          <button key={id} type="button" className="btn small" onClick={() => onChange(ids.filter((x) => x !== id))} title="Remove">
            <HeroChip hero={id} size={20} link={false} />
          </button>
        ))}
        <button className="btn small" type="button" onClick={() => setOpen((o) => !o)}>
          {open ? "Done" : "Add heroes"}
        </button>
      </div>
      {open && heroes && <HeroPicker heroes={heroes} taken={new Set(ids)} onPick={(h) => onChange([...ids, h.id])} />}
    </div>
  );
}

export function SettingsPage() {
  const { data: settings, error } = useSettings();
  const { data: version } = useVersion();
  const save = useSaveSettings();
  const [timerRules, setTimerRules] = useState<{ id: string; label: string; default_on: boolean; cite: string }[]>([]);
  const [account, setAccount] = useState<string | null>(null); // null: show the saved value
  const [key, setKey] = useState("");

  useEffect(() => {
    void api.get<{ rules: { id: string; label: string; default_on: boolean; cite: string }[] }>("/api/timers").then((r) => setTimerRules(r.rules));
  }, []);

  if (error) return <ErrorBox error={error} />;
  if (!settings) return <Loading what="settings" />;
  const set = (changes: Partial<Settings>) => save.mutate(changes);
  const accountText = account ?? (settings.account_id ? String(settings.account_id) : "");

  return (
    <>
      <div className="page-head">
        <div>
          <h1>Settings</h1>
          <p>Saved on this computer in {version?.user_dir ?? "your user folder"}. Changes apply at once.</p>
        </div>
      </div>
      <ErrorBox error={save.error} />
      <div className="grid cols-2">
        <section className="panel stack">
          <div>
            <h3>Steam account ID</h3>
            <div className="row">
              <input className="input" value={accountText} onChange={(e) => setAccount(e.target.value.replace(/\D/g, ""))} placeholder="e.g. 123456789" aria-label="Account ID" />
              <button className="btn" type="button" onClick={() => set({ account_id: accountText ? Number(accountText) : null })}>
                Save account
              </button>
            </div>
            <p className="small muted">The number in your Dota profile or OpenDota URL (the 32-bit account ID).</p>
          </div>
          <div>
            <h3>Rank bracket for advice</h3>
            <Segmented label="Rank bracket" value={settings.rank_bucket} onChange={(v) => set({ rank_bucket: v })} options={BUCKETS.map((b) => ({ value: b.value, label: b.label }))} />
          </div>
          <div>
            <h3>Synergy weight ({settings.synergy_weight.toFixed(2)})</h3>
            <input type="range" min={0} max={1} step={0.05} value={settings.synergy_weight} onChange={(e) => set({ synergy_weight: Number(e.target.value) })} aria-label="Synergy weight" />
            <p className="small muted">0 ranks picks only by how they do against the enemy; 1 counts synergy with your team fully.</p>
          </div>
          <div>
            <h3>Hero pool</h3>
            <Segmented
              label="Hero pool mode"
              value={settings.pool_mode}
              onChange={(v) => set({ pool_mode: v })}
              options={[
                { value: "off", label: "Ignore" },
                { value: "boost", label: "Prefer my heroes" },
                { value: "only", label: "Only my heroes" },
              ]}
            />
          </div>
          <HeroList label="My heroes" ids={settings.hero_pool} onChange={(ids) => set({ hero_pool: ids })} />
          <HeroList label="Never suggest" ids={settings.blacklist} onChange={(ids) => set({ blacklist: ids })} />
        </section>
        <section className="panel stack">
          <div>
            <h3>Timers</h3>
            {timerRules.map((r) => {
              const on = settings.timers.enabled[r.id] ?? r.default_on;
              return (
                <label key={r.id} className="check small" title={r.cite}>
                  <input type="checkbox" checked={on} onChange={(e) => set({ timers: { ...settings.timers, enabled: { ...settings.timers.enabled, [r.id]: e.target.checked } } })} />
                  {r.label}
                </label>
              );
            })}
            <label className="check small" style={{ marginTop: "0.5rem" }}>
              <input type="checkbox" checked={settings.timers.voice} onChange={(e) => set({ timers: { ...settings.timers, voice: e.target.checked } })} />
              Read alerts out loud (turn voice on once on the Live page too; browsers need a click)
            </label>
          </div>
          <div>
            <h3>After each game</h3>
            <label className="check small">
              <input type="checkbox" checked={settings.auto_post_game} onChange={(e) => set({ auto_post_game: e.target.checked })} />
              Fetch the match from OpenDota when it ends (a few requests per game)
            </label>
            <label className="check small">
              <input type="checkbox" checked={settings.request_parse} onChange={(e) => set({ request_parse: e.target.checked })} />
              Also ask OpenDota to parse the replay (gives item timings)
            </label>
            <label className="check small">
              <input type="checkbox" checked={settings.record_gsi} onChange={(e) => set({ record_gsi: e.target.checked })} />
              Record games on this computer for replay (keeps the newest {settings.keep_recordings})
            </label>
          </div>
          <div>
            <h3>OpenDota API key (optional)</h3>
            <div className="row">
              <input className="input" type="password" value={key} onChange={(e) => setKey(e.target.value)} placeholder={settings.opendota_api_key ? "A key is saved" : "Paste your key"} aria-label="OpenDota API key" />
              <button className="btn" type="button" disabled={!key} onClick={() => { set({ opendota_api_key: key }); setKey(""); }}>
                Save key
              </button>
              {settings.opendota_api_key && (
                <button className="btn danger" type="button" onClick={() => set({ opendota_api_key: null })}>
                  Forget key
                </button>
              )}
            </div>
            <p className="small muted">Raises OpenDota's limits. Create one yourself at opendota.com; it stays on this computer.</p>
          </div>
          <div>
            <h3>Look</h3>
            <Segmented label="Theme" value={settings.theme} onChange={(v) => set({ theme: v })} options={[{ value: "dark", label: "Dark" }, { value: "light", label: "Light" }]} />
          </div>
          <div>
            <h3>Phone or second screen</h3>
            <p className="small">
              Open <code>/compact</code> for a small view of timers and your next item. To use it from a phone on your Wi-Fi, start the
              app with <code>.\run.cmd --lan</code>; it prints the address with the access token.
            </p>
          </div>
        </section>
      </div>
    </>
  );
}
