import {
  canonicalizeMoneyRecords,
  closesCanonicalArithmetic,
  normalizeMoneyRecord,
  type RawMoneyRecord,
} from "./moneySweepDataLayers";

const raw = (overrides: Partial<RawMoneyRecord> = {}): RawMoneyRecord => ({
  sourceManifestationId: "src-1",
  sourceSha256: "a".repeat(64),
  sourceRowId: "row-1",
  rawName: "  Acme   LLC  ",
  uei: null,
  cage: null,
  amount: 100,
  ...overrides,
});

describe("MoneySweep RAW/NORMALIZED/CANONICAL separation", () => {
  it("normalizes presentation fields without changing raw provenance", () => {
    const n = normalizeMoneyRecord(raw());
    expect(n.layer).toBe("NORMALIZED");
    expect(n.normalizedName).toBe("ACME LLC");
    expect(n.rawName).toBe("  Acme   LLC  ");
    expect(n.sourceRowId).toBe("row-1");
  });

  it("admits UEI-backed identity", () => {
    const r = canonicalizeMoneyRecords([raw({ uei: "ABC123" })]);
    expect(r.admitted[0].canonicalId).toBe("uei:ABC123");
    expect(r.admitted[0].identityBasis).toBe("UEI");
  });

  it("admits CAGE-backed identity", () => {
    const r = canonicalizeMoneyRecords([raw({ cage: "1A2B3" })]);
    expect(r.admitted[0].canonicalId).toBe("cage:1A2B3");
  });

  it("admits an explicit source-row binding", () => {
    const r = canonicalizeMoneyRecords([raw()], { "row-1": "entity:verified-1" });
    expect(r.admitted[0].identityBasis).toBe("EXPLICIT_BINDING");
  });

  it("never promotes normalized name alone", () => {
    const r = canonicalizeMoneyRecords([raw()]);
    expect(r.admitted.length).toBe(0);
    expect(r.unresolved.length).toBe(1);
  });

  it("never turns null amount into zero", () => {
    const r = canonicalizeMoneyRecords([raw({ uei: "U1", amount: null })]);
    expect(r.admitted[0].amount).toBeNull();
  });

  it("excludes rows with missing source manifestation identity", () => {
    const r = canonicalizeMoneyRecords([raw({ sourceManifestationId: "" })]);
    expect(r.excluded.length).toBe(1);
  });

  it("excludes rows with invalid source hashes", () => {
    const r = canonicalizeMoneyRecords([raw({ sourceSha256: "not-a-hash" })]);
    expect(r.excluded.length).toBe(1);
  });

  it("keeps duplicate canonical IDs unresolved instead of merging rows", () => {
    const r = canonicalizeMoneyRecords([
      raw({ sourceRowId: "1", uei: "U1" }),
      raw({ sourceRowId: "2", uei: "U1" }),
    ]);
    expect(r.admitted.length).toBe(1);
    expect(r.unresolved.length).toBe(1);
  });

  it("preserves source-to-output provenance on every admitted row", () => {
    const row = raw({ uei: "U1" });
    const r = canonicalizeMoneyRecords([row]);
    expect(r.admitted[0].sourceManifestationId).toBe(row.sourceManifestationId);
    expect(r.admitted[0].sourceSha256).toBe(row.sourceSha256);
    expect(r.admitted[0].sourceRowId).toBe(row.sourceRowId);
  });

  it("closes admitted + excluded + unresolved arithmetic", () => {
    const r = canonicalizeMoneyRecords([
      raw({ sourceRowId: "1", uei: "U1" }),
      raw({ sourceRowId: "2" }),
      raw({ sourceRowId: "3", sourceSha256: "bad" }),
    ]);
    expect(closesCanonicalArithmetic(r)).toBeTrue();
  });
});
