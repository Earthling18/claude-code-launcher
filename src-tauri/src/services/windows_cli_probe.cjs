// Shared by installation verification and runtime checks. Never execute an EXE
// placeholder: Windows may display a modal "16-bit application" error for it.
const fs = require('node:fs');
const path = require('node:path');
const { createRequire } = require('node:module');
const { spawnSync } = require('node:child_process');

function verifyExe(file) {
  const fd = fs.openSync(file, 'r');
  try {
    const header = Buffer.alloc(64);
    if (fs.readSync(fd, header, 0, 64, 0) !== 64 || header.toString('ascii', 0, 2) !== 'MZ') {
      throw new Error(`Native executable is missing or is a placeholder: ${file}`);
    }
    const pe = Buffer.alloc(4);
    if (fs.readSync(fd, pe, 0, 4, header.readUInt32LE(60)) !== 4 || !pe.equals(Buffer.from([80, 69, 0, 0]))) {
      throw new Error(`Invalid PE executable: ${file}`);
    }
  } finally { fs.closeSync(fd); }
}

function inspectPackage(root, cli, arch = process.arch) {
  const manifestPath = path.join(root, 'package.json');
  const manifest = JSON.parse(fs.readFileSync(manifestPath, 'utf8'));
  const bin = typeof manifest.bin === 'string' ? manifest.bin : manifest.bin?.[cli];
  if (!bin) throw new Error(`Missing ${cli} command in ${manifestPath}`);
  const entry = path.resolve(root, bin);
  if (!fs.statSync(entry).isFile()) throw new Error(`Missing command: ${entry}`);
  let native = entry;
  if (cli === 'codex' && !entry.endsWith('.exe')) {
    const platform = `@openai/codex-win32-${arch}`;
    let vendor = path.join(root, 'vendor');
    try {
      vendor = path.join(path.dirname(createRequire(manifestPath).resolve(`${platform}/package.json`)), 'vendor');
    } catch { /* Older Codex releases bundle vendor directly. */ }
    const triple = arch === 'arm64' ? 'aarch64' : 'x86_64';
    native = path.join(vendor, `${triple}-pc-windows-msvc`, 'bin', 'codex.exe');
  }
  if (native.toLowerCase().endsWith('.exe')) verifyExe(native);
  return { entry, native, version: manifest.version };
}

function probe(root, cli) {
  const info = inspectPackage(root, cli);
  const result = info.entry.toLowerCase().endsWith('.exe')
    ? spawnSync(info.entry, ['--version'], { encoding: 'utf8', timeout: 20000, windowsHide: true })
    : spawnSync(process.execPath, [info.entry, '--version'], { encoding: 'utf8', timeout: 20000, windowsHide: true });
  if (result.error) throw result.error;
  if (result.status !== 0) throw new Error((result.stderr || result.stdout || `Exit ${result.status}`).trim());
  const version = `${result.stdout}\n${result.stderr}`.match(/\d+\.\d+\.\d+(?:[-+][\w.-]+)?/)?.[0];
  if (!version) throw new Error('CLI returned no version');
  if (version !== info.version) throw new Error(`Installed ${info.version}, executable reports ${version}`);
  return { ...info, version };
}

module.exports = { verifyExe, inspectPackage, probe };
if (require.main === module) {
  try { console.log(JSON.stringify(probe(process.argv[2], process.argv[3]))); }
  catch (error) { console.error(error.message); process.exitCode = 1; }
}
