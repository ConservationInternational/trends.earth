#!/usr/bin/env bash
echo "🪛 Running QGIS with the TRENDS profile:"
echo "--------------------------------"
echo "Do you want to enable debug mode?"
choice=$(gum choose "🪲 Yes" "🐞 No" )
case $choice in
	"🪲 Yes") DEBUG_MODE=1 ;;
	"🐞 No") DEBUG_MODE=0 ;;
esac

# Running on local used to skip tests that will not work in a local dev env
TRENDS_LOG=$HOME/TRENDS.log
rm -f $TRENDS_LOG
#nix-shell -p \
#  This is the old way using default nix packages with overrides
#  'qgis.override { extraPythonPackages = (ps: [ ps.pyqtwebengine ps.jsonschema ps.debugpy ps.future ps.psutil ]);}' \
#  --command "TRENDS_LOG=${TRENDS_LOG} TRENDS_DEBUG=${DEBUG_MODE} RUNNING_ON_LOCAL=1 qgis --profile TRENDS2"

# This is the new way, using Ivan Mincis nix spatial project and a flake
# see flake.nix for implementation details
TRENDS_LOG=${TRENDS_LOG} TRENDS_DEBUG=${DEBUG_MODE} RUNNING_ON_LOCAL=1 \
      nix run .#default -- qgis --profile TRENDS
