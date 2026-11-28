import { useState } from 'react'
import { Bar, BarChart, CartesianGrid, Cell, Line, LineChart, ReferenceLine, XAxis, YAxis, ResponsiveContainer, Tooltip } from 'recharts'
import type { Slot } from '../briefEvidence'
import { briefCopy } from '../briefCopy'
import type { Locale } from '../i18n'

const colors = {actual:'#bf510d', published:'#255ec4', tepco:'#7552b0', under:'#276692', over:'#a45227'}
const series = ['actual','published','tepco'] as const
export const hourText = (h:number) => String(h).padStart(2,'0')+':00'
const tick = { fontSize:11, fill:'#495e6a' }
const margin = {top:8, right:12, left:0, bottom:0}
export const fmt = (v:number, locale:Locale, sign=false) => v.toLocaleString(locale,{maximumFractionDigits:1, signDisplay:sign?'exceptZero':'auto'})

export function BriefDayChart({slots, locale, worst, best}: {slots:(Slot|null)[]; locale:Locale; worst:Slot; best:Slot}) {
  const w=briefCopy[locale], [hour,setHour]=useState(worst.hour)
  const pick=slots[hour] ?? worst
  const partial=slots.some(r=>r===null)
  const rows=slots.map((r,h)=>({actual:r?.actual??null,published:r?.published??null,tepco:r?.tepco??null,error:r?.error??null,time:hourText(h)}))
  const names={actual:w.actual,published:w.champion,tepco:w.tepco}
  const axis={tickLine:false,axisLine:false,tick, width:54}
  const x={dataKey:'time', ticks:['00:00','04:00','08:00','12:00','16:00','20:00','23:00'],tickLine:false,axisLine:false,tick,minTickGap:12}
  const onPoint=(e:{activeLabel?:string|number})=>{
    const h=Number(String(e.activeLabel).split(':')[0]);if(Number.isInteger(h)&&slots[h])setHour(h)
  }
  const tooltipValue=(v:unknown)=>typeof v==='number'?fmt(v,locale)+' MW':'—'
  return <figure className="brief-figure" aria-labelledby="ops-demand-title">
    <div className="brief-figure-head"><h2 id="ops-demand-title">{w.demand}</h2>
      <div className="brief-legend">{series.map((k,i)=><span key={k}><i style={{borderTopColor:colors[k],borderTopStyle:i===2?'dashed':i===1?'dotted':'solid'}}/>{names[k]}</span>)}</div>
    </div>
    <div className="brief-axis-title">MW</div>
    <div className="brief-curve" role="group" aria-label={w.demand}>
      <ResponsiveContainer width="100%" height="100%"><LineChart data={rows} margin={margin} onClick={onPoint} accessibilityLayer>
        <CartesianGrid vertical={false} stroke="#dbe4e9" strokeDasharray="3 4"/>
        <XAxis {...x} padding={{left:6,right:6}}/><YAxis {...axis} domain={['auto','auto']} tickCount={4} tickFormatter={v=>fmt(Number(v),locale)}/>
        <Tooltip formatter={tooltipValue} contentStyle={{fontSize:12}}/>
        {series.map((k,i)=><Line key={k} type="linear" dataKey={k} name={names[k]} stroke={colors[k]} strokeWidth={i===0?2.6:2}
          strokeDasharray={i===2?'7 4':i===1?'2 2':undefined} dot={partial?{r:2}:false} activeDot={{r:4}} connectNulls={false} isAnimationActive={false}/>)}
      </LineChart></ResponsiveContainer>
    </div>
    <div className="brief-error-head"><h3>{w.errors}</h3><span>{w.errorBasis}</span></div>
    <div className="brief-bars" role="group" aria-label={w.errors}>
      <ResponsiveContainer width="100%" height="100%"><BarChart data={rows} margin={margin} onClick={onPoint} accessibilityLayer>
        <CartesianGrid vertical={false} stroke="#e1e8eb" strokeDasharray="3 4"/><XAxis {...x}/>
        <YAxis {...axis} domain={[(min:number)=>Math.min(0,min),(max:number)=>Math.max(0,max)]} tickCount={3} tickFormatter={v=>fmt(Number(v),locale)}/>
        <Tooltip formatter={tooltipValue} contentStyle={{fontSize:12}}/><ReferenceLine y={0} stroke="#546576"/>
        <Bar dataKey="error" name={w.errors} maxBarSize={23} isAnimationActive={false}>{rows.map(r=><Cell key={r.time} fill={(r.error??0)<0?colors.under:colors.over}/>)}</Bar>
      </BarChart></ResponsiveContainer>
    </div>
    <figcaption>
      <div className="brief-inspect"><label>{w.selectedHour} <select value={pick.hour} onChange={e=>setHour(Number(e.target.value))}>
        {slots.filter((r):r is Slot=>r!==null).map(r=><option key={r.hour} value={r.hour}>{hourText(r.hour)} JST</option>)}</select></label>
        <span>{w.nearest}: <button type="button" title={w.first} onClick={()=>setHour(best.hour)}>{hourText(best.hour)} ({fmt(best.error,locale,true)} MW)</button></span>
      </div>
      <div className="brief-readout" aria-live="polite">
        {series.map(k=><span key={k}>{names[k]} <b>{fmt(pick[k],locale)} MW</b></span>)}
        <span>{w.errors} <b>{fmt(pick.error,locale,true)} MW</b></span>
        <a href={'#ops-v8-row-point/'+hourText(pick.hour)}>{w.evidence}</a>
      </div>
    </figcaption>
  </figure>
}
