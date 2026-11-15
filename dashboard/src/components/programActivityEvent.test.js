import { describe, expect, it } from "vitest";
import { PROGRAM_ACTIVITY_EVENT_VERSION as V, appendProgramActivityEvent, declaredEvents, mergeProgramActivity, readLiveProgramActivity, verifyCanonicalRoutes } from "./programActivityEvent";

const declared=[{id:"fn",phase:"NOW",title:"Declared",detail:"d",category:"c",href:"/ok"}];
const event=(overrides={})=>({
  schema:V,eventId:"evt-1",producerId:"app",functionId:"fn",eventType:"RUNTIME_STATE",
  title:"Live",detail:"d",category:"c",state:"NOW",priority:0,scheduledAt:null,
  observedAt:"2026-09-26T12:00:00.000Z",canonicalRoute:"/ok",
  provenance:{sourceId:"src-1",sourceType:"AUTHORITATIVE_RUNTIME"},source:"LIVE",...overrides,
});

describe("PROGRAM_ACTIVITY_EVENT/v1",()=>{
  it("does not invent dates for declared workflow fallbacks",()=>{
    const [row]=declaredEvents("app",declared); expect(row.scheduledAt).toBeNull(); expect(row.observedAt).toBeNull();
  });
  it("is append-only and fails changed-payload event-id collisions",()=>{
    let raw=null; const storage={getItem:()=>raw,setItem:(_,value)=>{raw=value}};
    expect(appendProgramActivityEvent(event(),storage)).toBe(true);
    expect(appendProgramActivityEvent(event(),storage)).toBe(false);
    expect(()=>appendProgramActivityEvent(event({title:"changed"}),storage)).toThrow(/ID_COLLISION/);
    expect(readLiveProgramActivity("app",storage)).toHaveLength(1);
  });
  it("merges by stable function id, not display name",()=>{
    expect(mergeProgramActivity("app",declared,[event({title:"renamed"})],Date.parse("2026-09-26T12:01:00Z"))[0].title).toBe("renamed");
  });
  it("retains null dates, closes conflicting ties as unresolved, and preserves completed supersession",()=>{
    expect(mergeProgramActivity("app",declared,[event({observedAt:null})],Date.parse("2035-01-01T00:00:00Z"))[0].observedAt).toBeNull();
    expect(mergeProgramActivity("app",declared,[event(),event({eventId:"evt-2",state:"BLOCKED",provenance:{sourceId:"src-2",sourceType:"AUTHORITATIVE_RUNTIME"}})],Date.parse("2026-09-26T12:01:00Z"))[0].state).toBe("UNRESOLVED");
    expect(mergeProgramActivity("app",declared,[event(),event({eventId:"evt-2",state:"COMPLETED",observedAt:"2026-09-26T13:00:00Z",supersedesEventId:"evt-1",provenance:{sourceId:"src-2",sourceType:"AUTHORITATIVE_RUNTIME"}})],Date.parse("2026-09-26T13:01:00Z"))[0].state).toBe("COMPLETED");
  });
  it("marks stale observed state unresolved, rejects broken routes, and handles empty queues",()=>{
    expect(mergeProgramActivity("app",declared,[event()],Date.parse("2026-10-10T12:00:00Z"))[0].state).toBe("UNRESOLVED");
    let raw=JSON.stringify([event({canonicalRoute:"https://bad.example"})]); const storage={getItem:()=>raw};
    expect(readLiveProgramActivity("app",storage)).toEqual([]);
    expect(verifyCanonicalRoutes([event(),event({eventId:"evt-2",canonicalRoute:"/missing"})],["/ok"])).toEqual([{eventId:"evt-2",route:"/missing"}]);
    expect(mergeProgramActivity("app",[],[],0)).toEqual([]);
  });
});
