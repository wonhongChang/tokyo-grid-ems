import test from 'node:test'
import assert from 'node:assert/strict'
import { chartSlots, verifiedAdvice } from '../src/briefEvidence.ts'

const tag=(name,attrs,...kids)=>[name,attrs,...kids]
const row=h=>tag('tr',{id:'row-point/'+h,'data-id':'point/'+h},...Object.entries({
  actual:'29,000.0',published:'28,060.2',tepco:'29,000.0',error:'-939.8',tepcoError:'0.0',
}).map(([key,num])=>tag('td',{'data-field':key},num)))
const group=(...rows)=>[tag('details',{id:'point'},tag('table',{},tag('tbody',{},...rows)))]
const report={operationsBrief:{},dataQuality:{comparableHours:2}}
test('strict JST archive projection retains partial gaps, signs and zero; does not mutate the issue',()=>{
  const body=group(row('00:00'),row('02:00')), before=JSON.stringify(body)
  const slots=chartSlots(body,report)
  assert.equal(slots.length,24);assert.equal(slots[1],null);assert.equal(slots[2].error,-939.8)
  assert.equal(slots[2].actual,29000);assert.equal(slots[0].tepcoError,0);assert.equal(JSON.stringify(body),before)
})
test('unavailable or ambiguous evidence leaves the written report, not an invented chart',()=>{
  for(const h of ['00:00','24:00','08:30'])assert.equal(chartSlots(group(row('00:00'),row(h)),report),null)
  for(const value of ['不明','—','','3,40','8 MW','2e4','Infinity']){
    const bad=row('01:00');bad[2][2]=value
    assert.equal(chartSlots(group(row('00:00'),bad),report),null)
  }
  const bad=row('01:00');bad.push(bad[2]);assert.equal(chartSlots(group(row('00:00'),bad),report),null)
  for(const sampleHours of [null,1,24])assert.equal(chartSlots(group(row('00:00'),row('01:00')),
    {...report,operationsBrief:{sampleHours}}),null)
  assert.equal(chartSlots([tag('details',{id:'stages'},row('00:00'),row('01:00'))],report),null)
})
const relation='vintage/16:00'
const note=tag('details',{id:'luna'},tag('a',{href:'#row-'+relation},'Evidence'))
const nodes=[note,tag('tr',{id:'row-'+relation,'data-id':relation})]
const accepted={advisoryStatus:'selected',selection:[{claim:'published_closer',relation}]}
test('both archived and current records credit only the named model and its adopted evidence',()=>{
  for(const generator of [{provider:'openai',model:'gpt-6-luna'},
    {provider:'python',model:null,advisory:{provider:'openai',model:'gpt-6-luna',status:'selected',attempted:true}}]){
    assert.equal(verifiedAdvice(nodes,{operationsBrief:accepted,generator}),note)
    for(const status of ['abstained','failed','not_requested','no_eligible_evidence','unavailable'])
      assert.equal(verifiedAdvice(nodes,{operationsBrief:{...accepted,advisoryStatus:status},generator}),undefined)
    assert.equal(verifiedAdvice(nodes,{operationsBrief:{...accepted,selection:[]},generator}),undefined)
    assert.equal(verifiedAdvice([note],{operationsBrief:accepted,generator}),undefined)
    assert.equal(verifiedAdvice(nodes,{operationsBrief:{...accepted,selection:[{claim:'opposite_directions',relation}]},generator}),undefined)
  }
  assert.equal(verifiedAdvice(nodes,{operationsBrief:accepted,generator:{provider:'fallback',model:null}}),undefined)
  for(const change of [{model:'unidentified'},{attempted:false},{status:'failed'},{provider:'other'}])
    assert.equal(verifiedAdvice(nodes,{operationsBrief:accepted,generator:{provider:'python',advisory:{
      provider:'openai',model:'gpt-6-luna',attempted:true,status:'selected',...change}}}),undefined)
})
