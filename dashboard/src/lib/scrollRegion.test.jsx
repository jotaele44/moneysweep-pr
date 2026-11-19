import { describe, it, expect } from 'vitest';
import { render, screen } from '@testing-library/react';

import { needsTabStop, scrollRegion } from '@/lib/scrollRegion';

// jsdom does no layout, so a box's scroll and client sizes are stubbed. What
// is under test is the decision and the attributes, not the browser's layout;
// the Chromium runtime pass covers the real thing.
function sized(node, { scrollWidth = 0, clientWidth = 0, scrollHeight = 0, clientHeight = 0 }) {
  for (const [name, value] of Object.entries({ scrollWidth, clientWidth, scrollHeight, clientHeight })) {
    Object.defineProperty(node, name, { configurable: true, value });
  }
  return node;
}

describe('needsTabStop', () => {
  it('is true for a box that overflows and holds nothing focusable', () => {
    const box = sized(document.createElement('div'), { scrollWidth: 800, clientWidth: 300 });
    box.innerHTML = '<table><tbody><tr><td>cell</td></tr></tbody></table>';

    expect(needsTabStop(box)).toBe(true);
  });

  it('is false when nothing overflows', () => {
    const box = sized(document.createElement('div'), { scrollWidth: 300, clientWidth: 300 });

    expect(needsTabStop(box)).toBe(false);
  });

  it('is false when the content can already take focus', () => {
    const box = sized(document.createElement('div'), { scrollHeight: 900, clientHeight: 200 });
    box.innerHTML = '<a href="/aircraft">Aircraft</a>';

    expect(needsTabStop(box)).toBe(false);
  });

  it('ignores content that is removed from the tab order', () => {
    const box = sized(document.createElement('div'), { scrollHeight: 900, clientHeight: 200 });
    box.innerHTML = '<button disabled>Off</button><span tabindex="-1">skip</span>';

    expect(needsTabStop(box)).toBe(true);
  });
});

describe('scrollRegion', () => {
  it('names the container as a group', () => {
    render(<div data-testid="box" {...scrollRegion('Airports table')} />);

    const box = screen.getByRole('group', { name: 'Airports table' });
    expect(box).toBe(screen.getByTestId('box'));
  });

  it('adds no role or name when no label is given', () => {
    render(<main data-testid="main" {...scrollRegion()} />);

    const main = screen.getByTestId('main');
    expect(main).not.toHaveAttribute('role');
    expect(main).not.toHaveAttribute('aria-label');
  });

  it('makes an overflowing box a tab stop and removes the stop when it no longer overflows', () => {
    const box = sized(document.createElement('div'), { scrollWidth: 800, clientWidth: 300 });
    const { ref } = scrollRegion('Wide table');

    ref(box);
    expect(box).toHaveAttribute('tabindex', '0');

    sized(box, { scrollWidth: 300, clientWidth: 300 });
    ref(box);
    expect(box).not.toHaveAttribute('tabindex');
  });

  it('leaves a box that does not overflow out of the tab order', () => {
    render(<div data-testid="box" {...scrollRegion('Short list')} />);

    expect(screen.getByTestId('box')).not.toHaveAttribute('tabindex');
  });
});
