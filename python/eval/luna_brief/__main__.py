"""Render an unpublished packet: python -m python.eval.luna_brief --help."""
import argparse
from datetime import date
from pathlib import Path

from .candidate import build, load, read_public, relations
from .display import LANG, render


def packet(root, day, archived, raw=None):
    brief=build(root,day,archived)
    if (isinstance(raw,dict) and raw.get("model")=="gpt-6-luna" and raw.get("effort")=="none"
        and raw.get("max_output_tokens")==4000):
        fb=relations.live._build_fallback_ai_daily_report(root,day,archived["generatedAt"],"en")
        sources={k:read_public(root,v) for k,v in fb["inputRefs"].items() if v}
        ledger=relations.build(day,sources,fb["inputSnapshot"])
        prompt=relations.live._sanitize_openai_context(relations.live._load_openai_context(root,fb))["factPacket"]
        # A response is accepted only with the matching target and prompt input fingerprint.
        if raw.get("date")==day and raw.get("inputSnapshot")==prompt.get("inputSnapshot"):
            checked=relations.optional_interpretations(prompt,raw.get("response"),ledger)
            if checked:brief=build(root,day,archived,checked)
    return brief


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--public-root",required=True,type=Path,help="Frozen local public artifacts")
    parser.add_argument("--date",required=True,type=date.fromisoformat)
    parser.add_argument("--output",required=True,type=Path,help="New directory under the repository's ignored tmp/")
    parser.add_argument("--verified-input-response",type=Path,help="Optional prior Luna response envelope; no API is called")
    args=parser.parse_args()
    root,out=args.public_root.resolve(),args.output.resolve()
    scratch=(Path(__file__).resolve().parents[3]/"tmp").resolve()
    if scratch not in out.parents or out==root or root in out.parents or out in root.parents:
        parser.error("output must be a new, separate local scratch directory")
    day=args.date.isoformat();arch=read_public(root,f"reports/ai/daily/en/{day}.json")
    b=packet(root,day,arch,load(args.verified_input_response) if args.verified_input_response else None)
    pages={l:render(b,l) for l in LANG}
    out.mkdir(parents=True,exist_ok=False)
    for l,html in pages.items(): (out/f"{l}.html").write_text(html,encoding="utf-8")


if __name__=="__main__": main()
