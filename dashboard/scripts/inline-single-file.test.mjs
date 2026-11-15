// @vitest-environment node
import fs from 'node:fs'
import os from 'node:os'
import path from 'node:path'
import { build } from 'vite'
import { afterAll, describe, expect, it } from 'vitest'
import { inlineScript, inlineSingleFile, inlineStyle } from './inline-single-file.mjs'

const PAGE = [
  '<!doctype html><html><head>',
  '<script type="module" crossorigin src="./index-abc123.js"></script>',
  '<link rel="stylesheet" crossorigin href="./index-abc123.css">',
  '</head><body><div id="root"></div></body></html>',
].join('')

describe('inlineScript', () => {
  it('replaces the tag that loads the chunk and keeps its other attributes', () => {
    const html = inlineScript(PAGE, 'index-abc123.js', '  console.log(1)  ')
    expect(html).toContain('<script type="module" crossorigin>console.log(1)</script>')
    expect(html).not.toContain('src="./index-abc123.js"')
  })

  it('matches the file name literally, not as a pattern', () => {
    expect(() => inlineScript(PAGE, 'index-abc123.js'.replace('.', 'x'), 'x')).toThrow(/no <script src>/)
  })

  it('does not expand replacement patterns in minified code', () => {
    const code = 'a="$&$1$$$`$\'";'
    expect(inlineScript(PAGE, 'index-abc123.js', code)).toContain(`<script type="module" crossorigin>${code}</script>`)
  })

  it('writes sequences that would end or confuse the script element as escapes', () => {
    const html = inlineScript(PAGE, 'index-abc123.js', 'a="</script>";b="</SCRIPT >";c="<!--";')
    expect(html).toContain('a="\\x3C/script>";b="\\x3C/SCRIPT >";c="\\x3C!--";')
    // Only the real closing tag is left: one script element, still well formed.
    expect(html.match(/<\/script/gi)).toHaveLength(1)
  })

  it('turns the Vite preload placeholder into void 0', () => {
    const html = inlineScript(PAGE, 'index-abc123.js', 'load(x,"__VITE_PRELOAD__");load(y,__VITE_PRELOAD__)')
    expect(html).toContain('load(x,void 0);load(y,void 0)')
  })

  it('fails when the page does not load the chunk', () => {
    expect(() => inlineScript(PAGE, 'other-999.js', 'x')).toThrow(/no <script src> for other-999\.js/)
  })
})

describe('inlineStyle', () => {
  it('replaces the stylesheet link and drops the charset rule', () => {
    const html = inlineStyle(PAGE, 'index-abc123.css', '@charset "UTF-8";\n.a{color:red}\n')
    expect(html).toContain('<style rel="stylesheet" crossorigin>.a{color:red}</style>')
    expect(html).not.toContain('href="./index-abc123.css"')
  })

  it('does not expand replacement patterns', () => {
    const css = '.a::after{content:"$&$1"}'
    expect(inlineStyle(PAGE, 'index-abc123.css', css)).toContain(`>${css}</style>`)
  })

  it('refuses CSS that would end the style element', () => {
    expect(() => inlineStyle(PAGE, 'index-abc123.css', '.a{content:"</style>"}')).toThrow(/cannot be inlined/)
  })

  it('fails when the page does not load the stylesheet', () => {
    expect(() => inlineStyle(PAGE, 'other-999.css', '.a{}')).toThrow(/no <link href> for other-999\.css/)
  })
})

describe('inlineSingleFile plugin', () => {
  it('inlines the chunk and the stylesheet into the page and removes them from the bundle', () => {
    const png = { type: 'asset', fileName: 'logo.png', source: new Uint8Array([1, 2, 3]) }
    const bundle = {
      'index.html': { type: 'asset', fileName: 'index.html', source: PAGE },
      'index-abc123.js': { type: 'chunk', fileName: 'index-abc123.js', code: 'run()' },
      'index-abc123.css': { type: 'asset', fileName: 'index-abc123.css', source: 'body{margin:0}' },
      'logo.png': png,
    }
    inlineSingleFile().generateBundle({}, bundle)
    expect(Object.keys(bundle)).toEqual(['index.html', 'logo.png'])
    expect(bundle['index.html'].source).toContain('>run()</script>')
    expect(bundle['index.html'].source).toContain('>body{margin:0}</style>')
    expect(bundle['logo.png']).toBe(png)
  })

  it('fails the build when an emitted chunk is not loaded by the page', () => {
    const bundle = {
      'index.html': { type: 'asset', fileName: 'index.html', source: PAGE },
      'index-abc123.js': { type: 'chunk', fileName: 'index-abc123.js', code: 'run()' },
      'index-abc123.css': { type: 'asset', fileName: 'index-abc123.css', source: 'body{}' },
      'lazy-777.js': { type: 'chunk', fileName: 'lazy-777.js', code: 'lazy()' },
    }
    expect(() => inlineSingleFile().generateBundle({}, bundle)).toThrow(/lazy-777\.js/)
  })
})

describe('vite build with the plugin', () => {
  const dirs = []
  afterAll(() => {
    for (const dir of dirs) fs.rmSync(dir, { recursive: true, force: true })
  })

  it('writes a single self-contained page, dynamic imports and assets included', async () => {
    const root = fs.mkdtempSync(path.join(os.tmpdir(), 'inline-single-file-'))
    dirs.push(root)
    const pixel = 'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg=='
    fs.writeFileSync(path.join(root, 'pixel.png'), Buffer.from(pixel, 'base64'))
    fs.writeFileSync(path.join(root, 'style.css'), 'body{background:url(./pixel.png)}\n.marker-css{color:red}\n')
    fs.writeFileSync(path.join(root, 'lazy.js'), 'export const lazy = "marker-lazy-chunk"\n')
    fs.writeFileSync(
      path.join(root, 'main.js'),
      [
        "import './style.css'",
        "import pixelUrl from './pixel.png'",
        "import('./lazy.js').then((m) => console.log(m.lazy, pixelUrl))",
        'console.log("marker-entry </script> <!--")',
      ].join('\n'),
    )
    fs.writeFileSync(
      path.join(root, 'index.html'),
      '<!doctype html><html><head><script type="module" src="/main.js"></script></head><body></body></html>',
    )

    const outDir = path.join(root, 'out')
    await build({
      root,
      configFile: false,
      logLevel: 'silent',
      plugins: [inlineSingleFile()],
      build: { outDir, emptyOutDir: true },
    })

    expect(fs.readdirSync(outDir)).toEqual(['index.html'])
    const html = fs.readFileSync(path.join(outDir, 'index.html'), 'utf8')
    expect(html).toContain('marker-entry')
    expect(html).toContain('marker-lazy-chunk')
    expect(html).toContain('.marker-css')
    expect(html).toContain('data:image/png;base64,')
    expect(html).not.toMatch(/<script[^>]* src=/)
    expect(html).not.toMatch(/<link[^>]* rel="stylesheet"/)
    // The literal </script> in the entry code was escaped, so the markup is still well formed.
    expect(html.match(/<\/script/gi)).toHaveLength(1)
  }, 60_000)
})
