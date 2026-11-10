"""Generate provisioned dashboards from version-controlled query definitions."""
import json
from pathlib import Path

OUT=Path(__file__).parent/"grafana/dashboards"
HEARTBEAT="and on() (time() - tgems_projector_timestamp_seconds < 180) and on() (up{job=\"pipeline\"} == 1)"
FRESH=HEARTBEAT+" and on() (tgems_projector_success == 1)"
QUALITY=FRESH+" and on() (tgems_quality_available == 1)"
READER_STATE='(((1 + (time() - tgems_projector_timestamp_seconds < bool 90)) * on() tgems_projector_success) '+HEARTBEAT+') or on() vector(-1)'


def durations(stages):
    return 'histogram_quantile(0.95, sum by(le,span_name)(rate(tgems_stage_duration_seconds_bucket{span_name=~"'+stages+'"}[1h])))'


def counts(stages):
    return 'sum by(span_name,outcome)(increase(tgems_stage_calls_total{span_name=~"'+stages+'"}[1h]))'


DASHBOARDS={
    "ops":("System Operations",[
        ("Recent ETL exits with no flagged stage","trace",'{ name =~ "etl.batch|etl.intraday" && span.outcome = "ok" }'),
        ("Observed completions (1h)","short",counts('etl.*|data.restore|publish.request|git.publish|workflow.dispatch')),
        ("Latest failed or degraded stages","trace",'{ span.outcome =~ "failed|degraded" }'),
        ("Pipeline stage duration p95","s",durations('etl.*|data.restore|publish.*|git.publish|workflow.dispatch')),
        ("Pages status age (external probe)","s","(time() - tgems_pages_status_timestamp_seconds) and on() (tgems_pages_success == 1) "+HEARTBEAT),
        ("Public projector observation age","s","time() - tgems_projector_timestamp_seconds"),
        ("Latest confirmed Pages deployment (GitHub)","dateTimeAsLocal","(1000 * tgems_pages_last_success_timestamp_seconds) "+HEARTBEAT),
        ("Public data artifact generated at","dateTimeAsLocal","(1000 * tgems_public_artifact_timestamp_seconds) "+FRESH),
        ("Status currently visible on Pages (generated at)","dateTimeAsLocal","(1000 * tgems_pages_status_timestamp_seconds) and on() (tgems_pages_success == 1) "+HEARTBEAT),
    ]),
    "input":("Data Acquisition",[
        ("Restore, TEPCO / weather fetch and quality outcomes","short",counts('restore.*|source.fetch|input.*|weather.*')),
        ("Successful fetch share by source (1h)","percentunit",'sum by(span_name)(increase(tgems_stage_calls_total{span_name=~"source.fetch|weather.fetch",outcome="ok"}[1h])) / sum by(span_name)(increase(tgems_stage_calls_total{span_name=~"source.fetch|weather.fetch"}[1h]))'),
        ("Latest successful source reads","trace",'{ name = "source.fetch" && span.outcome = "ok" }'),
        ("Source and weather latency p95","s",durations('source.fetch|input.*|weather.*|cache.prepare')),
        ("Observed / fallback slots (public data revision)","short","tgems_public_slots "+FRESH),
        ("Latest observed slot age (not provider acquisition time)","s","(time() - tgems_observed_slot_timestamp_seconds) "+FRESH),
        ("Pages vs data revision: status timestamps agree","short","tgems_pages_status_timestamp_match "+FRESH+" and on() (tgems_pages_success == 1)"),
    ]),
    "forecast":("Forecast Pipeline",[
        ("Model load, features, inference p95","s",durations('model.*|features.build')),
        ("Calibration and issue latency p95","s",durations('forecast.issue|forecast.calibrate|forecast.intraday')),
        ("Forecast writes, retention and freeze","short",counts('forecast.publish|snapshot.retain|origin.record|publication.freeze')),
        ("Forecast issue traces","trace",'{ name = "forecast.issue" }'),
    ]),
    "quality":("Champion Quality",[
        ("Latest finalized published daily MAE","short","tgems_quality_mae_mw "+QUALITY),
        ("Latest finalized published daily RMSE","short","tgems_quality_rmse_mw "+QUALITY),
        ("Published WAPE (ratio)","percentunit","tgems_quality_wape_ratio "+QUALITY),
        ("Comparable samples","short","tgems_quality_samples "+QUALITY),
        ("Time-band bias (MW)","short","tgems_quality_band_bias_mw "+QUALITY),
        ("Time-band MAE (MW)","short","tgems_quality_band_mae_mw "+QUALITY),
        ("Quality target age (since midnight JST)","s","(time() - tgems_quality_target_timestamp_seconds) "+QUALITY),
        ("Finalized quality target (public data revision)","dateTimeAsLocal","(1000 * tgems_quality_target_timestamp_seconds) "+QUALITY),
    ]),
    "health":("Observability Health",[
        ("Scrape targets","short",'up{job=~"collector|pipeline|tempo|grafana|prometheus"}'),
        ("Trace export queue","short","otelcol_exporter_queue_size"),
        ("Trace export failures / second","short","rate(otelcol_exporter_send_failed_spans[5m])"),
        ("Prometheus blocks on disk","bytes","prometheus_tsdb_storage_blocks_bytes"),
        ("Projector last read succeeded","short","tgems_projector_success "+HEARTBEAT),
        ("Finalized quality available","short","tgems_quality_available "+HEARTBEAT),
        ("Reader delivery state","readerState",READER_STATE),
        ("Last successful public read received (24h)","dateTimeAsLocal","1000 * max_over_time((tgems_projector_timestamp_seconds and on() (tgems_projector_success == 1))[24h:1m])"),
    ]),
}


def build(uid,title,specs):
    panels=[]
    for i,(name,unit,query) in enumerate(specs):
        trace=unit=="trace"
        ds={"type":"tempo" if trace else "prometheus","uid":"tgems-tempo" if trace else "tgems-prom"}
        target={"refId":"A","datasource":ds}
        if trace:target.update(queryType="traceql",query=query.replace("{ ", '{ resource.service.name != "tgems-fixture" && ',1),limit=20)
        else:target.update(expr=query)
        stat=unit in ("dateTimeAsLocal","readerState")
        if stat:target.update(instant=True,range=False)
        panels.append({"id":i+1,"title":name,"type":"table" if trace else "stat" if stat else "timeseries","datasource":ds,
            "gridPos":{"x":12*(i%2),"y":8*(i//2),"w":12,"h":8},"targets":[target],
            "fieldConfig":{"defaults":{"unit":"none" if trace else unit,"noValue":"Unavailable"},"overrides":[]}})
        if unit=="readerState":
            defaults=panels[-1]["fieldConfig"]["defaults"]
            defaults.update(unit="none",mappings=[{"type":"value","options":{
                "-1":{"text":"No recent delivery","color":"orange"},"0":{"text":"Source read failed","color":"red"},
                "1":{"text":"Delayed","color":"yellow"},"2":{"text":"Receiving","color":"green"}}}])
    return {"uid":"tgems-"+uid,"title":title,"schemaVersion":39,"version":1,
            "tags":["tokyo-grid-ems"],"timezone":"Asia/Tokyo","refresh":"30s","time":{"from":"now-6h","to":"now"},"panels":panels}


if __name__=="__main__":
    OUT.mkdir(parents=True,exist_ok=True)
    for uid,(title,specs) in DASHBOARDS.items():
        (OUT/(uid+".json")).write_text(json.dumps(build(uid,title,specs),indent=2)+"\n",encoding="utf8")
