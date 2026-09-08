import { useMemo } from 'react'
import {
  Select, SelectTrigger, SelectValue, SelectContent, SelectItem,
} from '@/components/ui/select'
import { cn } from '@/lib/utils'

// Null means no filter; encoded option values keep a source type named "all" distinct.
// The dropdown shared by the Entities and Relationships
// tabs. Derives its options from `items[field]` so callers don't repeat the memo.
export default function TypeFilterSelect({ items, field, value, onChange, width = 'w-[140px]', capitalize = false, label = 'Filter by type' }) {
  const options = useMemo(
    () => Array.from(new Set(items.map((i) => i[field]).filter(Boolean))),
    [items, field],
  )
  return (
    <Select value={value == null ? 'all' : `value:${value}`} onValueChange={(selected) => onChange(selected === 'all' ? null : selected.slice(6))}>
      <SelectTrigger aria-label={label} className={cn('h-7 text-xs', width)}><SelectValue /></SelectTrigger>
      <SelectContent>
        <SelectItem value="all" className="text-xs">All types</SelectItem>
        {options.map((o) => (
          <SelectItem key={o} value={`value:${o}`} className={cn('text-xs', capitalize && 'capitalize')}>{o}</SelectItem>
        ))}
      </SelectContent>
    </Select>
  )
}
