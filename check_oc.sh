#!/bin/bash
docker run --rm --entrypoint /bin/bash \
  -v /home/weitian/claw/swe_rebench/bundle:/claw:ro \
  swerebench/sweb.eval.x86_64.0b01001001_1776_spectree-64 \
  -c '
export PATH="/usr/local/bin:/opt/conda/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"
bash /claw/setup.sh > /dev/null 2>&1
echo ===HELP===
openclaw --help 2>&1
echo ===VERSION===
openclaw --version 2>&1
'
