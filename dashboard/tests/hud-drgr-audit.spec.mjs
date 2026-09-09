import { expect, test } from '@playwright/test';

for (const width of [390, 1440]) {
test(`audit preserves provenance and supports explicit retry at ${width}px`, async ({ page }) => {
  await page.setViewportSize({ width, height: 900 });
  let fail = true;
  let runs = 0;
  const audit = { path: '/saved/receipt.json', sha256: 'a'.repeat(64), state: 'VALID_RECEIPT',
    receipt: { generated_at_utc: '2026-09-06T18:37:57Z', result_state: 'PARTIAL_UNRESOLVED',
      blocker: 'No authorized export is proven.', arithmetic: { classified: 1, total: 1, authorized_candidates: 0 },
      records: [{ path: '/source/fixture.csv', classification: 'PARTIAL_UNRESOLVED', sha256: 'b'.repeat(64) }] } };
  await page.route('**/materialization/**', route => {
    const path = new URL(route.request().url()).pathname;
    let value = {};
    if (path.endsWith('/hud-drgr/audits')) {
      if (route.request().method() === 'POST') { runs++; value = { state: 'SNAPSHOT_CREATED' }; }
      else if (fail) return route.fulfill({ status: 503, json: { detail: 'Audit unavailable' } });
      else value = { audits: [audit] };
    } else if (path.endsWith('/sources')) value = [];
    else if (path.endsWith('/credentials')) value = { keys: {}, allowedKeys: [] };
    return route.fulfill({ json: value });
  });
  await page.goto('/');
  await page.getByRole('tab', { name: 'Data Sources', exact: true }).click();
  const panel = page.getByRole('region', { name: 'HUD DRGR source audit' });
  await expect(panel.getByRole('alert')).toContainText('Audit unavailable');
  expect(runs).toBe(0);
  fail = false;
  await panel.getByRole('button', { name: 'Refresh saved audits' }).click();
  await panel.locator('summary').first().click();
  await expect(panel).toContainText('Authorization: UNPROVEN');
  await expect(panel).toContainText('Classified: 1 / 1');
  await expect(panel).toContainText('a'.repeat(64));
  expect(runs).toBe(0);
  await panel.getByRole('button', { name: 'Create new audit snapshot' }).click();
  await expect(panel.getByRole('button', { name: 'Create new audit snapshot' })).toBeEnabled();
  expect(runs).toBe(1);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1)).toBe(true);
});

}


test('saved HUD DRGR audits reach the shipped backend without mocking', async ({ page }) => {
  const responsePromise = page.waitForResponse(response =>
    response.url().endsWith('/materialization/hud-drgr/audits') && response.request().method() === 'GET');
  await page.goto('/');
  await page.getByRole('tab', { name: 'Data Sources', exact: true }).click();
  const response = await responsePromise;
  expect(response.status()).toBe(200);
  const data = await response.json();
  expect(Array.isArray(data.audits)).toBe(true);
  expect(data.source_refresh).toBe(false);
  const panel = page.getByRole('region', { name: 'HUD DRGR source audit' });
  await expect(panel.getByRole('button', { name: 'Refresh saved audits' })).toBeEnabled();
  await expect(panel.getByRole('alert')).toHaveCount(0);
});


test('malformed audit responses expose a recoverable error instead of crashing the dashboard', async ({ page }) => {
  await page.route('**/materialization/hud-drgr/audits', route => route.fulfill({ json: { audits: null } }));
  await page.goto('/');
  await page.getByRole('tab', { name: 'Data Sources', exact: true }).click();
  const panel = page.getByRole('region', { name: 'HUD DRGR source audit' });
  await expect(panel.getByRole('alert')).toContainText('Audit response is invalid');
  await expect(panel.getByRole('button', { name: 'Refresh saved audits' })).toBeEnabled();
});
