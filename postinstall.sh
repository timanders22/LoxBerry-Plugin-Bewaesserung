#!/bin/bash
# Bewaesserung vorausschauend - postinstall
# command <TEMPFOLDER> <NAME> <FOLDER> <VERSION> <BASEFOLDER>
#
# Der Dienst kommt mit der Standardbibliothek aus. Genau EIN Paket ist
# freiwillig: paho-mqtt, und nur dann, wenn Messwerte ueber MQTT kommen
# sollen. Fehlt es, laeuft alles Uebrige weiter - Open-Meteo und die
# HTTP-Quellen brauchen es nicht.

ARGV3=$3
ARGV5=$5
PFOLDER="${ARGV3:-bewaesserung}"
BASE="${ARGV5:-$LBHOMEDIR}"
if [ -z "$BASE" ] || [ ! -d "$BASE" ]; then
    SELF=$(cd "$(dirname "$0")" && pwd)
    BASE=$(cd "$SELF/../.." 2>/dev/null && pwd)
fi

PBIN="$BASE/bin/plugins/$PFOLDER"
PDATA="$BASE/data/plugins/$PFOLDER"
PLOG="$BASE/log/plugins/$PFOLDER"
PCONFIG="$BASE/config/plugins/$PFOLDER"
VENV="$PBIN/venv"

mkdir -p "$PDATA" "$PLOG" "$PCONFIG" || {
    echo "<FAIL> Ordner konnten nicht angelegt werden."
    exit 1
}
chmod 755 "$PDATA" "$PLOG" "$PCONFIG" 2>/dev/null

for f in bewaesserung.json zonen.json quellen_zuordnung.json; do
    [ -f "$PCONFIG/$f" ] || echo '{}' > "$PCONFIG/$f"
done
chmod 644 "$PCONFIG"/*.json 2>/dev/null

# Aus der Sicherung zurueckholen, wenn die Datei leer ist.
for f in bewaesserung.json zonen.json quellen_zuordnung.json; do
    BK="$BASE/config/plugins/$PFOLDER.backup.$f"
    CF="$PCONFIG/$f"
    if [ -f "$BK" ]; then
        INHALT=$(cat "$CF" 2>/dev/null)
        if [ ! -s "$CF" ] || [ "$INHALT" = "{}" ]; then
            cp -p "$BK" "$CF" && echo "<OK> $f aus Sicherung wiederhergestellt."
        fi
    fi
done
BKV="$BASE/config/plugins/$PFOLDER.backup.verlauf.json"
if [ -f "$BKV" ] && [ ! -f "$PDATA/verlauf.json" ]; then
    cp -p "$BKV" "$PDATA/verlauf.json"
    echo "<OK> Verlauf des Wasserhaushalts wiederhergestellt - die Bilanz laeuft weiter."
fi

# ---------- Python ----------
PY3=$(command -v python3)
if [ -z "$PY3" ]; then
    echo "<FAIL> python3 ist nicht vorhanden."
    exit 1
fi
PYVER=$("$PY3" -c 'import sys;print("%d.%d"%sys.version_info[:2])' 2>/dev/null)
echo "<INFO> Gefundenes Python: $PYVER"
"$PY3" -c 'import sys;sys.exit(0 if sys.version_info>=(3,8) else 1)' || {
    echo "<FAIL> Python 3.8 oder neuer wird gebraucht, gefunden wurde $PYVER."
    exit 1
}

# ---------- venv nur fuer das freiwillige Paket ----------
if [ ! -x "$VENV/bin/python3" ]; then
    if "$PY3" -m venv "$VENV" 2>/dev/null; then
        echo "<OK> Virtuelle Umgebung angelegt."
    else
        echo "<INFO> Virtuelle Umgebung liess sich nicht anlegen (python3-venv fehlt?)."
        echo "<INFO> Das Plugin laeuft trotzdem - dann aber ohne MQTT-Quellen."
    fi
fi
if [ -x "$VENV/bin/pip" ]; then
    if "$VENV/bin/pip" install --no-cache-dir paho-mqtt >/tmp/bew_pip.log 2>&1; then
        echo "<OK> Paket paho-mqtt eingerichtet - Messwerte koennen ueber MQTT kommen."
    else
        echo "<INFO> paho-mqtt liess sich nicht einrichten. Open-Meteo und die"
        echo "<INFO> HTTP-Quellen funktionieren trotzdem; MQTT-Quellen bleiben leer."
        tail -n 5 /tmp/bew_pip.log
    fi
    rm -f /tmp/bew_pip.log
fi

chmod 755 "$PBIN/dienst.sh" 2>/dev/null
chmod 755 "$PBIN"/*.py 2>/dev/null

# ---------- MQTT-Gateway ----------
MSDATEI="$BASE/config/system/general.json"
if [ -f "$MSDATEI" ] && grep -q '"Gatewayautostart": *1' "$MSDATEI"; then
    echo "<OK> Das MQTT-Gateway steht auf Autostart."
else
    echo "<INFO> Das MQTT-Gateway ist nicht auf Autostart. Unter System,"
    echo "<INFO> MQTT Gateway einschalten - sonst kommt am Miniserver nichts an."
fi

# ---------- Selbsttest ----------
echo "<INFO> Selbsttest:"
"$PY3" "$PBIN/bewaesserung_dienst.py" --selbsttest 2>&1 | head -n 25 | sed 's/^/<INFO> /' || true

echo "<INFO> Naechste Schritte:"
echo "<INFO>   1. Reiter Einstellungen: Standort eintragen (ohne ihn keine Strahlung)"
echo "<INFO>   2. Reiter Quellen: Wetterstation zuordnen - oder bei Open-Meteo bleiben"
echo "<INFO>   3. Reiter Zonen: je Kreis Flaeche, Bepflanzung und Boden eintragen"
echo "<INFO>   4. Becherprobe machen - ohne sie sind Liter und Minuten geschaetzt"
echo "<INFO>   5. Reiter MQTT: das Abo im Gateway eintragen"
echo "<OK> Installation abgeschlossen."
exit 0
