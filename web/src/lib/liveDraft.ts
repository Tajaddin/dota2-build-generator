import type { Side } from "../api/types";

export interface BoardState {
  us: number[];
  them: number[];
  bans: number[];
  side: Side;
  /** The match the board belongs to, when it was filled from a game. */
  matchId?: string | null;
  /** Heroes the game already reported, so a hero he removed by hand is not added back. */
  fromGame?: number[];
}

export interface GameDraft {
  allies: number[];
  enemies: number[];
  bans: number[];
  side: Side;
  side_known?: boolean;
}

const MAX_PICKS = 5;

/**
 * Bring what the game reported into the board.
 *
 * A new match starts a fresh board from the game. Within a match, only heroes the game reports for the
 * first time are added (to the right team, if there is room and the hero is not placed already), so
 * his own edits stay. The side follows the game whenever the game knows it.
 */
export function mergeGameDraft(board: BoardState, game: GameDraft, matchId: string | null): BoardState {
  if (matchId && board.matchId !== matchId) {
    return {
      us: game.allies.slice(0, MAX_PICKS),
      them: game.enemies.slice(0, MAX_PICKS),
      bans: [...game.bans],
      side: game.side_known === false ? board.side : game.side,
      matchId,
      fromGame: [...game.allies, ...game.enemies, ...game.bans],
    };
  }
  const seen = new Set(board.fromGame ?? []);
  const placed = new Set([...board.us, ...board.them, ...board.bans]);
  const next: BoardState = {
    ...board,
    us: [...board.us],
    them: [...board.them],
    bans: [...board.bans],
    side: game.side_known === false ? board.side : game.side,
    fromGame: [...seen],
  };
  const add = (heroes: number[], target: number[], limit: number) => {
    for (const h of heroes) {
      if (seen.has(h)) continue;
      seen.add(h);
      next.fromGame!.push(h);
      if (!placed.has(h) && target.length < limit) {
        target.push(h);
        placed.add(h);
      }
    }
  };
  add(game.allies, next.us, MAX_PICKS);
  add(game.enemies, next.them, MAX_PICKS);
  add(game.bans, next.bans, 24);
  return next;
}
