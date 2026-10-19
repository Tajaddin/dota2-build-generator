import type { TimerView } from "../api/types";
import { clock } from "../lib/format";

const SPAN = 300; // seconds of game time the rail shows
const HEIGHT = 420; // px

/**
 * Upcoming events on a vertical ruler of the next five minutes of game time. The Roshan respawn
 * window is drawn as a band, so "maybe alive" and "certainly alive" are visible at a glance.
 */
export function ClockRail({ timers, now }: { timers: TimerView[]; now: number }) {
  const y = (t: number) => Math.max(0, Math.min(1, (t - now) / SPAN)) * HEIGHT;
  const ticks = [0, 60, 120, 180, 240, 300];
  const upcoming = timers.filter((t) => t.at !== null && t.seconds_left !== null && t.seconds_left <= SPAN);
  const later = timers.filter((t) => t.at === null || t.seconds_left === null || t.seconds_left > SPAN);

  // Keep labels from overlapping: push each one down below the previous.
  const placed: { t: TimerView; top: number }[] = [];
  for (const t of upcoming) {
    const want = y(t.at!);
    const prev = placed[placed.length - 1];
    placed.push({ t, top: prev ? Math.max(want, prev.top + 22) : want });
  }

  const rosh = timers.find((t) => t.id === "roshan" && t.status === "window");

  return (
    <div>
      <div className="rail-wrap">
        <div className="rail" style={{ height: HEIGHT }} aria-label="Upcoming timers">
          {ticks.map((s) => (
            <div key={s} className="tick" style={{ top: (s / SPAN) * HEIGHT }}>
              <span>{s === 0 ? "now" : `+${s / 60}m`}</span>
            </div>
          ))}
          {rosh && rosh.at !== null && (
            <div className="window" style={{ top: 0, height: y(rosh.at) }} title="Roshan may be alive" />
          )}
          {placed.map(({ t, top }) => (
            <div key={t.id} className={`event${(t.seconds_left ?? 99) <= t.lead ? " soon" : ""}`} style={{ top }} title={t.cite}>
              <span className="left">{clock(t.seconds_left)}</span>
              <span className="what">
                {t.label} <span className="muted small">{t.detail}</span>
              </span>
            </div>
          ))}
        </div>
      </div>
      {later.length > 0 && (
        <div className="standing">
          <ul>
            {later.map((t) => (
              <li key={t.id} title={t.cite}>
                <span>{t.label}</span>
                <span className="muted">{t.detail}</span>
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}
