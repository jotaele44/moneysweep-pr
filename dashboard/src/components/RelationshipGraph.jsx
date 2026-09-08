
import { useMemo, useState } from 'react'
import { useEdges } from '@/lib/hooks'
import QueryBoundary from '@/components/QueryBoundary'
import TypeFilterSelect from '@/components/TypeFilterSelect'
import { edgeTone, fmtMoney } from '@/lib/cs-format'
import { ArrowRight } from 'lucide-react'
import { cn } from '@/lib/utils'

export default function RelationshipGraph() {
  const query = useEdges()
  const edges = query.data ?? []
  const [type, setType] = useState(null)

  const rows = useMemo(
    () => (type === null ? edges : edges.filter((e) => e.edgeType === type)),
    [edges, type],
  )
  const hasFilter = type !== null

  return (
    <div className="flex h-full flex-col">
      <div className="ms-filter-bar flex items-center justify-between gap-2 p-2">
        <span className="text-xs text-muted-foreground">{rows.length} relationships</span>
        <TypeFilterSelect label="Relationship type" items={edges} field="edgeType" value={type} onChange={setType} width="w-[180px]" />
      </div>
      <div className="ms-scroll-region min-h-0 flex-1 overflow-auto">
        <QueryBoundary
          query={query}
          isEmpty={(d) => !d?.length}
          isFilteredEmpty={() => hasFilter && edges.length > 0 && rows.length === 0}
          emptyLabel="No relationships"
          filteredEmptyLabel="No relationships match this type"
          onResetFilters={() => setType(null)}
        >
          <div className="space-y-1.5 p-2">
            {rows.map((e) => (
              <div key={e.edgeId} className="flex items-center gap-2 rounded-md border border-border bg-card px-2.5 py-2">
                <span className="flex-1 truncate text-right text-xs text-foreground">{e.sourceLabel}</span>
                <div className="flex shrink-0 flex-col items-center px-1">
                  <span className={cn('text-[9px] uppercase tracking-wide', edgeTone(e.edgeType))}>{e.edgeType}</span>
                  <ArrowRight className={cn('h-3 w-3', edgeTone(e.edgeType))} />
                  {e.amount != null && <span className="text-[9px] text-muted-foreground">{fmtMoney(e.amount)}</span>}
                </div>
                <span className="flex-1 truncate text-xs text-foreground">{e.targetLabel}</span>
              </div>
            ))}
          </div>
        </QueryBoundary>
      </div>
    </div>
  )
}
