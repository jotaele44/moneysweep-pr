import { expect, test } from '@playwright/test';

test('an unknown route offers working home navigation', async ({ page }) => {
  await page.goto('/missing-page-for-recovery-check');
  await expect(page.getByRole('heading', { name: 'Page Not Found' })).toBeVisible();
  await page.getByRole('button', { name: 'Go Home' }).click();
  await expect(page).toHaveURL(/\/$/);
  await expect(page.getByRole('columnheader', { name: 'Amount', exact: true })).toBeVisible();
});

test('entity filtering distinguishes a source type called all from reset', async ({ page }) => {
  let requests = 0;
  await page.route('**/entities', async (route) => {
    requests += 1;
    await route.fulfill({ json: [
      { entityId: 'all-type', name: 'Literal All Entity', entityType: 'all' },
      { entityId: 'vendor-a', name: 'Vendor Alpha', entityType: 'vendor' },
      { entityId: 'vendor-b', name: 'Vendor Beta', entityType: 'vendor' },
    ] });
  });
  await page.goto('/');
  await page.getByRole('tab', { name: 'Entities', exact: true }).click();
  await expect(page.getByText('Vendor Alpha', { exact: true })).toBeVisible();
  const control = page.getByRole('combobox');
  await control.click();
  await page.getByRole('option', { name: /^all$/i }).click();
  await expect(page.getByText('Literal All Entity', { exact: true })).toBeVisible();
  await expect(page.getByText('Vendor Alpha', { exact: true })).toHaveCount(0);
  await expect(control).toHaveAccessibleName('Entity type');
  await control.click();
  await page.getByRole('option', { name: /^vendor$/i }).click();
  await expect(page.getByText('Literal All Entity', { exact: true })).toHaveCount(0);
  await expect(page.getByText('Vendor Beta', { exact: true })).toBeVisible();
  await control.click();
  await page.getByRole('option', { name: 'All types', exact: true }).click();
  await expect(page.getByText('Literal All Entity', { exact: true })).toBeVisible();
  expect(requests).toBe(1);
});

test('relationship filtering preserves the literal all category', async ({ page }) => {
  await page.route('**/edges', (route) => route.fulfill({ json: [
    { edgeId: 'one', sourceLabel: 'Source All', targetLabel: 'Target All', edgeType: 'all' },
    { edgeId: 'two', sourceLabel: 'Source Other', targetLabel: 'Target Other', edgeType: 'other' },
  ] }));
  await page.goto('/');
  await page.getByRole('tab', { name: 'Relationships', exact: true }).click();
  await expect(page.getByText('2 relationships', { exact: true })).toBeVisible();
  const control = page.getByRole('combobox');
  await control.click();
  await page.getByRole('option', { name: /^all$/i }).click();
  await expect(page.getByText('1 relationships', { exact: true })).toBeVisible();
  await expect(page.getByText('Source Other', { exact: true })).toHaveCount(0);
  await expect(control).toHaveAccessibleName('Relationship type');
  await control.click();
  await page.getByRole('option', { name: 'All types', exact: true }).click();
  await expect(page.getByText('2 relationships', { exact: true })).toBeVisible();
});

test('render recovery discards a bad cached response and fetches fresh data', async ({ page }) => {
  let requests = 0;
  await page.route('**/entities', async (route) => {
    requests += 1;
    await route.fulfill({ json: [{
      entityId: 'recovery-row', entityType: 'vendor',
      name: requests === 1 ? { invalid: 'render fault' } : 'Recovered Entity',
    }] });
  });
  await page.goto('/');
  await page.getByRole('tab', { name: 'Entities', exact: true }).click();
  await expect(page.getByRole('heading', { name: 'Something went wrong' })).toBeVisible();
  await Promise.all([
    page.waitForEvent('load'),
    page.getByRole('button', { name: 'Try again' }).click(),
  ]);
  await expect(page.getByRole('tab', { name: 'Entities', exact: true })).toHaveAttribute('aria-selected', 'true');
  await expect(page.getByText('Recovered Entity', { exact: true })).toBeVisible();
  expect(requests).toBeGreaterThan(1);
});
