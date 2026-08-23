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
# 0600, nicht 0644: in bewaesserung.json steht das Aktionstoken.
chmod 600 "$PCONFIG"/*.json 2>/dev/null

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

# ---------- Eigentuemer richtigstellen ----------
#
# Das hier ist die wichtigste Zeile dieses Skripts, und sie fehlte bis 0.9.0.
#
# LoxBerry fuehrt postinstall.sh als root aus. Alles, was hier entsteht,
# gehoert danach root: die mit 'echo {} >' angelegten Konfigurationsdateien
# ebenso wie die mit 'cp -p' aus der Sicherung zurueckgeholten - cp -p
# uebernimmt zwar Rechte und Zeitstempel, aber der Eigentuemer richtet sich
# nach dem, der kopiert.
#
# Oberflaeche und Dienst laufen als loxberry. Mit root-eigenen Dateien
# konnte die Oberflaeche sie zwar LESEN (0644), aber nicht schreiben. Wer
# nach der Installation eine Zone anlegte, klickte auf Speichern und bekam
# eine Fehlermeldung - oder schlimmer: gar keine, weil das Schreiben mit @
# unterdrueckt war. Das betraf nicht nur das Update, sondern schon die
# Erstinstallation.
if id loxberry >/dev/null 2>&1; then
    chown -R loxberry:loxberry "$PCONFIG" "$PDATA" "$PLOG" "$PBIN" 2>/dev/null
    for BKD in "$BASE/config/plugins/$PFOLDER".backup.*; do
        [ -e "$BKD" ] && chown loxberry:loxberry "$BKD" 2>/dev/null
    done
    echo "<OK> Eigentuemer der Konfigurations-, Daten- und Protokolldateien: loxberry."
else
    echo "<INFO> Benutzer loxberry nicht gefunden - Eigentuemer nicht geaendert."
fi

# ---------- Python ----------
PY3=$(command -v python3)
if [ -z "$PY3" ]; then
    echo "<FAIL> python3 ist nicht vorhanden."
    exit 1
fi
PYVER=$("$PY3" -c 'import sys;print("%d.%d"%sys.version_info[:2])' 2>/dev/null)
echo "<INFO> Gefundenes Python: $PYVER"
# Untergrenze 3.8 - und die bleibt so.
#
# Der Quelltext kommt mit 3.8 aus: 'from __future__ import annotations' macht
# die Schreibweisen 'float | None' und 'dict[str, Any]' zu blossen
# Zeichenketten, die zur Laufzeit gar nicht ausgewertet werden, und
# asyncio.run gibt es seit 3.7. Die Untergrenze anzuheben, weil LoxBerry 3
# ohnehin Python 3.9 mitbringt, wuerde also nichts gewinnen und nur
# Installationen ausschliessen, auf denen das Plugin laufen wuerde.
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

# ---------- Dienst wieder starten, wenn er vorher lief ----------
#
# Nur dann. Eine Neuinstallation startet NICHTS von selbst: der Anwender
# soll erst Standort, Quellen und Zonen eintragen. Wer den Dienst vorher
# bewusst angehalten hatte, findet ihn nach dem Update ebenfalls angehalten.
MERKER="$BASE/config/plugins/$PFOLDER.backup.lief_vorher"
if [ -f "$MERKER" ]; then
    rm -f "$MERKER"
    if [ -x "$PBIN/dienst.sh" ]; then
        if "$PBIN/dienst.sh" start >/dev/null 2>&1; then
            echo "<OK> Der Dienst lief vor dem Update und wurde wieder gestartet."
        else
            echo "<INFO> Der Dienst liess sich nicht starten - Reiter Einstellungen,"
            echo "<INFO> Knopf 'Dienst starten'. Der Grund steht im Reiter Logdateien."
        fi
    fi
fi

echo "<INFO> Naechste Schritte:"
echo "<INFO>   1. Reiter Einstellungen: Standort eintragen (ohne ihn keine Strahlung)"
echo "<INFO>   2. Reiter Quellen: Wetterstation zuordnen - oder bei Open-Meteo bleiben"
echo "<INFO>   3. Reiter Zonen: je Kreis Flaeche, Bepflanzung und Boden eintragen"
echo "<INFO>   4. Becherprobe machen - ohne sie sind Liter und Minuten geschaetzt"
echo "<INFO>   5. Reiter MQTT: das Abo im Gateway eintragen"
echo "<OK> Installation abgeschlossen."

# ---------- Langzeitwerte zurueckholen ----------
# Gegenstueck zu preupgrade.sh. Zwischen beiden Skripten hat der Installer
# data/plugins/<x>/ vollstaendig geloescht; der Nachbar mit dem Punkt hat es
# ueberstanden. Zurueckgeholt wird nur, was fehlt - eine Neuinstallation
# findet nichts vor und faengt sauber bei null an.
LANG_SICHER="$BASE/data/plugins/$PFOLDER.upgrade_sicherung"
if [ -d "$LANG_SICHER" ]; then
    for LANG_F in tagesextreme.json; do
        if [ -f "$LANG_SICHER/$LANG_F" ] \
           && [ ! -s "$BASE/data/plugins/$PFOLDER/$LANG_F" ]; then
            mkdir -p "$BASE/data/plugins/$PFOLDER" 2>/dev/null
            cp -p "$LANG_SICHER/$LANG_F" "$BASE/data/plugins/$PFOLDER/$LANG_F" \
                2>/dev/null && echo "<OK> $LANG_F ueber das Update gerettet."
        fi
    done
    rm -rf "$LANG_SICHER" 2>/dev/null
fi
exit 0
