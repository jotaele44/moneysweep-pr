// Folds every emitted script and stylesheet into index.html so the VITE_OFFLINE export
// (`npm run build:export`) is one self-contained file that opens from file://.
//
// This replaces vite-plugin-singlefile. That package's only dependency, micromatch, pulls in
// `braces`, which has an unpatched advisory (GHSA-vfj7-8cjw-p6xm) and fails `npm audit`. micromatch
// only serves the plugin's optional `inlinePattern` filter, which this repo never used; the default
// behaviour reproduced here (inline everything) needs no glob matching.

const escapeRegExp = (text) => text.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')

// Returns `html` with the <script src> that points at `fileName` replaced by an inline script.
export function inlineScript(html, fileName, code) {
  const tag = new RegExp(`<script([^>]*?) src="(?:[^"]*?/)?${escapeRegExp(fileName)}"([^>]*)></script>`)
  // The code now lives inside a <script> element, so neutralise what the HTML parser would act on.
  // Vite's preload marker only matters for lazy chunks, and there are none in a single file.
  const safe = code.replace(/"?__VITE_PRELOAD__"?/g, 'void 0').replace(/<(\/script>|!--)/g, '\\x3C$1')
  // A replacer function, not a replacement string: minified code is full of `$&` and `$'`.
  return html.replace(tag, (_match, before, after) => `<script${before}${after}>${safe.trim()}</script>`)
}

// Returns `html` with the <link href> that points at `fileName` replaced by an inline <style>.
export function inlineStylesheet(html, fileName, css) {
  const tag = new RegExp(`<link([^>]*?) href="(?:[^"]*?/)?${escapeRegExp(fileName)}"([^>]*)>`)
  const safe = css.replace('@charset "UTF-8";', '')
  return html.replace(tag, (_match, before, after) => `<style${before}${after}>${safe.trim()}</style>`)
}

export function inlineSingleFile() {
  return {
    name: 'moneysweep:inline-single-file',
    enforce: 'post',
    // Everything must end up in one chunk and one stylesheet, with nothing left to fetch.
    config: () => ({
      // Relative, so public/ files that are copied next to index.html still resolve over file://.
      base: './',
      build: {
        assetsDir: '',
        assetsInlineLimit: () => true,
        chunkSizeWarningLimit: 100000000,
        cssCodeSplit: false,
        rolldownOptions: { output: { codeSplitting: false } },
      },
    }),
    generateBundle(_options, bundle) {
      const names = Object.keys(bundle)
      const inlined = new Set()
      for (const pageName of names.filter((name) => /\.html?$/.test(name))) {
        const page = bundle[pageName]
        let html = page.source
        for (const name of names) {
          const asset = bundle[name]
          let next = html
          if (/\.[mc]?js$/.test(name) && asset.code != null) next = inlineScript(html, asset.fileName, asset.code)
          else if (/\.css$/.test(name)) next = inlineStylesheet(html, asset.fileName, asset.source)
          if (next !== html) {
            html = next
            inlined.add(name)
          }
        }
        page.source = html
      }
      // Drop only what was actually folded in (after every page has had its turn); an unreferenced
      // file stays in the bundle instead of vanishing.
      for (const name of inlined) delete bundle[name]
    },
  }
}
