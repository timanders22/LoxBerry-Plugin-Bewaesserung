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
# Ohne diese Rueckfallebene arbeitet das Skript bei leerem $BASE als root
# auf /data/plugins/... - es legte Verzeichnisse im Wurzelverzeichnis an,
# und KEINE Sicherung griff. postinstall.sh und uninstall haben sie seit
# jeher, hier fehlte sie.
if [ -z "$BASE" ] || [ ! -d "$BASE" ]; then
    SELF=$(cd "$(dirname "$0")" && pwd)
    BASE=$(cd "$SELF/../.." 2>/dev/null && pwd)
fi
if [ -z "$BASE" ] || [ ! -d "$BASE" ]; then
    echo "<FAIL> Der LoxBerry-Ordner ist nicht bestimmbar - es wird NICHTS gesichert."
    exit 1
fi

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

# Der Rueckgabewert von stop entscheidet. Bis 0.9.18 lief die
# Rueckfallebene nur, wenn dienst.sh FEHLTE - scheiterte das Anhalten,
# schrieb der Dienst waehrend des Updates weiter in data/plugins/<x>/.
if [ -x "$DIENST" ] && "$DIENST" stop >/dev/null 2>&1; then
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
    # 0600 auch auf die Zweitschrift: cp -p erbt die Rechte der Quelle,
    # und in bewaesserung.json steht das Aktionstoken.
    if [ -f "$CF" ] && cp -p "$CF" "$BASE/config/plugins/$PFOLDER.backup.$f"; then
        chmod 600 "$BASE/config/plugins/$PFOLDER.backup.$f" 2>/dev/null
        echo "<INFO> $f gesichert."
    fi
done
VL="$BASE/data/plugins/$PFOLDER/verlauf.json"
[ -f "$VL" ] && cp -p "$VL" "$BASE/config/plugins/$PFOLDER.backup.verlauf.json" \
    && echo "<INFO> Verlauf des Wasserhaushalts gesichert."
echo "<OK> preupgrade abgeschlossen."

# ---------- Langzeitwerte retten ----------
# die Tageshoechst- und -tiefstwerte, aus denen die Bilanz waechst.
# Der Installer loescht data/plugins/<x>/ bei JEDEM Update - gemessen an
# sbin/plugininstall.pl (Zweig master, 23.08.2026): &purge_installation steht
# im Upgrade-Zweig (:886), und ihr Rumpf loescht ohne Bedingung (:1631).
# Deshalb NEBEN den Ordner: "rm -rf .../<x>/" trifft den Nachbarn mit dem
# Punkt nicht. postinstall.sh holt ihn zurueck und raeumt ihn weg.
LANG_SICHER="$BASE/data/plugins/$PFOLDER.upgrade_sicherung"
mkdir -p "$LANG_SICHER" 2>/dev/null
chmod 0700 "$LANG_SICHER" 2>/dev/null
# nachtplan.json gehoert dazu: ein Update im Giessfenster raeumte ihn
# weg, der Dienst fror einen NEUEN Plan ein, und die Zahl, gegen die
# Loxone bereits zaehlt, aenderte sich mitten in der Nacht - das
# Gegenteil dessen, was das Einfrieren zusagt. zustand.json traegt die
# Meldezaehler; ohne ihn verschiebt sich jede Dauerstoerungsmeldung um
# die verlorenen Tage.
for LANG_F in tagesextreme.json nachtplan.json zustand.json; do
    [ -f "$BASE/data/plugins/$PFOLDER/$LANG_F" ] \
        && cp -p "$BASE/data/plugins/$PFOLDER/$LANG_F" "$LANG_SICHER/$LANG_F" 2>/dev/null
done
# Die Wirkung pruefen, nicht den Rueckgabewert: liegt hinterher etwas da?
if [ -n "$(ls -A "$LANG_SICHER" 2>/dev/null)" ]; then
    echo "<OK> Langzeitwerte gesichert."
fi
exit 0
