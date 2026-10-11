"""Real GPU/RGB/NN checks of all five intersection cameras; keep generated pixels in runs/."""
from pathlib import Path
import argparse
import json
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from sim.intersection.geometry import ARMS
from sim.intersection.world import IntersectionWorld
from sim.intersection.render_source import IntersectionRenderer,CAMERAS


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out",default="runs/intersection-render-check")
    parser.add_argument("--model",default="models/yolo11n_320.onnx")
    parser.add_argument("--condition",choices=["day","night","rain","fog"],default="day")
    args=parser.parse_args()
    output=Path(args.out);output.mkdir(parents=True,exist_ok=True)
    world=IntersectionWorld("empty")
    for arm in ARMS:
        for turn in ("straight","left"):
            route=world.geometry.routes[f"{arm}_{turn}"]
            world.spawn_vehicle(arm,turn,s=route.stop_s-7)
        for direction in (-1,1):
            walker=world.spawn_pedestrian(arm,direction=direction)
            walker.s=4 if direction==1 else 0
            world._locate(walker)
    renderer=IntersectionRenderer(world.geometry,detector="real",model=args.model,condition=args.condition)
    results=[]
    try:
        for i,camera in enumerate(CAMERAS):
            snapshot=world.snapshot();snapshot["t"]=i+1.
            jpg,raw,stats,labels=renderer.capture(snapshot,camera)
            (output/f"{camera}-detector.jpg").write_bytes(jpg)
            (output/f"{camera}-raw.jpg").write_bytes(raw)
            assert stats["projection_error_px"]<1
            assert any(label["pixels"]>0 and label["box"] for label in labels)
            results.append({"camera":camera,"projection_error_px":stats["projection_error_px"],
                "visible_agents":sum(label["pixels"]>0 for label in labels),
                "predictions":len(stats["predictions"]),"tracks":len(stats["tracks"])})
        assert sum(row["predictions"] for row in results)>0,"real model returned no predictions on any camera"
        report={"views":results,"run":renderer.report(),"javascript_errors":renderer.errors,
                "note":"Five staged camera frames, not a closed-loop vision-controller or field-transfer validation."}
        (output/"report.json").write_text(json.dumps(report,indent=2),encoding="utf-8")
        print(json.dumps({"views":results,"gpu":renderer.info["gpu"],"javascript_errors":renderer.errors},indent=2))
    finally:
        renderer.close()


if __name__=="__main__": main()
