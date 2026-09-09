import { describe, it, expect, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

import SortHead from '@/components/SortHead';

// The first component test in this dashboard. Beyond covering SortHead, it is
// what proves the jsdom half of the harness works — the lib tests alongside it
// would pass with testing-library entirely absent.
//
// It is also the binding test for useSortable. src/lib/use-sortable.test.js
// proves the hook toggles and orders correctly; that says nothing about whether
// this header still calls it, or still reports the direction it is in. The
// sort state is invisible to a screen reader except through aria-sort, and
// invisible to everyone else except through which chevron renders — so both are
// asserted by value.

const sorter = (over = {}) => ({ key: null, dir: 'asc', sort: vi.fn(), ...over });

// SortHead renders a <th>, so it needs a table ancestor or the columnheader role
// will not resolve and every query below would silently look at nothing.
const renderHead = (props) =>
  render(
    <table>
      <thead>
        <tr>
          <SortHead {...props} />
        </tr>
      </thead>
    </table>,
  );

const header = () => screen.getByRole('columnheader');
const iconOf = (container) => container.querySelector('svg');

describe('SortHead — sort state is announced', () => {
  it('reports no sort when this column is not the active one', () => {
    renderHead({ sortKey: 'amount', sorter: sorter({ key: 'name' }), children: 'Amount' });

    expect(header()).toHaveAttribute('aria-sort', 'none');
  });

  it('reports ascending when active and ascending', () => {
    renderHead({ sortKey: 'amount', sorter: sorter({ key: 'amount', dir: 'asc' }), children: 'Amount' });

    expect(header()).toHaveAttribute('aria-sort', 'ascending');
  });

  it('reports descending when active and descending', () => {
    renderHead({ sortKey: 'amount', sorter: sorter({ key: 'amount', dir: 'desc' }), children: 'Amount' });

    expect(header()).toHaveAttribute('aria-sort', 'descending');
  });

  it('keeps the three announced states distinct', () => {
    // The failure worth catching is all three collapsing to one value, which no
    // single assertion above would reveal on its own.
    const read = (s) => {
      const { unmount } = renderHead({ sortKey: 'amount', sorter: s, children: 'Amount' });
      const value = header().getAttribute('aria-sort');
      unmount();
      return value;
    };

    const states = [
      read(sorter({ key: 'name' })),
      read(sorter({ key: 'amount', dir: 'asc' })),
      read(sorter({ key: 'amount', dir: 'desc' })),
    ];

    expect(new Set(states).size).toBe(3);
  });
});

describe('SortHead — the chevron matches the state', () => {
  // Three icons, three states. Lucide renders each as an <svg> with a distinct
  // class, so compare the rendered markup rather than trusting that an icon
  // exists — one is always present regardless of state.
  const iconClassFor = (s) => {
    const { container, unmount } = renderHead({ sortKey: 'amount', sorter: s, children: 'Amount' });
    const cls = iconOf(container).getAttribute('class');
    unmount();
    return cls;
  };

  it('shows a different chevron for inactive, ascending and descending', () => {
    const classes = [
      iconClassFor(sorter({ key: 'name' })),
      iconClassFor(sorter({ key: 'amount', dir: 'asc' })),
      iconClassFor(sorter({ key: 'amount', dir: 'desc' })),
    ];

    expect(new Set(classes).size).toBe(3);
  });

  it('dims the chevron only while the column is inactive', () => {
    expect(iconClassFor(sorter({ key: 'name' }))).toContain('opacity-40');
    expect(iconClassFor(sorter({ key: 'amount', dir: 'asc' }))).toContain('text-primary');
  });
});

describe('SortHead — clicking', () => {
  it('asks the sorter for this column, not for whichever is active', () => {
    // Passing the active key instead of sortKey would make every header toggle
    // the current column, so clicking a new one would appear to do nothing.
    const s = sorter({ key: 'name' });
    renderHead({ sortKey: 'amount', sorter: s, children: 'Amount' });

    header().click();

    expect(s.sort).toHaveBeenCalledWith('amount');
  });

  it('is reachable with a real pointer interaction', async () => {
    const s = sorter();
    renderHead({ sortKey: 'name', sorter: s, children: 'Municipality' });

    await userEvent.click(screen.getByText('Municipality'));

    expect(s.sort).toHaveBeenCalledWith('name');
  });

  it('does not call the sorter on render', () => {
    const s = sorter();
    renderHead({ sortKey: 'name', sorter: s, children: 'Municipality' });

    expect(s.sort).not.toHaveBeenCalled();
  });
});

describe('SortHead — layout props', () => {
  it('renders its label', () => {
    renderHead({ sortKey: 'name', sorter: sorter(), children: 'Municipality' });

    expect(screen.getByText('Municipality')).toBeInTheDocument();
  });

  it('reverses the icon and label for a right-aligned column', () => {
    // Amount columns are right-aligned, so the chevron has to sit on the left of
    // the label rather than after it.
    const { container } = renderHead({
      sortKey: 'amount',
      sorter: sorter(),
      align: 'right',
      children: 'Amount',
    });

    expect(container.querySelector('span').className).toContain('flex-row-reverse');
  });

  it('leaves a left-aligned column in normal order', () => {
    const { container } = renderHead({ sortKey: 'name', sorter: sorter(), children: 'Name' });

    expect(container.querySelector('span').className).not.toContain('flex-row-reverse');
  });

  it('applies an extra className alongside its own', () => {
    renderHead({ sortKey: 'name', sorter: sorter(), className: 'w-32', children: 'Name' });

    expect(header().className).toContain('w-32');
    expect(header().className).toContain('cursor-pointer');
  });
});


describe('SortHead — keyboard access', () => {
  it('supports Tab, Enter and Space without duplicate sort calls', async () => {
    const s = sorter();
    const user = userEvent.setup();
    renderHead({ sortKey: 'amount', sorter: s, children: 'Amount' });
    await user.tab();
    expect(screen.getByRole('button', { name: 'Amount' })).toHaveFocus();
    await user.keyboard('{Enter}');
    expect(s.sort).toHaveBeenCalledTimes(1);
    await user.keyboard(' ');
    expect(s.sort).toHaveBeenCalledTimes(2);
    expect(s.sort).toHaveBeenLastCalledWith('amount');
  });
});
