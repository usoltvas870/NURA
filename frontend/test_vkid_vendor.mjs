import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';
import { existsSync, readFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

const frontend = dirname(fileURLToPath(import.meta.url));
const packageLock = JSON.parse(readFileSync(join(frontend, 'package-lock.json'), 'utf8'));
const metadata = JSON.parse(readFileSync(join(frontend, 'assets', 'vendor', 'vkid-sdk.meta.json'), 'utf8'));
const source = join(frontend, 'node_modules', '@vkid', 'sdk', 'dist-sdk', 'umd', 'index.js');
const asset = join(frontend, 'assets', 'vendor', 'vkid-sdk.js');
const packageEntry = packageLock.packages['node_modules/@vkid/sdk'];

assert.equal(packageLock.lockfileVersion >= 2, true);
assert.equal(packageEntry.version, '2.6.6');
assert.match(packageEntry.integrity, /^sha512-/);
assert.equal(metadata.package, '@vkid/sdk');
assert.equal(metadata.version, packageEntry.version);
assert.equal(metadata.license, 'vkid-sdk.LICENSE');
assert.equal(existsSync(join(frontend, 'assets', 'vendor', metadata.license)), true);
assert.equal(existsSync(asset), true);

const sourceBytes = readFileSync(source);
const assetBytes = readFileSync(asset);
assert.equal(assetBytes.length > 0, true);
assert.equal(assetBytes.equals(sourceBytes), true);
assert.equal(metadata.sha256, createHash('sha256').update(assetBytes).digest('hex'));
assert.doesNotMatch(assetBytes.toString('utf8'), /window\.VKIDSDK=window\.VKIDSDK\|\|\{\}/);
assert.doesNotMatch(assetBytes.toString('utf8'), /VK_CLIENT_SECRET/);
console.log('VK ID vendor asset matches the pinned official package');
