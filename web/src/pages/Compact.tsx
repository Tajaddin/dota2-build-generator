import { Link } from "react-router-dom";
import { useSettings } from "../api/hooks";
import { useSpeakAlerts } from "../lib/voice";
import { AlertList, NextItems, TimerColumn, type LiveState } from "./Live";

/** A narrow view for a second monitor, a phone, or the always-on-top window (`d2bg window`). */
export function CompactPage({ live }: { live: LiveState }) {
  const { snap } = live;
  const { data: settings } = useSettings();
  useSpeakAlerts(snap?.alerts, settings?.timers.voice ?? true);
  if (!snap || snap.phase === "waiting") {
    return (
      <div className="compact">
        <p className="muted">Waiting for Dota. <Link to="/">Open the full app</Link></p>
      </div>
    );
  }
  return (
    <div className="compact stack">
      <TimerColumn snap={snap} compact />
      {snap.next_items && <NextItems snap={snap} />}
      {snap.skills?.next && (snap.skills.unspent ?? 0) > 0 && <div className="note">Skill point: {snap.skills.next.name}</div>}
      {snap.buyback_warning && <div className="note">{snap.buyback_warning}</div>}
      <AlertList snap={snap} limit={6} />
    </div>
  );
}
