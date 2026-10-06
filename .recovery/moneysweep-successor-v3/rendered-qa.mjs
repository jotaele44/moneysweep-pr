import { chromium } from "playwright";
import fs from "node:fs";

const baseUrl = "http://127.0.0.1:4173";
const cases = [
  { id: "desktop-1440", width: 1440, height: 1000 },
  { id: "iphone-393", width: 393, height: 852 },
  { id: "iphone-430", width: 430, height: 932 },
];

const browser = await chromium.launch({ headless: true });
const results = [];
let failed = false;

for (const item of cases) {
  const context = await browser.newContext({
    viewport: { width: item.width, height: item.height },
    deviceScaleFactor: 1,
  });
  const page = await context.newPage();
  const consoleErrors = [];
  const pageErrors = [];
  page.on("console", msg => {
    if (msg.type() === "error") consoleErrors.push(msg.text());
  });
  page.on("pageerror", err => pageErrors.push(String(err)));

  const response = await page.goto(baseUrl + "/", { waitUntil: "networkidle", timeout: 30000 });
  await page.waitForTimeout(500);

  const metrics = await page.evaluate(() => ({
    href: location.href,
    origin: location.origin,
    path: location.pathname,
    documentClientWidth: document.documentElement.clientWidth,
    documentScrollWidth: document.documentElement.scrollWidth,
    bodyClientWidth: document.body?.clientWidth ?? 0,
    bodyScrollWidth: document.body?.scrollWidth ?? 0,
    bodyTextLength: (document.body?.innerText ?? "").trim().length,
    title: document.title,
  }));

  const sameOrigin = metrics.origin === baseUrl;
  const status = response?.status() ?? null;
  const statusOk = status !== null && status >= 200 && status < 400;
  const horizontalOverflow =
    metrics.documentScrollWidth > metrics.documentClientWidth ||
    metrics.bodyScrollWidth > metrics.bodyClientWidth;
  const contentOk = metrics.bodyTextLength >= 40;
  const ok =
    statusOk &&
    sameOrigin &&
    contentOk &&
    !horizontalOverflow &&
    consoleErrors.length === 0 &&
    pageErrors.length === 0;

  await page.screenshot({ path: `rendered-${item.id}.png`, fullPage: true });
  results.push({
    ...item,
    status,
    sameOrigin,
    finalUrl: metrics.href,
    path: metrics.path,
    title: metrics.title,
    contentOk,
    horizontalOverflow,
    metrics,
    consoleErrors,
    pageErrors,
    ok,
  });
  if (!ok) failed = true;
  await context.close();
}

await browser.close();
fs.writeFileSync("rendered-qa.json", JSON.stringify(results, null, 2) + "\n");
console.log(JSON.stringify(results, null, 2));
if (failed) process.exit(1);
