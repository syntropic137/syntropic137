#!/usr/bin/env bash
# `docker run -p` has the same defect one file over: the old gate required the
# argument to START with a digit or a `$`, so a quote in front of it was enough
# to skip the line entirely, and a dotted-quad prefix was accepted as "an
# interface" without ever asking WHICH interface. All five passed.
docker run -p 0.0.0.0:5432:5432 postgres
docker run --publish 0.0.0.0:5432:5432 postgres
docker run -p "[::]:5432:5432" postgres
docker run -d --name proxy -p "${PROXY_PORT}:8080" img
docker run -p '5432:5432' postgres
