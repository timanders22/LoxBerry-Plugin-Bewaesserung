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

# Anhalten ueber dienst.sh, nicht mit einem eigenen kill.
#
# Bis 0.9.0 stand hier: SIGTERM, zwei Sekunden warten, kill -9. Zwei Sekunden
# reichen nicht. Der Dienst prueft sein Halte-Merkmal zwar alle 0,5 s, aber
# ein laufender Rechengang blockiert die Schleife: die Abfrage bei Open-Meteo
# hat allein eine Zeitgrenze von 20 Sekunden.
#
# Was dabei NICHT passieren kann - anders als oft vermutet: eine kaputte
# verlauf.json. Der Dienst schreibt sie ueber eine Nebendatei und os.replace,
# und das ist auf Dateisystemebene unteilbar. Ein kill -9 mitten im Schreiben
# hinterlaesst die Nebendatei, nie eine halbe verlauf.json. Der Schaden eines
# harten Abschusses ist deshalb ein verlorener Rechengang, kein verlorener
# Wasserhaushalt.
#
# Trotzdem ist der harte Abschuss falsch, und dienst.sh stop laesst zehn
# Sekunden Zeit. Es entfernt ausserdem den Sollmerker, damit der Waechter aus
# dem Cron den Dienst nicht mitten im Update wieder hochzieht.
DIENST="$BASE/bin/plugins/$PFOLDER/dienst.sh"
PID="$BASE/data/plugins/$PFOLDER/dienst.pid"
# NEBEN das Datenverzeichnis, nicht hinein: der Installer raeumt
# data/plugins/<ordner>/ vollstaendig ab, bevor postinstall.sh laeuft.
# Gemessen am Installationsprotokoll vom 18.08.2026 (Zeilen 1148/1152).
MERKER="$BASE/config/plugins/$PFOLDER.backup.lief_vorher"

# Merken, ob der Dienst lief - und zwar VOR dem Anhalten.
#
# Das ist die Berichtigung eines Fehlers, der seit 0.9.0 in jedem Update
# steckte: 'dienst.sh stop' entfernt den Sollmerker (soll_laufen), und der
# minuetliche Waechter startet nur, wenn dieser Merker liegt. postinstall.sh
# ruft an keiner Stelle 'start' auf. Nach JEDEM Update stand das Plugin
# also still, bis jemand die Oberflaeche oeffnete und den Knopf drueckte -
# und weil der Endpunkt dann einfach den letzten Stand auslieferte, sah es
# in Loxone nicht nach einem Defekt aus, sondern nach einem ruhigen Garten.
rm -f "$MERKER"
if [ -x "$DIENST" ] && "$DIENST" status >/dev/null 2>&1; then
    : > "$MERKER"
    echo "<INFO> Der Dienst lief - er wird nach dem Update wieder gestartet."
fi

if [ -x "$DIENST" ]; then
    "$DIENST" stop >/dev/null 2>&1
    echo "<INFO> Laufender Dienst ueber dienst.sh angehalten."
elif [ -f "$PID" ]; then
    P=$(cat "$PID" 2>/dev/null)
    if [ -n "$P" ] && kill -0 "$P" 2>/dev/null; then
        kill "$P" 2>/dev/null || true
        i=0
        while [ $i -lt 15 ] && kill -0 "$P" 2>/dev/null; do
            sleep 1
            i=$((i + 1))
        done
        # Nummernrecycling ausschliessen, bevor mit -9 nachgesetzt wird.
        if kill -0 "$P" 2>/dev/null && grep -qa "bewaesserung_dienst.py" "/proc/$P/cmdline" 2>/dev/null; then
            kill -9 "$P" 2>/dev/null || true
        fi
    fi
    rm -f "$PID"
    echo "<INFO> Laufender Dienst angehalten (Rueckfallebene ohne dienst.sh)."
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
