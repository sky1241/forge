#!/bin/bash
# forge demo — record with asciinema for the README:
#   asciinema rec /tmp/forge-demo.cast -c 'bash scripts/demo.sh'
#   asciinema upload /tmp/forge-demo.cast        # → asciinema.org link
#
# Embed the link in README with the asciicast badge syntax:
#   [![asciicast](https://asciinema.org/a/<id>.svg)](https://asciinema.org/a/<id>)
#
# This script targets examples/calculator/ — must be run from forge repo root.
set -e

cd examples/calculator

if [ -d .git ]; then
    rm -rf .git baseline.json .forge
fi
git init -q
git config user.email demo@forge.local
git config user.name forge-demo

echo "$ ls"
ls
sleep 1.5
echo ""

echo "$ git add . && git commit -m init"
git add . && git commit -q -m "init"
sleep 1
echo ""

echo "$ forge --baseline"
forge --baseline 2>&1 | tail -8
sleep 2
echo ""

echo "# now we introduce a regression: change 'a + b' to 'a - b'"
echo "$ sed -i 's/return a + b/return a - b/' calculator.py"
sed -i 's/return a + b/return a - b/' calculator.py
sleep 1.5
echo ""

echo "$ forge"
forge 2>&1 | tail -20 || true
sleep 3
echo ""

echo "# regression detected, exit code != 0 → CI fails"
echo "$ git checkout calculator.py    # restore"
git checkout calculator.py
sleep 1.5
echo ""

echo "# Find files most likely to contain bugs"
echo "$ forge --carmack"
forge --carmack 2>&1 | tail -15 || true
sleep 3
echo ""

echo "# That's it — forge-shield in 60 seconds. See https://github.com/sky1241/forge"
sleep 2
