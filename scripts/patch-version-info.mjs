// Overwrite the Windows exe VERSIONINFO ProductName / FileDescription to the value
// required by the corporate security allowlist ("Mobot Launcher"), WITHOUT changing
// the user-visible product name. `productName` in tauri.conf.json stays "CC 启动器",
// so the install dir, Start-menu shortcut, uninstall entry and window title are all
// unchanged — only the exe's embedded VERSIONINFO strings that the security software
// reads get rewritten.
//
// Runs as tauri's `beforeBundleCommand`: after the binary is compiled but before NSIS
// packaging, so both the shipped installer and the portable zip (which copies the same
// target/release exe) carry the patched metadata.
//
// No-op on non-Windows — the macOS CI build runs this same hook.

import { existsSync, mkdirSync, writeFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, resolve } from 'node:path';
import { execFileSync } from 'node:child_process';

// Must match the VERSIONINFO standard defined by the security team.
const REQUIRED_NAME = 'Mobot Launcher';
const RCEDIT_URL =
  'https://github.com/electron/rcedit/releases/download/v2.0.0/rcedit-x64.exe';

const platform = process.env.TAURI_ENV_PLATFORM || process.platform;
const isWindows = platform === 'windows' || platform === 'win32';
if (!isWindows) {
  console.log(`[patch-version-info] platform=${platform}, skipping (Windows-only).`);
  process.exit(0);
}

const scriptDir = dirname(fileURLToPath(import.meta.url));
const root = resolve(scriptDir, '..');
const exePath = resolve(root, 'src-tauri/target/release/cc-launcher-tauri.exe');

if (!existsSync(exePath)) {
  console.error(`[patch-version-info] exe not found: ${exePath}`);
  process.exit(1);
}

// Reuse an existing rcedit if one is around (build.ps1 drops one at repo root),
// otherwise cache a copy under scripts/.bin (ignored by *.exe in .gitignore).
async function resolveRcedit() {
  const candidates = [
    process.env.RCEDIT,
    resolve(root, 'rcedit.exe'),
    resolve(scriptDir, '.bin', 'rcedit-x64.exe'),
  ].filter(Boolean);
  for (const c of candidates) {
    if (existsSync(c)) return c;
  }
  const dest = resolve(scriptDir, '.bin', 'rcedit-x64.exe');
  mkdirSync(dirname(dest), { recursive: true });
  console.log(`[patch-version-info] downloading rcedit from ${RCEDIT_URL}`);
  const res = await fetch(RCEDIT_URL);
  if (!res.ok) {
    console.error(`[patch-version-info] rcedit download failed: HTTP ${res.status}`);
    process.exit(1);
  }
  writeFileSync(dest, Buffer.from(await res.arrayBuffer()));
  return dest;
}

const rcedit = await resolveRcedit();

console.log(
  `[patch-version-info] setting ProductName/FileDescription="${REQUIRED_NAME}" on ${exePath}`,
);
execFileSync(
  rcedit,
  [
    exePath,
    '--set-version-string', 'ProductName', REQUIRED_NAME,
    '--set-version-string', 'FileDescription', REQUIRED_NAME,
  ],
  { stdio: 'inherit' },
);

console.log('[patch-version-info] done.');
