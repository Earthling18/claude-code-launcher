// Integration tests run the real PowerShell installer with an isolated fake npm.
const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const { spawnSync } = require('node:child_process');

function run(t, { broken = false, uninstallFails = false, nativeDownloadFails = false } = {}) {
  const tmp = fs.mkdtempSync(path.join(os.tmpdir(), 'ccl installer test '));
  t.after(() => fs.rmSync(tmp, { recursive: true, force: true }));
  const root = path.join(tmp, 'node_modules/@anthropic-ai/claude-code');
  fs.mkdirSync(root, { recursive: true });
  fs.writeFileSync(path.join(root, 'package.json'), JSON.stringify({ version: '1.2.3', bin: { claude: 'cli.js' }, optionalDependencies: { '@anthropic-ai/claude-code-win32-x64': '1.2.3' } }));
  fs.writeFileSync(path.join(root, 'cli.js'), broken ? 'process.exit(42)' : 'console.log("1.2.3")');
  fs.writeFileSync(path.join(tmp, 'claude.cmd'), '@echo off\r\necho 1.2.3\r\nexit /b 0\r\n');
  fs.writeFileSync(path.join(tmp, 'npm.cmd'), [
    '@echo off', `echo %*>>"${tmp}\\calls.txt"`,
    `if "%~1"=="prefix" (echo ${tmp}& exit /b 0)`,
    `if "%~1"=="root" (echo ${tmp}\\node_modules& exit /b 0)`,
    `if "%~1"=="view" (echo ${JSON.stringify({ version: '1.2.3', ...(nativeDownloadFails ? { optionalDependencies: { '@anthropic-ai/claude-code-win32-x64': '1.2.3' } } : {}) })}& exit /b 0)`,
    `if "%~1"=="uninstall" exit /b ${uninstallFails ? 17 : 0}`,
    // Global install returns 0 even in the broken case, as real npm does.
    'if "%~2"=="-g" exit /b 0',
    'exit /b 31', '',
  ].join('\r\n'));
  const env = { ...process.env, LOCALAPPDATA: tmp };
  const key = Object.keys(env).find(k => k.toLowerCase() === 'path') || 'PATH';
  env[key] = `${tmp};${env[key]}`;
  // Keep fixture locks separate from any real installer currently running.
  const script = path.join(tmp, 'install.ps1');
  fs.writeFileSync(script, fs.readFileSync('src-tauri/src/services/windows_cli_install.ps1', 'utf8').replace('Local\\CCLauncherNpmInstall', `Local\\CCLauncherTest-${path.basename(tmp)}`));
  fs.copyFileSync('src-tauri/src/services/windows_cli_probe.cjs', path.join(tmp, 'windows_cli_probe.cjs'));
  const result = spawnSync('powershell.exe', ['-NoLogo', '-NoProfile', '-NonInteractive', '-ExecutionPolicy', 'Bypass', '-File', script, '-Cli', 'claude', '-Action', uninstallFails ? 'reinstall' : 'update', '-Quiet'], { env, encoding: 'utf8', timeout: 30000, windowsHide: true });
  assert.ifError(result.error);
  const calls = path.join(tmp, 'calls.txt');
  return { ...result, calls: fs.existsSync(calls) ? fs.readFileSync(calls, 'utf8') : '' };
}
test('reports success only after package and shim startup verification, handles spaces', { skip: process.platform !== 'win32' }, t => {
  const result = run(t);
  assert.equal(result.status, 0, result.stdout + result.stderr);
  assert.match(result.stdout, /startup verified/);
  assert.match(result.calls, /--include=optional --ignore-scripts=false/);
});
test('npm exit 0 with a broken CLI triggers required-native repair and never success', { skip: process.platform !== 'win32' }, t => {
  const result = run(t, { broken: true });
  assert.equal(result.status, 1, result.stdout + result.stderr);
  assert.doesNotMatch(result.stdout, /\[OK\]/);
  assert.match(result.calls, /cclauncher-native-/);
  assert.match(result.stdout, /exit 31/);
});
test('failed uninstall stops reinstall instead of overwriting its error', { skip: process.platform !== 'win32' }, t => {
  const result = run(t, { uninstallFails: true });
  assert.equal(result.status, 1);
  assert.doesNotMatch(result.calls, /^install /m);
  assert.match(result.stdout, /exit 17/);
});
test('native download failure leaves the current installation untouched', { skip: process.platform !== 'win32' }, t => {
  const result = run(t, { nativeDownloadFails: true });
  assert.equal(result.status, 1);
  assert.match(result.calls, /install --prefix=.*cclauncher-native-/);
  assert.doesNotMatch(result.calls, /^(install -g|uninstall) /m);
  assert.doesNotMatch(result.stdout, /\[OK\]/);
});
