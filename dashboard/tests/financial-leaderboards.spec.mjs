import { expect, test } from "@playwright/test";

test("Top Entities tab is discoverable and renders the real ranking API", async ({ page }) => {
  const categoriesResponse = page.waitForResponse(
    (response) => response.url().includes("/leaderboards/categories") && response.status() === 200,
  );
  const topResponse = page.waitForResponse(
    (response) => response.url().includes("/leaderboards/top") && response.status() === 200,
  );

  await page.goto("/", { waitUntil: "domcontentloaded" });
  await page.getByRole("tab", { name: "Top Entities" }).click();
  await expect(page).toHaveURL(/tab=leaderboards/);

  const categories = await (await categoriesResponse).json();
  expect(categories.categories).toEqual(expect.any(Array));
  expect(categories.categories.length).toBeGreaterThan(1);

  const ranking = await (await topResponse).json();
  expect(ranking).toMatchObject({
    categoryId: "contract_award",
    rankingVersion: "moneysweep.leaderboard/v1",
    tiesIncluded: true,
  });
  await expect(page.getByRole("heading", { name: "Top financial entities" })).toBeVisible();
  await expect(page.getByText("Reconciliation")).toBeVisible();
});

test("unsupported category fails closed instead of synthesizing a leaderboard", async ({ page }) => {
  await page.goto("/?tab=leaderboards", { waitUntil: "domcontentloaded" });
  await expect(page.getByRole("heading", { name: "Top financial entities" })).toBeVisible();

  const request = page.waitForRequest(
    (req) => req.url().includes("/leaderboards/top") && req.url().includes("category=campaign_contribution"),
  );
  await page.getByLabel("Financial category").selectOption("campaign_contribution");
  await request;

  await expect(page.getByText("No certifiable ranking rows for this category.", { exact: false })).toBeVisible();
  await expect(page.getByText("CANDIDATE_NOT_IDENTITY")).toBeVisible();
});
