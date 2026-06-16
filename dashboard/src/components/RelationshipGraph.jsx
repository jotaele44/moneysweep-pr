import { useMemo, useState } from 'react'
import { useEdges } from '@/lib/hooks'
import {
  Select, SelectTrigger, SelectValue, SelectContent, SelectItem,
} from '@/components/ui/select'
import { edgeTone, fmtMoney } from '@/lib/cs-format'
import { ArrowRight } from 'lucide-react'
import { cn } from '@/lib/utils'

// Entity relationship graph rendered as a labelled adjacency list (64 edges).
// A list is more legible than a force layout at this scale and never overlaps.
export default function RelationshipGraph() {
  const { data: edges = [] } = useEdges()
  const [type, setType] = useState('all')

  const types = useMemo(
    () => ['all', ...Array.from(new Set(edges.map((e) => e.edgeType).filter(Boolean)))],
    [edges],
  )
  const rows = type === 'all' ? edges : edges.filter((e) => e.edgeType === type)

  return (
    <div className="flex flex-col h-full">
      <div className="flex items-center justify-between gap-2 p-2">
        <span className="text-xs text-slate-400">{rows.length} relationships</span>
        <Select value={type} onValueChange={setType}>
          <SelectTrigger className="h-7 w-[180px] text-xs"><SelectValue /></SelectTrigger>
          <SelectContent>
            {types.map((t) => <SelectItem key={t} value={t} className="text-xs">{t}</SelectItem>)}
          </SelectContent>
        </Select>
      </div>
      <div className="flex-1 overflow-auto p-2 space-y-1.5">
        {rows.map((e) => (
          <div key={e.edgeId} className="flex items-center gap-2 rounded-md border border-slate-800 bg-slate-900 px-2.5 py-2">
            <span className="text-xs text-slate-200 flex-1 truncate text-right">{e.sourceLabel}</span>
            <div className="flex flex-col items-center shrink-0 px-1">
              <span className={cn('text-[9px] uppercase tracking-wide', edgeTone(e.edgeType))}>{e.edgeType}</span>
              <ArrowRight className={cn('h-3 w-3', edgeTone(e.edgeType))} />
              {e.amount != null && <span className="text-[9px] text-slate-500">{fmtMoney(e.amount)}</span>}
            </div>
            <span className="text-xs text-slate-200 flex-1 truncate">{e.targetLabel}</span>
          </div>
        ))}
        {rows.length === 0 && <p className="text-center text-sm text-slate-500 py-8">No relationships</p>}
      </div>
    </div>
  )
}
