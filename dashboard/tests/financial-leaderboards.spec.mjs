import { expect, test } from "@playwright/test";

test("Top Entities tab is discoverable and wires ranking/history/signals APIs", async ({ page }) => {
  const categoriesResponse = page.waitForResponse(
    (response) => response.url().includes("/leaderboards/categories") && response.status() === 200,
  );
  const topResponse = page.waitForResponse(
    (response) => response.url().includes("/leaderboards/top") && response.status() === 200,
  );
  const historyResponse = page.waitForResponse(
    (response) => response.url().includes("/leaderboards/history") && response.status() === 200,
  );
  const signalsResponse = page.waitForResponse(
    (response) => response.url().includes("/leaderboards/signals") && response.status() === 200,
  );

  await page.goto("/", { waitUntil: "domcontentloaded" });
  await page.getByRole("tab", { name: "Top Entities" }).click();
  await expect(page).toHaveURL(/tab=leaderboards/);

  const categories = await (await categoriesResponse).json();
  expect(categories.rankingContractVersion).toBe("moneysweep.leaderboard/v1.1");
  expect(categories.categories).toEqual(expect.any(Array));
  expect(categories.categories.some((row) => row.id === "debt_issuance")).toBe(true);

  const ranking = await (await topResponse).json();
  expect(ranking).toMatchObject({
    categoryId: "contract_award",
    rankingVersion: "moneysweep.leaderboard/v1.1",
    tiesIncluded: true,
  });
  expect((await (await historyResponse).json()).snapshots).toEqual(expect.any(Array));
  expect((await (await signalsResponse).json()).certificationState).toBe("AUDIT_ONLY");
  await expect(page.getByRole("heading", { name: "Top financial entities" })).toBeVisible();
  await expect(page.getByText("Reconciliation")).toBeVisible();
  await expect(page.getByText("Frozen history / movers")).toBeVisible();
});

test("name-derived donor category fails closed instead of synthesizing identity", async ({ page }) => {
  await page.goto("/?tab=leaderboards", { waitUntil: "domcontentloaded" });
  await expect(page.getByRole("heading", { name: "Top financial entities" })).toBeVisible();

  const request = page.waitForRequest(
    (req) => req.url().includes("/leaderboards/top") && req.url().includes("category=campaign_donor_contribution"),
  );
  await page.getByLabel("Financial category").selectOption("campaign_donor_contribution");
  await request;

  await expect(page.getByText("No certifiable ranking rows for this category.", { exact: false })).toBeVisible();
  await expect(page.getByText("CANDIDATE_NOT_IDENTITY")).toBeVisible();
});

test("debt issuance remains a distinct financial measure", async ({ page }) => {
  const request = page.waitForResponse(
    (response) => response.url().includes("/leaderboards/top") && response.url().includes("category=debt_issuance") && response.status() === 200,
  );
  await page.goto("/?tab=leaderboards", { waitUntil: "domcontentloaded" });
  await page.getByLabel("Financial category").selectOption("debt_issuance");
  const body = await (await request).json();
  expect(body.metricType).toBe("DEBT_ISSUED_PAR");
  expect(body.rows.length).toBeGreaterThan(0);
});
