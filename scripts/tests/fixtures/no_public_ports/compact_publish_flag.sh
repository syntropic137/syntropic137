#!/usr/bin/env bash
# `-p5432:5432`, with no separator between the flag and its argument, is a
# spelling docker accepts and the first YAML-aware version of this gate did
# not: its flag pattern required `[=\s]+` after the flag, so every line below
# matched nothing at all and the file exited 0. `--publish=5432:5432` WAS
# rejected by that same version, which is the worst shape for this defect -
# the gate looked like it understood the flag, and which spelling you happened
# to write decided whether it was checked.
docker run -p5432:5432 postgres
docker run -p"0.0.0.0:5432:5432" postgres
docker run -p'[::]:5432:5432' postgres
