export type MoneySweepLayer = "RAW" | "NORMALIZED" | "CANONICAL";
export type CanonicalDisposition = "ADMITTED" | "EXCLUDED" | "UNRESOLVED";

export interface RawMoneyRecord {
  sourceManifestationId: string;
  sourceSha256: string;
  sourceRowId: string;
  rawName: string | null;
  uei: string | null;
  cage: string | null;
  amount: number | null;
}

export interface NormalizedMoneyRecord extends RawMoneyRecord {
  layer: "NORMALIZED";
  normalizedName: string | null;
}

export interface CanonicalMoneyRecord {
  layer: "CANONICAL";
  canonicalId: string;
  sourceManifestationId: string;
  sourceSha256: string;
  sourceRowId: string;
  amount: number | null;
  identityBasis: "UEI" | "CAGE" | "EXPLICIT_BINDING";
}

export interface CanonicalizationResult {
  admitted: CanonicalMoneyRecord[];
  excluded: RawMoneyRecord[];
  unresolved: RawMoneyRecord[];
  sourceCount: number;
}

export function normalizeMoneyRecord(raw: RawMoneyRecord): NormalizedMoneyRecord {
  return {
    ...raw,
    layer: "NORMALIZED",
    normalizedName: raw.rawName ? raw.rawName.trim().replace(/\s+/g, " ").toUpperCase() : null,
  };
}

export function canonicalizeMoneyRecords(
  rows: RawMoneyRecord[],
  explicitBindings: Record<string, string> = {}
): CanonicalizationResult {
  const admitted: CanonicalMoneyRecord[] = [];
  const excluded: RawMoneyRecord[] = [];
  const unresolved: RawMoneyRecord[] = [];
  const seenCanonicalIds = new Set<string>();

  for (const raw of rows) {
    if (!raw.sourceManifestationId || !/^[a-f0-9]{64}$/i.test(raw.sourceSha256) || !raw.sourceRowId) {
      excluded.push(raw);
      continue;
    }

    let canonicalId: string | null = null;
    let identityBasis: CanonicalMoneyRecord["identityBasis"] | null = null;
    if (raw.uei) {
      canonicalId = `uei:${raw.uei}`;
      identityBasis = "UEI";
    } else if (raw.cage) {
      canonicalId = `cage:${raw.cage}`;
      identityBasis = "CAGE";
    } else if (explicitBindings[raw.sourceRowId]) {
      canonicalId = explicitBindings[raw.sourceRowId];
      identityBasis = "EXPLICIT_BINDING";
    }

    if (!canonicalId || !identityBasis) {
      unresolved.push(raw);
      continue;
    }

    if (seenCanonicalIds.has(canonicalId)) {
      unresolved.push(raw);
      continue;
    }
    seenCanonicalIds.add(canonicalId);
    admitted.push({
      layer: "CANONICAL",
      canonicalId,
      sourceManifestationId: raw.sourceManifestationId,
      sourceSha256: raw.sourceSha256,
      sourceRowId: raw.sourceRowId,
      amount: raw.amount,
      identityBasis,
    });
  }

  return { admitted, excluded, unresolved, sourceCount: rows.length };
}

export function closesCanonicalArithmetic(result: CanonicalizationResult): boolean {
  return result.sourceCount === result.admitted.length + result.excluded.length + result.unresolved.length;
}
