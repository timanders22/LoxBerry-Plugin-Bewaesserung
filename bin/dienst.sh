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
LOGDATEI="$PLOG/bewaesserung.log"
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

# Laeuft der Dienst? Die PID-Datei ist die schnelle Antwort, nicht die
# einzige. Sie liegt in data/plugins/<x>/ und ist damit nach jedem
# Upgrade weg; auch ein misslungenes Anhalten kann sie entfernen,
# waehrend der Prozess weiterlaeuft. Bis 0.9.18 hiess "keine Datei"
# schlicht "laeuft nicht" - der Waechter startete dann minuetlich einen
# ZWEITEN Dienst daneben, und beide schrieben abbild.json und
# verlauf.json.
laeuft() {
    if [ -f "$PID" ]; then
        P=$(cat "$PID" 2>/dev/null)
        if [ -n "$P" ] && kill -0 "$P" 2>/dev/null \
           && grep -qa "bewaesserung_dienst.py" "/proc/$P/cmdline" 2>/dev/null; then
            return 0
        fi
    fi
    # Zweite Frage: laeuft GENAU DIESES Skript, auch ohne PID-Datei?
    # Eingeschraenkt auf den eigenen Pfad, damit eine zweite Installation
    # (LoxBerry haengt bei ihr _01 an) nicht mitgezaehlt wird.
    P=$(pgrep -f "$SKRIPT" 2>/dev/null | head -n 1)
    if [ -n "$P" ] && kill -0 "$P" 2>/dev/null; then
        echo "$P" > "$PID" 2>/dev/null
        return 0
    fi
    return 1
}

starten() {
    if laeuft; then
        echo "laeuft bereits (PID $(cat "$PID"))"
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
    # Ausgabe geht in die Logdatei. Das Python-Skript protokolliert deshalb
    # NICHT zusaetzlich nach stdout - sonst stuende jede Zeile doppelt darin.
    nohup "$PY" "$SKRIPT" >> "$LOGDATEI" 2>&1 &
    echo $! > "$PID"
    sleep 1
    if laeuft; then
        echo "gestartet (PID $(cat "$PID"))"
        return 0
    fi
    echo "FEHLER: Start fehlgeschlagen - siehe $LOGDATEI"
    rm -f "$PID"
    return 1
}

anhalten() {
    rm -f "$SOLL"
    if ! laeuft; then
        rm -f "$PID"
        echo "laeuft nicht"
        return 0
    fi
    P=$(cat "$PID")
    kill "$P" 2>/dev/null
    for i in 1 2 3 4 5 6 7 8 9 10; do
        laeuft || break
        sleep 1
    done
    if laeuft; then
        kill -9 "$P" 2>/dev/null
        sleep 1
    fi
    # Die Wirkung pruefen, nicht den Rueckgabewert. Bis 0.9.18 wurde nach
    # dem harten Abschuss nicht mehr nachgesehen: gehoert der Prozess root
    # und ruft loxberry das Skript, laeuft er weiter - die PID-Datei war
    # trotzdem weg, "angehalten" stand da, und der Waechter startete
    # einen zweiten daneben.
    if laeuft; then
        echo "FEHLER: Prozess $P laeuft weiter - Rechteproblem? Als root anhalten."
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
            echo "laeuft $(cat "$PID")"
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
        if [ -z "$PY" ] || [ ! -x "$PY" ]; then
            echo "FEHLER: kein python3 gefunden (weder $PYVENV noch im Suchpfad)."
            exit 1
        fi
        "$PY" "$SKRIPT" --einmal
        ;;
    waechter)
        # Nur neu starten, wenn der Dienst laufen SOLL. Ein bewusst
        # angehaltener Dienst bleibt angehalten.
        if [ -f "$SOLL" ] && ! laeuft; then
            echo "[$(date '+%Y-%m-%d %H:%M:%S')] Waechter: Dienst lief nicht, wird neu gestartet." >> "$LOGDATEI"
            starten >> "$LOGDATEI" 2>&1
        fi
        ;;
    *)
        echo "Aufruf: $0 {start|stop|restart|status|selbsttest|einmal|waechter}"
        exit 2
        ;;
esac
