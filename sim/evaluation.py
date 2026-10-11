"""The same event matcher and report schema for simulation and real recordings."""
from collections import Counter
import html
import json
import os
from pathlib import Path

from crosswalk.classes import KINDS
from tools.eval_counts import final_passages, match


def evaluate_events(events, ground_truth, tolerance=3.0):
    predicted = final_passages(events)
    actual = [e for e in ground_truth if e["type"] == "passage"]
    tp = match(actual, predicted, tolerance)
    rows = {}
    for kind in KINDS:
        gt = sum(e["kind"] == kind for e in actual)
        got = sum(e["kind"] == kind for e in predicted)
        rows[kind] = {"gt": gt, "counted": got, "matched": tp[kind],
                      "precision": tp[kind] / got if got else None,
                      "recall": tp[kind] / gt if gt else None, "error": got - gt}
    total_gt = len(actual)
    accuracy = 1 - sum(abs(r["error"]) for r in rows.values()) / max(1, total_gt)
    directions = Counter(f"{e['kind']}:{e['dir']}" for e in predicted if e.get("dir"))
    gt_directions = Counter(f"{e['kind']}:{e['dir']}" for e in actual if e.get("dir"))
    direction_keys = directions.keys() | gt_directions.keys()
    direction_accuracy = (1 - sum(abs(directions[k] - gt_directions[k]) for k in direction_keys) / max(1, total_gt)
                          if all(e.get("dir") for e in actual) else None)
    return {"classes": rows, "count_accuracy": accuracy,
            "precision": sum(tp.values()) / len(predicted) if predicted else None,
            "recall": sum(tp.values()) / total_gt if total_gt else None,
            "directions": dict(directions), "gt_directions": dict(gt_directions),
            "direction_accuracy": direction_accuracy,
            "event_counts": dict(Counter(e["type"] for e in events if not e.get("log_only"))),
            "passages": len(predicted), "gt_passages": total_gt}


def check_expectations(result, expected):
    checks = []

    def check(name, got, want, ok):
        checks.append({"name": name, "got": got, "expected": want, "passed": bool(ok)})

    counts = result["metrics"]["classes"]
    if "counts" in expected:
        for kind in KINDS:
            want = expected["counts"].get(kind, 0)
            check(f"count:{kind}", counts[kind]["counted"], want, counts[kind]["counted"] == want)
    if "directions" in expected:
        keys = expected["directions"].keys() | result["metrics"]["directions"].keys()
        for direction in sorted(keys):
            want = expected["directions"].get(direction, 0)
            got = result["metrics"]["directions"].get(direction, 0)
            check(f"direction:{direction}", got, want, got == want)
    for event in expected.get("required_events", []):
        got = result["metrics"]["event_counts"].get(event, 0)
        check(f"event:{event}", got, ">=1", got >= 1)
    for event in expected.get("forbidden_events", []):
        got = result["metrics"]["event_counts"].get(event, 0)
        check(f"no:{event}", got, 0, got == 0)
    rules = Counter(e.get("rule") for e in result["events"])
    for rule in expected.get("required_rules", []):
        check(f"rule:{rule}", rules[rule], ">=1", rules[rule] >= 1)
    for rule in expected.get("forbidden_rules", []):
        check(f"no_rule:{rule}", rules[rule], 0, rules[rule] == 0)
    for rule, limit in expected.get("max_rule_latency_s", {}).items():
        row = result["temporal"]["rules"][rule]
        values = row["onset_latency_s"]["values"]
        got = max(values) if values else None
        check(f"latency:{rule}", got, limit,
              got is not None and got <= limit and row["missed_onsets"] == 0)
    if "min_extension_s" in expected:
        got = result["signal"]["extension_s"]
        check("extension_s", got, expected["min_extension_s"], got >= expected["min_extension_s"])
    collisions = sum(e["type"] == "collision" for e in result["ground_truth"])
    if "collisions" in expected:
        check("collisions", collisions, expected["collisions"], collisions == expected["collisions"])
    if "max_collisions" in expected:
        check("max_collisions", collisions, expected["max_collisions"], collisions <= expected["max_collisions"])
    if "min_passages" in expected:
        got = result["metrics"]["passages"]
        check("min_passages", got, expected["min_passages"], got >= expected["min_passages"])
    return checks


def write_html(path, results, title="\u00f2cio virtual proving ground"):
    path = Path(path)
    rows, sections = [], []

    def escaped(value):
        return html.escape(str(value))

    def percentage(value):
        return "unassessed" if value is None else f"{value:.1%}"

    def table(headers, data):
        return ("<div class='scroll'><table><thead><tr>" + "".join(f"<th>{escaped(h)}</th>" for h in headers) +
                "</tr></thead><tbody>" + "".join("<tr>" + "".join(f"<td>{escaped(v)}</td>" for v in row) +
                                               "</tr>" for row in data) + "</tbody></table></div>")

    passed = 0
    for r in results:
        checks = r.get("checks", [])
        status = "ERROR" if r.get("error") else "PASS" if checks and all(c["passed"] for c in checks) else "FAIL" if checks else "UNASSESSED"
        passed += status == "PASS"
        detail = r.get("error") or "; ".join(f"{c['name']}: {c['got']} (expected {c['expected']})" for c in checks if not c["passed"])
        metrics = r.get("metrics", {})
        direction_accuracy = metrics.get("direction_accuracy")
        direction_text = f"{direction_accuracy:.1%}" if direction_accuracy is not None else "unlabelled"
        rows.append(f"<tr><td><a href='#case-{len(sections)}'>{escaped(r['scenario'])}</a></td><td>{escaped(r['level'])}</td>"
                    f"<td class='{status}'>{status}</td><td>{metrics.get('count_accuracy', 0):.1%}</td>"
                    f"<td>{direction_text}</td>"
                    f"<td>{metrics.get('passages', 0)}/{metrics.get('gt_passages', 0)}</td><td>{html.escape(detail)}</td></tr>")
        body = f"<section id='case-{len(sections)}'><h2>{escaped(r['scenario'])} <span class='{status}'>{status}</span></h2>"
        body += f"<p>{escaped(r['level'])} &middot; seed {escaped(r.get('seed', '-'))} &middot; {escaped(r.get('execution', 'closed-loop'))}</p>"
        if r.get("error"):
            body += f"<p class='ERROR'>{escaped(r['error'])}</p>"
        else:
            body += "<h3>Crossings</h3>" + table(["Class", "GT", "Counted", "Precision", "Recall"],
                         [[k, v["gt"], v["counted"], percentage(v["precision"]), percentage(v["recall"])]
                          for k, v in metrics.get("classes", {}).items()])
            body += table(["Class / direction", "GT", "Counted"],
                          [[k, metrics["gt_directions"].get(k, 0), metrics["directions"].get(k, 0)]
                           for k in sorted(metrics.get("gt_directions", {}).keys() | metrics.get("directions", {}).keys())])
            if r.get("detection"):
                body += "<h3>Raw Detector</h3>" + table(["Class / size / condition", "GT boxes", "Matched", "Recall", "Precision", "FP"],
                            [[k, v["gt"], v["matched_gt"], percentage(v["recall"]), percentage(v["precision"]), v["false_positives"]]
                             for k, v in sorted(r["detection"]["bins"].items())])
                body += f"<p>{escaped(r['detection']['frames'])} NN-sampled frames; {r['detection']['fp_per_minute']:.2f} FP/min. Visible silhouette boxes, IoU 0.5; precision uses predicted size bins.</p>"
            temporal = r.get("temporal", {})
            if temporal.get("rules"):
                body += "<h3>Light Rules</h3>" + table(["Rule", "Time precision", "Time recall", "Onset p95 (s)", "Missed onsets", "False-on (s/h)"],
                             [[k, percentage(v.get("precision")), percentage(v.get("recall")),
                               v["onset_latency_s"].get("p95"), v["missed_onsets"], v.get("false_on_s_per_hour")]
                              for k, v in temporal["rules"].items()])
            if temporal.get("approach"):
                body += "<h3>Approaching Users</h3>" + table(["Category", "Precision", "Recall", "Lead-time median (s)", "ETA MAE (s)"],
                             [[k, percentage(v.get("precision")), percentage(v.get("recall")),
                               v.get("lead_time_s", {}).get("median"), v.get("eta_mae_s")]
                              for k, v in temporal["approach"].items()])
            body += "<h3>Expectations</h3>" + table(["Check", "Observed", "Expected", "Outcome"],
                        [[c["name"], c["got"], c["expected"], "PASS" if c["passed"] else "FAIL"] for c in checks])
            source = r.get("source", {})
            visibility = r.get("camera_visibility", source.get("first_visible_vehicles", []))
            if visibility:
                body += "<h3>Camera Visibility</h3>" + table(["Vehicle ID", "First visible (s)", "Distance to zebra (m)", "Under 10 m", "Visible pixels"],
                             [[v["id"], v["t"], v["distance_to_zebra_m"], v["late_under_10m"], v["pixels"]] for v in visibility])
            body += f"<p>Simulated {r.get('duration_s', 0):.2f}s in {r.get('wall_seconds', 0):.2f}s wall time. Render: {source.get('render_fps', 'n/a')} fps.</p>"
            for limitation in r.get("limitations", []):
                body += f"<p class='note'>{escaped(limitation)}</p>"
            if r.get("gates"):
                body += "<h3>Validation Gates</h3>" + table(["Gate", "Evidence / status"], r["gates"].items())
            cache = Path(r["cache"]) if r.get("cache") else None
            if cache and cache.is_dir():
                index = max(1, int(r.get("render", {}).get("frame_count", r.get("frames", 1))) // 2)
                image = cache / f"{index:06d}.jpg"
                if image.exists():
                    url = Path(os.path.relpath(image, path.parent)).as_posix()
                    body += f"<figure><img src='{escaped(url)}' width='640' height='480' loading='lazy' alt='Rendered camera frame for {escaped(r['scenario'])}'><figcaption>Raw rendered camera pixels, not detector overlays.</figcaption></figure>"
        sections.append(body + "</section>")
    payload = json.dumps(results, default=str).replace("<", "\\u003c")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("<!doctype html><html lang='en'><meta charset='utf-8'>"
                    "<meta name='viewport' content='width=device-width,initial-scale=1'>"
                    f"<title>{html.escape(title)}</title><style>"
                    "*{box-sizing:border-box;letter-spacing:0}body{font:14px system-ui;background:#f6f7f8;color:#20242a;margin:0;padding:24px;max-width:1400px;margin:auto}"
                    "h1{font-size:28px}h2{font-size:21px}h3{font-size:16px}a{color:#006979}.scroll{overflow:auto}"
                    "table{border-collapse:collapse;width:100%;background:white}td,th{padding:9px;border-bottom:1px solid #dce0e3;text-align:left}th{background:#edf0f1;white-space:nowrap}td{min-width:70px;overflow-wrap:anywhere}"
                    "section{border-top:2px solid #a6b3b8;margin-top:32px;padding-top:12px}figure{margin:16px 0}img{display:block;width:100%;max-width:480px;height:auto}figcaption{color:#525b65;font-size:12px}"
                    ".PASS{color:#087443}.FAIL,.ERROR{color:#b62236}.note{border-left:3px solid #ae7011;padding-left:12px}pre{white-space:pre-wrap;overflow-wrap:anywhere}"
                    "@media(max-width:600px){body{padding:12px}h1{font-size:24px}td,th{padding:7px}}"
                    "</style>" + f"<h1>{html.escape(title)}</h1>"
                    f"<p><strong>{passed}/{len(results)} scenarios PASS</strong>. Scenario PASS is not sim-to-real certification. G2-G6 need measured real evidence.</p>"
                    "<div class='scroll'><table><thead><tr><th>Scenario</th><th>Level</th><th>Outcome</th><th>Count accuracy</th><th>Direction accuracy</th><th>Predicted / GT</th><th>Failures</th></tr></thead><tbody>"
                    + "".join(rows) + "</tbody></table></div>" + "".join(sections) + "<details><summary>Reproducibility and full metrics</summary><pre id='metadata'></pre></details>"
                    + f"<script>document.getElementById('metadata').textContent=JSON.stringify({payload},null,2)</script></html>", encoding="utf-8")
