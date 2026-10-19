import { useEffect, useMemo, useState } from "react";
import { NavLink, Route, Routes, useLocation, useNavigate } from "react-router-dom";
import { useLive, useSettings, useVersion } from "./api/hooks";
import { useHotkeys } from "./lib/hotkeys";
import { CompactPage } from "./pages/Compact";
import { DraftPage } from "./pages/Draft";
import { HeroPage } from "./pages/Hero";
import { HeroesPage } from "./pages/Heroes";
import { ItemPage, ItemsPage } from "./pages/Items";
import { LivePage } from "./pages/Live";
import { MatchPage } from "./pages/Match";
import { MetaPage } from "./pages/Meta";
import { ProfilePage } from "./pages/Profile";
import { SettingsPage } from "./pages/Settings";
import { SetupPage } from "./pages/Setup";

const NAV = [
  { to: "/", label: "Live", key: "1" },
  { to: "/draft", label: "Draft", key: "2" },
  { to: "/heroes", label: "Heroes", key: "3" },
  { to: "/items", label: "Items", key: "4" },
  { to: "/meta", label: "Meta", key: "5" },
  { to: "/profile", label: "Profile", key: "6" },
  { to: "/match", label: "Matches", key: "7" },
  { to: "/setup", label: "Setup", key: "8" },
  { to: "/settings", label: "Settings", key: "9" },
] as const;

function Shortcuts({ onClose }: { onClose: () => void }) {
  return (
    <div className="panel kbd-help" role="dialog" aria-label="Keyboard shortcuts">
      <h3>Keyboard shortcuts</h3>
      <p className="small">1–9 switch pages. On Draft: / to search, Enter to add, Tab to switch teams, B to ban, Backspace to undo. On Live: R Roshan killed, T Tormentor killed, A Aegis taken. ? shows this.</p>
      <button className="btn" type="button" onClick={onClose}>
        Close
      </button>
    </div>
  );
}

export function App() {
  const location = useLocation();
  const navigate = useNavigate();
  const { data: settings } = useSettings();
  const { data: version } = useVersion();
  const live = useLive();
  const [help, setHelp] = useState(false);

  useEffect(() => {
    document.documentElement.dataset.theme = settings?.theme ?? "dark";
  }, [settings?.theme]);

  const keys = useMemo(() => {
    const map: Record<string, () => void> = { "?": () => setHelp((h) => !h), Escape: () => setHelp(false) };
    for (const n of NAV) map[n.key] = () => navigate(n.to);
    return map;
  }, [navigate]);
  useHotkeys(keys);

  if (location.pathname.startsWith("/compact")) return <CompactPage live={live} />;

  const conn = live.snap?.connection;
  return (
    <div className="shell">
      <nav className="nav" aria-label="Main">
        <div className="brand">
          d2bg
          <small>Dota 2 companion, patch {version?.patch ?? "…"}</small>
        </div>
        {NAV.map((n) => (
          <NavLink key={n.to} to={n.to} end={n.to === "/"} className={({ isActive }) => (isActive ? "active" : undefined)}>
            {n.label}
            <kbd>{n.key}</kbd>
          </NavLink>
        ))}
        <div className="status" aria-live="polite">
          <span className={`dot ${conn?.connected ? "on" : live.online ? "" : "off"}`} />
          {!live.online ? "App server offline" : conn?.connected ? (conn.source === "game" ? "Receiving game data" : `Playing ${conn.source}`) : "Waiting for Dota"}
        </div>
      </nav>
      <main className="main">
        <Routes>
          <Route path="/" element={<LivePage live={live} />} />
          <Route path="/draft" element={<DraftPage live={live.snap} />} />
          <Route path="/heroes" element={<HeroesPage />} />
          <Route path="/heroes/:ref" element={<HeroPage />} />
          <Route path="/items" element={<ItemsPage />} />
          <Route path="/items/:key" element={<ItemPage />} />
          <Route path="/meta" element={<MetaPage />} />
          <Route path="/profile" element={<ProfilePage />} />
          <Route path="/match" element={<MatchPage />} />
          <Route path="/match/:id" element={<MatchPage />} />
          <Route path="/setup" element={<SetupPage live={live.snap} />} />
          <Route path="/settings" element={<SettingsPage />} />
          <Route path="*" element={<p>Nothing here. Pick a page on the left.</p>} />
        </Routes>
      </main>
      {help && <Shortcuts onClose={() => setHelp(false)} />}
    </div>
  );
}
