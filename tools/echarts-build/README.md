# ECharts Insights Bundle

This directory builds the reduced ECharts bundle used only by `/insights`.

The bundle keeps the APIs and chart modules required by
`web/static/js/pages/insights/charts.js`:

- Bar, pie, and treemap charts
- Canvas renderer
- Tooltip, axis pointer, grid, graphic, and mark-line components
- Label layout and universal transitions

Build from this directory:

```powershell
npm ci
npm run build
```

ESBuild creates the module bundle, then Terser applies a second compression
pass. The output replaces `web/static/vendor/echarts/echarts.min.js`. ECharts
is pinned to the same upstream version recorded in
`web/static/vendor/manifest.json`.

The pinned ESBuild installation is also used by the release-only
`minifyReleaseWebAssets` Gradle task. That task minifies first-party JS and
CSS inside the generated `app.imy`; it excludes vendor files and leaves the
source tree unchanged. Original sources remain available for diagnostics.
