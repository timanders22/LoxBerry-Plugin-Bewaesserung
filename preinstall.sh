#!/bin/bash
# Bewaesserung vorausschauend - preinstall
# command <TEMPFOLDER> <NAME> <FOLDER> <VERSION> <BASEFOLDER>
#
# Neu in 0.9.35 (I1, Entscheidung 1 vom 29.09.2026), Bauart AudiConnect
# 0.9.22. Der Installer ruft dieses Skript bei JEDEM Einbau auf, nach dem
# Aufraeumen der alten Fassung und VOR dem Kopieren von Konfiguration,
# Cron-Datei und Oberflaeche (sbin/plugininstall.pl: preupgrade :846,
# purge :874, preinstall :877).
#
# Eine Aktualisierung erkennt es allein an der Marke
# data/plugins/<ordner>.upgrade_laeuft, die preupgrade.sh als Erstes anlegt
# (kein Altersvergleich). Dann tut es nichts: die Zweitschriften und die
# Update-Sicherung braucht postinstall.sh.
#
# Ohne Marke ist es eine NEUINSTALLATION. Liegengebliebene Zweitschriften
# einer frueheren Installation (config/plugins/<ordner>.backup.*: die
# Konfiguration mit dem Aktionstoken, Zonen, Quellenzuordnung, Verlauf) und
# die Update-Sicherung (data/plugins/<ordner>.upgrade_sicherung) gehen nach
# <name>.alt, der Startmerker .backup.lief_vorher wird entfernt, gemeldet mit
# genau einer <WARNING>. Bis 0.9.34 spielte postinstall.sh sie ungefragt
# zurueck, und schon der erste Seitenaufruf holte das alte Token aus
# <ordner>.backup.json (Pruefbericht Installer). Die Bibliothek und der
# Dienst lesen .alt nie; die Deinstallation raeumt es ab.
ARGV3=$3
ARGV5=$5
PFOLDER="${ARGV3:-bewaesserung}"
BASE="${ARGV5:-$LBHOMEDIR}"
# Wurzelsuche wie in den uebrigen Hakenskripten: ohne config/plugins,
# data/plugins UND config/system/general.json wird nichts angefasst.
if [ -z "$BASE" ] || [ ! -d "$BASE/config/plugins" ] || [ ! -d "$BASE/data/plugins" ] \
   || [ ! -f "$BASE/config/system/general.json" ]; then
    echo "<WARNING> Kein LoxBerry-Wurzelverzeichnis erkannt ('$BASE') - nichts beiseitegelegt."
    exit 0
fi
case "$PFOLDER" in
    ''|*/*|*..*) echo "<WARNING> Unzulaessiger Ordnername '$PFOLDER' - nichts beiseitegelegt."; exit 0 ;;
esac
[ -f "$BASE/data/plugins/$PFOLDER.upgrade_laeuft" ] && exit 0

BEISEITE=""
FEST=""
# Der Startmerker gehoert zu einer Aktualisierung - ohne Marke weg damit.
MERKER="$BASE/config/plugins/$PFOLDER.backup.lief_vorher"
if [ -e "$MERKER" ] || [ -L "$MERKER" ]; then
    rm -f "$MERKER" && BEISEITE="$BEISEITE (Startmerker $(basename "$MERKER") entfernt)"
fi
for ZIEL in "$BASE/config/plugins/$PFOLDER".backup.* "$BASE/data/plugins/$PFOLDER.upgrade_sicherung"; do
    [ -e "$ZIEL" ] || [ -L "$ZIEL" ] || continue
    case "$ZIEL" in *.alt) continue ;; esac
    rm -rf "${ZIEL:?}.alt" 2>/dev/null
    if mv -f "$ZIEL" "$ZIEL.alt" 2>/dev/null; then
        BEISEITE="$BEISEITE $(basename "$ZIEL").alt"
        [ -f "$ZIEL.alt" ] && [ ! -L "$ZIEL.alt" ] && chmod 600 "$ZIEL.alt" 2>/dev/null
    else
        FEST="$FEST $ZIEL"
    fi
done
if [ -n "$BEISEITE" ] || [ -n "$FEST" ]; then
    T="<WARNING> Neuinstallation: Einstellungen, Token und Verlauf einer frueheren Installation werden NICHT eingespielt."
    [ -n "$BEISEITE" ] && T="$T Beiseitegelegt:$BEISEITE (die Deinstallation raeumt sie ab)."
    [ -n "$FEST" ] && T="$T Nicht zu verschieben, bitte von Hand entfernen:$FEST"
    echo "$T"
fi
exit 0
