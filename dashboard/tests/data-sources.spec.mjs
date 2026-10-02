import { expect, test } from "@playwright/test";

const STATUS = {
  registeredSources: 158,
  manualExportSources: 42,
  readiness: {
    total_sources: 158,
    automatable_total: 109,
    queued_excluded: { manual_export: 42 },
    source_count_provenance: {
      source_ids_sha256: "673659d9c53e8428e21052d95819ff35023e90142756686e73a9c9f1b326bbf2",
    },
  },
  production: { production_status: "NON_PRODUCTION_DIAGNOSTIC" },
  apiKeys: { FRED_API_KEY: false },
  secretsReturned: false,
};

const SOURCES = [
  {
    sourceId: "manual_fixture_source",
    family: "manual",
    authentication: "manual_export",
    requiredSecret: null,
    required: false,
    automatable: false,
    producerScript: "scripts.manual_fixture_source.py",
    expectedOutputs: ["data/staging/manual_fixture.parquet"],
    manualDropDir: "data/manual/manual_fixture_source",
    manualFilenamePattern: "*.csv",
  },
  {
    sourceId: "fema_pa_openfema_v2",
    family: "federal",
    authentication: "none",
    requiredSecret: null,
    required: true,
    automatable: true,
    producerScript: "scripts.download_fema_openfema.py",
    expectedOutputs: ["data/raw/fema_pa_openfema_v2.json"],
    manualDropDir: null,
    manualFilenamePattern: null,
  },
];

async function installDesktopDataPlaneStubs(page) {
  const calls = [];
  await page.route("**/materialization/**", async (route) => {
    const request = route.request();
    const url = new URL(request.url());
    const path = url.pathname;
    calls.push({ method: request.method(), path, postData: request.postData() });

    const json = (value, status = 200) => route.fulfill({
      status,
      contentType: "application/json",
      body: JSON.stringify(value),
    });

    if (request.method() === "GET" && path === "/materialization/status") return json(STATUS);
    if (request.method() === "GET" && path === "/materialization/sources") return json(SOURCES);
    if (request.method() === "GET" && path === "/materialization/credentials") {
      return json({ keys: { FRED_API_KEY: false }, allowedKeys: ["FRED_API_KEY"], secretsReturned: false });
    }
    if (request.method() === "POST" && path === "/materialization/api/run") {
      return json({ selected_count: 1, selected: ["fema_pa_openfema_v2"], dry_run: true, ran: [] });
    }
    if (request.method() === "POST" && path === "/materialization/offline/upload") {
      return json({
        source_id: "manual_fixture_source",
        raw_filename: "offline.csv",
        bytes: 12,
        sha256: "a".repeat(64),
        classification: "NEW_PAYLOAD",
        promotion_state: "STAGED_NOT_PROMOTED",
      });
    }
    if (request.method() === "PUT" && path === "/materialization/credentials/FRED_API_KEY") {
      return json({ keyName: "FRED_API_KEY", configured: true, secretReturned: false });
    }
    return json({ detail: `unexpected test route ${request.method()} ${path}` }, 500);
  });
  return calls;
}

test("Data Sources exposes terminal-free offline/API controls", async ({ page }) => {
  const calls = await installDesktopDataPlaneStubs(page);
  await page.goto("/?tab=data-sources", { waitUntil: "domcontentloaded" });

  await expect(page.getByRole("heading", { name: "Data-plane state" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Offline files" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "API materialization" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "API credentials" })).toBeVisible();
  await expect(page.getByText("NON_PRODUCTION_DIAGNOSTIC")).toBeVisible();

  await page.getByLabel("Choose offline source file").setInputFiles({
    name: "offline.csv",
    mimeType: "text/csv",
    buffer: Buffer.from("id,amount\n1,5\n"),
  });
  await page.getByRole("button", { name: "Stage + hash" }).click();
  await expect(page.getByText("STAGED_NOT_PROMOTED", { exact: true })).toBeVisible();

  await page.getByRole("button", { name: "Dry run" }).click();
  await expect(page.getByText('"dry_run": true')).toBeVisible();

  const dryRunCall = calls.find((call) => call.method === "POST" && call.path === "/materialization/api/run");
  expect(dryRunCall).toBeTruthy();
  expect(JSON.parse(dryRunCall.postData)).toEqual({
    source: "fema_pa_openfema_v2",
    family: null,
    dry_run: true,
  });

  await page.getByLabel("API credential value").fill("example-test-secret-never-echoed");
  await page.getByRole("button", { name: "Save to vault" }).click();
  await expect(page.getByText('"secretReturned": false')).toBeVisible();
  await expect(page.locator("body")).not.toContainText("example-test-secret-never-echoed");
});
