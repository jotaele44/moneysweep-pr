import { expect, test } from '@playwright/test'

test('visible tab reads real research registry and exposes provenance', async ({ page }) => {
  await page.goto('/')
  await page.getByRole('tab', { name: 'Research Lenses', exact: true }).click()
  await expect(page.getByRole('heading', { name: 'Research lenses' })).toBeVisible()
  await expect(page.getByRole('status').filter({ hasText: '24/24 lenses registered' })).toBeVisible()
  await expect(page.getByRole('row')).toHaveCount(25)
  await page.getByText('Registry provenance', { exact: true }).click()
  await expect(page.getByText('Baseline revision:')).toBeVisible()
  await page.getByText('Inspect family lineages', { exact: true }).click()
  await expect(page.getByText('Who is related to whom through which documented generational path?')).toBeVisible()
  await expect(page.getByRole('cell', { name: 'UNATTEMPTED', exact: true })).toHaveCount(72)
  await page.getByRole('button', { name: 'Refresh lenses', exact: true }).click()
  await expect(page.getByRole('status').filter({ hasText: 'Readiness: UNRESOLVED' })).toBeVisible()
})

test('source failure is visible and retry recovers', async ({ page }) => {
  let failed = true
  await page.route('**/investigation/lenses', async route => {
    if (failed) return route.fulfill({ status: 503, contentType: 'application/json', body: '{"detail":"registry unavailable"}' })
    return route.continue()
  })
  await page.goto('/?tab=research-lenses')
  await expect(page.getByRole('alert')).toContainText('Research lens registry unavailable')
  await expect(page.getByRole('table')).toHaveCount(0)
  failed = false
  await page.getByRole('button', { name: 'Refresh lenses', exact: true }).click()
  await expect(page.getByRole('table')).toBeVisible()
  await expect(page.getByRole('row')).toHaveCount(25)
})
