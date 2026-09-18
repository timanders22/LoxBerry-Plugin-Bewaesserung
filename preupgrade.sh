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
if [ -z "$BASE" ] || [ ! -f "$BASE/config/system/general.json" ]; then
    echo "<FAIL> Der LoxBerry-Ordner ist nicht bestimmbar ($BASE) - es wird NICHTS gesichert."
    # exit 2, nicht 1.
    #
    # Gemessen an sbin/plugininstall.pl eines LoxBerry 4, Zeilen
    # 854-864: Rueckgabewert 1 erzeugt nur eine Fehlerzeile und ein
    # push(@errors,...), 'exit > 1' ruft &fail(). Unmittelbar danach steht
    # bei :872-874 "# Purge old installation" und &purge_installation. Mit
    # 'exit 1' sagte dieses Skript also "es wird NICHTS gesichert" - und
    # liess anschliessend genau das geschehen, wovor es warnt:
    # config/plugins/<x>/ und data/plugins/<x>/ waren weg, samt
    # Aktionstoken, Zonen, Quellenzuordnung und Wasserhaushalt.
    #
    # Zusaetzlich wird jetzt gegen config/system/general.json geprueft: ein
    # LoxBerry hat sie immer, ein Rest aus einem Pruefstand nie.
    exit 2
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
BW_SKRIPT="$BASE/bin/plugins/$PFOLDER/bewaesserung_dienst.py"
# Dieses Skript ruft der Installer als root. Der Dienst gehoert loxberry -
# wo es den Benutzer nicht gibt, dem eigenen.
BW_UID=$(id -u loxberry 2>/dev/null || id -u)

# Ist die Nummer $1 GENAU dieser Dienst? Argumentweise, nicht als Suche
# ueber die ganze Befehlszeile: argv[0] ist ein python-Interpreter, argv[1]
# ist der eigene Dienstpfad, ein drittes Argument gibt es nicht.
# Wortgleich mit bw_ist_dienst() in bin/dienst.sh; Bauart:
# LoxBerry-Plugin-APC-UPS-1.2.11 (apc_ist_dienst).
bw_ist_dienst() {   # $1 Nummer, $2 UID des Dienstbenutzers ("" = nicht pruefen)
    [ -r "/proc/$1/cmdline" ] || return 1
    tr '\0' '\n' 2>/dev/null < "/proc/$1/cmdline" | {
        IFS= read -r a0 || exit 1
        IFS= read -r a1 || exit 1
        IFS= read -r a2 && exit 1
        case "${a0##*/}" in
            python|python3|python3.[0-9]|python3.[0-9][0-9]) ;;
            *) exit 1 ;;
        esac
        [ "$a1" = "$BW_SKRIPT" ]
    } || return 1
    [ -z "$2" ] && return 0
    [ "$(stat -c %u "/proc/$1" 2>/dev/null)" = "$2" ]
}

# Alle eigenen Dienste, eine Nummer je Zeile. Rein lesend.
bw_dienste_suchen() {
    for BW_D in /proc/[0-9]*; do
        BW_P=${BW_D#/proc/}
        bw_ist_dienst "$BW_P" "$BW_UID" && echo "$BW_P"
    done
    return 0
}
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
# Die Meldung haengt am MERKER, nicht am Rueckgabewert von stop.
#
# `anhalten()` in dienst.sh gibt auch dann 0 zurueck, wenn gar kein
# Dienst lief („laeuft nicht", return 0) - diese Bedingung war also
# immer wahr, und das Installationsprotokoll meldete bei jedem Update
# einen angehaltenen Dienst. Gemessen am 11.09.2026 ueber den Bestand;
# derselbe Fehler steckte in vier Linien.
if [ -x "$DIENST" ] && "$DIENST" stop >/dev/null 2>&1; then
    if [ -f "$MERKER" ]; then
        echo "<INFO> Laufender Dienst ueber dienst.sh angehalten."
    else
        echo "<INFO> Der Dienst lief nicht - es war nichts anzuhalten."
    fi
else
    # Rueckfallebene: dienst.sh fehlt oder sein 'stop' ist gescheitert.
    #
    # Beendet wird nur, was argumentweise als eigener Dienst erkannt ist -
    # nicht, was in der PID-Datei steht. Bis 0.9.29 genuegten die Nummer
    # aus der Datei und ein 'kill -0'; ein fremder Vorgang, der die Nummer
    # geerbt hatte, bekam SIGTERM. Gemessen am 18.09.2026 in WSL
    # (Bestand-2026-09-18/klasse-F, Fall 8 des Pruefstands): ein
    # 'sleep 600' mit seiner Nummer in dienst.pid war nach diesem Skript
    # tot. Die Probe auf die Befehlszeile gab es nur vor dem 'kill -9',
    # nicht vor dem SIGTERM davor.
    #
    # Gesucht wird ueber /proc, nicht ueber die PID-Datei: der Installer
    # loescht data/plugins/<x>/ beim Upgrade, ein Dienst ohne Eintrag war
    # hier sonst unsichtbar und haette waehrend des Updates weiter in den
    # Datenordner geschrieben.
    BW_ZIEL=$(bw_dienste_suchen)
    if [ -n "$BW_ZIEL" ]; then
        for P in $BW_ZIEL; do
            bw_ist_dienst "$P" "$BW_UID" && kill "$P" 2>/dev/null
        done
        i=0
        while [ $i -lt 15 ] && [ -n "$(bw_dienste_suchen)" ]; do
            sleep 1
            i=$((i + 1))
        done
        # Nummernrecycling ausschliessen, bevor mit -9 nachgesetzt wird:
        # die Befehlszeile wird VOR diesem Signal erneut gelesen.
        for P in $(bw_dienste_suchen); do
            bw_ist_dienst "$P" "$BW_UID" && kill -9 "$P" 2>/dev/null
        done
        # Nur hier gemeldet: eine liegengebliebene PID-Datei allein ist
        # kein laufender Dienst.
        echo "<INFO> Laufender Dienst angehalten (Rueckfallebene ohne dienst.sh)."
    elif [ -f "$PID" ]; then
        echo "<INFO> Die Nummer aus $(basename "$PID") gehoert keinem eigenen Dienst -"
        echo "<INFO> es wurde nichts beendet, die Datei wird entfernt."
    fi
    rm -f "$PID"
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
# 0600 auch hier. Die Schleife darueber setzt es, diese Kopie liess es
# bis 0.9.20 aus - und "cp -p" erbt die Rechte der Quelle, die in
# data/plugins/ 0664 ist. Am Geraet gemessen (06.09.2026): von vier
# Zweitschriften dieser Linie stand genau diese eine auf 0664. Im
# Verlauf steht kein Token, aber der Konfigurationszweig ist 0600, und
# eine Ausnahme, die niemand beabsichtigt hat, ist keine.
VL="$BASE/data/plugins/$PFOLDER/verlauf.json"
VLB="$BASE/config/plugins/$PFOLDER.backup.verlauf.json"
if [ -f "$VL" ] && cp -p "$VL" "$VLB"; then
    chmod 600 "$VLB" 2>/dev/null
    echo "<INFO> Verlauf des Wasserhaushalts gesichert."
fi
# Die WIRKUNG pruefen, nicht den Rueckgabewert: liegt hinterher etwas da?
#
# Scheiterte 'cp' (volles Dateisystem, Rechte), fehlte bis 0.9.21 nur eine
# <INFO>-Zeile, und 'exit 0' am Ende meldete Erfolg - waehrend der Purge
# gleich danach das Original loeschte.
BW_FEHLT=""
for f in bewaesserung.json zonen.json quellen_zuordnung.json; do
    if [ -f "$BASE/config/plugins/$PFOLDER/$f" ] \
       && [ ! -f "$BASE/config/plugins/$PFOLDER.backup.$f" ]; then
        BW_FEHLT="$BW_FEHLT $f"
    fi
done
if [ -n "$BW_FEHLT" ]; then
    echo "<FAIL> Nicht gesichert:$BW_FEHLT - das Update wird abgebrochen, damit der Purge die Originale nicht loescht."
    exit 2
fi
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
