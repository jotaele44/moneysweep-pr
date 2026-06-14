import { useMemo, useState } from 'react'
import { useEntities } from '@/lib/hooks'
import {
  Table, TableHeader, TableBody, TableRow, TableHead, TableCell,
} from '@/components/ui/table'
import { Badge } from '@/components/ui/badge'
import { Input } from '@/components/ui/input'
import {
  Select, SelectTrigger, SelectValue, SelectContent, SelectItem,
} from '@/components/ui/select'
import { entityTone } from '@/lib/cs-format'
import { cn } from '@/lib/utils'

export default function EntitiesTable() {
  const { data: entities = [] } = useEntities()
  const [type, setType] = useState('all')
  const [q, setQ] = useState('')

  const types = useMemo(
    () => ['all', ...Array.from(new Set(entities.map((e) => e.entityType).filter(Boolean)))],
    [entities],
  )
  const rows = entities.filter((e) =>
    (type === 'all' || e.entityType === type) &&
    (!q || (e.name || '').toLowerCase().includes(q.toLowerCase())))

  return (
    <div className="flex flex-col h-full">
      <div className="flex items-center gap-2 p-2">
        <span className="text-xs text-slate-400 shrink-0">{rows.length}</span>
        <Input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Search entities…" className="h-7 flex-1 text-xs bg-slate-950 border-slate-800" />
        <Select value={type} onValueChange={setType}>
          <SelectTrigger className="h-7 w-[120px] text-xs"><SelectValue /></SelectTrigger>
          <SelectContent>
            {types.map((t) => <SelectItem key={t} value={t} className="text-xs capitalize">{t}</SelectItem>)}
          </SelectContent>
        </Select>
      </div>
      <div className="flex-1 overflow-auto">
        <Table>
          <TableHeader className="sticky top-0 bg-slate-900">
            <TableRow className="hover:bg-transparent border-slate-800">
              <TableHead className="text-slate-400">Name</TableHead>
              <TableHead className="text-slate-400">Type</TableHead>
              <TableHead className="text-slate-400">Jurisdiction</TableHead>
              <TableHead className="text-slate-400 text-right">Conf.</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {rows.map((e) => (
              <TableRow key={e.entityId} className="border-slate-800 hover:bg-slate-800/50">
                <TableCell className="text-xs text-slate-200 max-w-[220px] truncate">{e.name}</TableCell>
                <TableCell><Badge variant="outline" className={cn('text-[10px] capitalize', entityTone(e.entityType))}>{e.entityType}</Badge></TableCell>
                <TableCell className="text-xs text-slate-400">{e.jurisdiction || '—'}</TableCell>
                <TableCell className="text-xs text-slate-400 text-right tabular-nums">{e.confidence ?? '—'}</TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </div>
    </div>
  )
}
