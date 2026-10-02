import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { expect, test } from "@playwright/test";

function findRepositoryRoot(start) {
  let current = start;
  while (current !== path.dirname(current)) {
    if (fs.existsSync(path.join(current, ".federation", "gui-capabilities.json"))) {
      return current;
    }
    current = path.dirname(current);
  }
  throw new Error("Could not locate .federation/gui-capabilities.json");
}

const here = path.dirname(fileURLToPath(import.meta.url));
const repositoryRoot = findRepositoryRoot(here);
const manifest = JSON.parse(
  fs.readFileSync(
    path.join(repositoryRoot, ".federation", "gui-capabilities.json"),
    "utf8",
  ),
);

const routes = [
  ...new Set(
    manifest.capabilities
      .filter(
        (capability) =>
          capability.status === "active" && capability.classification !== "internal",
      )
      .flatMap((capability) => capability.frontend?.e2e_routes ?? []),
  ),
].sort();

test("manifest exposes at least one active GUI route", () => {
  expect(routes.length).toBeGreaterThan(0);
});

for (const route of routes) {
  test(`GUI route ${route} is rendered and discoverable`, async ({ page }) => {
    const runtimeFailures = [];
    page.on("pageerror", (error) => {
      runtimeFailures.push(`page error: ${error.message}`);
    });
    page.on("response", (response) => {
      if (response.status() >= 500) {
        runtimeFailures.push(`${response.status()} ${response.url()}`);
      }
    });

    if (route !== "/") {
      await page.goto("/", { waitUntil: "domcontentloaded" });
      const link = page.locator(`a[href="${route}"]`).first();
      await expect(
        link,
        `No clickable GUI navigation reaches ${route}`,
      ).toBeVisible();
      await link.click();
      await expect(page).toHaveURL(new RegExp(`${route.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")}/?$`));
    } else {
      await page.goto(route, { waitUntil: "domcontentloaded" });
    }

    await expect(page.locator("#root")).toBeVisible();
    if (route === "/") {
      await page.getByRole("tab", { name: "Campaign Finance" }).click();
      await expect(page.getByLabel("Campaign-finance view")).toBeVisible();
      await expect(page.getByText(/campaign-finance (?:contributions|datasets)/i).first()).toBeVisible();
    }
    await page.waitForTimeout(750);
    await expect(page.locator("body")).not.toContainText(
      /(?:something broke while rendering|page\s+not\s+found|route\s+not\s+found|404\s*—?\s*not\s+found)/i,
    );
    expect(runtimeFailures, runtimeFailures.join("\n")).toEqual([]);
  });
}
