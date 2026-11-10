import json
import math
import pytest
from python.observability import public_source as src


def advertisement(sha):
    body=(sha+" refs/heads/data\n").encode()
    return b"001e# service=git-upload-pack\n0000"+f"{len(body)+4:04x}".encode()+body+b"0000"


def test_reads_only_allowed_public_paths_pinned_to_each_tick(monkeypatch):
    current=["1"*40]; urls=[]
    def get(url,n):
        urls.append(url)
        return advertisement(current[0]) if "/info/refs" in url else json.dumps(url).encode()
    monkeypatch.setattr(src,"fetch",get)
    remote=src.RemoteData();old=remote.reader()
    assert current[0] in old("status.json",4096)
    assert current[0] in remote.reader()("status.json",4096)
    assert sum("raw.githubusercontent" in u for u in urls)==1
    with pytest.raises(ValueError):old("notes/private/anything",4096)
    with pytest.raises(ValueError):old("status.json",1)
    current[0]="2"*40;new=remote.reader()
    assert current[0] in new("status.json",4096) and "1"*40 in old("status.json",4096)
    monkeypatch.setattr(src,"fetch",lambda u,n:b"0009no")
    with pytest.raises(ValueError):remote.reader()


def test_deployment_is_confirmed_success_not_creation_or_other_site(monkeypatch):
    clock=[1000]; urls=[]
    def get(url,n):
        urls.append(url)
        if "environment=" in url:return b'[{"id":1,"environment":"github-pages"}]'
        return json.dumps([{"state":"in_progress"},{"state":"success","environment_url":"https://other"},
            {"state":"success","created_at":"2000-01-01T00:00:00Z","environment_url":src.PAGES}]).encode()
    monkeypatch.setattr(src.time,"monotonic",lambda:clock[0])
    monkeypatch.setattr(src,"fetch",get)
    probe=src.PagesDeployment()
    assert probe.read()==946684800 and probe.read()==946684800 and len(urls)==2
    clock[0]+=361;monkeypatch.setattr(src,"fetch",lambda u,n:b"[]")
    assert math.isnan(probe.read())
