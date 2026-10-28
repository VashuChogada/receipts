#!/usr/bin/env node
// Deploy (docs/setup.md): build the UI here, copy the app to the server's
// receipts folder. The server runs stock images (python:3.12-slim,
// caddy:2-alpine) over those files, so nothing is built there.
//
//   node scripts/deploy.mjs            build the UI, copy it all over
//   node scripts/deploy.mjs --dry-run  show what would be copied
//   node scripts/deploy.mjs --compose  print deploy/compose.yaml with .env's
//                                      values filled in, for pasting into a
//                                      web UI (ZimaOS, CasaOS)
//
// Where it copies to: RECEIPTS_SHARE, the receipts folder as this machine
// sees it (a network share such as //server/data/receipts, or a local path
// when Docker runs here). It defaults to RECEIPTS_DIR, the same folder as the
// server sees it. Both come from the environment or from .env in the repo.
//
// In that folder:
//   app/app/          backend/app
//   app/static/       frontend/dist (index.html last, so a visit mid-copy
//                     never gets a page whose files aren't there yet)
//   app/start.sh      deploy/start.sh
//   app/requirements.txt
//   config/Caddyfile  deploy/Caddyfile (Caddy runs --watch)
//   data/models/rapidocr/  the PP-OCRv6 models from backend/.models, if there,
//                     so the server needn't fetch them from RapidOCR's mirror

import { execSync } from 'node:child_process';
import { copyFileSync, existsSync, mkdirSync, readdirSync, readFileSync, rmSync, statSync, writeFileSync } from 'node:fs';
import { dirname, join, relative } from 'node:path';
import { fileURLToPath } from 'node:url';

const ROOT = join(dirname(fileURLToPath(import.meta.url)), '..');

// .env: KEY=value lines; the real environment wins.
const env = {};
if (existsSync(join(ROOT, '.env'))) {
  for (const line of readFileSync(join(ROOT, '.env'), 'utf8').split(/\r?\n/)) {
    const m = line.match(/^\s*([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*?)\s*$/);
    if (m) env[m[1]] = m[2].replace(/^(['"])(.*)\1$/, '$2');
  }
}
Object.assign(env, process.env);

if (process.argv.includes('--compose')) {
  // Compose's own ${VAR}, ${VAR:-default} and ${VAR:?error} forms.
  const yaml = readFileSync(join(ROOT, 'deploy', 'compose.yaml'), 'utf8');
  const out = yaml.replace(/\$\{([A-Za-z_][A-Za-z0-9_]*)(?::([-?])([^}]*))?\}/g, (_, name, op, arg) => {
    if (env[name]) return env[name];
    if (op === '-') return arg;
    console.error(`${name} isn't set: add it to .env (see .env.example).`);
    process.exit(1);
  });
  process.stdout.write(out);
  process.exit(0);
}

const SHARE = env.RECEIPTS_SHARE || env.RECEIPTS_DIR;
const dry = process.argv.includes('--dry-run');
if (!SHARE) {
  console.error('Set RECEIPTS_SHARE (or RECEIPTS_DIR) in .env: where to copy the app. See .env.example.');
  process.exit(1);
}

function walk(dir) {
  if (!existsSync(dir)) return [];
  return readdirSync(dir).flatMap((name) => {
    const p = join(dir, name);
    return statSync(p).isDirectory() ? walk(p) : [p];
  });
}

// Shell scripts and the Caddyfile run on Linux: whatever an editor here
// saved, they go over with LF line endings (sh stops at a CR after `set -eu`).
const LF_ONLY = /(\.sh|Caddyfile)$/;
const CR = String.fromCharCode(13);

function contents(file) {
  const data = readFileSync(file);
  return LF_ONLY.test(file) ? Buffer.from(data.toString('utf8').split(CR).join('')) : data;
}

function same(a, b) {
  return existsSync(b) && contents(a).equals(readFileSync(b));
}

if (!existsSync(dirname(SHARE))) {
  console.error(`Can't reach ${dirname(SHARE)}: is the server on and the share reachable?`);
  process.exit(1);
}

console.log('Building the UI…');
execSync('npm run build', { cwd: join(ROOT, 'frontend'), stdio: dry ? 'ignore' : 'inherit' });

// [source file, path under the share]
const plan = [];
for (const f of walk(join(ROOT, 'backend', 'app'))) {
  if (f.includes('__pycache__')) continue;
  plan.push([f, join('app', 'app', relative(join(ROOT, 'backend', 'app'), f))]);
}
plan.push([join(ROOT, 'backend', 'requirements.txt'), join('app', 'requirements.txt')]);
plan.push([join(ROOT, 'deploy', 'start.sh'), join('app', 'start.sh')]);
const dist = join(ROOT, 'frontend', 'dist');
const statics = walk(dist).map((f) => [f, join('app', 'static', relative(dist, f))]);
statics.sort(([a], [b]) => (a.endsWith('index.html') ? 1 : 0) - (b.endsWith('index.html') ? 1 : 0));
plan.push(...statics);
plan.push([join(ROOT, 'deploy', 'Caddyfile'), join('config', 'Caddyfile')]);
const ocrModels = join(ROOT, 'backend', '.models', 'rapidocr');
for (const f of walk(ocrModels)) plan.push([f, join('data', 'models', 'rapidocr', relative(ocrModels, f))]);

const changed = plan.filter(([from, to]) => !same(from, join(SHARE, to)));
console.log(`${changed.length} of ${plan.length} files changed${dry ? ' (dry run)' : ''}`);
if (dry) {
  changed.forEach(([, to]) => console.log(`  ${to}`));
  process.exit(0);
}

for (const dir of ['app', 'data', 'config', 'caddy/data', 'caddy/config']) mkdirSync(join(SHARE, dir), { recursive: true });
for (const [from, to] of changed) {
  mkdirSync(dirname(join(SHARE, to)), { recursive: true });
  if (LF_ONLY.test(from)) writeFileSync(join(SHARE, to), contents(from));
  else copyFileSync(from, join(SHARE, to));
}

// Old code files go; old hashed UI chunks stay, for a page already open
// (a cached page may still ask for them). Only app/ is ever pruned; data/ is
// never touched.
const wanted = new Set(plan.map(([, to]) => join(SHARE, to)));
let removed = 0;
for (const p of walk(join(SHARE, 'app'))) {
  const rel = relative(join(SHARE, 'app'), p);
  if (!wanted.has(p) && !rel.startsWith(join('static', 'assets'))) {
    rmSync(p);
    removed++;
  }
}

const backendChanged = changed.some(([, to]) => to.startsWith(join('app', 'app')) || to.endsWith('requirements.txt') || to.endsWith('start.sh'));
console.log(`Copied ${changed.length}, removed ${removed}.`);
if (backendChanged) {
  console.log('\nThe server code changed: restart receipts-app to load it (`docker restart receipts-app`, or from your server\'s app list).');
  console.log('(First install: start the compose file; see docs/setup.md.)');
} else {
  console.log('Only the UI changed: live already, no restart needed.');
}
