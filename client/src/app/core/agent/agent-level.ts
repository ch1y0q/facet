/** The grant tiers an agent session can hold, lowest first. The only place the ladder is spelled. */
export const LEVEL_TIERS = ['readonly', 'user', 'edition'] as const;

export type AgentLevel = (typeof LEVEL_TIERS)[number];

/** Rank of each tier, for "at least this level" comparisons. */
export const LEVEL_RANK: Record<string, number> = Object.fromEntries(LEVEL_TIERS.map((tier, rank) => [tier, rank]));

export interface LevelFacts {
  authenticated: boolean;
  multi_user: boolean;
  edition_authenticated: boolean;
}

/** The level a session carries: edition when unlocked, user for a signed-in multi-user account, else readonly. */
export function agentLevel(facts: LevelFacts): AgentLevel {
  if (facts.edition_authenticated) return 'edition';
  return facts.multi_user && facts.authenticated ? 'user' : 'readonly';
}
