import assert from "node:assert/strict";
import { spawn } from "node:child_process";
import { randomUUID } from "node:crypto";
import * as fs from "node:fs";
import { createRequire } from "node:module";
import { createServer } from "node:net";
import * as os from "node:os";
import * as path from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

import { createMockBackend, runBrowserScenarios } from "./browser-fixture.mjs";
import { plannerWorkspaceRegressions } from "./planner-workspace.browser.mjs";

// Runtime configuration supplies installed tools; this runner never installs them.
const require = createRequire(import.meta.url);
async function loadDriver() {
  const configured = process.env.TRENDORA_BROWSER_DRIVER;
  for (const name of configured ? [configured] : ["playwright", "playwright-core"]) {
    try {
      const driverModule = await import(pathToFileURL(require.resolve(name)).href);
      const chromium = driverModule.chromium ?? driverModule.default?.chromium;
      if (chromium) return { name, chromium };
    } catch {
      // An unavailable driver is a prerequisite failure, never browser coverage.
    }
  }
  return null;
}

const driver = await loadDriver();
if (!driver) {
  console.error("Browser regressions NOT RUN: set TRENDORA_BROWSER_DRIVER to an installed Playwright-compatible module.");
  process.exit(2);
}

const source = fileURLToPath(new URL("../", import.meta.url));
const root = fs.realpathSync(fs.mkdtempSync(path.join(os.tmpdir(), "trendora-browser-")));
fs.chmodSync(root, 0o700);
const owner = { root, uid: process.getuid?.() ?? null, nonce: randomUUID() };
const output = (name, value) => fs.writeFileSync(path.join(root, name), JSON.stringify(value, null, 2), { mode: 0o600 });
output("owner.json", owner);
const total = plannerWorkspaceRegressions({}).length;
const children = [];
const commands = [];
let mock;
let reservation;
let nextProcess;
let closeBrowser;
let cleanupPromise;
let summary = { passed: 0, failed: 0, skipped: total, total };
const delay = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

function spawnOwned(args, env, logName) {
  const log = fs.openSync(path.join(root, logName), "w", 0o600);
  const child = spawn(process.execPath, args, {
    cwd: path.join(root, "web"), env, detached: process.platform !== "win32",
    stdio: ["ignore", log, log],
  });
  fs.closeSync(log);
  child.command = [process.execPath, ...args];
  children.push(child);
  child.on("error", (error) => { child.spawnError = error; });
  return child;
}

async function stopOwned(child) {
  if (child.exitCode !== null || child.signalCode !== null || !child.pid) return;
  const signal = (name) => {
    try {
      if (process.platform === "win32") child.kill(name);
      else process.kill(-child.pid, name);
    } catch (error) {
      if (error.code !== "ESRCH") throw error;
    }
  };
  signal("SIGTERM");
  await Promise.race([new Promise((resolve) => child.once("exit", resolve)), delay(5_000)]);
  if (child.exitCode === null && child.signalCode === null) {
    signal("SIGKILL");
    await new Promise((resolve) => child.once("exit", resolve));
  }
}

async function cleanup() {
  if (cleanupPromise) return cleanupPromise;
  cleanupPromise = (async () => {
    let browserError;
    try { await closeBrowser?.(); } catch (error) { browserError = error; }
    if (reservation?.listening) await new Promise((resolve) => reservation.close(resolve));
    for (const child of children) await stopOwned(child);
    if (mock) await mock.close();
    if (browserError) throw browserError;
    const actual = JSON.parse(fs.readFileSync(path.join(root, "owner.json"), "utf8"));
    assert.deepEqual(actual, owner);
    assert.equal(fs.realpathSync(root), root);
    assert.equal(fs.statSync(root).mode & 0o777, 0o700);
    if (owner.uid !== null) assert.equal(fs.statSync(root).uid, owner.uid);
    const removed = [];
    for (const name of ["web", "home", "runtime"]) {
      const target = path.join(root, name);
      if (!fs.existsSync(target)) continue;
      assert.equal(path.dirname(target), root);
      assert.equal(fs.realpathSync(target), target);
      assert(!fs.lstatSync(target).isSymbolicLink());
      if (owner.uid !== null) assert.equal(fs.statSync(target).uid, owner.uid);
      fs.rmSync(target, { recursive: true });
      removed.push(name);
    }
    output("cleanup.json", { exactOwnerValidated: true, browserClosed: Boolean(closeBrowser), ownedChildrenStopped: true, mockClosed: Boolean(mock), removed });
  })();
  return cleanupPromise;
}

for (const signal of ["SIGINT", "SIGTERM"]) {
  process.once(signal, () => { void cleanup().finally(() => process.exit(130)); });
}

try {
  const excluded = new Set(["node_modules", ".next", "out", "coverage", ".cache", ".git", ".DS_Store", "next-env.d.ts", "opencode.json", ".npmrc", ".yarnrc", ".yarnrc.yml"]);
  fs.cpSync(source, path.join(root, "web"), {
    recursive: true,
    filter: (entry) => {
      const name = path.basename(entry);
      if (excluded.has(name) || name.startsWith(".env") || name.endsWith(".env") || name.endsWith(".tsbuildinfo")) return false;
      assert(!fs.lstatSync(entry).isSymbolicLink(), `Unexpected source symlink: ${entry}`);
      return true;
    },
  });
  const modules = path.join(source, "node_modules");
  assert(fs.statSync(modules).isDirectory(), "Installed frontend dependencies are missing");
  fs.symlinkSync(fs.realpathSync(modules), path.join(root, "web", "node_modules"), "dir");
  for (const name of ["home", "runtime"]) fs.mkdirSync(path.join(root, name), { mode: 0o700 });

  const fontMock = path.join(root, "font-mock.cjs");
  fs.writeFileSync(fontMock, `module.exports = new Proxy({}, { get(_, url) {
    return "@font-face { font-family: '" + (String(url).includes('Geist+Mono') ? 'Geist Mono' : 'Geist') + "'; src: local('Arial'); font-weight: 100 900; }";
  }});`, { mode: 0o600 });
  const guard = path.join(root, "network-guard.cjs");
  fs.writeFileSync(guard, `const net = require('node:net');
const fs = require('node:fs');
const allowed = new Set((process.env.TRENDORA_BROWSER_PORTS || '').split(',').filter(Boolean).map(Number));
const connect = net.Socket.prototype.connect;
net.Socket.prototype.connect = function(...args) {
  const value = Array.isArray(args[0]) ? args[0][0] : args[0];
  const port = typeof value === 'object' ? value.port : value;
  const host = typeof value === 'object' ? value.host || 'localhost' : typeof args[1] === 'string' ? args[1] : 'localhost';
  if (typeof value === 'object' && value.path) return connect.apply(this, args);
  if (!allowed.has(Number(port)) || !['127.0.0.1', 'localhost', '::1'].includes(host)) {
    fs.appendFileSync(process.env.TRENDORA_BROWSER_NETWORK_LOG, JSON.stringify({host, port, blocked:true}) + '\\n');
    throw new Error('Browser fixture outbound connection blocked');
  }
  return connect.apply(this, args);
};`, { mode: 0o600 });

  mock = await createMockBackend();
  const mockUrl = new URL(mock.origin);
  assert.equal(mockUrl.protocol, "http:");
  assert.equal(mockUrl.hostname, "127.0.0.1");
  assert.notEqual(mockUrl.port, "5432");
  assert.equal((await (await fetch(mock.origin + "/__owner", { signal: AbortSignal.timeout(5_000) })).json()).nonce, mock.nonce);
  reservation = createServer();
  await new Promise((resolve, reject) => {
    reservation.once("error", reject);
    reservation.listen(0, "127.0.0.1", resolve);
  });
  const frontPort = reservation.address().port;
  const origin = `http://127.0.0.1:${frontPort}`;
  const env = { PATH: `${path.dirname(process.execPath)}:/usr/bin:/bin`, HOME: path.join(root, "home"), TMPDIR: path.join(root, "runtime") };
  const childEnv = {
    ...env, CI: "1", NEXT_TELEMETRY_DISABLED: "1",
    NODE_OPTIONS: `--require=${JSON.stringify(guard)}`,
    TRENDORA_BROWSER_PORTS: `${frontPort},${mockUrl.port}`,
    TRENDORA_BROWSER_NETWORK_LOG: path.join(root, "network.jsonl"),
    NEXT_FONT_GOOGLE_MOCKED_RESPONSES: fontMock,
    NEXT_PUBLIC_SUPABASE_URL: mock.origin,
    NEXT_PUBLIC_SUPABASE_ANON_KEY: "fictional-browser-public-key",
    TRENDORA_API_BASE_URL: mock.origin,
  };
  const installedWasm = path.join(modules, "next", "wasm", "@next", "swc-wasm-nodejs");
  if (fs.existsSync(path.join(installedWasm, "wasm.js")) && fs.existsSync(path.join(installedWasm, "wasm_bg.wasm"))) {
    childEnv.NEXT_TEST_WASM = "1";
    childEnv.NEXT_TEST_WASM_DIR = fs.realpathSync(installedWasm);
  }
  output("isolation.json", { source, root, origin, mockOrigin: mock.origin, driver: driver.name, environmentKeys: Object.keys(childEnv), dotenvFilesCopied: false, font: "Installed Next font mock; local Arial, no download" });
  const probe = spawnOwned(["--eval", `const assert = require('node:assert/strict');
const net = require('node:net');
for (const endpoint of [{host:'198.51.100.9',port:443}, {host:'127.0.0.1',port:5432}]) {
  const socket = new net.Socket();
  assert.throws(() => socket.connect(endpoint), /outbound connection blocked/);
  socket.destroy();
}
assert(!Object.keys(process.env).some(key => /^PG/.test(key)));
console.log('Isolation probe: external network and unrelated loopback database blocked before connection; no PG variables inherited.');`], childEnv, "isolation-probe.log");
  const probeCode = await new Promise((resolve, reject) => { probe.once("error", reject); probe.once("exit", resolve); });
  commands.push({ command: probe.command, exitCode: probeCode });
  assert.equal(probeCode, 0, "Offline isolation probe failed");
  const next = path.join(root, "web", "node_modules", "next", "dist", "bin", "next");
  console.log(`Browser evidence: ${root}`);
  console.log("Building isolated frontend with installed tools and offline fonts…");
  const buildArgs = [next, "build", "--webpack"];
  const build = spawnOwned(buildArgs, childEnv, "build.log");
  const buildCode = await new Promise((resolve, reject) => {
    build.once("error", reject);
    build.once("exit", (code) => resolve(code));
  });
  commands.push({ command: [process.execPath, ...buildArgs], exitCode: buildCode });
  assert.equal(buildCode, 0, `Frontend build failed; inspect ${path.join(root, "build.log")}`);

  await new Promise((resolve) => reservation.close(resolve));
  const startArgs = [next, "start", "--hostname", "127.0.0.1", "--port", String(frontPort)];
  nextProcess = spawnOwned(startArgs, childEnv, "next.log");
  let ready = false;
  for (let attempt = 0; attempt < 300; attempt += 1) {
    if (nextProcess.spawnError) throw nextProcess.spawnError;
    assert(nextProcess.exitCode === null && nextProcess.signalCode === null, "Owned frontend startup failed");
    if (fs.readFileSync(path.join(root, "next.log"), "utf8").includes("Ready in")) { ready = true; break; }
    await delay(100);
  }
  assert(ready, "Owned frontend did not become ready");
  summary = await runBrowserScenarios({ chromium: driver.chromium, origin, mock, root, env, executablePath: process.env.TRENDORA_BROWSER_EXECUTABLE, registerBrowserCleanup: (close) => { closeBrowser = close; } });
  for (const key of ["passed", "failed", "skipped", "total"]) assert(Number.isInteger(summary[key]) && summary[key] >= 0);
  assert.equal(summary.total, total);
  assert.equal(summary.passed + summary.failed + summary.skipped, total);
  process.exitCode = summary.failed || summary.skipped ? 1 : 0;
} catch (error) {
  output("blocker.json", { error: String(error.stack ?? error) });
  console.error(`Browser execution stopped: ${error.message}`);
  process.exitCode = 2;
} finally {
  try { await cleanup(); }
  catch (error) {
    output("cleanup-error.json", { error: String(error.stack ?? error) });
    console.error(`Owned cleanup failed: ${error.message}`);
    process.exitCode = 1;
  }
  if (nextProcess) commands.push({ command: nextProcess.command, exitCode: nextProcess.exitCode, signal: nextProcess.signalCode });
  output("commands.json", commands);
  output("summary.json", summary);
  console.log(`Browser scenarios: ${summary.passed} passed, ${summary.failed} failed, ${summary.skipped} skipped (${summary.total} total)`);
  console.log(`Retained diagnostics: ${root}`);
}
