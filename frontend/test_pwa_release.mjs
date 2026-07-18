import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { createHash } from 'node:crypto';

const frontend = new URL('./', import.meta.url);
const metadata = JSON.parse(readFileSync(new URL('./pwa/pwa-release.json', frontend)));
const releaseScript = readFileSync(new URL('./pwa/pwa-release.js', frontend), 'utf8');
const worker = readFileSync(new URL('./service-worker.js', frontend), 'utf8');

const aggregate = Object.entries(metadata.assets)
  .sort(([left], [right]) => (left < right ? -1 : left > right ? 1 : 0))
  .map(([path, digest]) => `${path}:${digest}\n`)
  .join('');
assert.equal(metadata.release_id, createHash('sha256').update(aggregate).digest('hex').slice(0, 16));
assert.match(releaseScript, new RegExp(metadata.release_id));
assert.match(worker, /importScripts\('\/pwa-release\.js'\)/);
assert.match(worker, /isPrivatePath/);
assert.doesNotMatch(worker, /cache\.put/);
