import { useState } from 'react'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { useApiKeys } from '@/lib/hooks'
import { setApiKey } from '@/lib/api'
import {
  Table, TableHeader, TableBody, TableRow, TableCell, TableHead,
} from '@/components/ui/table'
import { Badge } from '@/components/ui/badge'
import { Input } from '@/components/ui/input'
import { Button } from '@/components/ui/button'
import QueryBoundary from '@/components/QueryBoundary'
import { scrollRegion } from '@/lib/scrollRegion'

function ApiKeyRow({ keyInfo }) {
  const queryClient = useQueryClient()
  const [value, setValue] = useState('')
  const mutation = useMutation({
    mutationFn: () => setApiKey(keyInfo.name, value),
    onSuccess: () => {
      setValue('')
      queryClient.invalidateQueries({ queryKey: ['api-keys'] })
    },
  })

  return (
    <TableRow className="border-border" data-testid={`api-key-row-${keyInfo.name}`}>
      <TableCell className="whitespace-nowrap font-mono text-xs text-foreground">{keyInfo.name}</TableCell>
      <TableCell className="max-w-[280px] text-xs text-muted-foreground">{keyInfo.description}</TableCell>
      <TableCell>
        <Badge variant="outline" className="text-[10px]">{keyInfo.required ? 'Required' : 'Optional'}</Badge>
      </TableCell>
      <TableCell>
        <Badge
          data-testid={`api-key-status-${keyInfo.name}`}
          variant={keyInfo.is_set ? 'default' : 'secondary'}
          className="text-[10px]"
        >
          {keyInfo.is_set ? 'Set' : 'Not set'}
        </Badge>
      </TableCell>
      <TableCell>
        <div className="flex items-center gap-2">
          <Input
            type="password"
            value={value}
            onChange={(e) => setValue(e.target.value)}
            placeholder={keyInfo.is_set ? 'Replace value…' : 'Paste value…'}
            aria-label={`Value for ${keyInfo.name}`}
            className="h-7 w-40 bg-background text-xs"
            autoComplete="off"
          />
          <Button
            size="sm"
            className="h-7 px-2 text-xs"
            disabled={!value.trim() || mutation.isPending}
            onClick={() => mutation.mutate()}
          >
            {mutation.isPending ? 'Saving…' : 'Save'}
          </Button>
        </div>
        {mutation.isError && (
          <p className="mt-1 text-[10px] text-destructive">{mutation.error?.message || 'Save failed'}</p>
        )}
      </TableCell>
    </TableRow>
  )
}

export default function ApiKeysPanel() {
  const query = useApiKeys()
  const rows = query.data ?? []

  return (
    <div className="flex h-full flex-col" data-testid="api-keys-panel">
      <div className="ms-filter-bar border-b border-border p-3 text-xs text-muted-foreground">
        Saving a key here writes it to this machine's local <code className="font-mono">.env</code> file.
        It does not start or affect any running pipeline, and does not by itself authorize live
        data acquisition — the pipeline's existing preflight and pause-lock gates still apply.
        Values are never displayed back once saved.
      </div>
      <div {...scrollRegion('API keys')} className="ms-scroll-region min-h-0 flex-1 overflow-auto">
        <QueryBoundary query={query} isEmpty={(d) => !d?.length} emptyLabel="No known API keys">
          <Table>
            <TableHeader className="sticky top-0 bg-card">
              <TableRow className="border-border hover:bg-transparent">
                <TableHead>Key</TableHead>
                <TableHead>Description</TableHead>
                <TableHead>Requirement</TableHead>
                <TableHead>Status</TableHead>
                <TableHead>Set value</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {rows.map((keyInfo) => (
                <ApiKeyRow key={keyInfo.name} keyInfo={keyInfo} />
              ))}
            </TableBody>
          </Table>
        </QueryBoundary>
      </div>
    </div>
  )
}
