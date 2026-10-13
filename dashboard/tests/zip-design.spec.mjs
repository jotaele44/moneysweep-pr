import { test, expect } from 'playwright/test';

// Explicit failure fixtures exercise chrome without reading mutable sources.
// These tests certify UI behavior only; they do not certify backend data.
test.beforeEach(async ({ page }) => {
 await page.route('**/*', async route => {
  const url = new URL(route.request().url());
  if (url.pathname.includes('public-settings')) return route.fulfill({json: {requires_auth: false}});
  if (url.hostname === '127.0.0.1' && url.port === '5419' && !url.pathname.startsWith('/api/')) return route.continue();
  return route.abort('connectionrefused');
 });
});
for (const width of [390, 1440]) {
 test(`archive design renders and stays within ${width}px viewport`, async ({ page }) => {
  await page.setViewportSize({width, height: 900});
  const errors = [];
  page.on('pageerror', error => errors.push(error.message));
  await page.goto('/');
  await expect(page.locator('.zip-surface')).toBeVisible();
  await expect.poll(() => page.locator('#root').innerText()).not.toBe('');
  await page.evaluate(() => document.fonts.ready);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1)).toBe(true);
  expect(errors).toEqual([]);
  const css = await page.locator('.zip-surface').evaluate(el => getComputedStyle(el).getPropertyValue('--zip-background'));
  expect(css.trim()).not.toBe('');
 });
}
test('record tabs remain reachable at phone width', async ({page}) => {
 await page.setViewportSize({width:390,height:900}); await page.goto('/');
 await expect(page.locator('.zip-surface')).toBeVisible();
 const tabs=page.getByRole('tab'); const count=await tabs.count(); expect(count).toBeGreaterThan(2);
 for(let i=0;i<count;i++){ const tab=tabs.nth(i); await tab.click(); await expect(tab).toHaveAttribute('aria-selected','true'); }
});
