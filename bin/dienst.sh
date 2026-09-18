#!/bin/bash
# Bewaesserung vorausschauend - Start, Stopp und Waechter des Dienstes.
#
# Die Pfade werden aus dem EIGENEN Ablageort abgeleitet, nicht ueber
# LoxBerry::System. Grund: LoxBerry::System leitet den Pluginordner aus dem
# Aufrufort ab; wird dieses Skript aus postinstall.sh oder aus dem Cron
# gestartet, kommt dort ueberall Leerstring zurueck - das Skript werkelt dann
# gegen /-Pfade und meldet trotzdem Erfolg.

# readlink -f loest Symlinks auf, BEVOR das Verzeichnis bestimmt wird.
#
# LoxBerry legt Daemons als Symlink unter system/daemons/plugins/ ab. Von dort
# aufgerufen ergaebe dirname "$0" den Pfad .../system/daemons/plugins, PNAME
# waere buchstaeblich "plugins", und der Dienst legte PID-Datei, Sollmerker
# und Protokoll unter <home>/data/plugins/plugins/ an - neben, nicht in
# seinem eigenen Ordner. Die Oberflaeche saehe den Dienst nie laufen, und der
# Waechter startete ihn jede Minute ein weiteres Mal.
# Als loxberry laufen, nicht als root.
#
# Der minuetliche Waechter kommt aus dem Cron. Laeuft der als root - und je
# nach Ablage des Cronjobs tut er das -, dann gehoerten PID-Datei, Sollmerker
# und Protokoll danach root. Die Oberflaeche laeuft als loxberry und koennte
# den Dienst anschliessend weder anhalten noch neu starten: sie darf die
# Dateien nicht mehr schreiben. Schlimmer noch, 'dienst.sh stop' meldet dann
# Erfolg - das kill scheitert, aber das rm der PID-Datei gelingt, weil das
# Verzeichnis loxberry gehoert. Der Dienst laeuft weiter und ist nur noch
# ueber die Prozessliste zu finden.
#
# Deshalb setzt sich das Skript selbst herunter, EINMAL und bevor es
# irgendetwas anlegt. exec, damit kein zusaetzlicher Prozess stehen bleibt.
# '-s /bin/bash' ausdruecklich: ohne das nimmt su die Login-Shell aus
# /etc/passwd. Steht dort nologin oder /bin/false, endet dieses Skript hier
# still und ohne Meldung - und weil es 'exec' ist, kaeme nicht einmal ein
# Rueckgabewert zurueck. Auf einem regulaeren LoxBerry ist der Zweig ohnehin
# unerreichbar (der Cron laeuft bereits als loxberry); er greift nur, wenn
# jemand von Hand mit sudo aufruft.
#
# Woertlich uebernommen aus LoxBerry-Plugin-Dashboard-0.9.12, dort seit dem
# 16.08.2026 in Betrieb. Ueber den Bestand gezaehlt am 31.08.2026: 15 von 17
# dienst.sh hatten den Abstieg nicht, obwohl REGELN_2 ihn seit langem
# verlangt.
if [ "$(id -u)" = "0" ] && id loxberry >/dev/null 2>&1; then
    exec su -s /bin/bash loxberry -c "$(printf '%q ' "$0" "$@")"
fi

SELF=$(cd "$(dirname "$(readlink -f "$0")")" && pwd)   # <home>/bin/plugins/<ordner>
PNAME=$(basename "$SELF")
LBHOMEDIR=$(cd "$SELF/../../.." && pwd)
PDATA="$LBHOMEDIR/data/plugins/$PNAME"
PLOG="$LBHOMEDIR/log/plugins/$PNAME"
PCONFIG="$LBHOMEDIR/config/plugins/$PNAME"
PID="$PDATA/dienst.pid"
SOLL="$PDATA/soll_laufen"
# Die Marke "Aktualisierung laeuft". Sie liegt NEBEN dem Datenordner, weil
# purge_installation data/plugins/<ordner>/ zwischen preupgrade.sh und
# postinstall.sh restlos abraeumt (Regeln/06) - im Ordner waere sie genau
# dann fort, wenn sie gebraucht wird. preupgrade.sh legt sie als Erstes an,
# postinstall.sh - das letzte Hakenskript dieser Linie; postupgrade.sh und
# postroot.sh gibt es hier nicht - entfernt sie wieder.
MARKE="$LBHOMEDIR/data/plugins/$PNAME.upgrade_laeuft"
LOGDATEI="$PLOG/bewaesserung.log"
# Eigene Datei fuer alles, was NEBEN dem Protokoll anfaellt: Meldungen des
# Starts und alles, was das Programm nach stderr schreibt, bevor sein
# Protokoll steht (Syntaxfehler, fehlende Bibliothek, Abbruch im Importpfad).
#
# Bis 0.9.24 ging diese Ausgabe mit ">> $LOGDATEI" in DIESELBE Datei, die
# bin/bewaesserung_dienst.py mit einem umlaufenden Handler fuehrt. Das haelt einen zweiten,
# anhaengenden Deskriptor auf diese Datei offen. Beim Ueberlauf benennt der
# Handler um, beim Leeren der Ramdisk verschwindet die Datei ganz - der
# Deskriptor dieser Shell zeigt danach weiter auf die weggeschobene oder
# geloeschte Datei, und was er traegt, sieht niemand mehr. Am Geraet gemessen
# (06.09.2026): sieben Dienste hielten so eine geloeschte Protokolldatei offen.
# Regel: genau einer schreibt in eine Protokolldatei.
STARTLOG="$PLOG/bewaesserung_start.log"
SKRIPT="$SELF/bewaesserung_dienst.py"
# Welcher Python?
#
# Die virtuelle Umgebung gibt es nur, damit das FREIWILLIGE Paket paho-mqtt
# einen Platz hat. Der Dienst selbst kommt mit der Standardbibliothek aus.
#
# postinstall.sh sagt darum ausdruecklich: 'Das Plugin laeuft trotzdem - dann
# aber ohne MQTT-Quellen', wenn sich die Umgebung nicht anlegen laesst (etwa
# weil das Paket python3-venv fehlt). Bis 0.9.1 hielt dieses Skript sich
# nicht daran: es bestand auf venv/bin/python3 und verweigerte den Start mit
# 'Plugin neu installieren'. Die Installation meldete also Erfolg mit einer
# beruhigenden Nebenbemerkung, und der Dienst lief nie an - auch der Reiter
# Test schlug fehl, mit einem Hinweis auf die falsche Ursache.
#
# Deshalb: die Umgebung wird bevorzugt, der System-Python ist die
# Rueckfallebene. Erst wenn es beide nicht gibt, ist es ein Fehler.
PYVENV="$SELF/venv/bin/python3"
if [ -x "$PYVENV" ]; then
    PY="$PYVENV"
    PYHERKUNFT="virtuelle Umgebung"
else
    PY=$(command -v python3 2>/dev/null)
    PYHERKUNFT="System-Python (ohne virtuelle Umgebung - MQTT-Quellen brauchen paho-mqtt)"
fi

mkdir -p "$PDATA" "$PLOG" 2>/dev/null

# Wem gehoert der Dienst? Genau die Bedingung, nach der dieses Skript sich
# ganz oben selbst herunterstuft: gibt es den Benutzer loxberry und laeuft
# das Skript als root, dann gehoert der Dienst loxberry - sonst dem
# aufrufenden Benutzer.
dienst_uid() {
    if [ "$(id -u)" = "0" ] && id loxberry >/dev/null 2>&1; then
        id -u loxberry 2>/dev/null
    else
        id -u
    fi
}
DIENST_UID=$(dienst_uid)

# Ist die Nummer $1 GENAU dieser Dienst? Argumentweise, nicht als Suche ueber
# die ganze Befehlszeile.
#
# Bis 0.9.29 entschied hier zweierlei, und beides ist zu weit:
#   - im PID-Datei-Zweig ein grep nach "bewaesserung_dienst.py" ueber die
#     ganze Befehlszeile. Das trifft auch "tail -f <dienstpfad>" oder einen
#     Editor mit der Datei offen;
#   - ohne PID-Datei eine Suche nach der Zeichenkette "$SKRIPT" in jeder
#     Befehlszeile des Systems, deren ERSTER Treffer genommen und in die
#     eigene PID-Datei geschrieben wurde. Gemessen am 18.09.2026 in WSL
#     (Bestand-2026-09-18/klasse-F): ein
#     "python3 -c 'import time; time.sleep(300)' <dienstpfad>" wurde von
#     'status' als laufender Dienst gemeldet, seine Nummer landete in
#     dienst.pid, und 'stop' hat ihn beendet.
#
# Geprueft wird deshalb jedes Argument fuer sich:
#   argv[0] ist ein python-Interpreter,
#   argv[1] ist genau der eigene Dienstpfad,
#   ein drittes Argument gibt es nicht ("--einmal", "--selbsttest" sind
#   kurze Laeufe im Vordergrund, kein Dauerlaeufer),
#   und der Prozess gehoert dem Dienstbenutzer.
# Bauart: LoxBerry-Plugin-APC-UPS-1.2.11 (apc_ist_dienst),
# LoxBerry-Plugin-Midea2Lox-4.5.7 (eigener_dienst).
#
# Der Rumpf laeuft hinter einer Pipe, also in einer Unterschale: das 'exit'
# darin beendet nur sie.
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
        [ "$a1" = "$SKRIPT" ]
    } || return 1
    [ -z "$2" ] && return 0
    [ "$(stat -c %u "/proc/$1" 2>/dev/null)" = "$2" ]
}

# Alle eigenen Dienste, eine Nummer je Zeile. Rein lesend.
bw_dienste_suchen() {
    local d p
    for d in /proc/[0-9]*; do
        p=${d#/proc/}
        bw_ist_dienst "$p" "$DIENST_UID" && echo "$p"
    done
    return 0
}

# Laeuft der Dienst? Die PID-Datei ist die schnelle Antwort, nicht die
# einzige. Sie liegt in data/plugins/<x>/ und ist damit nach jedem
# Upgrade weg; auch ein misslungenes Anhalten kann sie entfernen,
# waehrend der Prozess weiterlaeuft. Bis 0.9.18 hiess "keine Datei"
# schlicht "laeuft nicht" - der Waechter startete dann minuetlich einen
# ZWEITEN Dienst daneben, und beide schrieben abbild.json und
# verlauf.json.
#
# Diese Funktion SCHREIBT NICHTS. Bis 0.9.29 trug sie die im zweiten
# Schritt gefundene Nummer in die eigene PID-Datei ein - eine Abfrage
# ('status') veraenderte damit den Datenordner, und im Messfall stand
# dort hinterher die Nummer eines fremden Vorgangs. Die gefundene Nummer
# steht jetzt in BW_PID; wer sie festhalten will, tut das dort, wo es
# hingehoert (starten()).
BW_PID=""
laeuft() {
    local p
    BW_PID=""
    if [ -f "$PID" ]; then
        p=$(cat "$PID" 2>/dev/null)
        case "$p" in ''|*[!0-9]*) p="" ;; esac
        if [ -n "$p" ] && bw_ist_dienst "$p" "$DIENST_UID"; then
            BW_PID="$p"
            return 0
        fi
    fi
    # Zweite Frage: laeuft GENAU DIESES Skript, auch ohne PID-Datei?
    # Eingeschraenkt auf den eigenen Pfad, damit eine zweite Installation
    # (LoxBerry haengt bei ihr _01 an) nicht mitgezaehlt wird.
    p=$(bw_dienste_suchen | head -n 1)
    if [ -n "$p" ]; then
        BW_PID="$p"
        return 0
    fi
    return 1
}

# Laeuft gerade eine Aktualisierung dieses Plugins?
#
# Gemessen (Pruefung-Bewaesserung-0.9.30, 18.09.2026, WSL, rot vorher): ohne
# diese Frage startete der Knopf "Dienst starten" mitten in der
# Upgrade-Luecke einen Dienst (Fall A2a). Die Oberflaeche hatte die
# Konfiguration kurz vorher aus der Zweitschrift geheilt, der Verlauf des
# Wasserhaushalts lag aber noch in der Sicherung. Der Dienst rechnete ohne
# ihn und sandte "giessen 0", Ventilzeit 0, retained (A2c/A2g: mit dem
# Verlauf waeren es "giessen 1" und 649 s gewesen) - und postinstall.sh
# holte den Verlauf danach nicht mehr zurueck, weil schon einer dalag
# (A2e). Ebenso "Jetzt rechnen" (A4) und "neu starten" (A3).
#
# Vier Ausgaenge:
#   Marke hoechstens 3600 s alt  -> gesperrt (Fall C1)
#   Marke aelter, aus der Zukunft, leer oder unlesbar -> sie gilt nicht
#                                (C2 bis C5; eine abgebrochene Installation
#                                darf den Dienst nicht fuer immer stilllegen)
#   keine lesbare Uhr            -> die Pruefung faellt GESCHLOSSEN aus
#                                (CLAUDE.md 4; Fall C6)
#   BW_START_TROTZ_MARKE=1       -> Ausnahme fuer postinstall.sh (Fall C10)
# Bauart: LoxBerry-Plugin-Govee-0.9.19 (marke_sperrt).
marke_sperrt() {
    [ -f "$MARKE" ] || return 1
    [ "${BW_START_TROTZ_MARKE:-0}" = "1" ] && return 1
    JETZT=$(date +%s 2>/dev/null)
    case "$JETZT" in ''|*[!0-9]*) return 0 ;; esac
    SEIT=$(cat "$MARKE" 2>/dev/null)
    case "$SEIT" in ''|*[!0-9]*) return 1 ;; esac
    ALTER=$((JETZT - SEIT))
    [ "$ALTER" -lt 0 ] && return 1
    [ "$ALTER" -le 3600 ]
}

starten() {
    if laeuft; then
        # Trug die PID-Datei ihn nicht, wird die Nummer nachgetragen - und
        # zwar hier, nicht in laeuft(). In die eigene PID-Datei kommt nur
        # eine Nummer, die bw_ist_dienst() argumentweise als eigenen Dienst
        # bestaetigt hat. "start" auf einen laufenden Dienst heisst "laeuft
        # bereits"; ein Dienst ohne Buchfuehrung ist derselbe Fall und wird
        # weder beendet noch ein zweites Mal gestartet.
        # Bauart: LoxBerry-Plugin-Midea2Lox-4.5.7 (start_dienst).
        if [ "$(cat "$PID" 2>/dev/null)" != "$BW_PID" ]; then
            echo "$BW_PID" > "$PID" 2>/dev/null
            echo "laeuft bereits, lief aber ohne PID-Datei - Nummer nachgetragen (PID $BW_PID)"
            return 0
        fi
        echo "laeuft bereits (PID $BW_PID)"
        return 0
    fi
    # Diese Frage steht VOR dem touch auf soll_laufen weiter unten. Stuende
    # sie dahinter, legte der abgewiesene Start den Merker trotzdem an, und
    # der Waechter startete den Dienst eine Minute nach der Aktualisierung
    # doch - auch einen, der vorher bewusst angehalten war (Faelle C1c, B2a;
    # an Govee 0.9.19 gemessen). Rueckgabewert 0: eine laufende
    # Aktualisierung ist kein Fehlschlag.
    if marke_sperrt; then
        echo "Eine Aktualisierung dieses Plugins laeuft - jetzt wird nichts gestartet. Lief der Dienst vorher, startet ihn die Installation am Ende selbst; sonst danach den Knopf erneut druecken."
        return 0
    fi
    if [ -z "$PY" ] || [ ! -x "$PY" ]; then
        echo "FEHLER: es wurde ueberhaupt kein python3 gefunden - weder unter"
        echo "        $PYVENV noch im Suchpfad. Ohne Python laeuft der Dienst nicht."
        return 1
    fi
    if [ "$PY" != "$PYVENV" ]; then
        echo "[$(date '+%Y-%m-%d %H:%M:%S')] Hinweis: die virtuelle Umgebung fehlt, es wird $PY benutzt. Alles laeuft - nur MQTT-Quellen brauchen paho-mqtt." >> "$LOGDATEI"
    fi
    if [ ! -f "$SKRIPT" ]; then
        echo "FEHLER: $SKRIPT fehlt. Plugin neu installieren."
        return 1
    fi
    if [ ! -f "$PCONFIG/bewaesserung.json" ]; then
        echo "FEHLER: Konfiguration fehlt ($PCONFIG/bewaesserung.json). Erst die Oberflaeche oeffnen."
        return 1
    fi
    touch "$SOLL"
    # Die Ausgabe des Dienstes geht in die Startdatei, NICHT in das Protokoll:
    # dort schreibt allein der Handler des Programms. Beim Start gekappt, damit
    # sie nur die Ausgabe EINES Laufes sammelt und nicht unbegrenzt waechst.
    : > "$STARTLOG"
    nohup "$PY" "$SKRIPT" >> "$STARTLOG" 2>&1 &
    echo $! > "$PID"
    sleep 1
    if laeuft; then
        echo "gestartet (PID $BW_PID)"
        return 0
    fi
    echo "FEHLER: Start fehlgeschlagen - siehe $STARTLOG und $LOGDATEI"
    rm -f "$PID"
    return 1
}

# Beendet ALLE eigenen Dienste, nicht nur den aus der PID-Datei.
#
# Die PID-Datei liegt in data/plugins/<x>/ und ist nach jedem Upgrade weg;
# ein Dienst ohne Eintrag war damit fuer 'stop' unsichtbar. Bis 0.9.29 kam
# er nur durch einen Nebeneffekt mit: laeuft() schrieb die Variable P der
# aufrufenden Funktion um, und 'kill -9' traf deshalb eine andere Nummer
# als das vorangegangene SIGTERM - auch dann, wenn die neue Nummer
# inzwischen einem fremden Vorgang gehoerte.
#
# Vor JEDEM Signal wird die Befehlszeile erneut gelesen: zwischen der Suche
# und dem harten Abschuss liegen zehn Sekunden, in denen eine freigewordene
# Nummer laengst neu vergeben sein kann.
anhalten() {
    local ziel rest p i
    rm -f "$SOLL"
    ziel=$(bw_dienste_suchen)
    if [ -z "$ziel" ]; then
        rm -f "$PID"
        echo "laeuft nicht"
        return 0
    fi
    for p in $ziel; do
        bw_ist_dienst "$p" "$DIENST_UID" && kill "$p" 2>/dev/null
    done
    i=0
    while [ $i -lt 10 ]; do
        rest=$(bw_dienste_suchen)
        [ -n "$rest" ] || break
        sleep 1
        i=$((i + 1))
    done
    rest=$(bw_dienste_suchen)
    if [ -n "$rest" ]; then
        for p in $rest; do
            bw_ist_dienst "$p" "$DIENST_UID" && kill -9 "$p" 2>/dev/null
        done
        sleep 1
    fi
    # Die Wirkung pruefen, nicht den Rueckgabewert. Bis 0.9.18 wurde nach
    # dem harten Abschuss nicht mehr nachgesehen: gehoert der Prozess root
    # und ruft loxberry das Skript, laeuft er weiter - die PID-Datei war
    # trotzdem weg, "angehalten" stand da, und der Waechter startete
    # einen zweiten daneben.
    rest=$(bw_dienste_suchen)
    if [ -n "$rest" ]; then
        echo "FEHLER: Prozess $(echo $rest) laeuft weiter - Rechteproblem? Als root anhalten."
        return 1
    fi
    rm -f "$PID"
    echo "angehalten"
    return 0
}

case "$1" in
    start)   starten ;;
    stop)    anhalten ;;
    restart) anhalten; sleep 1; starten ;;
    status)
        if laeuft; then
            echo "laeuft $BW_PID"
            exit 0
        fi
        echo "gestoppt"
        exit 1
        ;;
    selbsttest)
        # Auch hier gilt die Rueckfallebene. Bis 0.9.1 schlug der Reiter Test
        # fehl, sobald die virtuelle Umgebung fehlte - und die Meldung wies
        # auf 'Plugin neu installieren' statt auf den wahren Grund.
        if [ -z "$PY" ] || [ ! -x "$PY" ]; then
            echo "FEHLER: kein python3 gefunden (weder $PYVENV noch im Suchpfad)."
            exit 1
        fi
        echo "Python: $PY  ($PYHERKUNFT)"
        "$PY" "$SKRIPT" --selbsttest
        ;;
    einmal)
        # "Jetzt rechnen" ist ein Startweg wie jeder andere: es rechnet,
        # schreibt verlauf.json und sendet an Loxone. In der Luecke hiess
        # das "giessen 0" und ein verlorener Wasserhaushalt (Faelle A4a bis
        # A4d, rot vorher). Rueckgabewert 1: es wurde NICHT gerechnet, und
        # die Oberflaeche soll das als Fehler zeigen, nicht als Ergebnis.
        if marke_sperrt; then
            echo "Eine Aktualisierung dieses Plugins laeuft - jetzt wird nicht gerechnet. Bitte nach ihrem Ende erneut versuchen."
            exit 1
        fi
        if [ -z "$PY" ] || [ ! -x "$PY" ]; then
            echo "FEHLER: kein python3 gefunden (weder $PYVENV noch im Suchpfad)."
            exit 1
        fi
        "$PY" "$SKRIPT" --einmal
        ;;
    waechter)
        # Nur neu starten, wenn der Dienst laufen SOLL. Ein bewusst
        # angehaltener Dienst bleibt angehalten. Bei liegender Marke nicht
        # einmal die Protokollzeile: starten() wiese ohnehin ab, und die
        # Zeile "wird neu gestartet" stimmte dann nicht (Fall C7).
        if [ -f "$SOLL" ] && ! marke_sperrt && ! laeuft; then
            echo "[$(date '+%Y-%m-%d %H:%M:%S')] Waechter: Dienst lief nicht, wird neu gestartet." >> "$LOGDATEI"
            starten >> "$STARTLOG" 2>&1
        fi
        ;;
    *)
        echo "Aufruf: $0 {start|stop|restart|status|selbsttest|einmal|waechter}"
        exit 2
        ;;
esac
