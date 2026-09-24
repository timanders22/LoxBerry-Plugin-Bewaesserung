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
# Fail-closed - preupgrade.sh und uninstall haben diese Bremse seit jeher,
# hier fehlte sie (der Kommentar in preupgrade.sh:14 behauptete das
# Gegenteil). '$0' ist der Arbeitsordner des Installateurs unter /tmp;
# '$SELF/../..' ergibt dann '/tmp' - ein Verzeichnis, das '[ -d ]' besteht.
# Ein LoxBerry hat immer config/system/general.json; ein Rest hat sie nie.
if [ -z "$BASE" ] || [ ! -f "$BASE/config/system/general.json" ]; then
    echo "<FAIL> Der LoxBerry-Ordner ist nicht bestimmbar ($BASE) - es wird NICHTS angelegt."
    exit 2
fi

# ---------- Die Marke "Aktualisierung laeuft" faellt hier ----------
# Dieses Skript ist das LETZTE, das LoxBerry in dieser Linie aufruft:
# preroot, preinstall, preupgrade, postinstall, postupgrade, postroot
# (Regeln/06) - postupgrade.sh und postroot.sh gibt es hier nicht.
#
# Entfernt wird sie ueber einen trap auf EXIT, nicht am Dateiende: dieses
# Skript steigt an mehreren Stellen mit 'exit 1' aus (Ordner, python3,
# Python zu alt). Ohne trap bliebe der Dienst danach eine Stunde gesperrt,
# ohne dass irgendwo stuende, warum (Fall C12). Eine Kommandoersetzung oder
# Unterschale loest den EXIT-Trap nicht aus (Regeln/06, bash 5.2) - die
# Marke faellt also nicht zu frueh.
#
# Der trap laeuft NACH dem Dienststart am Ende; der eigene Start bekommt
# dafuer die Ausnahme BW_START_TROTZ_MARKE=1 (bin/dienst.sh, marke_sperrt()).
# Zwischen dem "touch soll_laufen" in bin/dienst.sh und dem Augenblick, in
# dem der neue Prozess als Dienst erkennbar ist, koennte der Minutentakt
# denselben Dienst ein zweites Mal starten; solange die Marke liegt, ist
# dieses Fenster zu. Gemessen (Pruefung-Bewaesserung-0.9.30,
# messe_reihenfolge.sh, vier Waechterschleifen ohne Pause waehrend
# postinstall.sh): in dieser Linie trat der Doppelstart in KEINER Reihenfolge
# auf - je 0 von 15 Runden mit der Marke danach, mit der Marke davor und ganz
# ohne Marke; starten() fragt vor dem Start ein zweites Mal nach einem
# laufenden Dienst. Die Reihenfolge ist hier also Vorsicht, kein gemessener
# Schaden; bei Chromecast4lox 1.3.10 war sie einer (Regeln/06).
BW_MARKE="$BASE/data/plugins/$PFOLDER.upgrade_laeuft"
bw_marke_weg() {
    if [ -f "$BW_MARKE" ]; then
        rm -f "$BW_MARKE" && echo "<INFO> Die Aktualisierung ist durch - Dienststart wieder frei."
    fi
}
trap bw_marke_weg EXIT

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

# Aus der Sicherung zurueckholen, wenn die Datei leer ist.
#
# Der Python-Block steht seit 0.9.22 DARUEBER. Bis 0.9.21 stand er 59 Zeilen
# weiter unten, und die Lesbarkeitspruefung ein paar Zeilen tiefer benutzte
# "$PY3", bevor er zugewiesen war. Gemessen mit 'bash -x': die Trace-Zeile
# lautete
#     + '' -c 'import json,sys;json.load(open(sys.argv[1]))' .../bewaesserung.json
# 'LESBAR' blieb damit IMMER 0, die Bedingung darunter war immer wahr, und
# die Zweitschrift wurde bedingungslos ueber die Konfiguration kopiert -
# auch ueber eine heile. Der Kommentar sagte das Gegenteil zu.
#
# Zurueckgespielt wird nur eine Zweitschrift MIT Inhalt. Bis 0.9.31 wurde
# auch eine Zweitschrift "{}" kopiert und mit "<OK> ... aus Sicherung
# wiederhergestellt" gemeldet - eine Erfolgsmeldung ueber nichts
# (gemessen 24.09.2026, Pruefung-Bewaesserung-0.9.32, Fall c). Inhalt heisst
# fuer bewaesserung.json dasselbe wie bw_zweitschrift_taugt() in
# webfrontend/html/bw_lib.php: ein nicht leeres Aktionstoken; fuer zonen.json
# und quellen_zuordnung.json: lesbares JSON, das nicht leer ist.
bw_hat_token() {
    "$PY3" -c 'import json,sys
d=json.load(open(sys.argv[1]))
t=d.get("aktionstoken") if isinstance(d,dict) else None
sys.exit(0 if t is not None and str(t).strip() else 1)' "$1" >/dev/null 2>&1
}
bw_sicherung_taugt() {   # $1 Dateiname, $2 Pfad der Zweitschrift
    case "$1" in
        bewaesserung.json) bw_hat_token "$2" ;;
        *) "$PY3" -c 'import json,sys
sys.exit(0 if json.load(open(sys.argv[1])) else 1)' "$2" >/dev/null 2>&1 ;;
    esac
}
for f in bewaesserung.json zonen.json quellen_zuordnung.json; do
    BK="$BASE/config/plugins/$PFOLDER.backup.$f"
    CF="$PCONFIG/$f"
    if [ -f "$BK" ]; then
        INHALT=$(cat "$CF" 2>/dev/null)
        # -s heisst nur "vorhanden und nicht leer". Eine halb
        # geschriebene Datei ist beides - die heile Sicherung daneben
        # wurde bis 0.9.18 dann NICHT eingespielt. Gefragt ist, ob sich
        # die Datei lesen laesst; den Interpreter dafuer haben wir schon.
        LESBAR=0
        [ -s "$CF" ] && "$PY3" -c 'import json,sys;json.load(open(sys.argv[1]))' \
            "$CF" >/dev/null 2>&1 && LESBAR=1
        if [ "$LESBAR" = "0" ] || [ "$INHALT" = "{}" ]; then
            if ! bw_sicherung_taugt "$f" "$BK"; then
                echo "<INFO> $f: Sicherung ohne Einstellungen - nichts zurueckgespielt."
            elif cp -p "$BK" "$CF"; then
                echo "<OK> $f aus Sicherung wiederhergestellt."
            else
                echo "<FAIL> $f liess sich NICHT wiederherstellen."
            fi
        fi
    fi
done
BKV="$BASE/config/plugins/$PFOLDER.backup.verlauf.json"
if [ -f "$BKV" ] && [ ! -f "$PDATA/verlauf.json" ]; then
    if cp -p "$BKV" "$PDATA/verlauf.json"; then
        echo "<OK> Verlauf des Wasserhaushalts wiederhergestellt - die Bilanz laeuft weiter."
    else
        echo "<FAIL> Der Verlauf liess sich NICHT wiederherstellen - die Bilanz faengt bei null an und giesst erst einmal zu wenig."
    fi
fi

# Noch einmal, NACH dem Wiederherstellen: cp -p uebertraegt die Rechte
# der Quelle. Kommt eine Anlage aus einer Fassung ohne 0600, waere die
# alte 0644 sonst ueber die frisch gesetzte 0600 zurueckkopiert worden
# - mit dem Aktionstoken darin.
chmod 600 "$PCONFIG"/*.json 2>/dev/null

# ---------- Eigentuemer ----------
#
# BERICHTIGT 06.09.2026. Hier stand: "LoxBerry fuehrt postinstall.sh als root
# aus" und darunter, dies sei "die wichtigste Zeile dieses Skripts". Beides
# ist falsch. Gemessen an sbin/plugininstall.pl eines LoxBerry 4,
# Zeile 1310:
#
#   command => "cd \"$tempfolder\" && $sudobin -n -u loxberry \"$script\" ..."
#
# Das Skript laeuft als loxberry, nicht als root. Eine root-eigene Datei
# koennte es also gar nicht umschreiben - und muss es auch nicht: der
# Installateur chownt die vier Baeume selbst, VOR diesem Skript (:918
# config/, :937 bin/, :1022 data/, :1042 log/).
#
# Der Aufruf bleibt trotzdem stehen: die Zweitschriften NEBEN dem
# Konfigordner fasst der Installateur nicht an, und die entstehen hier. Was
# nicht bleibt, ist die Erfolgs- bzw. Fehlermeldung: ein <FAIL> ueber einen
# Zustand, den das Skript nicht herstellen kann und den der Installateur
# schon hergestellt hat, schickt den Betreiber auf die Suche nach einem
# Fehler, den es nicht gibt.
if id loxberry >/dev/null 2>&1; then
    chown -R loxberry:loxberry "$PCONFIG" "$PDATA" "$PLOG" "$PBIN" 2>/dev/null
    for BKD in "$BASE/config/plugins/$PFOLDER".backup.*; do
        [ -e "$BKD" ] && chown loxberry:loxberry "$BKD" 2>/dev/null
    done
    echo "<INFO> Eigentuemer der Zweitschriften nachgezogen (die Plugin-Ordner setzt der Installateur selbst)."
else
    echo "<INFO> Benutzer loxberry nicht gefunden - Eigentuemer nicht geaendert."
fi


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
    # Eigene Datei statt /tmp/bew_pip.log: /tmp ist fuer alle schreibbar,
    # der Name war vorhersagbar, und dieses Skript laeuft als root.
    #
    # paho-mqtt<2: die Fassung 2.0 hat die Rueckruf-Schnittstelle
    # umgestellt. Der Dienst kommt mit beiden zurecht, aber eine
    # festgelegte Fassung ist eine gemessene Aussage, eine offene nicht.
    PIPLOG=$(mktemp 2>/dev/null || echo "$PDATA/pip.log")
    if "$VENV/bin/pip" install --no-cache-dir "paho-mqtt<2" >"$PIPLOG" 2>&1; then
        echo "<OK> Paket paho-mqtt eingerichtet - Messwerte koennen ueber MQTT kommen."
    else
        echo "<INFO> paho-mqtt liess sich nicht einrichten. Open-Meteo und die"
        echo "<INFO> HTTP-Quellen funktionieren trotzdem; MQTT-Quellen bleiben leer."
        tail -n 5 "$PIPLOG"
    fi
    rm -f "$PIPLOG"
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
# Kein "|| true" am Ende: der Rueckgabewert einer Roehre ist der des
# letzten Glieds (sed, praktisch immer 0). Es griff nie und taeuschte
# eine Absicherung vor, die es nicht gab.
"$PY3" "$PBIN/bewaesserung_dienst.py" --selbsttest 2>&1 | head -n 25 | sed 's/^/<INFO> /'

# ---------- Langzeitwerte zurueckholen ----------
# Gegenstueck zu preupgrade.sh. Zwischen beiden Skripten hat der Installer
# data/plugins/<x>/ vollstaendig geloescht; der Nachbar mit dem Punkt hat es
# ueberstanden. Zurueckgeholt wird nur, was fehlt - eine Neuinstallation
# findet nichts vor und faengt sauber bei null an.
#
# Dieser Block stand bis 0.9.18 HINTER dem Dienststart. Der Dienst liest
# tagesextreme.json beim Anlauf (bewaesserung_dienst.py, tag_laden) und
# schreibt sie im ersten Rechengang zurueck: die gerettete Datei landete zwar
# auf der Platte, aber nicht im Speicher des Dienstes und wurde sofort wieder
# ueberschrieben. War der Dienst schneller, griff ausserdem die Bedingung
# "noch nichts da" nicht mehr, und das rm -rf am Ende loeschte die Rettung
# endgueltig. Nach einem Update um die Mittagszeit war Tmin dann die
# Mittagstemperatur - und ET0 nach der Messung im README 1,95 statt 5,40 mm.
LANG_SICHER="$BASE/data/plugins/$PFOLDER.upgrade_sicherung"
if [ -d "$LANG_SICHER" ]; then
    LANG_FEHL=0
    for LANG_F in tagesextreme.json nachtplan.json zustand.json; do
        if [ -f "$LANG_SICHER/$LANG_F" ] \
           && [ ! -s "$BASE/data/plugins/$PFOLDER/$LANG_F" ]; then
            mkdir -p "$BASE/data/plugins/$PFOLDER" 2>/dev/null
            if cp -p "$LANG_SICHER/$LANG_F" "$BASE/data/plugins/$PFOLDER/$LANG_F" \
                2>/dev/null; then
                echo "<OK> $LANG_F ueber das Update gerettet."
            else
                echo "<FAIL> $LANG_F liess sich NICHT zurueckholen."
                LANG_FEHL=1
            fi
        fi
    done
    # Weggeraeumt wird nur, wenn NICHTS gescheitert ist.
    #
    # Bis 0.9.21 stand das rm ausserhalb jeder Erfolgspruefung: genau die
    # Datei, deren Verlust dieses Skript oben ausfuehrlich begruendet
    # (tagesextreme.json - nach einem Mittags-Update ist Tmin die
    # Mittagstemperatur, ET0 1,95 statt 5,40 mm), wurde nach einem
    # gescheiterten Zurueckholen endgueltig weggeworfen, obwohl sie noch
    # dalag und beim naechsten Lauf zu retten gewesen waere.
    if [ "$LANG_FEHL" = "0" ]; then
        rm -rf "$LANG_SICHER" 2>/dev/null
    else
        echo "<INFO> Die Update-Sicherung bleibt liegen ($LANG_SICHER) - beim naechsten Lauf wird es erneut versucht."
    fi
fi

# ---------- Dienst wieder starten, wenn er vorher lief ----------
#
# Nur dann. Eine Neuinstallation startet NICHTS von selbst: der Anwender
# soll erst Standort, Quellen und Zonen eintragen. Wer den Dienst vorher
# bewusst angehalten hatte, findet ihn nach dem Update ebenfalls angehalten.
MERKER="$BASE/config/plugins/$PFOLDER.backup.lief_vorher"
if [ -f "$MERKER" ]; then
    rm -f "$MERKER"
    if [ -x "$PBIN/dienst.sh" ]; then
        # Die Ausnahme von der Marke - siehe bw_marke_weg() oben.
        if BW_START_TROTZ_MARKE=1 "$PBIN/dienst.sh" start >/dev/null 2>&1; then
            echo "<OK> Der Dienst lief vor dem Update und wurde wieder gestartet."
        else
            echo "<INFO> Der Dienst liess sich nicht starten - Reiter Einstellungen,"
            echo "<INFO> Knopf 'Dienst starten'. Der Grund steht im Reiter Logdateien."
        fi
    fi
fi

# ---------- Abschluss: Erstanleitung nur ohne eingerichtete Konfiguration ----------
#
# Dieses Skript laeuft bei der Erstinstallation UND bei jedem Upgrade;
# plugininstall.pl uebergibt kein Kennzeichen. Bis 0.9.31 stand die Anleitung
# darunter deshalb auch nach jedem gelungenen Upgrade da - mit der
# Aufforderung, Standort, Quellen und Zonen einzutragen, die laengst
# zurueckgespielt waren (gemessen 24.09.2026, Pruefung-Bewaesserung-0.9.32,
# Fall b). Wer das liest, haelt seine Einstellungen fuer verloren - und
# uebersieht den Fall, in dem sie es wirklich sind.
#
# Entschieden wird nach dem INHALT der Konfiguration, nicht nach einer
# Upgrade-Marke: dasselbe Merkmal wie bw_config_hat_inhalt() und
# bw_zweitschrift_taugt() in webfrontend/html/bw_lib.php - ein nicht leeres
# Aktionstoken in bewaesserung.json (bw_hat_token, oben beim Zurueckholen).
# Fehlt es nach einem Upgrade, ist die Rueckholung gescheitert, und dann ist
# die Anleitung genau richtig.
if bw_hat_token "$PCONFIG/bewaesserung.json"; then
    echo "<OK> Aktualisierung abgeschlossen, Einstellungen uebernommen."
else
    echo "<INFO> Naechste Schritte:"
    echo "<INFO>   1. Reiter Einstellungen: Standort eintragen (ohne ihn keine Strahlung)"
    echo "<INFO>   2. Reiter Quellen: Wetterstation zuordnen - oder bei Open-Meteo bleiben"
    echo "<INFO>   3. Reiter Zonen: je Kreis Flaeche, Bepflanzung und Boden eintragen"
    echo "<INFO>   4. Becherprobe machen - ohne sie sind Liter und Minuten geschaetzt"
    echo "<INFO>   5. Reiter MQTT: das Abo im Gateway eintragen"
    echo "<OK> Installation abgeschlossen."
fi

exit 0
