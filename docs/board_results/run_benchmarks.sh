#!/usr/bin/env bash
# Run on the UNO Q from ~/occhio. No camera/pipeline competes with inference.
# Each backend gets its own process so an optional NCNN crash cannot erase ONNX results.
set -uo pipefail
cd /home/arduino/occhio
date -Is
for z in /sys/class/thermal/thermal_zone*; do
  printf '%s ' "$z"
  cat "$z/type" "$z/temp"
done
ps -eo pid,pcpu,comm --sort=-pcpu | head -12
timeout 1200 .venv/bin/python -u tools/bench.py --models models/*.onnx --threads 2 3 4
echo "onnx_exit=$?"
cp runs/bench_*.json runs/bench_*.md docs/board_results/
for model in models/*_ncnn_model; do
  timeout 300 .venv/bin/python -u tools/bench.py --models "$model" --threads 2 3 4
  echo "ncnn_exit=$? model=$model"
  cp runs/bench_*.json runs/bench_*.md docs/board_results/
done
date -Is
touch docs/board_results/benchmarks.done
