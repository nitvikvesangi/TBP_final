#!/bin/bash
#
# STOP — double-click to shut the receiver down.
# The board keeps working on its own; it just stops streaming to the dashboard.

set -uo pipefail
cd "$(dirname "$0")" || exit 1

./start.sh --stop
echo
[ "${PAUSE:-1}" = 0 ] || { read -n 1 -s -r -p "Press any key to close this window"; echo; }
