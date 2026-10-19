import { mergeGameDraft, type BoardState } from "./liveDraft";

const empty: BoardState = { us: [], them: [], bans: [], side: "radiant" };

describe("mergeGameDraft", () => {
  it("starts a new match from what the game sent, including his side", () => {
    const b = mergeGameDraft(empty, { allies: [54], enemies: [], bans: [25, 53], side: "dire" }, "m1");
    expect(b).toMatchObject({ us: [54], them: [], bans: [25, 53], side: "dire", matchId: "m1" });
  });

  it("adds newly reported heroes and keeps his own picks", () => {
    let b = mergeGameDraft(empty, { allies: [54], enemies: [], bans: [], side: "dire" }, "m1");
    b = { ...b, them: [1, 2] }; // typed in by hand
    b = mergeGameDraft(b, { allies: [54, 36], enemies: [3], bans: [7], side: "dire" }, "m1");
    expect(b.us).toEqual([54, 36]);
    expect(b.them).toEqual([1, 2, 3]);
    expect(b.bans).toEqual([7]);
  });

  it("does not add back a hero he removed", () => {
    let b = mergeGameDraft(empty, { allies: [54, 36], enemies: [], bans: [], side: "dire" }, "m1");
    b = { ...b, us: [54] }; // he removed 36
    b = mergeGameDraft(b, { allies: [54, 36], enemies: [], bans: [], side: "dire" }, "m1");
    expect(b.us).toEqual([54]);
  });

  it("keeps the board's side while the game does not know it, and never overfills a team", () => {
    const b = mergeGameDraft(
      { ...empty, us: [1, 2, 3, 4, 5], matchId: "m1", fromGame: [] },
      { allies: [6], enemies: [], bans: [], side: "dire", side_known: false },
      "m1",
    );
    expect(b.side).toBe("radiant");
    expect(b.us).toHaveLength(5);
  });

  it("does not place a hero twice", () => {
    const b = mergeGameDraft(
      { ...empty, them: [36], matchId: "m1", fromGame: [] },
      { allies: [36], enemies: [], bans: [], side: "radiant" },
      "m1",
    );
    expect(b.us).toEqual([]);
    expect(b.them).toEqual([36]);
  });
});
