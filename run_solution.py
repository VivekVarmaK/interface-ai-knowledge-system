#!/usr/bin/env python3
"""Inspect offline answers or export conflicts using the supplied snapshot loader."""
import argparse
import json
import sys
from dataclasses import asdict
from pathlib import Path

ROOT=Path(__file__).resolve().parent
sys.path.insert(0,str(ROOT/'submission'))
from solution import build


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--question',help='Question to ask the ingested knowledge system')
    parser.add_argument('--as-of',help='Historical view, ISO date YYYY-MM-DD')
    parser.add_argument('--kit',type=Path,default=ROOT,help='Path to the supplied participant kit, not distributed here')
    parser.add_argument('--snapshots',type=Path,help='Override the kit snapshot directory')
    parser.add_argument('--conflicts',action='store_true',help='Print the conflict report as JSON')
    args=parser.parse_args()
    if not args.question and not args.conflicts:
        parser.error('provide --question or --conflicts')
    if not (args.kit/'harness'/'run_eval.py').is_file():
        parser.error('--kit must point to the supplied participant kit containing harness/run_eval.py')
    sys.path.insert(0,str(args.kit/'harness'))
    from run_eval import load_snapshots
    ks=build()
    for snapshot in load_snapshots(args.snapshots or args.kit/'snapshots'):
        ks.ingest(snapshot)
    result={}
    if args.question:result['answer']=asdict(ks.answer(args.question,args.as_of))
    if args.conflicts:result['conflicts']=[asdict(c) for c in ks.conflicts()]
    print(json.dumps(result,indent=2,ensure_ascii=False))


if __name__=='__main__':
    main()
