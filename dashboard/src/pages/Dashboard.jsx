import { Tabs, TabsList, TabsTrigger, TabsContent } from '@/components/ui/tabs'
import StatsBar from '@/components/StatsBar'
import ContractsTable from '@/components/ContractsTable'
import EntitiesTable from '@/components/EntitiesTable'
import RelationshipGraph from '@/components/RelationshipGraph'
import MunicipalityAggregates from '@/components/MunicipalityAggregates'
import { Banknote } from 'lucide-react'

export default function Dashboard() {
  return (
    <div className="flex flex-col h-screen bg-slate-950 text-slate-200">
      <header className="flex items-center gap-2 px-4 py-2.5 border-b border-slate-800 bg-slate-900">
        <Banknote className="h-5 w-5 text-amber-400" />
        <div>
          <h1 className="text-sm font-semibold text-slate-100 leading-none">Contract-Sweeper</h1>
          <p className="text-[11px] text-slate-500 mt-0.5">Puerto Rico public-money contracts & entity network</p>
        </div>
      </header>

      <StatsBar />

      <div className="flex-1 min-h-0 p-3">
        <Tabs defaultValue="contracts" className="flex flex-col h-full">
          <TabsList className="grid grid-cols-4 w-full max-w-2xl bg-slate-900">
            <TabsTrigger value="contracts" className="text-xs">Contracts</TabsTrigger>
            <TabsTrigger value="entities" className="text-xs">Entities</TabsTrigger>
            <TabsTrigger value="graph" className="text-xs">Relationships</TabsTrigger>
            <TabsTrigger value="municipios" className="text-xs">Municipios</TabsTrigger>
          </TabsList>
          <div className="flex-1 min-h-0 mt-3 rounded-lg border border-slate-800 bg-slate-950 overflow-hidden">
            <TabsContent value="contracts" className="h-full m-0"><ContractsTable /></TabsContent>
            <TabsContent value="entities" className="h-full m-0"><EntitiesTable /></TabsContent>
            <TabsContent value="graph" className="h-full m-0"><RelationshipGraph /></TabsContent>
            <TabsContent value="municipios" className="h-full m-0"><MunicipalityAggregates /></TabsContent>
          </div>
        </Tabs>
      </div>
    </div>
  )
}
