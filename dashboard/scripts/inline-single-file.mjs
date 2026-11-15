// Inlines the emitted JS and CSS into index.html, so `VITE_OFFLINE=1 vite build`
// (`npm run build:export`) writes one self-contained page that opens over file://.
//
// This replaces vite-plugin-singlefile. Its micromatch -> braces dependency (GHSA-vfj7-8cjw-p6xm,
// no patched release) only served an include-pattern option this repo never used, and its latest
// release still carries it. Only what the export needs is implemented here, and a chunk or
// stylesheet the page does not reference fails the build instead of shipping a dangling reference.
//
// Single-page only: every emitted chunk and stylesheet must be loaded by every HTML page.

const escapeRegExp = (text) => text.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')

/**
 * Replace the `<script src="…fileName">` that loads a chunk with the chunk's code. The callback form
 * of `replace` is deliberate: minified code is full of `$&`, `$1` and `` $` ``, which a replacement
 * string would expand.
 */
export function inlineScript(html, fileName, code) {
  const tag = new RegExp(`<script([^>]*?) src="(?:[^"]*?/)?${escapeRegExp(fileName)}"([^>]*)></script>`)
  if (!tag.test(html)) throw new Error(`inline-single-file: the page has no <script src> for ${fileName}`)
  const safe = code
    // Vite leaves this placeholder where a dynamic import's preload list would go.
    .replace(/"?__VITE_PRELOAD__"?/g, 'void 0')
    // `</script` would end the element and `<!--` opens an HTML comment inside script data. Writing
    // the `<` as \x3C is valid in strings, template literals, regex literals and comments.
    .replace(/<(\/script|!--)/gi, '\\x3C$1')
  return html.replace(tag, (_match, before, after) => `<script${before}${after}>${safe.trim()}</script>`)
}

/** Replace the `<link href="…fileName">` that loads a stylesheet with a `<style>` element. */
export function inlineStyle(html, fileName, css) {
  const tag = new RegExp(`<link([^>]*?) href="(?:[^"]*?/)?${escapeRegExp(fileName)}"([^>]*)>`)
  if (!tag.test(html)) throw new Error(`inline-single-file: the page has no <link href> for ${fileName}`)
  if (/<\/style/i.test(css)) throw new Error(`inline-single-file: ${fileName} contains "</style" and cannot be inlined`)
  const body = css.replace('@charset "UTF-8";', '').trim()
  return html.replace(tag, (_match, before, after) => `<style${before}${after}>${body}</style>`)
}

export function inlineSingleFile() {
  return {
    name: 'moneysweep:inline-single-file',
    apply: 'build',
    enforce: 'post',
    config: () => ({
      // Relative URLs, so the page works from any folder and over file://.
      base: './',
      build: {
        // Inline every asset (the bundled fonts included) as a data URI, however large.
        assetsInlineLimit: () => true,
        chunkSizeWarningLimit: 100_000_000,
        // One stylesheet and one script, which are what gets inlined.
        cssCodeSplit: false,
        assetsDir: '',
        rolldownOptions: { output: { codeSplitting: false } },
      },
    }),
    generateBundle(_options, bundle) {
      const files = Object.values(bundle)
      const pages = files.filter((file) => file.type === 'asset' && /\.html?$/.test(file.fileName))
      const scripts = files.filter((file) => file.type === 'chunk')
      const styles = files.filter((file) => file.type === 'asset' && file.fileName.endsWith('.css'))
      for (const page of pages) {
        let html = String(page.source)
        for (const chunk of scripts) html = inlineScript(html, chunk.fileName, chunk.code)
        for (const sheet of styles) html = inlineStyle(html, sheet.fileName, String(sheet.source))
        page.source = html
      }
      for (const file of [...scripts, ...styles]) delete bundle[file.fileName]
    },
  }
}
