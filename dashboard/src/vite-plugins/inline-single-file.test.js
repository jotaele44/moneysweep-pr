import { describe, expect, it } from 'vitest'
import { inlineScript, inlineSingleFile, inlineStylesheet } from './inline-single-file.js'

const page = (head = '') =>
  `<!doctype html><html><head>${head}</head><body><div id="root"></div></body></html>`

const SCRIPT = '<script type="module" crossorigin src="./index-AbC123.js"></script>'
const LINK = '<link rel="stylesheet" crossorigin href="./index-XyZ789.css">'

describe('inlineScript', () => {
  it('replaces the matching <script src> with the code, keeping the other attributes', () => {
    const out = inlineScript(page(SCRIPT), 'index-AbC123.js', 'console.log(1)')
    expect(out).toContain('<script type="module" crossorigin>console.log(1)</script>')
    expect(out).not.toContain('src=')
  })

  it('matches when the src carries a directory prefix', () => {
    const html = page('<script type="module" src="/assets/index-AbC123.js"></script>')
    expect(inlineScript(html, 'index-AbC123.js', 'x()')).toContain('<script type="module">x()</script>')
  })

  it('escapes sequences the HTML parser would act on', () => {
    const out = inlineScript(page(SCRIPT), 'index-AbC123.js', 'a="</script><!--"')
    expect(out).toContain('a="\\x3C/script>\\x3C!--"')
    expect(out.match(/<\/script>/g)).toHaveLength(1)
  })

  it('replaces the preload marker with void 0', () => {
    const out = inlineScript(page(SCRIPT), 'index-AbC123.js', 'f("__VITE_PRELOAD__");g(__VITE_PRELOAD__)')
    expect(out).toContain('f(void 0);g(void 0)')
  })

  it('does not interpret $ patterns that minified code is full of', () => {
    const code = "var a=`$&`,b='$`',c=\"$'\",d='$1$$'"
    expect(inlineScript(page(SCRIPT), 'index-AbC123.js', code)).toContain(`>${code}</script>`)
  })

  it('does not treat the file name as a pattern', () => {
    const html = page('<script type="module" src="./index-aXc.js"></script>')
    expect(inlineScript(html, 'index-a.c.js', 'x()')).toBe(html)
  })

  it('leaves the page untouched when nothing references the file', () => {
    const html = page(SCRIPT)
    expect(inlineScript(html, 'other.js', 'x()')).toBe(html)
  })
})

describe('inlineStylesheet', () => {
  it('replaces the matching <link href> with an inline <style>', () => {
    const out = inlineStylesheet(page(LINK), 'index-XyZ789.css', 'body{margin:0}')
    expect(out).toContain('<style rel="stylesheet" crossorigin>body{margin:0}</style>')
    expect(out).not.toContain('href=')
  })

  it('drops the @charset rule, which is invalid mid-document', () => {
    const out = inlineStylesheet(page(LINK), 'index-XyZ789.css', '@charset "UTF-8";a{b:c}')
    expect(out).toContain('>a{b:c}</style>')
    expect(out).not.toContain('@charset')
  })

  it('does not interpret $ patterns in the stylesheet', () => {
    const css = 'a::after{content:"$&$1"}'
    expect(inlineStylesheet(page(LINK), 'index-XyZ789.css', css)).toContain(css)
  })
})

describe('inlineSingleFile plugin', () => {
  const run = (bundle) => {
    const plugin = inlineSingleFile()
    plugin.generateBundle({}, bundle)
    return bundle
  }
  const baseBundle = () => ({
    'index.html': { type: 'asset', fileName: 'index.html', source: page(`${SCRIPT}${LINK}`) },
    'index-AbC123.js': { type: 'chunk', fileName: 'index-AbC123.js', code: 'run()' },
    'index-XyZ789.css': { type: 'asset', fileName: 'index-XyZ789.css', source: 'a{b:c}' },
  })

  it('inlines the chunk and stylesheet into the page and removes them from the bundle', () => {
    const bundle = run(baseBundle())
    expect(Object.keys(bundle)).toEqual(['index.html'])
    expect(bundle['index.html'].source).toContain('<script type="module" crossorigin>run()</script>')
    expect(bundle['index.html'].source).toContain('>a{b:c}</style>')
  })

  it('keeps a file that no page references', () => {
    const bundle = baseBundle()
    bundle['orphan.js'] = { type: 'chunk', fileName: 'orphan.js', code: 'never()' }
    expect(Object.keys(run(bundle)).sort()).toEqual(['index.html', 'orphan.js'])
  })

  it('lets two pages share one chunk', () => {
    const bundle = baseBundle()
    bundle['second.html'] = { type: 'asset', fileName: 'second.html', source: page(SCRIPT) }
    const out = run(bundle)
    expect(out['second.html'].source).toContain('<script type="module" crossorigin>run()</script>')
    expect(out['index.html'].source).toContain('<script type="module" crossorigin>run()</script>')
  })

  it('configures a single relative, fully inlined build', () => {
    const { base, build } = inlineSingleFile().config()
    expect(base).toBe('./')
    expect(build.cssCodeSplit).toBe(false)
    expect(build.assetsDir).toBe('')
    expect(build.assetsInlineLimit()).toBe(true)
    expect(build.rolldownOptions.output.codeSplitting).toBe(false)
  })
})
