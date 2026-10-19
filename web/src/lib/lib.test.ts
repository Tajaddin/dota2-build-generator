import type { HeroSummary } from "../api/types";
import { clock, gold, ordinal, pct, percentileText, pts } from "./format";
import { searchHeroes } from "./search";

const hero = (id: number, name: string, key: string, aliases: string[] = []): HeroSummary => ({
  id,
  name,
  key,
  aliases,
  primary_attr: "agi",
  attack_type: "Melee",
  roles: [],
  img: null,
  icon: null,
});

const HEROES = [
  hero(1, "Anti-Mage", "antimage", ["am", "magina"]),
  hero(44, "Phantom Assassin", "phantom_assassin", ["pa"]),
  hero(39, "Queen of Pain", "queenofpain", ["qop"]),
  hero(74, "Invoker", "invoker"),
  hero(12, "Phantom Lancer", "phantom_lancer", ["pl"]),
];

describe("format", () => {
  it("formats the game clock", () => {
    expect(clock(75)).toBe("1:15");
    expect(clock(-12)).toBe("-0:12");
    expect(clock(0)).toBe("0:00");
    expect(clock(null)).toBe("–");
  });
  it("formats numbers", () => {
    expect(pct(0.5234)).toBe("52.3%");
    expect(pct(null)).toBe("–");
    expect(pts(2.345)).toBe("+2.3");
    expect(pts(-1)).toBe("-1.0");
    expect(gold(12345)).toBe("12,345");
    expect(ordinal(1)).toBe("1st");
    expect(ordinal(12)).toBe("12th");
    expect(ordinal(23)).toBe("23rd");
    expect(percentileText(0.62)).toBe("62nd percentile");
  });
});

describe("searchHeroes", () => {
  it("understands aliases, prefixes and initials", () => {
    expect(searchHeroes(HEROES, "am")[0]!.name).toBe("Anti-Mage");
    expect(searchHeroes(HEROES, "qop")[0]!.name).toBe("Queen of Pain");
    expect(searchHeroes(HEROES, "inv")[0]!.name).toBe("Invoker");
    expect(searchHeroes(HEROES, "phantom").map((h) => h.name)).toEqual(["Phantom Assassin", "Phantom Lancer"]);
    expect(searchHeroes(HEROES, "")).toEqual([]);
    expect(searchHeroes(HEROES, "zzz")).toEqual([]);
  });
});
