import { useSearchParams } from 'react-router-dom'
import { Tabs, TabsList, TabsTrigger, TabsContent } from '@/components/ui/tabs'
import StatsBar from '@/components/StatsBar'
import ContractsTable from '@/components/ContractsTable'
import EntitiesTable from '@/components/EntitiesTable'
import RelationshipGraph from '@/components/RelationshipGraph'
import MunicipalityAggregates from '@/components/MunicipalityAggregates'
import CampaignFinance from '@/components/CampaignFinance'
import GovernmentChanges from '@/components/GovernmentChanges'
import DataSources from '@/components/DataSources'
import ApiKeysPanel from '@/components/ApiKeysPanel'
import OwnershipDeepDive from '@/components/OwnershipDeepDive'
import brandMark from "@/assets/icon-64.png?inline";

// API Keys writes to a local backend .env file — no backend exists in the
// OFFLINE/standalone export, so the tab is hidden entirely there.
const OFFLINE = import.meta.env.VITE_OFFLINE === '1'

const TABS = [
  'contracts', 'entities', 'government-changes', 'graph', 'municipios', 'campaign-finance',
  ...(OFFLINE ? [] : ['data-sources', 'api-keys']),
  'ownership',
]

export default function Dashboard() {
  const [params, setParams] = useSearchParams()
  const tab = TABS.includes(params.get('tab')) ? params.get('tab') : 'contracts'
  const setTab = (value) => setParams((prev) => {
    prev.set('tab', value)
    return prev
  }, { replace: true })

  const triggerClass = 'min-h-11 text-xs data-[state=active]:glow-border'

  return (
    <div className="flex h-screen flex-col bg-background text-foreground">
      <header className="panel-glass flex items-center gap-2 border-b border-border px-4 py-2.5">
        <img src={brandMark} alt="" aria-hidden="true" className="h-6 w-6 rounded-md" />
        <div>
          <h1 className="text-sm font-semibold leading-none text-foreground">moneysweep-pr</h1>
          <p className="mt-0.5 text-[11px] text-muted-foreground">Puerto Rico public-money contracts, entities, campaign finance &amp; certified ownership</p>
        </div>
      </header>

      <StatsBar />

      <div className="min-h-0 flex-1 p-3">
        <Tabs value={tab} onValueChange={setTab} className="flex h-full flex-col">
          <div className="overflow-x-auto pb-1">
            <TabsList className={`grid h-auto min-w-[760px] ${OFFLINE ? 'grid-cols-7' : 'grid-cols-9'} bg-card`}>
              <TabsTrigger value="contracts" className={triggerClass}>Contracts</TabsTrigger>
              <TabsTrigger value="entities" className={triggerClass}>Entities</TabsTrigger>
              <TabsTrigger value="government-changes" className={triggerClass}>Gov Changes</TabsTrigger>
              <TabsTrigger value="graph" className={triggerClass}>Relationships</TabsTrigger>
              <TabsTrigger value="municipios" className={triggerClass}>Municipios</TabsTrigger>
              <TabsTrigger value="campaign-finance" className={triggerClass}>Campaign Finance</TabsTrigger>
              {!OFFLINE && <TabsTrigger value="data-sources" className={triggerClass}>Data Sources</TabsTrigger>}
              {!OFFLINE && <TabsTrigger value="api-keys" className={triggerClass}>API Keys</TabsTrigger>}
              <TabsTrigger value="ownership" className={triggerClass}>Ownership</TabsTrigger>
            </TabsList>
          </div>
          <div className="mt-2 min-h-0 flex-1 overflow-hidden rounded-lg border border-border bg-background/40">
            <TabsContent value="contracts" className="m-0 h-full"><ContractsTable /></TabsContent>
            <TabsContent value="entities" className="m-0 h-full"><EntitiesTable /></TabsContent>
            <TabsContent value="government-changes" className="m-0 h-full"><GovernmentChanges /></TabsContent>
            <TabsContent value="graph" className="m-0 h-full"><RelationshipGraph /></TabsContent>
            <TabsContent value="municipios" className="m-0 h-full"><MunicipalityAggregates /></TabsContent>
            <TabsContent value="campaign-finance" className="m-0 h-full"><CampaignFinance /></TabsContent>
            {!OFFLINE && <TabsContent value="data-sources" className="m-0 h-full"><DataSources /></TabsContent>}
            {!OFFLINE && <TabsContent value="api-keys" className="m-0 h-full"><ApiKeysPanel /></TabsContent>}
            <TabsContent value="ownership" className="m-0 h-full"><OwnershipDeepDive /></TabsContent>
          </div>
        </Tabs>
      </div>
    </div>
  )
}
