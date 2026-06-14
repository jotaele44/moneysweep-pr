import { useState } from 'react'
import { useContracts } from '@/lib/hooks'
import {
  Table, TableHeader, TableBody, TableRow, TableHead, TableCell,
} from '@/components/ui/table'
import { Badge } from '@/components/ui/badge'
import { Input } from '@/components/ui/input'
import {
  Sheet, SheetContent, SheetHeader, SheetTitle, SheetDescription,
} from '@/components/ui/sheet'
import { fmtMoney, statusTone } from '@/lib/cs-format'
import { cn } from '@/lib/utils'

export default function ContractsTable() {
  const { data: contracts = [], isLoading } = useContracts()
  const [agency, setAgency] = useState('')
  const [open, setOpen] = useState(null)

  const rows = agency
    ? contracts.filter((c) => (c.awardingName || '').toLowerCase().includes(agency.toLowerCase()))
    : contracts

  return (
    <div className="flex flex-col h-full">
      <div className="flex items-center justify-between gap-2 p-2">
        <span className="text-xs text-slate-400">{rows.length} contracts</span>
        <Input
          value={agency} onChange={(e) => setAgency(e.target.value)}
          placeholder="Filter by awarding agency…"
          className="h-7 w-[240px] text-xs bg-slate-950 border-slate-800"
        />
      </div>
      <div className="flex-1 overflow-auto">
        <Table>
          <TableHeader className="sticky top-0 bg-slate-900">
            <TableRow className="hover:bg-transparent border-slate-800">
              <TableHead className="text-slate-400">Contract</TableHead>
              <TableHead className="text-slate-400">Awarding</TableHead>
              <TableHead className="text-slate-400">Contractor</TableHead>
              <TableHead className="text-slate-400">Municipio</TableHead>
              <TableHead className="text-slate-400 text-right">Amount</TableHead>
              <TableHead className="text-slate-400">Status</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {rows.map((c) => (
              <TableRow key={c.contractId} onClick={() => setOpen(c)} className="cursor-pointer border-slate-800 hover:bg-slate-800/50">
                <TableCell className="text-xs text-slate-200 max-w-[160px] truncate">{c.contractNumber || c.contractId}</TableCell>
                <TableCell className="text-xs text-slate-300 max-w-[160px] truncate">{c.awardingName || '—'}</TableCell>
                <TableCell className="text-xs text-slate-300 max-w-[160px] truncate">{c.contractorName || '—'}</TableCell>
                <TableCell className="text-xs text-slate-400">{c.municipality || '—'}</TableCell>
                <TableCell className="text-xs text-slate-200 text-right tabular-nums">{fmtMoney(c.awardAmount)}</TableCell>
                <TableCell><Badge variant="outline" className={cn('text-[10px]', statusTone(c.status))}>{c.status}</Badge></TableCell>
              </TableRow>
            ))}
            {!isLoading && rows.length === 0 && (
              <TableRow><TableCell colSpan={6} className="text-center text-sm text-slate-500 py-8">No contracts</TableCell></TableRow>
            )}
          </TableBody>
        </Table>
      </div>

      <Sheet open={!!open} onOpenChange={(o) => !o && setOpen(null)}>
        <SheetContent className="bg-slate-950 border-slate-800 text-slate-200 w-full sm:max-w-md overflow-y-auto">
          {open && (
            <>
              <SheetHeader>
                <Badge variant="outline" className={cn('w-fit text-[10px]', statusTone(open.status))}>{open.status}</Badge>
                <SheetTitle className="text-slate-100 text-left">{open.serviceType || open.contractNumber}</SheetTitle>
                <SheetDescription className="text-slate-400 text-left">{open.contractNumber} · {open.contractId}</SheetDescription>
              </SheetHeader>
              <dl className="mt-4 space-y-2 text-sm">
                <Row k="Awarding entity" v={open.awardingName} />
                <Row k="Contractor" v={open.contractorName} />
                <Row k="Municipality" v={open.municipality} />
                <Row k="Award amount" v={fmtMoney(open.awardAmount)} />
                <Row k="Period" v={`${open.startDate || '?'} → ${open.endDate || '?'}`} />
                <Row k="Fiscal year" v={open.fiscalYear} />
                <Row k="Confidence" v={open.confidence} />
              </dl>
            </>
          )}
        </SheetContent>
      </Sheet>
    </div>
  )
}

function Row({ k, v }) {
  return (
    <div className="flex justify-between gap-4 border-b border-slate-900 pb-1.5">
      <dt className="text-slate-500">{k}</dt>
      <dd className="text-slate-200 text-right">{v ?? '—'}</dd>
    </div>
  )
}
