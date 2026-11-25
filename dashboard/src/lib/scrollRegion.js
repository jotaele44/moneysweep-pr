// Keyboard access for scrolling containers.
//
// A container that scrolls and holds nothing focusable cannot be scrolled from
// the keyboard unless it is itself a tab stop. Making every such container a
// permanent tab stop adds stops that do nothing, so `scrollRegion` adds the
// stop only while the container has content to scroll and nothing inside it
// can take focus (a table of links is scrolled by moving through the links).
//
// Usage: <div className="overflow-x-auto" {...scrollRegion("Airports table")}>
//
// The label names the container for assistive technology; pass none for an
// element that already has a role and a name of its own, such as <main>.
// An element that already has a ref object passes it as the second argument:
//   <div {...scrollRegion("Alerts", scrollRef)}>
//
// App-local on purpose. The shared design system has the same behaviour as
// FederationScrollRegion (@pr-federation/react, unreleased at the time of
// writing); replace this with it when the package pin moves.

const FOCUSABLE =
  'a[href], button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])';

export function needsTabStop(node) {
  const scrolls = node.scrollHeight > node.clientHeight + 1 || node.scrollWidth > node.clientWidth + 1;
  return scrolls && !node.querySelector(FOCUSABLE);
}

export function scrollRegion(label, existingRef) {
  let observers = [];
  const ref = (node) => {
    if (existingRef) existingRef.current = node;
    for (const observer of observers) observer.disconnect();
    observers = [];
    if (!node) return;
    const measure = () => {
      if (needsTabStop(node)) node.setAttribute("tabindex", "0");
      else node.removeAttribute("tabindex");
    };
    measure();
    if (typeof ResizeObserver === "function") {
      const resize = new ResizeObserver(measure);
      resize.observe(node);
      for (const child of node.children) resize.observe(child);
      observers.push(resize);
    }
    if (typeof MutationObserver === "function") {
      const mutation = new MutationObserver(measure);
      mutation.observe(node, { childList: true, subtree: true });
      observers.push(mutation);
    }
  };
  return label ? { ref, role: "group", "aria-label": label } : { ref };
}
