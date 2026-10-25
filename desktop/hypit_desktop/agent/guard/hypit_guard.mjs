// Stands in for the `hypit` command inside an agent workspace.
// Read-only and planning commands go through to the real CLI. Anything that spends money, logs in,
// downloads or changes the machine is refused with an explanation, so the agent reports what it
// would have run. The app itself talks to the real CLI directly and does the spending after the
// user's confirmation. Every call is appended to guard.log in the workspace.
import { spawnSync } from "node:child_process";
import { appendFileSync, existsSync, readFileSync } from "node:fs";
import { join } from "node:path";

const launcher = process.env.HYPIT_LAUNCHER;
const workspace = process.env.HYPIT_GUARD_WORKSPACE || process.cwd();
const argv = process.argv.slice(2);
const command = argv[0] ?? "help";
const sub = argv[1] ?? "";

const ALLOWED = new Set(["version", "paths", "check", "plan", "pricing", "doctor", "vocabulary", "media",
  "estimate", "builds", "history", "inspect", "status", "logs", "get", "help", "--help", "-h", "--version", "-v"]);
const ALLOWED_SUB = { runtime: new Set(["init", "use", "status", "unset"]), programs: new Set(["status"]), cli: new Set(["status"]) };
const WHY = {
  build: "submits a paid Build (the app does this after the user confirms the price)",
  auth: "logs in or out of a service",
  download: "fetches a network video (the app already prepared the reference)",
  cancel: "controls a running Build",
  capture: "installs or runs a browser",
};
const TRANSCRIBE_LIMIT = 3; // hosted speech recognition costs a little; allow a few calls

const logPath = join(workspace, "guard.log");
const log = (entry) => appendFileSync(logPath, JSON.stringify({ ...entry, time: new Date().toISOString() }) + "\n");
const past = () => (existsSync(logPath) ? readFileSync(logPath, "utf8").split("\n").filter(Boolean).map((l) => JSON.parse(l)) : []);

let allowed = ALLOWED.has(command) || (ALLOWED_SUB[command]?.has(sub) ?? false);
let reason = WHY[command] ?? "is not part of this task";
if (command === "transcribe") {
  const used = past().filter((e) => e.argv?.[0] === "transcribe" && e.allowed).length;
  allowed = used < TRANSCRIBE_LIMIT;
  reason = `would be call number ${used + 1}; at most ${TRANSCRIBE_LIMIT} are allowed because each one is billed`;
}
log({ argv, allowed });
if (!allowed) {
  console.error(`BLOCKED: \`hypit ${argv.join(" ")}\` ${reason}. Do not retry it. ` +
    "Continue with what you can do, and mention it in your final summary.");
  process.exit(3);
}
const done = spawnSync(process.execPath, [launcher, ...argv], {
  stdio: "inherit", env: { ...process.env, NODE_USE_ENV_PROXY: "1" },
});
process.exit(done.status ?? 1);
