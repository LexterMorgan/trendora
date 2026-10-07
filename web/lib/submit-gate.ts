/**
 * Guards a single submit path against double-fire (double click, repeated
 * Enter presses) without touching React state.
 */

export interface SubmitGate {
  isActive(): boolean;
  acquire(): boolean;
  release(): void;
}

export function createSubmitGate(): SubmitGate {
  let active = false;
  return {
    isActive: () => active,
    acquire(): boolean {
      if (active) return false;
      active = true;
      return true;
    },
    release(): void {
      active = false;
    },
  };
}
