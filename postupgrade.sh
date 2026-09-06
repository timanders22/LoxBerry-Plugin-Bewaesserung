#!/bin/bash
# Bewaesserung vorausschauend - postupgrade
# command <TEMPFOLDER> <NAME> <FOLDER> <VERSION> <BASEFOLDER>
SELF=$(cd "$(dirname "$0")" && pwd)
# Geprueft wird, ob die Datei DA ist - nicht, ob sie das Ausfuehrungsbit
# traegt. Kam sie ohne aus dem Archiv (ZIP-Umweg, Windows-Zwischenstation,
# unzip ohne -X), lief bis 0.9.18 KEINE der sechs Rueckholungen, und die
# Meldung nannte dazu die falsche Ursache: die Datei war da, nur nicht
# ausfuehrbar. Die Schale stellt den Interpreter selbst.
if [ -f "$SELF/postinstall.sh" ]; then
    bash "$SELF/postinstall.sh" "$@"
    exit $?
fi
echo "<FAIL> postinstall.sh liegt nicht neben diesem Skript - Upgrade unvollstaendig."
exit 1
