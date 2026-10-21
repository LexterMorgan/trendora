/** Human-readable elapsed time. Values are measurements; null is unknown. */
export function formatElapsed(milliseconds: number | null | undefined): string {
  if (milliseconds === null || milliseconds === undefined) return "Unknown";
  if (milliseconds < 1000) return `${Math.max(0, Math.round(milliseconds))} ms`;
  const seconds = milliseconds / 1000;
  if (seconds < 60) return `${seconds.toFixed(1)} s`;
  const minutes = Math.floor(seconds / 60);
  const remainder = Math.round(seconds % 60);
  return `${minutes}m ${remainder}s`;
}
