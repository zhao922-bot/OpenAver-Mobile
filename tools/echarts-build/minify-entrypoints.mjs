import { readFile } from 'node:fs/promises';
import path from 'node:path';
import { build } from 'esbuild';

const [inputRoot, manifestPath, outputRoot] = process.argv.slice(2);
if (!inputRoot || !manifestPath || !outputRoot) {
    console.error(
        'usage: node minify-entrypoints.mjs <input-root> <manifest> <output-root>',
    );
    process.exit(2);
}

const entries = JSON.parse(await readFile(manifestPath, 'utf8'));
if (!Array.isArray(entries) || entries.length === 0) {
    console.error('entry manifest must contain at least one path');
    process.exit(2);
}

const absoluteInputRoot = path.resolve(inputRoot);
await build({
    entryPoints: entries.map((entry) => path.resolve(absoluteInputRoot, entry)),
    outbase: absoluteInputRoot,
    outdir: path.resolve(outputRoot),
    bundle: false,
    minify: true,
    sourcemap: false,
    legalComments: 'none',
    platform: 'browser',
    target: 'chrome103',
    logLevel: 'silent',
    write: true,
});
