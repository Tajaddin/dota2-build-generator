/** Game clock text: 75 -> "1:15", -12 -> "-0:12". */
export function clock(seconds: number | null | undefined): string {
  if (seconds === null || seconds === undefined || Number.isNaN(seconds)) return "–";
  const sign = seconds < 0 ? "-" : "";
  const s = Math.floor(Math.abs(seconds));
  return `${sign}${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`;
}

/** 0.5234 -> "52.3%". */
export function pct(value: number | null | undefined, digits = 1): string {
  if (value === null || value === undefined) return "–";
  return `${(value * 100).toFixed(digits)}%`;
}

/** Signed percentage points: 2.345 -> "+2.3". */
export function pts(value: number, digits = 1): string {
  const v = value.toFixed(digits);
  return value > 0 ? `+${v}` : v;
}

export function gold(value: number | null | undefined): string {
  if (value === null || value === undefined) return "–";
  return value.toLocaleString("en-US");
}

export function ordinal(n: number): string {
  const rem100 = n % 100;
  if (rem100 >= 11 && rem100 <= 13) return `${n}th`;
  return `${n}${({ 1: "st", 2: "nd", 3: "rd" } as Record<number, string>)[n % 10] ?? "th"}`;
}

export function percentileText(p: number | null | undefined): string {
  if (p === null || p === undefined) return "–";
  return `${ordinal(Math.round(p * 100))} percentile`;
}

export function date(ts: number | null | undefined): string {
  if (!ts) return "–";
  return new Date(ts * 1000).toLocaleDateString(undefined, { month: "short", day: "numeric", year: "numeric" });
}

export function dateTime(ts: number | null | undefined): string {
  if (!ts) return "–";
  return new Date(ts * 1000).toLocaleString(undefined, { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" });
}

export const POSITION_NAMES: Record<number, string> = {
  1: "Safe lane carry",
  2: "Mid",
  3: "Off lane",
  4: "Soft support",
  5: "Hard support",
};

export const BUCKETS = [
  { value: "all", label: "All ranks" },
  { value: "1-2", label: "Herald–Guardian" },
  { value: "3-4", label: "Crusader–Archon" },
  { value: "5-6", label: "Legend–Ancient" },
  { value: "7-8", label: "Divine–Immortal" },
] as const;

export const MEDALS = ["Herald", "Guardian", "Crusader", "Archon", "Legend", "Ancient", "Divine", "Immortal"];
