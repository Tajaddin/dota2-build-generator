import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen } from "@testing-library/react";
import type { ReactNode } from "react";
import { MemoryRouter } from "react-router-dom";
import type { HeroListRow, TimerView } from "../api/types";
import { ClockRail } from "./ClockRail";
import { HeroPicker } from "./HeroPicker";

function wrap(node: ReactNode) {
  const qc = new QueryClient({ defaultOptions: { queries: { enabled: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter>{node}</MemoryRouter>
    </QueryClientProvider>,
  );
}

const timer = (id: string, label: string, at: number | null, now: number, status: TimerView["status"] = "upcoming"): TimerView => ({
  id,
  label,
  at,
  seconds_left: at === null ? null : at - now,
  lead: 15,
  status,
  detail: `detail ${id}`,
  cite: `cite ${id}`,
});

describe("ClockRail", () => {
  it("puts near events on the rail and the rest in a list", () => {
    const now = 300;
    wrap(<ClockRail now={now} timers={[timer("power_rune", "Power rune", 360, now), timer("roshan", "Roshan", null, now, "alive"), timer("tormentor", "Tormentor", 1200, now)]} />);
    expect(screen.getByText("Power rune")).toBeInTheDocument();
    expect(screen.getByText("1:00")).toBeInTheDocument();
    expect(screen.getByText("Roshan")).toBeInTheDocument();
    expect(screen.getByText("detail tormentor")).toBeInTheDocument();
    expect(screen.getByText("Power rune").closest(".event")).toHaveAttribute("title", "cite power_rune");
  });
});

const row = (id: number, name: string): HeroListRow => ({
  id,
  name,
  key: name.toLowerCase(),
  aliases: [],
  primary_attr: "str",
  attack_type: "Melee",
  roles: [],
  img: null,
  icon: null,
  traits: [],
  positions: [],
  win_rate: 0.5,
  pick_rate: 0.1,
});

describe("HeroPicker", () => {
  it("adds the first free match on Enter and disables taken heroes", () => {
    const picked: string[] = [];
    const heroes = [row(2, "Axe"), row(3, "Bane"), row(4, "Abaddon")];
    wrap(<HeroPicker heroes={heroes} taken={new Set([4])} onPick={(h) => picked.push(h.name)} />);
    const input = screen.getByLabelText("Search heroes");
    fireEvent.change(input, { target: { value: "a" } });
    fireEvent.keyDown(input, { key: "Enter" });
    expect(picked).toEqual(["Axe"]);
    expect(screen.getByTitle("Abaddon")).toBeDisabled();
  });

  it("calls onTab instead of moving focus", () => {
    let tabs = 0;
    wrap(<HeroPicker heroes={[row(2, "Axe")]} taken={new Set()} onPick={() => undefined} onTab={() => (tabs += 1)} />);
    fireEvent.keyDown(screen.getByLabelText("Search heroes"), { key: "Tab" });
    expect(tabs).toBe(1);
  });
});
