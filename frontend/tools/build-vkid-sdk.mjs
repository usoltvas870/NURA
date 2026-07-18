import { copyFile, mkdir, readFile, writeFile } from 'node:fs/promises';
import { createHash } from 'node:crypto';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';

const frontend = dirname(dirname(fileURLToPath(import.meta.url)));
const packageRoot = join(frontend, 'node_modules', '@vkid', 'sdk');
const packageJson = JSON.parse(await readFile(join(packageRoot, 'package.json'), 'utf8'));
const source = join(packageRoot, 'dist-sdk', 'umd', 'index.js');
const vendorDir = join(frontend, 'assets', 'vendor');
const target = join(vendorDir, 'vkid-sdk.js');
const metadata = join(vendorDir, 'vkid-sdk.meta.json');

if (packageJson.version !== '2.6.6') {
  throw new Error(`Expected @vkid/sdk 2.6.6, received ${packageJson.version}`);
}

const sourceBytes = await readFile(source);
if (sourceBytes.length === 0) {
  throw new Error('Official VK ID UMD bundle is empty');
}

await mkdir(vendorDir, { recursive: true });
await copyFile(source, target);
await copyFile(join(packageRoot, 'LICENSE'), join(vendorDir, 'vkid-sdk.LICENSE'));
await writeFile(metadata, `${JSON.stringify({
  package: '@vkid/sdk',
  version: packageJson.version,
  source: 'node_modules/@vkid/sdk/dist-sdk/umd/index.js',
  sha256: createHash('sha256').update(sourceBytes).digest('hex'),
  license: 'vkid-sdk.LICENSE'
}, null, 2)}\n`);

console.log(`Built ${target}`);
