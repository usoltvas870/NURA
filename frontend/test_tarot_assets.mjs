import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';
import { existsSync, readFileSync, readdirSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import vm from 'node:vm';

const frontend = new URL('./', import.meta.url);
const app = new URL('./pwa/app/', frontend);
const assetDirectory = new URL('./images/major-v1/', app);
const manifests = readdirSync(fileURLToPath(assetDirectory)).filter((name) => /^tarot-assets\.[a-f0-9]{12}\.json$/.test(name));
assert.equal(manifests.length, 1, 'exactly one content-addressed manifest is required');
const manifestPath = new URL(manifests[0], assetDirectory);
const manifestBytes = readFileSync(manifestPath);
assert.equal(manifests[0], `tarot-assets.${createHash('sha256').update(manifestBytes).digest('hex').slice(0, 12)}.json`);
const manifest = JSON.parse(manifestBytes);

assert.equal(manifest.schema, 1);
assert.equal(manifest.deck, 'major-v1');
assert.equal(manifest.cards.length, 22);
assert.deepEqual(manifest.cards.map((card) => card.arcana_id).sort((a, b) => a - b), Array.from({ length: 22 }, (_, index) => index + 1));
assert.equal(manifest.cards.find((card) => card.arcana_id === 22).filename, '00-fool.png');

const urls = new Set();
for (const card of manifest.cards) {
  assert.deepEqual(Object.keys(card.derivatives).sort(), ['480', '900']);
  for (const [width, derivative] of Object.entries(card.derivatives)) {
    const path = new URL(`./pwa/app/${derivative.path}`, frontend);
    assert.ok(existsSync(path), `${derivative.path} is missing`);
    const bytes = readFileSync(path);
    assert.equal(createHash('sha256').update(bytes).digest('hex'), derivative.sha256);
    assert.equal(bytes.length, derivative.bytes);
    assert.equal(derivative.width, Number(width));
    assert.match(derivative.path, new RegExp(`\\.${derivative.sha256.slice(0, 12)}\\.w${width}\\.webp$`));
    assert.ok(!urls.has(derivative.path), `duplicate derivative URL: ${derivative.path}`);
    urls.add(derivative.path);
  }
}

const modules = readdirSync(fileURLToPath(app)).filter((name) => /^tarot-assets-v1\.[a-f0-9]{12}\.js$/.test(name));
assert.equal(modules.length, 1, 'exactly one content-addressed runtime mapping is required');
const modulePath = new URL(modules[0], app);
const moduleBytes = readFileSync(modulePath);
assert.equal(modules[0], `tarot-assets-v1.${createHash('sha256').update(moduleBytes).digest('hex').slice(0, 12)}.js`);
const context = { window: {} };
vm.runInNewContext(moduleBytes.toString('utf8'), context, { filename: modules[0] });
const assets = context.window.NURA.TarotAssets;
assert.ok(Object.isFrozen(assets));
assert.equal(assets.forArcana(22).compact, manifest.cards.find((card) => card.arcana_id === 22).derivatives['480'].path);
assert.equal(assets.forArcana(0), null);
assert.equal(assets.forArcana(23), null);
assert.doesNotMatch(moduleBytes.toString('utf8'), /new Image|fetch\(|preload|document\./);

for (const page of ['index.html', 'chat.html', 'tarot.html']) {
  const html = readFileSync(new URL(page, app), 'utf8');
  assert.match(html, new RegExp(`<script src="${modules[0].replace('.', '\\.')}"`));
  assert.match(html, /TarotAssets\.forArcana/);
  assert.doesNotMatch(html, /['"]images\/[^'"]+\.png['"]/);
}

console.log('Tarot asset delivery contract is valid');
