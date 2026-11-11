const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const { inspectPackage, probe } = require('../src-tauri/src/services/windows_cli_probe.cjs');

function fixture(t, cli, bin = `bin/${cli}.js`) {
  const tmp = fs.mkdtempSync(path.join(os.tmpdir(), 'ccl-probe-'));
  t.after(() => fs.rmSync(tmp, { recursive: true, force: true }));
  const root = path.join(tmp, 'node_modules', cli === 'claude' ? '@anthropic-ai/claude-code' : '@openai/codex');
  fs.mkdirSync(path.join(root, 'bin'), { recursive: true });
  fs.writeFileSync(path.join(root, 'package.json'), JSON.stringify({ version: '1.2.3', bin: { [cli]: bin } }));
  fs.writeFileSync(path.join(root, bin), 'console.log("1.2.3");');
  return { root, tmp };
}
function native(file) {
  fs.mkdirSync(path.dirname(file), { recursive: true });
  const bytes = Buffer.alloc(128);
  bytes.write('MZ'); bytes.writeUInt32LE(64, 60); bytes.write('PE\0\0', 64);
  fs.writeFileSync(file, bytes);
}
test('rejects Claude text placeholder without executing it', t => {
  const { root } = fixture(t, 'claude', 'bin/claude.exe');
  assert.throws(() => inspectPackage(root, 'claude'), /placeholder/);
});
test('supports older Claude JavaScript entry points and executes version', t => {
  const { root } = fixture(t, 'claude');
  assert.equal(probe(root, 'claude').version, '1.2.3');
});
test('detects command failure and version mismatch', t => {
  const { root } = fixture(t, 'claude');
  fs.writeFileSync(path.join(root, 'bin/claude.js'), 'console.log("9.9.9")');
  assert.throws(() => probe(root, 'claude'), /executable reports 9.9.9/);
  fs.writeFileSync(path.join(root, 'bin/claude.js'), 'process.exit(7)');
  assert.throws(() => probe(root, 'claude'), /Exit 7/);
});
test('detects absent Codex native package despite present shim entry', t => {
  const { root } = fixture(t, 'codex');
  assert.throws(() => inspectPackage(root, 'codex', 'x64'), /ENOENT/);
});
for (const hoisted of [false, true]) {
  test(`resolves ${hoisted ? 'hoisted' : 'nested'} Codex platform packages`, t => {
    const { root, tmp } = fixture(t, 'codex');
    const pkg = path.join(hoisted ? tmp : root, 'node_modules/@openai/codex-win32-x64');
    fs.mkdirSync(pkg, { recursive: true });
    fs.writeFileSync(path.join(pkg, 'package.json'), '{}');
    const exe = path.join(pkg, 'vendor/x86_64-pc-windows-msvc/bin/codex.exe');
    native(exe);
    assert.equal(inspectPackage(root, 'codex', 'x64').native, exe);
    fs.writeFileSync(exe, Buffer.from('MZ')); // MZ alone is not an intact PE header.
    assert.throws(() => inspectPackage(root, 'codex', 'x64'));
  });
}
test('supports legacy vendor layout and Node ARM64 architecture', t => {
  const { root } = fixture(t, 'codex');
  const exe = path.join(root, 'vendor/aarch64-pc-windows-msvc/bin/codex.exe');
  native(exe);
  assert.equal(inspectPackage(root, 'codex', 'arm64').native, exe);
});
