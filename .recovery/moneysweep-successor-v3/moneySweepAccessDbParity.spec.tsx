import fs from "node:fs";
import path from "node:path";

function walk(dir: string): string[] {
  const out: string[] = [];
  for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
    const full = path.join(dir, entry.name);
    if (entry.isDirectory()) out.push(...walk(full));
    else out.push(full.replaceAll("\\", "/"));
  }
  return out;
}

describe("MoneySweep recovered access/database parity", () => {
  it("freezes exactly five recovered API handlers", () => {
    const handlers = walk("endpoints").filter(file => /_(GET|POST|PUT|PATCH|DELETE)\.ts$/.test(file) && !file.endsWith(".schema.ts"));
    expect(handlers.sort()).toEqual([
      "endpoints/dashboard_GET.ts",
      "endpoints/evidence_GET.ts",
      "endpoints/mobile-plane_GET.ts",
      "endpoints/producer-status_GET.ts",
      "endpoints/release-audit_GET.ts",
    ]);
  });

  it("has no recovered mutation endpoint surface requiring write ACL", () => {
    const handlers = walk("endpoints").filter(file => /_(POST|PUT|PATCH|DELETE)\.ts$/.test(file) && !file.endsWith(".schema.ts"));
    expect(handlers).toEqual([]);
  });

  it("keeps write authorization explicitly not-applicable rather than silently passed", () => {
    const handlers = walk("endpoints").filter(file => /_(POST|PUT|PATCH|DELETE)\.ts$/.test(file) && !file.endsWith(".schema.ts"));
    const state = handlers.length === 0 ? "NOT_APPLICABLE_READ_ONLY_SURFACE" : "REQUIRES_AUTH_ACL_TESTS";
    expect(state).toBe("NOT_APPLICABLE_READ_ONLY_SURFACE");
  });

  it("preserves the exact five-table recovered DB type denominator", () => {
    const schema = fs.readFileSync("helpers/schema.tsx", "utf8");
    const expected = ["contracts", "edges", "entities", "municipalities", "sourceSnapshots"];
    for (const table of expected) expect(schema).toMatch(new RegExp("\\b" + table + "\\s*:"));
    const dbBody = schema.match(/export interface DB\s*\{([\s\S]*?)\n\}/)?.[1] ?? "";
    const declared = [...dbBody.matchAll(/^\s{2}([A-Za-z0-9_]+):/gm)].map(match => match[1]);
    expect(declared.sort()).toEqual([...expected].sort());
  });
});
