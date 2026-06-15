import { useQuery } from '@tanstack/react-query'
import { getHealth, getContracts, getEntities, getEdges, getMunicipalities, getStats } from '@/lib/api'

export const useHealth = () => useQuery({ queryKey: ['health'], queryFn: getHealth, refetchInterval: 15_000 })
export const useStats = () => useQuery({ queryKey: ['stats'], queryFn: getStats })
export const useContracts = (filters = {}) =>
  useQuery({ queryKey: ['contracts', filters], queryFn: () => getContracts(filters) })
export const useEntities = (filters = {}) =>
  useQuery({ queryKey: ['entities', filters], queryFn: () => getEntities(filters) })
export const useEdges = (filters = {}) =>
  useQuery({ queryKey: ['edges', filters], queryFn: () => getEdges(filters) })
export const useMunicipalities = () => useQuery({ queryKey: ['municipalities'], queryFn: getMunicipalities })
