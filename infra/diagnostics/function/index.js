'use strict';

const MAX_BODY_BYTES = 128 * 1024;
const ALLOWED_KINDS = new Set([
  'webview_renderer_missing',
  'rust_panic',
  'tauri_startup_fatal',
  'manual_diagnostic',
]);
const ALLOWED_STAGES = new Set([
  'standard',
  'no_sandbox',
  'no_sandbox_disable_gpu',
]);

function response(statusCode, body) {
  return {
    statusCode,
    headers: { 'content-type': 'application/json; charset=utf-8' },
    isBase64Encoded: false,
    body: JSON.stringify(body),
  };
}

function getHeader(headers, name) {
  const wanted = name.toLowerCase();
  for (const [key, value] of Object.entries(headers || {})) {
    if (key.toLowerCase() === wanted) return String(value);
  }
  return '';
}

function hasOnlyKeys(value, keys) {
  if (!value || typeof value !== 'object' || Array.isArray(value)) return false;
  const allowed = new Set(keys);
  return Object.keys(value).every((key) => allowed.has(key));
}

function boundedString(value, max, pattern) {
  return typeof value === 'string'
    && value.length > 0
    && value.length <= max
    && (!pattern || pattern.test(value));
}

function validCount(value) {
  return Number.isInteger(value) && value >= 0 && value <= 64;
}

function validateSample(sample) {
  return hasOnlyKeys(sample, [
    'browser_count',
    'renderer_count',
    'gpu_count',
    'utility_count',
  ])
    && validCount(sample.browser_count)
    && validCount(sample.renderer_count)
    && validCount(sample.gpu_count)
    && validCount(sample.utility_count);
}

function scrubText(value, max) {
  return String(value)
    .replace(/[\u0000-\u0008\u000b\u000c\u000e-\u001f\u007f]/g, '')
    .replace(/C:\\Users\\[^\\\s]+/gi, 'C:\\Users\\<user>')
    .replace(/\/Users\/[^/\s]+/g, '/Users/<user>')
    .replace(/[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}/g, '<email>')
    .replace(/\bBearer\s+[A-Za-z0-9._~+\/-]+=*/gi, 'Bearer <redacted>')
    .replace(/\b(sk-[A-Za-z0-9_-]{8,})\b/g, '<redacted-token>')
    .replace(/\b(token|api[_-]?key|authorization|secret|password|base[_-]?url)\b\s*[:=]\s*[^\s,;]+/gi, '$1=<redacted>')
    .slice(0, max);
}

function validateAndSanitize(report) {
  if (!hasOnlyKeys(report, [
    'schema_version',
    'incident_id',
    'install_id',
    'kind',
    'occurred_at',
    'app_version',
    'os_version',
    'compatibility_stage',
    'samples',
    'note',
    'diagnostic_log_tail',
  ])) return null;

  const idPattern = /^[a-z]+-[a-f0-9]+-[a-f0-9]+$/;
  const versionPattern = /^\d+\.\d+\.\d+(?:[-+][0-9A-Za-z.-]+)?$/;
  const now = Math.floor(Date.now() / 1000);
  if (report.schema_version !== 1
      || !boundedString(report.incident_id, 96, idPattern)
      || !boundedString(report.install_id, 96, idPattern)
      || !ALLOWED_KINDS.has(report.kind)
      || !Number.isInteger(report.occurred_at)
      || report.occurred_at < 1_577_836_800
      || report.occurred_at > now + 600
      || !boundedString(report.app_version, 64, versionPattern)
      || !boundedString(report.os_version, 200)
      || !ALLOWED_STAGES.has(report.compatibility_stage)
      || !Array.isArray(report.samples)
      || report.samples.length > 3
      || !report.samples.every(validateSample)
      || !(report.note === null || typeof report.note === 'string')
      || (typeof report.note === 'string' && report.note.length > 1000)
      || !Array.isArray(report.diagnostic_log_tail)
      || report.diagnostic_log_tail.length > 80
      || !report.diagnostic_log_tail.every((line) => typeof line === 'string' && line.length <= 500)) {
    return null;
  }

  if (report.kind === 'webview_renderer_missing') {
    const rendererDefinitelyMissing = report.samples.length === 3
      && report.samples.every((sample) => sample.browser_count > 0 && sample.renderer_count === 0);
    if (!rendererDefinitelyMissing) return null;
  } else if ((report.kind === 'rust_panic' || report.kind === 'tauri_startup_fatal')
      && report.samples.length !== 0) {
    return null;
  }

  return {
    ...report,
    os_version: scrubText(report.os_version, 200),
    note: report.note === null ? null : scrubText(report.note, 1000),
    diagnostic_log_tail: report.diagnostic_log_tail.map((line) => scrubText(line, 500)),
  };
}

function decodeBody(event) {
  if (event && typeof event.body === 'object' && event.body !== null) {
    return Buffer.from(JSON.stringify(event.body));
  }
  const body = event && typeof event.body === 'string' ? event.body : '';
  return Buffer.from(body, event && event.isBase64Encoded ? 'base64' : 'utf8');
}

exports.handler = async function handler(event) {
  const method = event?.requestContext?.http?.method || event?.httpMethod || 'POST';
  if (method !== 'POST') return response(405, { accepted: false, error: 'method_not_allowed' });

  const expectedSecret = process.env.INGEST_SHARED_SECRET || '';
  const providedSecret = getHeader(event?.headers, 'x-ccl-ingest-key');
  if (!expectedSecret || providedSecret !== expectedSecret) {
    return response(404, { accepted: false, error: 'not_found' });
  }

  const raw = decodeBody(event);
  if (raw.length === 0 || raw.length > MAX_BODY_BYTES) {
    return response(413, { accepted: false, error: 'payload_too_large' });
  }

  let parsed;
  try {
    parsed = JSON.parse(raw.toString('utf8'));
  } catch {
    return response(400, { accepted: false, error: 'invalid_json' });
  }

  const report = validateAndSanitize(parsed);
  if (!report) return response(422, { accepted: false, error: 'invalid_report' });

  // Function Compute forwards stdout to the configured SLS Logstore. Only the
  // validated and re-sanitized whitelist schema reaches this line.
  console.log(`CCL_DIAGNOSTIC ${JSON.stringify(report)}`);
  return response(202, { accepted: true, report_id: report.incident_id });
};

exports._internal = { validateAndSanitize, scrubText, MAX_BODY_BYTES };
