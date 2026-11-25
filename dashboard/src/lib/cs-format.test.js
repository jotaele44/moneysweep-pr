import { describe, it, expect } from 'vitest';

import {
  AMOUNTS_NOTE,
  amountsUnpopulated,
  edgeTone,
  entityTone,
  fmtMoney,
  statusRole,
} from '@/lib/cs-format';

// cs-format.js is small, but fmtMoney renders award amounts on a public-money
// oversight surface, and amountsUnpopulated decides whether the Tranche A
// caveat appears at all. Both fail quietly: a wrong amount still looks like an
// amount, and a suppressed caveat still looks like a complete dataset.

describe('fmtMoney', () => {
  it('formats a whole-dollar amount with no cents', () => {
    expect(fmtMoney(1234567)).toBe('$1,234,567');
  });

  it('renders an em dash for a missing amount', () => {
    // U+2014, not a hyphen — assert the exact character.
    expect(fmtMoney(null)).toBe('—');
    expect(fmtMoney(undefined)).toBe('—');
  });

  it('renders a genuine zero as $0, not as missing', () => {
    // The guard is `v == null`, deliberately not `!v`. A zero-dollar award is a
    // fact about a contract; showing it as an em dash would report it as data we
    // do not have.
    expect(fmtMoney(0)).toBe('$0');
  });

  it('rounds rather than truncating', () => {
    // maximumFractionDigits: 0. Truncation would understate every rounded-up
    // amount by a dollar, consistently and invisibly.
    expect(fmtMoney(1234.5)).toBe('$1,235');
    expect(fmtMoney(1234.4)).toBe('$1,234');
  });

  it('formats a negative amount rather than dropping the sign', () => {
    expect(fmtMoney(-500)).toBe('-$500');
  });

  it('renders a blank or non-finite value as missing, never as a real zero', () => {
    // This test used to pin `fmtMoney('') === '$0'` as a known sharp edge: `'' == null`
    // is false, so an empty CSV cell that arrived as '' rather than null was coerced
    // to 0 inside Intl and shown as a zero-dollar award. It was a tripwire for a
    // change in the loader's null handling. The loader already guarantees null for
    // blank values (`_num` in server/backend/main.py), so the case was unreachable.
    // The tripwire is retired on purpose: the formatter now refuses the case itself,
    // so a missing amount is never a zero amount whatever shape the absence takes.
    expect(fmtMoney('')).toBe('—');
    expect(fmtMoney('   ')).toBe('—');
    expect(fmtMoney(NaN)).toBe('—');
    expect(fmtMoney(Infinity)).toBe('—');
    expect(fmtMoney(-Infinity)).toBe('—');
    expect(fmtMoney('not a number')).toBe('—');
  });

  it('still formats a numeric string as an amount, and a genuine zero as $0', () => {
    expect(fmtMoney('1234.5')).toBe('$1,235');
    expect(fmtMoney('0')).toBe('$0');
    expect(fmtMoney(0)).toBe('$0');
  });
});

describe('amountsUnpopulated', () => {
  // Gates the Tranche A caveat in both StatsBar and MunicipalityAggregates, so
  // the two surfaces cannot disagree about whether amounts are trustworthy.

  it('is true when no contract carries an amount', () => {
    expect(amountsUnpopulated({ contractsWithAmount: 0 })).toBe(true);
  });

  it('is false as soon as one contract does', () => {
    expect(amountsUnpopulated({ contractsWithAmount: 1 })).toBe(false);
  });

  it('treats absent stats as unpopulated rather than assuming the best', () => {
    // `?? 0` — if stats have not loaded, or the field is missing, the caveat
    // shows. Failing the other way would present an incomplete dataset as
    // complete, which is the more damaging error on a spending surface.
    expect(amountsUnpopulated(undefined)).toBe(true);
    expect(amountsUnpopulated(null)).toBe(true);
    expect(amountsUnpopulated({})).toBe(true);
  });

  it('has a caveat string to show', () => {
    expect(AMOUNTS_NOTE).toBeTruthy();
  });
});

describe('tone lookups', () => {
  it.each([
    ['agency'],
    ['utility'],
    ['firm'],
    ['fund'],
    ['person'],
  ])('gives the %s entity type a tone of its own', (type) => {
    expect(entityTone(type)).not.toBe(entityTone('not-an-entity-type'));
  });

  it('keeps every entity tone distinct', () => {
    const tones = ['agency', 'utility', 'firm', 'fund', 'person'].map(entityTone);

    expect(new Set(tones).size).toBe(5);
  });

  it.each([
    ['active', 'success'],
    ['flagged', 'danger'],
    ['amended', 'warning'],
    ['executed', 'info'],
  ])('maps contract status %s to the federation role %s', (status, role) => {
    expect(statusRole(status)).toBe(role);
  });

  it('does not let flagged and active collapse into the same role', () => {
    // The one pairing that matters: `flagged` is the reason this surface exists.
    expect(statusRole('flagged')).not.toBe(statusRole('active'));
    expect(statusRole('flagged')).not.toBe(statusRole('unknown-status'));
  });

  it('falls back to neutral and slate for values it does not know', () => {
    expect(statusRole('not-a-status')).toBe('neutral');
    expect(statusRole(undefined)).toBe('neutral');
    expect(entityTone(undefined)).toContain('slate');
    expect(edgeTone(undefined)).toBe('text-slate-300');
  });

  it('keeps every edge type distinct', () => {
    const types = ['LOCATED_IN', 'AWARDED_TO', 'CONTROLS', 'AFFILIATED_WITH', 'SUBSIDIARY_OF'];

    expect(new Set(types.map(edgeTone)).size).toBe(types.length);
  });
});


describe('inherited keys do not leak through the lookup tables', () => {
  // Each helper indexes a plain object literal, and all three keys are
  // server-supplied. A bare `MAP[key] ?? fallback` resolves these five strings
  // through Object.prototype to something truthy, so the fallback never fires.
  //
  // Contained here — statusRole would render "[object Object]" into a
  // data-status attribute, and entityTone would lose its badge classes entirely,
  // because clsx finds no own enumerable keys on the prototype and emits nothing.
  // Not reachable from the frozen canonical_v1 vocabularies. Fixed because the
  // identical pattern was a genuine crash in aguayluz-pr, where the key came
  // from the URL rather than from data.
  const INHERITED = ['__proto__', 'constructor', 'toString', 'valueOf', 'hasOwnProperty'];

  it.each(INHERITED)('statusRole(%s) falls back to neutral', (key) => {
    expect(statusRole(key)).toBe('neutral');
  });

  it.each(INHERITED)('edgeTone(%s) falls back to the slate class', (key) => {
    expect(edgeTone(key)).toBe('text-slate-300');
  });

  it.each(INHERITED)('entityTone(%s) returns the slate badge string', (key) => {
    // Assert the type as well as the value: the bug returned an object here, and
    // an object stringifies into a className without complaint.
    expect(typeof entityTone(key)).toBe('string');
    expect(entityTone(key)).toBe(entityTone('not-an-entity-type'));
  });

  it.each(INHERITED)('the bare index this replaced does NOT fall back for %s', (key) => {
    // The premise, pinned. If this starts failing, JavaScript changed and the
    // lookup() indirection is no longer earning its place.
    const MAP = { real: 'value' };
    expect(MAP[key] ?? 'fallback').not.toBe('fallback');
  });
});
