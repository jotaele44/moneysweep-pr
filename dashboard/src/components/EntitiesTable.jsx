import { useMemo, useState } from 'react'
import { useEntities } from '@/lib/hooks'
import {
  Table, TableHeader, TableBody, TableRow, TableCell,
} from '@/components/ui/table'
import { Badge } from '@/components/ui/badge'
import { Input } from '@/components/ui/input'
import {
  Sheet, SheetContent, SheetHeader, SheetTitle, SheetDescription,
} from '@/components/ui/sheet'
import QueryBoundary from '@/components/QueryBoundary'
import DetailRow from '@/components/DetailRow'
import SortHead from '@/components/SortHead'
import TypeFilterSelect from '@/components/TypeFilterSelect'
import { entityTone } from '@/lib/cs-format'
import { useSortable } from '@/lib/use-sortable'
import { cn } from '@/lib/utils'

export default function EntitiesTable() {
  const query = useEntities()
  const entities = query.data ?? []
  const [type, setType] = useState(null)
  const [q, setQ] = useState('')
  const [open, setOpen] = useState(null)

  const filtered = useMemo(
    () => entities.filter((e) =>
      (type === null || e.entityType === type) &&
      (!q || (e.name || '').toLowerCase().includes(q.toLowerCase()))),
    [entities, type, q],
  )
  const { sorted: rows, sort, key, dir } = useSortable(filtered)
  const sorter = { sort, key, dir }
  const hasFilters = type !== null || q.trim().length > 0

  const resetFilters = () => {
    setType(null)
    setQ('')
  }

  return (
    <div className="flex h-full flex-col">
      <div className="ms-filter-bar flex items-center gap-2 p-2">
        <span className="shrink-0 text-xs text-muted-foreground">{rows.length}</span>
        <Input
          value={q}
          onChange={(e) => setQ(e.target.value)}
          placeholder="Search entities…"
          aria-label="Search entities"
          className="ms-filter-control h-7 flex-1 bg-background text-xs"
        />
        <TypeFilterSelect label="Entity type" items={entities} field="entityType" value={type} onChange={setType} width="w-[120px]" capitalize />
      </div>
      <div className="ms-scroll-region min-h-0 flex-1 overflow-auto">
        <QueryBoundary
          query={query}
          isEmpty={(d) => !d?.length}
          isFilteredEmpty={() => hasFilters && entities.length > 0 && rows.length === 0}
          emptyLabel="No entities"
          filteredEmptyLabel="No entities match these filters"
          onResetFilters={resetFilters}
        >
          <Table>
            <TableHeader className="sticky top-0 bg-card">
              <TableRow className="border-border hover:bg-transparent">
                <SortHead sortKey="name" sorter={sorter}>Name</SortHead>
                <SortHead sortKey="entityType" sorter={sorter}>Type</SortHead>
                <SortHead sortKey="jurisdiction" sorter={sorter}>Jurisdiction</SortHead>
                <SortHead sortKey="confidence" sorter={sorter} align="right" className="text-right">Conf.</SortHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {rows.map((e) => (
                <TableRow
                  key={e.entityId}
                  role="button"
                  tabIndex={0}
                  onClick={() => setOpen(e)}
                  onKeyDown={(ev) => { if (ev.key === 'Enter' || ev.key === ' ') { ev.preventDefault(); setOpen(e) } }}
                  className="cursor-pointer border-border hover:bg-muted/50 focus:bg-muted/50 focus:outline-none"
                >
                  <TableCell className="max-w-[220px] truncate text-xs text-foreground">{e.name}</TableCell>
                  <TableCell><Badge variant="outline" className={cn('text-[10px] capitalize', entityTone(e.entityType))}>{e.entityType}</Badge></TableCell>
                  <TableCell className="text-xs text-muted-foreground">{e.jurisdiction || '—'}</TableCell>
                  <TableCell className="text-right font-mono text-xs tabular-nums text-muted-foreground">{e.confidence ?? '—'}</TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </QueryBoundary>
      </div>

      <Sheet open={!!open} onOpenChange={(o) => !o && setOpen(null)}>
        <SheetContent className="w-full overflow-y-auto border-border bg-background text-foreground sm:max-w-md">
          {open && (
            <>
              <SheetHeader>
                <Badge variant="outline" className={cn('w-fit text-[10px] capitalize', entityTone(open.entityType))}>{open.entityType}</Badge>
                <SheetTitle className="text-left text-foreground">{open.name}</SheetTitle>
                <SheetDescription className="text-left text-muted-foreground">{open.entityId}</SheetDescription>
              </SheetHeader>
              <dl className="mt-4 space-y-2 text-sm">
                <DetailRow k="Type" v={open.entityType} />
                <DetailRow k="Jurisdiction" v={open.jurisdiction} />
                <DetailRow k="Parent entity" v={open.parentEntityId} />
                <DetailRow k="Confidence" v={open.confidence} />
                <DetailRow k="Notes" v={open.notes} />
              </dl>
            </>
          )}
        </SheetContent>
      </Sheet>
    </div>
  )
}
