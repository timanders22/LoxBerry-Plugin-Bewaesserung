#!/bin/bash
# Bewaesserung vorausschauend - preupgrade
# command <TEMPFOLDER> <NAME> <FOLDER> <VERSION> <BASEFOLDER>
#
# Gesichert werden Konfiguration, Zonen, Quellenzuordnung UND der Verlauf.
# Der Verlauf ist der Wasserhaushalt der letzten Wochen - geht er verloren,
# faengt die Bilanz bei Null an und giesst erst einmal zu wenig.
ARGV3=$3
ARGV5=$5
PFOLDER="${ARGV3:-bewaesserung}"
BASE="${ARGV5:-$LBHOMEDIR}"

PID="$BASE/data/plugins/$PFOLDER/dienst.pid"
if [ -f "$PID" ]; then
    kill "$(cat "$PID")" 2>/dev/null || true
    sleep 2
    kill -9 "$(cat "$PID")" 2>/dev/null || true
    rm -f "$PID"
    echo "<INFO> Laufender Dienst angehalten."
fi

for f in bewaesserung.json zonen.json quellen_zuordnung.json; do
    CF="$BASE/config/plugins/$PFOLDER/$f"
    [ -f "$CF" ] && cp -p "$CF" "$BASE/config/plugins/$PFOLDER.backup.$f" \
        && echo "<INFO> $f gesichert."
done
VL="$BASE/data/plugins/$PFOLDER/verlauf.json"
[ -f "$VL" ] && cp -p "$VL" "$BASE/config/plugins/$PFOLDER.backup.verlauf.json" \
    && echo "<INFO> Verlauf des Wasserhaushalts gesichert."
echo "<OK> preupgrade abgeschlossen."
exit 0
