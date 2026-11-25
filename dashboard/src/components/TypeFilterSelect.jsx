import { useMemo } from 'react'
import {
  Select, SelectTrigger, SelectValue, SelectContent, SelectItem,
} from '@/components/ui/select'
import { cn } from '@/lib/utils'

// The "all + distinct values" dropdown shared by the Entities and Relationships
// tabs. Derives its options from `items[field]` so callers don't repeat the memo.
// `label` names the dropdown for assistive technology: its trigger shows only
// the current value, so without it the control is announced as an unnamed button.
export default function TypeFilterSelect({ items, field, value, onChange, label, width = 'w-[140px]', capitalize = false }) {
  const options = useMemo(
    () => ['all', ...Array.from(new Set(items.map((i) => i[field]).filter(Boolean)))],
    [items, field],
  )
  return (
    <Select value={value} onValueChange={onChange}>
      <SelectTrigger aria-label={label} className={cn('h-7 text-xs', width)}><SelectValue /></SelectTrigger>
      <SelectContent>
        {options.map((o) => (
          <SelectItem key={o} value={o} className={cn('text-xs', capitalize && 'capitalize')}>{o}</SelectItem>
        ))}
      </SelectContent>
    </Select>
  )
}
