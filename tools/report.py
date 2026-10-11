"""One event scorer / HTML report for simulator JSON or real JSONL events + count GT."""
import argparse
import csv
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from sim.evaluation import evaluate_events, write_html
from sim.repro import file_hash


def real_result(events_path, gt_path):
    events = []
    for line in events_path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            message = json.loads(line)
            events.append(message.get("event", message))
    if gt_path.suffix == ".csv":
        with gt_path.open(encoding="utf-8", newline="") as stream:
            truth = [{**r, "type": "passage", "t": float(r["t"])} for r in csv.DictReader(stream)]
    else:
        truth = json.loads(gt_path.read_text(encoding="utf-8"))
        if isinstance(truth, dict):
            truth = truth["events"]
    return {"scenario": events_path.parent.name, "level": "real", "domain": "real", "execution": "recorded real events",
            "events": events, "ground_truth": truth, "metrics": evaluate_events(events, truth), "checks": [],
            "event_file_hash": file_hash(events_path), "gt_file_hash": file_hash(gt_path),
            "limitations": ["Manual count GT does not label detector boxes, rule conditions, or approach lead time."]}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--results", type=Path, help="simulation result object or suite array")
    ap.add_argument("--events", type=Path, help="real events.jsonl")
    ap.add_argument("--gt", type=Path, help="manual .gt.csv or structured ground_truth.json")
    ap.add_argument("--out", type=Path, default=ROOT / "runs/report")
    args = ap.parse_args()
    if args.results and not (args.events or args.gt):
        results = json.loads(args.results.read_text(encoding="utf-8"))
        results = results if isinstance(results, list) else [results]
    elif args.events and args.gt and not args.results:
        results = [real_result(args.events, args.gt)]
    else:
        ap.error("supply --results OR both --events and --gt")
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "results.json").write_text(json.dumps(results, indent=2), encoding="utf-8")
    write_html(args.out / "report.html", results)
    print(f"Report: {args.out / 'report.html'}")


if __name__ == "__main__":
    main()
