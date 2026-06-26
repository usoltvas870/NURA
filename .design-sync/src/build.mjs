import * as esbuild from 'esbuild';
import { mkdir, copyFile, readdir } from 'fs/promises';
import { existsSync } from 'fs';
import { join, dirname } from 'path';
import { fileURLToPath } from 'url';

const __dir = dirname(fileURLToPath(import.meta.url));
const OUT = join(__dir, '..', 'ds-bundle');

await mkdir(OUT, { recursive: true });

await esbuild.build({
  entryPoints: [join(__dir, 'index.jsx')],
  bundle: true,
  format: 'iife',
  globalName: 'NuraPWA',
  outfile: join(OUT, '_ds_bundle.js'),
  banner: {
    js: '// @ds-bundle globalName="NuraPWA" react="18" version="1.0.0"',
  },
  define: {
    'process.env.NODE_ENV': '"production"',
  },
  minify: false,
  jsx: 'automatic',
});

console.log('Bundle built to', join(OUT, '_ds_bundle.js'));
