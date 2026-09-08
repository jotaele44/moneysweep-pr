import { expect, test } from '@playwright/test';

test('contract sorting is reachable by keyboard and announces both directions', async ({ page }) => {
  await page.goto('/');
  const header = page.getByRole('columnheader', { name: 'Amount', exact: true });
  const control = header.getByRole('button', { name: 'Amount', exact: true });
  await expect(control).toBeVisible();
  await control.focus();
  await page.keyboard.press('Enter');
  await expect(header).toHaveAttribute('aria-sort', 'ascending');
  await page.keyboard.press('Space');
  await expect(header).toHaveAttribute('aria-sort', 'descending');
});
