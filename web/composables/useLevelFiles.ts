import type { LevelFiles } from './useVelum'

/** The level currently open in the Viewer, handed to the Editor. Lives in this tab only. */
export function useLevelFiles() {
  return useState<LevelFiles | null>('velum-level', () => null)
}
