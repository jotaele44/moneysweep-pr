import { useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { ArrowUpDown, CalendarClock, CircleDot, Search } from "lucide-react";

const PHASE_RANK = { NOW: 0, NEXT: 1, QUEUED: 2, BLOCKED: 3 };

function PhaseBadge({ phase }) {
  const tone = {
    NOW: "border-primary/50 text-primary",
    NEXT: "border-emerald-500/50 text-emerald-500",
    QUEUED: "border-sky-500/50 text-sky-500",
    BLOCKED: "border-amber-500/50 text-amber-500",
  }[phase] || "border-border text-muted-foreground";
  return <span className={`inline-flex min-w-16 justify-center rounded-full border px-2 py-1 text-[10px] font-bold tracking-wide ${tone}`}>{phase}</span>;
}

export default function ProgramTimeline({ items, title = "Timeline", queueTitle = "Upcoming work" }) {
  const [query, setQuery] = useState("");
  const [filter, setFilter] = useState("ALL");
  const [sort, setSort] = useState("priority");

  const visible = useMemo(() => {
    const q = query.trim().toLowerCase();
    return [...items]
      .filter((item) => (filter === "ALL" || item.phase === filter) && (!q || [item.title, item.detail, item.category, item.phase].some((value) => value.toLowerCase().includes(q))))
      .sort((a, b) => sort === "priority" ? PHASE_RANK[a.phase] - PHASE_RANK[b.phase] || a.title.localeCompare(b.title) : a.title.localeCompare(b.title));
  }, [items, query, filter, sort]);

  const upcoming = items.filter((item) => ["NEXT", "QUEUED", "BLOCKED"].includes(item.phase)).slice(0, 5);

  return (
    <section className="grid gap-4 lg:grid-cols-[minmax(0,1.6fr)_minmax(18rem,.8fr)]" aria-label="Program timeline and upcoming work">
      <div className="overflow-hidden rounded-xl border border-border bg-card">
        <div className="flex items-center justify-between gap-4 border-b border-border p-4">
          <div><p className="font-mono text-[10px] font-bold tracking-[0.12em] text-muted-foreground">PROGRAM ACTIVITY</p><h2 className="mt-1 text-lg font-semibold">{title}</h2></div>
          <CalendarClock className="h-5 w-5 text-primary" />
        </div>
        <div className="grid gap-3 border-b border-border p-4">
          <div className="flex gap-2 overflow-x-auto pb-1">
            {["ALL", "NOW", "NEXT", "QUEUED", "BLOCKED"].map((value) => (
              <button key={value} type="button" onClick={() => setFilter(value)} className={`min-h-9 rounded-lg border px-3 font-mono text-[11px] font-semibold ${filter === value ? "border-primary/60 bg-primary/10 text-foreground" : "border-border text-muted-foreground"}`}>{value}</button>
            ))}
            <button type="button" onClick={() => setSort((value) => value === "priority" ? "name" : "priority")} className="ml-auto inline-flex min-h-9 items-center gap-2 rounded-lg border border-border px-3 font-mono text-[11px] font-semibold text-muted-foreground">
              <ArrowUpDown className="h-3.5 w-3.5" /> {sort === "priority" ? "Priority" : "Name"}
            </button>
          </div>
          <label className="flex items-center gap-2 rounded-lg border border-border bg-background px-3">
            <Search className="h-4 w-4 text-muted-foreground" />
            <input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Search activity, function, or state" className="min-h-11 w-full bg-transparent text-sm text-foreground outline-none placeholder:text-muted-foreground" />
          </label>
        </div>
        <div className="px-4 pb-2">
          {visible.length ? visible.map((item) => (
            <div key={item.id} className="grid grid-cols-[4.5rem_minmax(0,1fr)] gap-3 border-b border-border py-4 last:border-b-0">
              <PhaseBadge phase={item.phase} />
              <div>
                <strong className="text-sm text-foreground">{item.href ? <Link className="hover:text-primary" to={item.href}>{item.title}</Link> : item.title}</strong>
                <p className="mt-1 text-xs leading-5 text-muted-foreground">{item.detail}</p>
                <span className="mt-2 block font-mono text-[10px] font-semibold uppercase tracking-wide text-muted-foreground">{item.category}</span>
              </div>
            </div>
          )) : <p className="p-4 text-sm text-muted-foreground">No timeline items match this filter.</p>}
        </div>
      </div>

      <div className="overflow-hidden rounded-xl border border-border bg-card">
        <div className="flex items-center justify-between gap-4 border-b border-border p-4">
          <div><p className="font-mono text-[10px] font-bold tracking-[0.12em] text-muted-foreground">NEXT QUEUE</p><h2 className="mt-1 text-lg font-semibold">{queueTitle}</h2></div>
          <CircleDot className="h-5 w-5 text-primary" />
        </div>
        <div className="px-4 py-2">
          {upcoming.map((item) => (
            <div key={item.id} className="grid grid-cols-[4.5rem_minmax(0,1fr)] gap-3 border-b border-border py-4 last:border-b-0">
              <PhaseBadge phase={item.phase} />
              <div>
                <strong className="text-sm text-foreground">{item.href ? <Link className="hover:text-primary" to={item.href}>{item.title}</Link> : item.title}</strong>
                <p className="mt-1 text-xs leading-5 text-muted-foreground">{item.category} · {item.detail}</p>
              </div>
            </div>
          ))}
        </div>
      </div>
    </section>
  );
}
