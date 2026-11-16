export const PROGRAM_ACTIVITY_EVENT_VERSION = "PROGRAM_ACTIVITY_EVENT/v1";

const STORAGE_PREFIX = "federation.programActivity.v1.";
const PRIORITY = { NOW: 0, NEXT: 1, QUEUED: 2, BLOCKED: 3 };
const validRoute = (value) => !value || (/^\/(?!\/)/.test(value) && !value.includes("://"));
const validIso = (value) => value == null || (typeof value === "string" && Number.isFinite(Date.parse(value)));

function canonical(value) {
  if (Array.isArray(value)) return "[" + value.map(canonical).join(",") + "]";
  if (value && typeof value === "object") return "{" + Object.entries(value).sort(([a],[b]) => a.localeCompare(b)).map(([k,v]) => JSON.stringify(k)+":"+canonical(v)).join(",") + "}";
  return JSON.stringify(value);
}

export function declaredEvents(producerId, items) {
  return items.map((item) => ({
    schema: PROGRAM_ACTIVITY_EVENT_VERSION,
    eventId: `declared:${producerId}:${item.id}`,
    producerId,
    functionId: item.id,
    eventType: "DECLARED_WORKFLOW",
    title: item.title,
    detail: item.detail,
    category: item.category,
    state: item.phase,
    priority: PRIORITY[item.phase],
    scheduledAt: null,
    observedAt: null,
    canonicalRoute: validRoute(item.href) ? item.href : undefined,
    provenance: { sourceId:`dashboard-declared:${producerId}:${item.id}`, sourceType:"DECLARED_WORKFLOW" },
    source: "DECLARED",
  }));
}

export function validateProgramActivityEvent(event) {
  const errors=[];
  if (event?.schema !== PROGRAM_ACTIVITY_EVENT_VERSION) errors.push("schema");
  if (!event?.eventId) errors.push("eventId");
  if (!event?.producerId) errors.push("producerId");
  if (!event?.functionId) errors.push("functionId");
  if (!event?.eventType) errors.push("eventType");
  if (!event?.title) errors.push("title");
  if (!event?.category) errors.push("category");
  if (!Number.isInteger(event?.priority) || event.priority < 0 || event.priority > 4) errors.push("priority");
  if (!validIso(event?.scheduledAt ?? null)) errors.push("scheduledAt");
  if (!validIso(event?.observedAt ?? null)) errors.push("observedAt");
  if (!validRoute(event?.canonicalRoute)) errors.push("canonicalRoute");
  if (!event?.provenance?.sourceId || !event?.provenance?.sourceType) errors.push("provenance");
  return errors;
}

export function readLiveProgramActivity(producerId, storage = globalThis?.localStorage) {
  if (!storage) return [];
  try {
    const raw=storage.getItem(STORAGE_PREFIX + producerId);
    if (!raw) return [];
    const parsed=JSON.parse(raw);
    if (!Array.isArray(parsed)) return [];
    return parsed.filter((event) => event?.producerId===producerId && event?.source==="LIVE" && validateProgramActivityEvent(event).length===0);
  } catch {
    return [];
  }
}

export function appendProgramActivityEvent(event, storage = globalThis?.localStorage) {
  if (!storage) throw new Error("PROGRAM_ACTIVITY_STORAGE_UNAVAILABLE");
  const errors=validateProgramActivityEvent(event);
  if (event?.source !== "LIVE") errors.push("source");
  if (errors.length) throw new Error("INVALID_PROGRAM_ACTIVITY_EVENT:" + errors.join(","));
  const rows=readLiveProgramActivity(event.producerId, storage);
  const existing=rows.find((row)=>row.eventId===event.eventId);
  if (existing) {
    if (canonical(existing)===canonical(event)) return false;
    throw new Error("PROGRAM_ACTIVITY_EVENT_ID_COLLISION");
  }
  storage.setItem(STORAGE_PREFIX + event.producerId, JSON.stringify([...rows,event]));
  return true;
}

const eventTime=(event)=>event.observedAt ?? event.scheduledAt ?? "";

export function mergeProgramActivity(producerId, declared, live, nowMs=Date.now(), staleAfterMs=7*86400000) {
  const liveRows=live.filter((event)=>event?.producerId===producerId && event?.source==="LIVE" && validateProgramActivityEvent(event).length===0);
  const rows=[...declaredEvents(producerId,declared),...liveRows];
  const byId=new Map();
  for (const event of rows) {
    const prior=byId.get(event.eventId);
    if (!prior) byId.set(event.eventId,event);
    else if (canonical(prior)!==canonical(event)) byId.set(event.eventId,{...prior,state:"UNRESOLVED",detail:prior.detail+" · event ID collision"});
  }
  const unique=[...byId.values()];
  const superseded=new Set(unique.map((event)=>event.supersedesEventId).filter(Boolean));
  const groups=new Map();
  for (const event of unique) groups.set(event.functionId,[...(groups.get(event.functionId)||[]),event]);
  const output=[];
  for (const group of groups.values()) {
    const liveCandidates=group.filter((event)=>event.source==="LIVE"&&!superseded.has(event.eventId)).sort((a,b)=>eventTime(b).localeCompare(eventTime(a))||a.priority-b.priority||a.eventId.localeCompare(b.eventId));
    const chosen=liveCandidates[0] || group.find((event)=>event.source==="DECLARED");
    if (!chosen) continue;
    const tied=liveCandidates.filter((event)=>eventTime(event)===eventTime(chosen)&&event.priority===chosen.priority);
    const signatures=new Set(tied.map((event)=>[event.state,event.title,event.canonicalRoute,event.eventType,event.conflictKey||""].join("|")));
    let state=tied.length>1&&signatures.size>1 ? "UNRESOLVED" : chosen.state;
    if (chosen.source==="LIVE" && chosen.observedAt && !["COMPLETED","SUPERSEDED"].includes(state) && nowMs-Date.parse(chosen.observedAt)>staleAfterMs) state="UNRESOLVED";
    output.push({...chosen,state,phase:state,href:chosen.canonicalRoute});
  }
  return output.sort((a,b)=>a.priority-b.priority||eventTime(a).localeCompare(eventTime(b))||a.functionId.localeCompare(b.functionId)||a.eventId.localeCompare(b.eventId));
}

export function verifyCanonicalRoutes(events, routePaths) {
  const allowed=new Set(routePaths);
  return events.filter((event)=>event.canonicalRoute && !allowed.has(event.canonicalRoute)).map((event)=>({eventId:event.eventId,route:event.canonicalRoute}));
}
