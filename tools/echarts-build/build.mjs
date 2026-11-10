import { writeFile } from 'node:fs/promises';
import { fileURLToPath } from 'node:url';
import { build } from 'esbuild';
import { minify } from 'terser';

const banner =
    '/*! ECharts 6.1.0 | Apache-2.0 | custom OpenAver Insights bundle */\n';
const output = fileURLToPath(
    new URL(
        '../../app/src/main/python/web/static/vendor/echarts/echarts.min.js',
        import.meta.url,
    ),
);

const result = await build({
    entryPoints: [fileURLToPath(new URL('src/insights-entry.js', import.meta.url))],
    bundle: true,
    minify: true,
    format: 'iife',
    target: 'chrome103',
    legalComments: 'inline',
    write: false,
});
const minified = await minify(result.outputFiles[0].text, {
    compress: { passes: 2 },
    mangle: true,
    format: { comments: /^!/ },
});
if (!minified.code) {
    throw new Error('Terser returned an empty ECharts bundle');
}
await writeFile(output, banner + minified.code, 'utf8');
