/**
 * Contract check for the rendered browser regression module.
 *
 * This verifies the module loads and exports a well-formed, non-empty scenario
 * list. It does NOT execute any browser scenario and MUST NOT be reported as
 * browser coverage. Execution lives in `run-browser-regressions.mjs`, which
 * requires a real driver.
 *
 * Exit codes: 0 when the module contract holds; 1 when it is broken or empty.
 */

import { plannerWorkspaceRegressions } from "./planner-workspace.browser.mjs";

function fakeFixture() {
  // The module only builds closures at load time; it does not touch the
  // fixture until a scenario runs, so a minimal stand-in is enough here.
  return { page: {}, calls: [], records: {} };
}

let scenarios;
try {
  scenarios = plannerWorkspaceRegressions(fakeFixture());
} catch (error) {
  console.error("browser module failed to load:", error);
  process.exit(1);
}

if (!Array.isArray(scenarios) || scenarios.length === 0) {
  console.error("browser module exported no scenarios");
  process.exit(1);
}

const malformed = scenarios.filter(
  (entry) =>
    !Array.isArray(entry) ||
    typeof entry[0] !== "string" ||
    typeof entry[1] !== "function",
);
if (malformed.length > 0) {
  console.error(`browser module has ${malformed.length} malformed scenario(s)`);
  process.exit(1);
}

console.log(
  `browser module contract: ${scenarios.length} scenarios declared (none executed)`,
);
for (const [name] of scenarios) {
  console.log(`  - ${name}`);
}
