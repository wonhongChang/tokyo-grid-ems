"""Standalone, accessible rendering: all three locales bind to the same typed facts."""
from html import escape
from .labels import LANG, GROUP, BASIS, VOCAB, PAIR, STAGE, tr, label, cell
from .. import daily_operation_report as rules


STYLE="""*{box-sizing:border-box}body{margin:0;background:#f7f9f8;color:#192b31;font:16px/1.5 system-ui,sans-serif}main{max-width:960px;margin:auto;background:#fff;padding:24px 32px 40px}header{border-bottom:3px solid #187261}small,.note{color:#465a60}h1{font-size:27px;margin:2px 0 8px}h2{font-size:20px;margin:23px 0 8px}p{margin:6px 0}#next{border-left:3px solid #147566;padding:5px 10px;margin:10px 0}details{border-bottom:1px solid #dce3e2;padding:6px 0}summary{cursor:pointer;font-weight:600;color:#125b53}a{color:#125b53}.scroll{overflow:auto;max-width:100%;margin:8px 0}table{border-collapse:collapse;font-size:14px;font-variant-numeric:tabular-nums}th,td{padding:5px 8px;text-align:start;vertical-align:top;border-bottom:1px solid #e3e8e7}th{font-weight:600}code{overflow-wrap:anywhere}.note{font-size:14px}dl{margin:8px 0}dt{font-weight:600}dd{margin:0 0 8px}section{min-width:0}@media(max-width:600px){main{padding:12px 15px 24px}h1{font-size:22px}body{font-size:15px}h2{font-size:18px;margin-top:16px}}"""


def render(b, lang):
    if lang not in LANG: raise ValueError("unsupported language")
    def t(msg, **kw): return tr(msg,lang).format(**{k:escape(str(v)) for k,v in kw.items()})
    def val(v): return cell("",v,lang)
    def mw(x,signed=False): return f"{x:+,.1f}" if signed else f"{x:,.1f}"
    def at(x): return ", ".join(x)
    def det(title, body, id=""):
        return f'<details id="{escape(id)}"><summary>{title}</summary>{body}</details>'
    def p(s): return "<p>"+s+"</p>"
    day=b["day"]; rows=b["rows"]; daily=b["daily"]; points={i[6:]:r["cells"] for i,r in rows.items() if i.startswith("point/")}
    cv=b["coverage"]; ranked=b["ranked"]; peaks=b["peaks"]; hist=b["history"]
    full=b["state"]=="daily_report_full"
    title=t("Demand forecast review|전력 수요 예측 리뷰|電力需要予測レビュー")
    first=[f'<header><small>Tokyo Grid EMS · {day} JST</small><h1>{title}</h1></header><section id="brief">']
    scope=t("Complete daily evaluation using archived report actuals|보존 일간 리포트 실측 기준 · 하루 전체 평가|保存した日別報告の実績に基づく全日評価") if full else val(b["state"])
    if full or b["state"]=="partial":
        first.append(p(t("{scope} · {n}/24 paired hours. Signed error = forecast − actual.|{scope} · 24시간 중 {n}시간 비교. 오차는 예측−실측입니다.|{scope} · 24時間中{n}時間を比較。誤差は予測−実績です。",scope=scope,n=len(points))))
    else:
        first.append(p(t("{scope}. Paired population not confirmed; counts in the archive are not a validated evaluation.|{scope}. 비교 모집단을 확인하지 못했습니다. 보존 자료의 시간 수는 검증된 성능 표본이 아닙니다.|{scope}。比較母集団は未確認です。保存資料の時間数を検証済みの評価標本として扱いません。",scope=scope)))
    if peaks:
        h,c=next(iter(peaks.items()))
        first.append(p(t("Observed maximum: {a} MW at {h}; published model maximum at {ph}.|관측 최고 수요는 {h}의 {a} MW이고, 공개 모델의 최고 시각은 {ph}입니다.|観測最大需要は{h}の{a} MW、公開モデルの最大時刻は{ph}です。",a=mw(c["actualPeak"]),h=at(peaks),ph=at(c["publishedHours"]))))
        if full:
            first.append(p(t("Observed demand at the day’s endpoints: 00:00 {start} → 23:00 {end} MW.|실측 수요: 00시 {start} → 23시 {end} MW.|実績需要：0時 {start} → 23時 {end} MW。",start=mw(points["00:00"]["actual"]),end=mw(points["23:00"]["actual"]))))
        if len(peaks)==1 and h not in c["publishedHours"]:
            first.append(p(t("Maximum minus maximum (published − actual): {maxdiff} MW. At the actual peak ({h}), published minus actual: {err} MW.|최고값끼리 비교하면 공개−실측은 {maxdiff} MW입니다. 실측 피크({h}) 한 시각의 공개−실측은 {err} MW입니다.|最大値同士の公開−実績は {maxdiff} MW。実績ピーク（{h}）の同時刻の公開−実績は {err} MWです。",h=h,maxdiff=mw(c["maxDifference"],True),err=mw(c["error"],True))))
    if daily:
        first.append(p(t("Daily MAE: published {m} / TEPCO {e} MW. Rule verdict: {v}. Hourly wins: published {w}, TEPCO {z}, ties {ties}.|일간 MAE: 공개 모델 {m} / TEPCO {e} MW. 규칙 판정: {v}. 시간별 우위는 모델 {w} / TEPCO {z}, 동률 {ties}입니다.|日別MAE：公開モデル {m} / TEPCO {e} MW。規則判定：{v}。各時刻の優位はモデル {w} / TEPCO {z}、同差 {ties}。",m=mw(daily["modelMaeMw"]),e=mw(daily["tepcoMaeMw"]),v=val(daily["verdict"]),w=daily["modelWins"],z=daily["tepcoWins"],ties=daily["ties"])))
    if ranked:
        h=ranked[0];c=points[h]
        first.append(p(t("Largest absolute published error: {h}, {e} MW vs actual (TEPCO {te} MW at that hour).|공개 모델의 절대오차가 가장 큰 시각은 {h}입니다. 실측 대비 {e} MW, 같은 시각 TEPCO는 {te} MW였습니다.|公開モデルの絶対誤差が最大の時刻は{h}。実績比 {e} MW、同時刻のTEPCOは {te} MWでした。",h=h,e=mw(c["error"],True),te=mw(c["tepcoError"],True))))
        for r in rows.values():
            if r["kind"]!="band":continue
            lo,hi=map(int,r["target"].split("-"))
            bc=r["cells"]
            if lo<=int(h[:2])<=hi and c["closer"]!=bc["lowerMAE"] and "tie" not in (c["closer"],bc["lowerMAE"]):
                first.append(p(t("At {h}, {point} had the smaller miss; over {w} the lower MAE was {band} (published vs TEPCO).|{h} 한 시간의 절대오차는 {point} 쪽이 작지만, {w}시 평균절대오차 기준으로는 {band} 쪽이 작습니다(공개 모델 대 TEPCO).|{h}単時刻の絶対誤差は{point}の方が小さく、{w}時の平均絶対誤差は{band}の方が小さい結果です（公開モデル対TEPCO）。",h=h,w=r["target"],point=val(c["closer"]),band=val(bc["lowerMAE"]))))
                break
    if hist:
        r=hist[0]; bc=rows["band/"+r["band"]]["cells"]
        first.append(p(t("{band}: published mean error today {bias} MW. Including today, {count}/{n} days met the existing {dir} bias criterion.|{band}시 공개 모델 평균 오차는 {bias} MW입니다. 대상일 포함 {n}일 중 {count}일이 기존 {dir} 편향 기준에 해당했습니다.|{band}時の公開モデルの平均誤差は {bias} MW。対象日を含む{n}日中{count}日で既存の{dir}バイアス基準に該当しました。",band=r["band"],bias=mw(bc["bias"],True),count=r["count"],n=r["n"],dir=val("under" if r["direction"]=="underprediction" else "over"))))
    iv=b["intervals"]["95"]
    act={
      "none":"No special follow-up indicated by the available checks.|확인한 자료에서는 별도 후속 점검이 필요하지 않습니다.|確認した資料では特別な追加点検は不要です。",
      "coverage":"Check actuals and target matching first; do not assign a daily winner.|실측 확정 여부와 대상 시각 매칭부터 확인하세요. 일간 우위를 판정하지 않습니다.|実績の確定状況と対象時刻の対応を確認。日別の優劣は判定しません。",
      "band_data":"Check missing published bounds before interpreting interval coverage.|구간 포함률을 해석하기 전에 누락된 공개 상·하한을 확인하세요.|区間内率を解釈する前に欠落した公開上下限を確認してください。",
      "bounds":"Check the daily actual against the published 95% bounds at {h}.|{h}의 일간 실측을 공개 95% 구간 상·하한과 대조하세요.|{h}の日別実績を公開95%区間の上下限と照合してください。",
      "history":"Retrieve releases targeting {band} JST at matched lead; compare opposite-sign cases before attributing a cause.|{band}시를 예측 대상으로 한 원 발행본을 같은 리드로 맞추고 반대 방향 사례도 대조하세요. 원인은 아직 미확인입니다.|{band}時を対象とする当初発行の予測を同一リードでそろえ、逆方向の事例も比較してください。原因は未確認です。",
      "issue":"Look up the original release for {worst}. If its inputs are absent, stop at the observed miss.|{worst}의 원 발행 입력을 확인하세요. 없으면 관측된 오차까지만 기록합니다.|{worst}の当初の発行入力を確認。なければ観測された誤差の記録にとどめます。"}
    if b["action"]=="none" and b["revisionTargets"]:
        act["none"]=t("No priority check of published point accuracy or interval exceptions. Separately, {n} target hours meet the published-vs-recalculated gap criterion; look up original issues only if investigating revisions.|공개 점예측과 구간 이탈에 우선 점검할 사항은 없습니다. 별도로 {n}개 대상 시각에서 공개선과 재계산선 차이가 확인 기준을 넘었습니다. 발행 이력을 조사할 때만 원 발행본을 확인하세요.|公開点予測と区間逸脱について優先点検はありません。別に{n}対象時刻で公開予測と再計算の差が確認基準に該当します。改定を調査する場合に限り当初の発行記録を確認してください。",n=len(b["revisionTargets"]))
    first.append('<p id="next"><b>'+t("Next check|다음 확인|次の確認")+'</b> · '+t(act[b["action"]],h=at(iv["outside"]),band=hist[0]["band"] if hist else "",worst=ranked[0] if ranked else "")+'</p>')
    first.append('<p class="note">'+t("Retrospective, same target hours; original issue times and equal lead are unverified.|같은 대상 시각의 사후 비교입니다. 원 발행 시각과 동일 리드 여부는 확인되지 않았습니다.|同じ対象時刻の事後比較です。当初の発行時刻とリードの一致は未確認です。")+"</p></section>")
    body=["".join(first),"<h2>"+t("Supporting evidence|상세 근거|詳細な根拠")+"</h2>"]
    if ranked:
        body.append(det(t("Largest hourly misses|주요 오차 시각|主な誤差時刻"),p(t("Top three by absolute published error; earlier JST hour breaks ties. Not a representative sample or a daily verdict.|공개 모델 절대오차 상위 세 시간입니다. 동률은 이른 시각부터 표시합니다. 대표 표본이나 일간 판정이 아닙니다.|公開モデルの絶対誤差上位3時刻です。同値は早い時刻を優先。代表標本や日別判定ではありません。"))+"".join(p(t("{h}: {m} MW (",h=h,m=mw(points[h]["error"],True))+t("published|공개|公開")+") / "+mw(points[h]["tepcoError"],True)+" MW (TEPCO)") for h in ranked),"rank"))
    extras={
        "maxDifference":"Published maximum − actual maximum (MW)|공개 최고값−실측 최고값 (MW)|公開最大値−実績最大値 (MW)",
        "forecastAtPeak":"Published at this actual peak hour (MW)|이 실측 피크 시각의 공개 예측 (MW)|この実績ピーク時刻の公開予測 (MW)",
        "forecastDropFromPeak":"Published maximum − published at actual peak (MW)|공개 최고값−실측 피크 시각의 공개 예측 (MW)|公開最大値−実績ピーク時刻の公開予測 (MW)"}
    for kind in ("peak","band","point","change","shape_daily","vintage","stages","coverage","daily","check","history","control","weather","regime"):
        group=[(i,r) for i,r in rows.items() if r["kind"]==kind]
        if not group: continue
        def data(r): return peaks[r["target"]] if kind=="peak" else r["cells"]
        keys=list(dict.fromkeys(k for _,r in group for k in data(r)))
        def col(k):
            if kind=="peak" and k=="error":return t("Published error at THIS actual peak hour (MW)|이 실측 피크 시각의 공개 예측−실측 (MW)|この実績ピーク時刻の公開予測−実績 (MW)")
            if k in extras:return t(extras[k])
            return escape(label(k,lang))
        compare=t(BASIS[kind])
        if kind=="daily" and daily.get("modelWapePct") is not None and daily.get("tepcoWapePct") is not None:
            compare+=" "+t("Close requires both absolute gaps: MAE ≤ {m} MW and WAPE ≤ {w} percentage points. Hourly wins are not votes; conflicting metrics can give a mixed verdict.|비슷함은 두 절대 격차가 모두 작을 때(MAE ≤ {m} MW, WAPE ≤ {w}%p)입니다. 시간별 승수의 다수결이 아니며 지표가 엇갈리면 혼재일 수 있습니다.|同程度には両方の絶対差が小さいこと（MAE ≤ {m} MW、WAPE ≤ {w}ポイント）が必要です。時刻別勝数の多数決ではなく、指標が一致しなければ混在になり得ます。",m=rules._CLOSE_MAE_GAP_MW,w=rules._CLOSE_WAPE_GAP_PCT)
        if kind=="vintage":compare=t(STAGE)+" "+t("The comparison is published vs latest, each against the same actual; not two stages of one issue.|비교 대상은 공개선과 최신 재계산선이며 같은 실측을 기준으로 합니다. 한 발행의 연속 단계가 아닙니다.|同一実績に対する公開予測と最新再計算の比較で、一つの発行の連続段階ではありません。")
        if kind=="change":compare+=" "+t("Lower error compares the published and TEPCO changes against the observed change.|우위는 실측 변화량 기준으로 공개 모델과 TEPCO의 변화량 오차를 비교합니다.|優位は実績変化量に対する公開モデルとTEPCOの変化量誤差の比較です。")
        if kind=="band":
            counts=[]
            for _,rr in group:
                lo,hi=map(int,rr["target"].split("-"))
                errors=[c["error"] for h,c in points.items() if lo<=int(h[:2])<=hi]
                if any(x<0 for x in errors) and any(x>0 for x in errors):
                    counts.append(rr["target"]+" ("+str(sum(x>0 for x in errors))+"/"+str(sum(x<0 for x in errors))+")")
            if counts:
                compare+=" "+t("Opposite errors cancel in signed bias, not in MAE. Bands with both signs (over/under hours): {items}.|과대와 과소는 부호 편향에서 상쇄되지만 MAE에서는 상쇄되지 않습니다. 두 부호가 함께 나타난 구간(과대/과소 시간 수): {items}.|過大と過小は符号付き誤差では相殺されますがMAEでは相殺されません。両符号のある時間帯（過大/過小の時間数）：{items}。",items=", ".join(counts))
        if kind=="check":
            compare+=" "+t("A published point miss is an accuracy check. A published-vs-recalculated gap alone is only a lead for an optional revision study, not a failed forecast. An original issue must be recovered before replay.|공개 점오차는 정확도 점검 대상입니다. 공개선과 재계산선의 차이만 있는 행은 발행 이력 연구를 선택할 때의 단서이지 예측 실패가 아닙니다. 원 발행을 확보하기 전에는 재현하지 않습니다.|公開点予測の誤差は精度点検の対象です。公開予測と再計算の差だけの行は任意の改定調査の手掛かりで、予測失敗ではありません。当初の発行入力を確保するまで再現しません。")
        data_rows=[]
        for rid,r in group:
            d=data(r)
            data_rows.append(f'<tr id="row-{escape(rid)}" data-id="{escape(rid)}" tabindex="-1"><th scope="row">{escape(val(r["target"]))}</th>'+''.join(
                f'<td data-field="{k}">'+escape(mw(d[k]) if k in extras and d.get(k) is not None else cell(k,d.get(k),lang))+'</td>' for k in keys)+'</tr>')
        table='<div class="scroll" tabindex="0"><table><thead><tr><th>JST</th>'+''.join('<th>'+col(k)+'</th>' for k in keys)+'</tr></thead><tbody>'+''.join(data_rows)+'</tbody></table></div>'
        group_title=t("Accuracy checks and optional revision inquiries|정확도 점검과 선택적 발행 이력 조사|精度点検と任意の改定調査") if kind=="check" else t(GROUP[kind])
        body.append(det(group_title,p(compare)+table,kind))
    block=[]
    for level,v in b["intervals"].items():
        block.append(p(t("{l}%: inside {i}/{n}; median half-width {w} MW; outside: {out}; excluded paired hours: {ex}.|{l}%: 구간 내 {i}/{n}시간, 반폭 중앙값 {w} MW. 이탈: {out}. 구간 집계 제외: {ex}시간.|{l}%：区間内 {i}/{n}時間、半幅中央値 {w} MW。区間外：{out}。区間集計除外：{ex}時間。",l=level,i=val(v["inside"]),n=v["n"],w=mw(v["medianHalfWidth"]) if v["medianHalfWidth"] is not None else val(None),out=at(v["outside"]) or (t("none|없음|なし") if v["n"] else val(None)),ex=v["excluded"])))
        for x in v["exceptions"]:
            block.append(p(t("{h}: actual {a} MW · published {l}% range {lo}–{hi} MW · {side}.|{h}: 실측 {a} MW · 공개 {l}% 구간 {lo}~{hi} MW · {side}.|{h}：実績 {a} MW・公開{l}%区間 {lo}～{hi} MW・{side}。",h=x["target"],a=mw(x["actual"]),l=level,lo=mw(x["lower"]),hi=mw(x["upper"]),side=t("above upper bound|상한 초과|上限超過") if x["side"]=="above" else t("below lower bound|하한 미만|下限未満"))))
    body.append(det(t("Prediction intervals|예측 구간|予測区間"),"".join(block)+p(t("Inclusion does not establish point accuracy or future calibration.|구간에 포함돼도 점예측 정확도나 미래 보정 품질을 보장하지 않습니다.|区間内でも点予測の精度や将来の較正は保証されません。")),"intervals"))
    if hist:
        body.append(det(t("Repeated bias by date|반복 편향의 날짜별 근거|反復バイアスの日別根拠"),p(t("Existing criterion: daily band mean ≥ +300 or ≤ −300 MW. Target date included; not independent matched-policy replications.|기존 기준은 해당 일자의 구간 평균 ≥ +300 또는 ≤ −300 MW입니다. 대상일 포함이며 같은 정책의 독립 재현 횟수가 아닙니다.|既存基準は各日の時間帯平均 ≥ +300 または ≤ −300 MW。対象日を含み、同一方針での独立再現回数ではありません。"))+"".join(p(escape(r["band"])+": "+", ".join(d+" "+mw(v,True)+" MW" for d,v in r["days"].items())) for r in hist),"repeat"))
    provenance=p(t("Archived report generated: {s}. This is not the original issue or an actual revision time.|보존 리포트 생성: {s}. 원 예측 발행이나 실측 정정 시각이 아닙니다.|保存レポート生成：{s}。当初の予測発行時刻や実績改訂時刻ではありません。",s=b["reportTime"]))
    for k,name in (("actual","Actual source generation|실측 자료 생성|実績資料の生成"),("forecast","Forecast source generation|예측 자료 생성|予測資料の生成"),("operationalCalibration","Retained calculation|보존 재계산|保存再計算")):
        provenance+=p(t(name)+": "+escape(val(b["sourceTimes"][k])))
    provenance+=p(t("Actual revision history and original-issue attribution are unverified.|실측 수정 이력 및 원 발행 정책의 기여는 미확인입니다.|実績の改訂履歴と当初発行の方針の寄与は未確認です。"))
    provenance+=p(t("Retained run records: {body} verified bodies / {idx} index entries in these inputs. They do not prove the original publication.|이 입력에서 날짜·시각이 확인된 보존 실행 본문 {body}개 / 인덱스 {idx}개입니다. 본문이 있어도 원 발행을 입증하지 않습니다.|この資料で日付・時刻が一致した保存実行の本体 {body}件 / 索引 {idx}件。当初の発行を証明するものではありません。",body=val(b["retained"]["bodies"]),idx=val(b["retained"]["indexed"])))
    provenance+=p(t("Recorded serving policy fingerprint|기록된 서빙 정책 지문|記録された配信方針の識別子")+": <code>"+escape(val(b["policy"]))+"</code>")
    body.append(det(t("Source and publication times|자료·발행 시점|資料と発行時点"),provenance,"provenance"))
    if b["optional"]:
        o=b["optional"][0]; rid=o["relation"]; target=rows[rid]["target"]; hint=(
          "At {h} the published model was closer to the daily actual than the latest recalculation; check the two vintages separately.|{h}의 공개 모델은 최신 재계산보다 일간 실측에 가까웠습니다. 공개선과 사후 재계산의 기준 시점을 구분하세요.|{h}の公開モデルは最新再計算より日別実績に近い値でした。両者の算出時点を区別して確認してください。"
          if o["claim"]=="published_closer" else
          "Over {h}, the actual and published model moved in opposite directions. Compare the increments, not just the levels.|{h}에 실측과 공개 모델은 반대 방향으로 움직였습니다. 수요 수준뿐 아니라 변화량을 대조하세요.|{h}に実績と公開モデルは逆方向に動きました。水準だけでなく変化量を比較してください。")
        body.append(det(t("Luna reading suggestion|Luna가 고른 확인 지점|Lunaが選んだ確認箇所"),p(t(hint,h=target))+f'<a href="#row-{escape(rid)}">'+t("Evidence|근거|根拠")+'</a>',"luna"))
    if b["window"]:
        w=b["window"]
        body.append("<h2>"+t("Research worksheet|연구 작업표|研究用ワークシート")+"</h2>"+det(t("Replay question · {w} JST|리플레이 질문 · {w}시 JST|再現検証の問い · {w}時 JST",w=w),research(b,lang),"research"))
    reveal="""<script>function reveal(){let row=document.getElementById(decodeURIComponent(location.hash.slice(1)));if(!row||!row.hasAttribute('data-id'))return;row.closest('details').open=true;row.focus();row.scrollIntoView({block:'center'});}addEventListener('hashchange',reveal);reveal();</script>"""
    return f'<!doctype html><html lang="{lang}"><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><title>{day} · {title}</title><style>{STYLE}</style><main>'+''.join(body)+'</main>'+reveal+'</html>'


def research(b,lang):
    t=lambda s:tr(s,lang)
    w=b["window"]
    content=[("Question|질문|問い",t("Does the signed error in this window persist after matching original issue, lead and day type?|원 발행·리드·영업형태를 맞춰도 이 구간의 부호 오차가 반복되는가?|当初発行・リード・営業区分をそろえてもこの時間帯の符号付き誤差は繰り返されるか。")),
        ("Scope|대상|対象",w+" JST · "+t("Prior 2–4 weeks, same issue/target pairs; group Japanese business days, holidays and weekends separately.|이전 2~4주 같은 발행·대상 쌍. 일본 영업일·공휴일·주말을 나눕니다.|過去2～4週の同一発行・対象ペア。日本の営業日・祝日・週末を区別します。")),
        ("Control|대조군|対照群",t("Unchanged published policy; include opposite-sign and quiet dates at matched lead. Do not count repeat issues as independent targets.|기존 정책을 대조군으로 두고 같은 리드의 반대 부호일과 정상일을 포함합니다. 반복 발행을 독립 대상으로 세지 않습니다.|現行方針を対照とし、同一リードの逆符号日と平常日を含めます。繰り返し発行を独立対象に数えません。")),
        ("Procedure|절차|手順",t("1. Recover original issue ID, timestamp, policy/model identity and then-available inputs. 2. Within one run compare raw, pre- and post-calibration. 3. Compare publication separately. Exclude unmatched pairs; stop if original inputs are missing.|1. 원 발행 ID·시각·정책/모델·당시 입력을 확보합니다. 2. 같은 실행 안에서 원천·보정 전·보정 후를 비교합니다. 3. 공개선은 별도로 평가합니다. 미매칭 쌍을 제외하고 원 발행 입력이 없으면 중단합니다.|1. 当初の発行ID・時刻・方針/モデル・当時の入力を確保。2. 同一実行の元予測・補正前・補正後を比較。3. 公開予測は別に評価。未対応ペアを除外し、当初の入力がなければ中止します。")),
        ("Measures|측정 지표|評価指標",t("Band MAE, WAPE, signed bias, maximum absolute error; report opposite-case degradation and excluded pairs. No tuning recommendation.|구간 MAE·WAPE·부호 편향·최대절대오차, 반대 사례의 악화 및 제외 쌍을 보고합니다. 튜닝 권고가 아닙니다.|時間帯MAE・WAPE・符号付きバイアス・最大絶対誤差、逆方向例の悪化と除外ペアを報告。調整の推奨ではありません。"))]
    card='<dl>'+''.join('<dt>'+t(k)+'</dt><dd>'+escape(v)+'</dd>' for k,v in content)+'</dl>'
    lo,hi=map(int,w.split("-"))
    h=max((k.split("/")[1] for k in b["rows"] if k.startswith("point/") and lo<=int(k[6:8])<=hi),
          key=lambda h:abs(b["rows"]["point/"+h]["cells"]["error"]))
    stage=b["rows"]["stages/"+h]["cells"];point=b["rows"]["point/"+h]["cells"]
    card+='<p>'+t("Start here (largest published absolute error in this window)|이 구간의 공개 절대오차 최대 시각부터 확인|この時間帯で公開絶対誤差が最大の時刻から確認")+f': {h} · '+t("published minus daily actual|공개−일간 실측|公開−日別実績")+f' {point["error"]:+,.1f} MW.</p>'
    card+='<p>'+t("Separately, retained run|별도 보존 실행|別の保存実行")+' '+escape(cell("",stage["run"],lang))+': '+', '.join(label(k,lang)+' '+cell(k,stage[k],lang) for k in ("rawError","preError","postError"))+'.</p>'
    if (x:=b["contrast"]):
        card+='<p>'+t("Opposite-sign control at the same target hour (from prior published top-miss lists; equal lead not established)|같은 시각의 반대 부호 대조 사례(이전 공개 주요 오차 목록 기준, 동일 리드 미확인)|同じ対象時刻の逆符号対照例（過去の公開主要誤差リストから。リードの一致は未確認）")+f': {x["target"]} JST · {x["priorDate"]} {x["priorError"]:+,.1f} MW / {b["day"]} {x["currentError"]:+,.1f} MW.</p>'
    elig=b["eligibility"]
    if elig:
        title=t("Retained business-midday input (not an attribution)|보존 영업일 점심 입력(기여도 아님)|保存された営業日昼間の入力（寄与ではない）")
        card+='<details><summary>'+title+'</summary><p>'+t("Business day, 11–13 JST only. Outside the mask = control; a nonzero value is not proof of original application, nor is zero proof of no tree contribution.|영업일 11~13시만 정의역입니다. 범위 밖은 대조 사례입니다. 0이 아니어도 원 발행 적용 증거가 아니며, 0이어도 트리 기여가 없다는 뜻이 아닙니다.|営業日11～13時のみが定義域です。域外は対照例。非ゼロでも当初の適用証明ではなく、ゼロでも木への寄与がないとはいえません。")+'</p>'
        for h,v in sorted(elig.items()):
            if 11<=int(h[:2])<=15:
                status=t("in mask|범위 안|範囲内") if v["mask"] is True else t("out of mask|범위 밖|範囲外") if v["mask"] is False else cell("",None,lang)
                card+=f'<p>{h} · {status} · '+escape(cell("",v["value"],lang))+'</p>'
        card+='</details>'
    return card
