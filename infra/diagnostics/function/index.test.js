'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const { handler, _internal } = require('./index');

function validReport() {
  return {
    schema_version: 1,
    incident_id: 'incident-abcdef-10',
    install_id: 'install-123abc-10',
    kind: 'webview_renderer_missing',
    occurred_at: Math.floor(Date.now() / 1000),
    app_version: '1.2.7',
    os_version: 'Windows 11',
    compatibility_stage: 'standard',
    samples: [0, 1, 2].map(() => ({
      browser_count: 1,
      renderer_count: 0,
      gpu_count: 1,
      utility_count: 2,
    })),
    note: null,
    diagnostic_log_tail: [],
  };
}

function event(report, secret = 'test-secret') {
  return {
    requestContext: { http: { method: 'POST' } },
    headers: { 'x-ccl-ingest-key': secret },
    body: JSON.stringify(report),
    isBase64Encoded: false,
  };
}

test('accepts only three confirmed renderer-missing samples', async () => {
  process.env.INGEST_SHARED_SECRET = 'test-secret';
  const original = console.log;
  console.log = () => {};
  try {
    const accepted = await handler(event(validReport()));
    assert.equal(accepted.statusCode, 202);

    const ambiguous = validReport();
    ambiguous.samples[2].renderer_count = 1;
    const rejected = await handler(event(ambiguous));
    assert.equal(rejected.statusCode, 422);
  } finally {
    console.log = original;
  }
});

test('rejects unknown fields instead of storing an expanded payload', () => {
  const report = validReport();
  report.project_path = 'D:\\secret';
  assert.equal(_internal.validateAndSanitize(report), null);
});

test('redacts credentials and user paths a second time', () => {
  const report = validReport();
  report.note = 'token=abc123 C:\\Users\\alice\\project alice@example.com';
  const clean = _internal.validateAndSanitize(report);
  assert.ok(clean);
  assert.doesNotMatch(clean.note, /abc123|alice|example\.com/);
});

test('hides the direct Function Compute endpoint without the gateway secret', async () => {
  process.env.INGEST_SHARED_SECRET = 'test-secret';
  const result = await handler(event(validReport(), 'wrong-secret'));
  assert.equal(result.statusCode, 404);
});

test('rejects request bodies above the hard byte limit', async () => {
  process.env.INGEST_SHARED_SECRET = 'test-secret';
  const oversized = event(validReport());
  oversized.body = 'x'.repeat(_internal.MAX_BODY_BYTES + 1);
  const result = await handler(oversized);
  assert.equal(result.statusCode, 413);
});

test('rejects log tails that exceed line count or line length limits', () => {
  const tooManyLines = validReport();
  tooManyLines.diagnostic_log_tail = Array.from({ length: 31 }, () => 'safe');
  assert.equal(_internal.validateAndSanitize(tooManyLines), null);

  const tooLongLine = validReport();
  tooLongLine.diagnostic_log_tail = ['x'.repeat(301)];
  assert.equal(_internal.validateAndSanitize(tooLongLine), null);
});
