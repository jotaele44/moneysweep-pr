import { TableHead } from '@/components/ui/table'
import { ChevronUp, ChevronDown, ChevronsUpDown } from 'lucide-react'
import { cn } from '@/lib/utils'

// A clickable column header wired to useSortable. `sortKey` names the row field;
// `sorter` is the object returned by useSortable().
export default function SortHead({ sortKey, sorter, className, align = 'left', children }) {
  const active = sorter.key === sortKey
  const Icon = !active ? ChevronsUpDown : sorter.dir === 'asc' ? ChevronUp : ChevronDown
  return (
    <TableHead
      className={cn('cursor-pointer select-none text-muted-foreground hover:text-foreground', className)}
      aria-sort={active ? (sorter.dir === 'asc' ? 'ascending' : 'descending') : 'none'}
      onClick={() => sorter.sort(sortKey)}
    >
      <button type="button" className="min-h-10 rounded-sm focus-visible:outline focus-visible:outline-2 focus-visible:outline-ring">
      <span className={cn('inline-flex items-center gap-1', align === 'right' && 'flex-row-reverse')}>
        {children}
        <Icon aria-hidden="true" className={cn('h-3 w-3 shrink-0', active ? 'text-primary' : 'opacity-40')} />
      </span>
      </button>
    </TableHead>
  )
}
