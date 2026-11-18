#!/bin/bash
cd /e/procon
IDS=3,5,0,1,2,4,12,15
for cfg in "BEAM=1 ILS=1" "BEAM=0 ILS=1" "BEAM=1 ILS=0" "BEAM=0 ILS=0"; do
  set -- $cfg
  echo "== $cfg"
  env HEX_${1} HEX_${2} HEX_STEPS=50,200 HEX_ES=0 HEX_HORIZON=0 PYTHONIOENCODING=utf-8 python bench_wide.py 0 400 $IDS | tail -1
done
