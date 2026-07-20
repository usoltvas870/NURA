import assert from 'node:assert/strict';
import { existsSync, readFileSync } from 'node:fs';
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

// Major Arcana PNGs are validated here, but intentionally remain outside the
// deterministic release asset map. This PR does not change service-worker behavior.
const approvedMajorArcana = [
  ['00-fool.png', '2ded1481dbcad8fdf41b1bcf5103151339d95a12d9424d213e005bf469e902ca', 1024, 1535, 8, 2],
  ['01-magician.png', 'b7c6451441a32a11f7f791e9293f6af75e69e76702eb6ad69221acc93736b80c', 1024, 1536, 8, 2],
  ['02-high-priestess.png', 'c3723a1f91aa247aa359d9745d1461c7fb66f3dfcb09b3590f2a91b79c835222', 1024, 1536, 8, 2],
  ['03-empress.png', '902fdbc280acb79f185f13ca034e7236bf97d997d90d2e4198d06a86003211fa', 1024, 1536, 8, 2],
  ['04-emperor.png', '99e37728979677265e4fe7f8343e108a8f8c422a61b27eac38abe209e633364d', 1024, 1536, 8, 2],
  ['05-hierophant.png', 'b9db6f2e4fde611be5597514a72aee8753b181cfb5c7c25b28ce98e9f2590880', 1024, 1536, 8, 2],
  ['06-lovers.png', '05e7d2c1494abe5198a345217ac8a576c3370d303644415f37248ce5af298298', 1024, 1535, 8, 2],
  ['07-chariot.png', '13d16d071d3ccfc66306b940547ce9fc59f1d8195ce74ac4b4ed899616336d85', 1024, 1535, 8, 2],
  ['08-justice.png', '8d7eddafcb8339accf837a69724d8c3b827895666ca1158fd1f17aea7e193f5a', 1024, 1536, 8, 2],
  ['09-hermit.png', '196bfa58b68390b7b3374418a5c4daa3811a47341e89d000f6f138a06a07ecba', 1024, 1536, 8, 2],
  ['10-wheel-of-fortune.png', '24c70cd429d6b4a1d561036cb33ee711d4369c52aeffe1822485c9d26732e679', 1024, 1535, 8, 2],
  ['11-strength.png', '38fe9a3392d0e9e340d835218250cf131d1acef90c6890be1a319a457a954fa9', 1024, 1536, 8, 2],
  ['12-hanged-man.png', '300542681a3eeea45c5a1afd507ae8d320b95363df39302064d0f9522980f542', 1024, 1535, 8, 2],
  ['13-death.png', '4adcd37ea80343a0019ce4296ef7ba0f60040a854e2690db12074a2b8c1eef84', 1024, 1535, 8, 2],
  ['14-temperance.png', '4398fe3ae4cf727f6983400eb2ffbaa05cb457dd905fa28bab1cbd54ff701794', 1024, 1536, 8, 2],
  ['15-devil.png', '6cc53901d70f80f1514a15071b744c478a262b7c5ace09eebfa43531e0b3419c', 1024, 1536, 8, 2],
  ['16-tower.png', 'b74d453588e875d225ae5dd25740fe3842d4816f9cccc5fa1ecb4fe5439495b7', 1024, 1536, 8, 2],
  ['17-star.png', 'd5eb0b5948c500fe4ccf3e6375ea41d8c99b91cd2e0c85a58bd2e26544298f66', 1024, 1535, 8, 2],
  ['18-moon.png', '915eb225c63c1ebca099cbaa96660c948e4445dd4e89f1cc34a990ed215c67d6', 1024, 1535, 8, 2],
  ['19-sun.png', '118c02ec72d2584d282fc4feddfdc5f9c2307f7a6620412c8c7849e7128eb821', 1024, 1535, 8, 2],
  ['20-judgement.png', 'eca83cec6505fa5640388a08b7378c49d58e71ba32cf26d19b3f2681cde9e99b', 1024, 1536, 8, 2],
  ['21-world.png', '2244c95c73214cfb0036085a4fd6d0ee8d10311cb3bcd7c435b977ce88ce6e9c', 1024, 1536, 8, 2],
];

assert.equal(approvedMajorArcana.length, 22);
assert.equal(new Set(approvedMajorArcana.map(([filename]) => filename)).size, 22);
assert.doesNotMatch(JSON.stringify(metadata.assets), /\/pwa\/app\/images\//);

for (const [filename, expectedHash, expectedWidth, expectedHeight, expectedBitDepth, expectedColorType] of approvedMajorArcana) {
  const imagePath = new URL(`./pwa/app/images/${filename}`, frontend);
  assert.ok(existsSync(imagePath), `${filename} is missing`);
  const buffer = readFileSync(imagePath);
  assert.ok(buffer.length >= 33, `${filename} is truncated before IHDR`);
  assert.deepEqual(buffer.subarray(0, 8), Buffer.from([137, 80, 78, 71, 13, 10, 26, 10]), `${filename} is not a PNG`);
  assert.equal(buffer.readUInt32BE(8), 13, `${filename} has an invalid IHDR length`);
  assert.equal(buffer.subarray(12, 16).toString('ascii'), 'IHDR', `${filename} is missing IHDR`);
  assert.equal(buffer.readUInt32BE(16), expectedWidth, `${filename} width changed`);
  assert.equal(buffer.readUInt32BE(20), expectedHeight, `${filename} height changed`);
  assert.equal(buffer[24], expectedBitDepth, `${filename} bit depth changed`);
  assert.equal(buffer[25], expectedColorType, `${filename} must remain RGB without alpha`);
  assert.equal(createHash('sha256').update(buffer).digest('hex'), expectedHash, `${filename} bytes changed`);
}
assert.equal(new Set(approvedMajorArcana.map(([, hash]) => hash)).size, 22, 'approved images must be distinct');

const expectedCardFiles = new Map([
  [1, '01-magician.png'], [2, '02-high-priestess.png'], [3, '03-empress.png'], [4, '04-emperor.png'],
  [5, '05-hierophant.png'], [6, '06-lovers.png'], [7, '07-chariot.png'], [8, '08-justice.png'],
  [9, '09-hermit.png'], [10, '10-wheel-of-fortune.png'], [11, '11-strength.png'], [12, '12-hanged-man.png'],
  [13, '13-death.png'], [14, '14-temperance.png'], [15, '15-devil.png'], [16, '16-tower.png'],
  [17, '17-star.png'], [18, '18-moon.png'], [19, '19-sun.png'], [20, '20-judgement.png'],
  [21, '21-world.png'], [22, '00-fool.png'],
]);

function parseCardMap(html, mapName, suffix = '') {
  const declaration = new RegExp(`\\b${mapName}\\s*=\\s*\\{([\\s\\S]*?)\\}`, 'm').exec(html);
  assert.ok(declaration, `${mapName} mapping is missing`);
  const entries = [...declaration[1].matchAll(/(?:^|,)\s*(\d+)\s*:\s*['"]([^'"]+)['"]/g)]
    .map(([, key, value]) => [Number(key), `${value}${suffix}`]);
  assert.equal(entries.length, 22, `${mapName} must have exactly 22 entries`);
  assert.equal(new Set(entries.map(([key]) => key)).size, 22, `${mapName} has duplicate keys`);
  return new Map(entries);
}

for (const [file, mapName, suffix] of [
  ['app/index.html', 'DAILY_CARD_FILES', ''],
  ['app/tarot.html', 'faces', '.png'],
  ['app/chat.html', 'CARD', ''],
]) {
  const map = parseCardMap(readFileSync(new URL(`./pwa/${file}`, frontend), 'utf8'), mapName, suffix);
  assert.equal(map.has(0), false, `${file} must not use key 0 for Fool`);
  assert.deepEqual([...map.keys()].sort((left, right) => left - right), [...expectedCardFiles.keys()]);
  for (const [number, filename] of expectedCardFiles) assert.equal(map.get(number), filename, `${file} maps ${number} incorrectly`);
}
