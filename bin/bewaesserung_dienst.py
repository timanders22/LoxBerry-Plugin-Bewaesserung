#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Bewaesserung vorausschauend - der Dienst.

Er tut vier Dinge und sonst nichts:

  1. Messwerte einsammeln (eigene Station ueber MQTT oder HTTP, sonst online)
  2. Einmal am Tag die Bilanz je Zone fortschreiben und den Plan rechnen
  3. Das Ergebnis in einen Zwischenspeicher schreiben
  4. Es ueber MQTT veroeffentlichen, damit Loxone es abonnieren kann

Was er ausdruecklich NICHT tut: Ventile schalten. Das macht der
Bewaesserungsbaustein im Miniserver, der das seit Jahren kann. Das Plugin
liefert die Zahl, Loxone entscheidet - dieselbe Aufgabenteilung wie bei den
uebrigen Plugins dieser Reihe.

Seit 0.9.7 hoert er zusaetzlich zu, WAS Loxone ausgebracht hat. Das ist
keine Umkehrung der Aufgabenteilung, sondern ihre Voraussetzung: eine
Wasserbilanz, die den Zufluss nicht kennt, laeuft weg. Gemessen an einer
Zone mit 105 mm Speicher, 14 Tage trocken bei ET0 5 mm/Tag - ohne
Rueckmeldung 63,2 mm Defizit und 'die Anlage schafft es nicht', mit
4 mm je Nacht 10,5 mm und 'kein Bedarf'. Bis 0.9.6 gab es das Feld dafuer
in der Bilanzgleichung, aber keinen Weg, es zu fuellen.

Aufrufe:
    bewaesserung_dienst.py             Dauerbetrieb
    bewaesserung_dienst.py --einmal    einmal rechnen und beenden
    bewaesserung_dienst.py --selbsttest
"""

from __future__ import annotations

import asyncio
import datetime
import json
import logging
import logging.handlers
import os
import signal
import socket
import sys
import time
from pathlib import Path
from typing import Any

HIER = Path(__file__).resolve().parent
sys.path.insert(0, str(HIER))

import fao56                                        # noqa: E402
import giessplan                                    # noqa: E402
import quellen                                      # noqa: E402


def lb_wurzel_ermitteln():
    """Den LoxBerry-Wurzelordner ohne festen Systempfad bestimmen.

    Vom eigenen Ablageort aufwaerts, bis ein Verzeichnis gefunden ist, das
    config/plugins UND webfrontend enthaelt. Trifft die uebliche
    Installation genauso wie eine an einem anderen Ort.
    """
    d = os.path.dirname(os.path.abspath(__file__))
    for _ in range(8):
        if os.path.isdir(os.path.join(d, "config", "plugins")) \
                and os.path.isdir(os.path.join(d, "webfrontend")):
            return d
        eltern = os.path.dirname(d)
        if eltern == d:
            break
        d = eltern
    return ""


def mqtt_wert_saeubern(wert):
    """Einen Wert fuer den UDP-Eingang des MQTT-Gateways unschaedlich machen.

    Das Gateway liest zeilenweise. Ein Zeilenumbruch im Wert zerlegt die
    Uebertragung, und aus den Bruchstuecken bildet das Gateway erfundene
    Themen. Ein Tabulator schadet ebenso, weil Leerzeichen Thema und Wert
    trennt.
    """
    text = str(wert)
    for zeichen in ("\r\n", "\r", "\n", "\t"):
        text = text.replace(zeichen, " ")
    while "  " in text:
        text = text.replace("  ", " ")
    return text.strip()



def _home() -> str:
    h = os.environ.get("LBHOMEDIR", "")
    if h and os.path.isdir(h):
        return h
    # Kein fester Systempfad als Rueckfall mehr.
    #
    # Der frueher hier stehende feste Rueckfallpfad gibt es auf dem
    # gemessenen Geraet nicht - dessen Wurzel liegt woanders -, und ein
    # Systempfad im Quelltext ist gegen den Hausstandard. Der Rueckfall war
    # damit toter Code, der nur die Regel riss. Findet die Aufwaertssuche
    # nichts, bleibt der eigene Ablageort - so wie bisher auch.
    k = lb_wurzel_ermitteln()
    if k and os.path.isdir(k):
        return k
    return str(HIER.parent.parent)


HOME = _home()
ORDNER = HIER.name if HIER.parent.name == "plugins" else HIER.parent.name
CONFIGDIR = os.path.join(HOME, "config", "plugins", ORDNER)
DATADIR = os.path.join(HOME, "data", "plugins", ORDNER)
LOGDIR = os.path.join(HOME, "log", "plugins", ORDNER)
TEMPLATES = os.path.join(HOME, "templates", "plugins", ORDNER)

DATEI_CONFIG = os.path.join(CONFIGDIR, "bewaesserung.json")
DATEI_ZONEN = os.path.join(CONFIGDIR, "zonen.json")
DATEI_QUELLEN = os.path.join(CONFIGDIR, "quellen_zuordnung.json")
DATEI_VORLAGEN = os.path.join(TEMPLATES, "quellen.json")
DATEI_PFLANZEN = os.path.join(TEMPLATES, "pflanzen.json")
DATEI_ABBILD = os.path.join(DATADIR, "abbild.json")
DATEI_ZUSTAND = os.path.join(DATADIR, "zustand.json")
DATEI_VERLAUF = os.path.join(DATADIR, "verlauf.json")
DATEI_ROH = os.path.join(DATADIR, "roh.json")
DATEI_EXTREME = os.path.join(DATADIR, "tagesextreme.json")
DATEI_NACHTPLAN = os.path.join(DATADIR, "nachtplan.json")
DATEI_PID = os.path.join(DATADIR, "dienst.pid")
DATEI_LOG = os.path.join(LOGDIR, "bewaesserung.log")

VORGABEN = {
    "breite": 0.0, "laenge": 0.0, "hoehe": 0.0, "wind_hoehe": 2.0,
    "kuestennah": 0, "vorlage": "online",
    "rechenzeit": "20:00",        # wann der Plan fuer die Nacht steht
    "vorschautage": 2, "regen_anteil": 0.7, "wirkungsgrad": 0.75,
    "zonendauer_s": 240, "pause_min": 45,
    "fenster_von": "22:00", "fenster_bis": "08:00", "max_durchlaeufe": 8,
    "mqtt_ein": 1, "mqtt_topic": "bewaesserung",
    "aktionstoken": "", "takt": 300,

    # ---- neu in 0.9.7 ----
    #
    # Groesste Laufzeit, die eine gerechnete Ventilzeit annehmen darf.
    "zonendauer_max_s": 1800,
    #
    # Luecken im Verlauf aus den Vergangenheitstagen von Open-Meteo fuellen.
    #
    # Das ist der EINZIGE neue Schalter, der ab Werk AN steht, und das ist
    # eine bewusste Entscheidung mit Begruendung:
    #
    # Eine Luecke im Verlauf ist kein Geschmack, sondern ein Messfehler. Der
    # Dienst schreibt nur den jeweils heutigen Tag; war der LoxBerry aus oder
    # das Netz weg, fehlt der Tag fuer immer, und die Fortschreibung
    # ueberspringt ihn stillschweigend. Gemessen: fehlen 5 von 14 Tagen,
    # sinkt der gemeldete Bedarf von 24,3 auf 9,2 mm - auf 200 m2 sind das
    # 3 000 Liter, die niemand ausbringt, weil das Plugin sie nicht verlangt.
    #
    # Die Daten dafuer holt der Dienst ohnehin bei JEDEM Lauf mit
    # (past_days=10) und warf sie bis 0.9.6 weg. Gefuellt werden nur Tage,
    # die GAR NICHT dastehen; ein vorhandener Tag wird nie ueberschrieben,
    # auch nicht, wenn er von der eigenen Station stammt.
    #
    # Wer das nicht will, stellt es im Reiter Einstellungen ab. Die 0
    # ueberlebt jedes weitere Speichern - gemessen, siehe Reiter Test.
    "luecken_fuellen": 1,
    #
    # Die drei Sperren. Alle AUS: eine Sperre, die nach einem Update von
    # selbst greift, koennte einen Garten in der Hitze trockenlegen, ohne
    # dass jemand etwas angeklickt hat.
    "frost_ein": 0, "frost_c": 2.0,
    "wind_ein": 0, "wind_kmh_max": 40.0,
    "regen_ein": 0, "regen_mmh_max": 0.5,
    #
    # Den Plan der Nacht zur Rechenzeit einfrieren. AUS, weil es das
    # Verhalten aendert: bis dahin gilt immer der zuletzt gerechnete Stand.
    "plan_festhalten": 0,
    #
    # Meldungen in den LoxBerry-Benachrichtigungsbereich. AUS.
    "melden_ein": 0, "melden_limit_tage": 3, "melden_station_tage": 2,
    #
    # Groesstes Alter eines Stationswerts in Sekunden.
    "hoechstalter": 3600,
}

_LOG = logging.getLogger("bewaesserung")


def log_einrichten(nach_stdout: bool = False) -> None:
    """Das Protokoll einrichten - mit genau EINEM Kanal in die Datei.

    Bis 0.9.6 hingen hier zwei Aufnehmer: einer auf die Logdatei und einer
    auf die Standardausgabe. dienst.sh leitet die Standardausgabe aber in
    DIESELBE Datei um - der Kommentar dort sagt sogar ausdruecklich, das
    Python-Skript protokolliere deshalb nicht zusaetzlich dorthin. Tat es
    doch: jede Zeile stand zweimal drin.

    Schlimmer als die Doppelung ist die Nebenwirkung. Der
    RotatingFileHandler benennt die Datei beim Ueberlauf um; die
    Shell-Umleitung schreibt danach weiter in den alten Dateizeiger, also
    in die weggerollte Datei. Das Protokoll zerfaellt still in zwei Haelften.

    Der zweite Kanal wird deshalb nur noch dort angehaengt, wo die Ausgabe
    wirklich auf den Bildschirm gehoert: bei --einmal und --selbsttest.
    """
    os.makedirs(LOGDIR, exist_ok=True)
    _LOG.setLevel(logging.INFO)
    if _LOG.handlers:
        return
    h = logging.handlers.RotatingFileHandler(DATEI_LOG, maxBytes=512000,
                                             backupCount=2, encoding="utf-8")
    h.setFormatter(logging.Formatter("[%(asctime)s] %(levelname)s %(message)s",
                                     "%Y-%m-%d %H:%M:%S"))
    _LOG.addHandler(h)
    if nach_stdout:
        k = logging.StreamHandler(sys.stdout)
        k.setFormatter(logging.Formatter("%(levelname)s %(message)s"))
        _LOG.addHandler(k)


def melden(schwere: int, text: str) -> bool:
    """Eine Zeile in den LoxBerry-Benachrichtigungsbereich legen.

    Fuer Python gibt es dort keine Schnittstelle; das Zwischenstueck
    bin/bw_notify.php ruft notify_ext() aus libs/phplib/loxberry_log.php auf -
    derselbe Weg, den das APC-UPS-Plugin dieser Reihe seit Langem geht.

    Schlaegt es fehl, ist das kein Grund, den Rechengang abzubrechen: eine
    Meldung ist eine Beigabe, keine Aufgabe des Dienstes.
    """
    skript = os.path.join(HIER, "bw_notify.php")
    if not os.path.isfile(skript):
        return False
    php = None
    for k in ("/usr/bin/php", "/usr/local/bin/php", "php"):
        if os.path.isabs(k) and os.path.isfile(k):
            php = k
            break
        if not os.path.isabs(k):
            php = k
    try:
        import subprocess
        r = subprocess.run([php, skript, str(int(schwere)), str(text), ORDNER],
                           capture_output=True, text=True, timeout=20)
        if r.returncode != 0:
            _LOG.info("Meldung nicht abgelegt: %s",
                      (r.stderr or r.stdout or "").strip()[:200])
            return False
        return True
    except Exception as f:                        # noqa: BLE001
        _LOG.info("Meldung nicht abgelegt (%s): %s", type(f).__name__, f)
        return False


def meldungen_pruefen(abbild: dict, cfg: dict) -> list:
    """Dauerstoerungen melden - nicht jede einzelne Nacht.

    Zwei Lagen, beide erst nach mehreren Tagen: die Anlage kommt dem Bedarf
    nicht nach, und die eigene Station liefert nichts mehr. Eine Meldung je
    Lage und Tag, gemerkt in der Zustandsdatei - sonst steht der
    Benachrichtigungsbereich nach einer Woche voll mit derselben Zeile.

    AUS ab Werk.
    """
    if not int(cfg.get("melden_ein") or 0):
        return []
    stand = json_lesen(DATEI_ZUSTAND)
    zaehler = stand.get("meldezaehler") or {}
    heute = abbild.get("datum") or ""
    raus = []

    plan = abbild.get("plan") or {}
    if not int(plan.get("reicht") or 0) and int(plan.get("noetige_durchlaeufe") or 0) > 0:
        zaehler["limit"] = int(zaehler.get("limit") or 0) + 1
    else:
        zaehler["limit"] = 0
    grenze = max(1, int(cfg.get("melden_limit_tage") or 3))
    if zaehler["limit"] == grenze:
        raus.append((4, "Die Bewaesserung kommt dem Bedarf seit %d Rechengaengen "
                        "nicht nach (noetig %d, geplant %d)."
                     % (grenze, plan.get("noetige_durchlaeufe", 0),
                        plan.get("durchlaeufe", 0))))

    # Wer eine Station eingerichtet hat und NULL Werte von ihr bekommt,
    # hat ein Problem. Wer bewusst keine betreibt und rein mit dem Modell
    # rechnet, hat keines - bis 0.9.18 bekam er dieselbe Meldung, seine
    # Wetterstation liefere nichts mehr. Der Reiter Test hatte diesen
    # Waechter schon; hier fehlte er.
    herkunft = abbild.get("herkunft") or {}
    zuordnung = json_lesen(DATEI_QUELLEN)
    eingerichtet = sum(1 for f in ((zuordnung or {}).get("felder") or {}).values()
                       if isinstance(f, dict) and f.get("weg"))
    hat_station = any(w == "station" for w in herkunft.values())
    if herkunft and eingerichtet > 0 and not hat_station:
        zaehler["station"] = int(zaehler.get("station") or 0) + 1
    else:
        zaehler["station"] = 0
    grenze2 = max(1, int(cfg.get("melden_station_tage") or 2))
    if zaehler["station"] == grenze2:
        raus.append((4, "Die eigene Wetterstation liefert seit %d Rechengaengen "
                        "keinen Wert mehr - gerechnet wird mit dem Modell."
                     % grenze2))

    stand["meldezaehler"] = zaehler
    stand["meldetag"] = heute
    json_schreiben(DATEI_ZUSTAND, stand)
    for schwere, text in raus:
        melden(schwere, text)
    return [t for _s, t in raus]


def stationslage_protokollieren(abbild: dict) -> bool:
    """Einmal je Tag ins Protokoll: greift die eigene Zuordnung ueberhaupt?

    Anlass, am Geraet gemessen am 06.09.2026: eine Anlage lief sechseinhalb
    Stunden mit eingerichteter Wetterstation, mit empfangenen Nutzlasten
    (34 Sekunden alt) - und NULL uebernommenen Werten. Jede Groesse kam von
    Open-Meteo, 'et0_abdeckung_h' blieb bei 0.0, 'tagesextreme.json' blieb
    leer, und die eigene Rechnung wurde in JEDEM Rechengang verworfen. Im
    Protokoll stand davon nichts.

    Den Waechter dafuer gibt es in meldungen_pruefen() - aber der steigt in
    seiner ersten Zeile aus, wenn 'melden_ein' nicht gesetzt ist, und das
    ist es ab Werk. Eine Benachrichtigung ist auch der falsche Ort: sie ist
    eine Beigabe. Das Protokoll ist der Ort, an dem man nachsieht.

    Deshalb hier, UNABHAENGIG von 'melden_ein' - und genau einmal je Tag.
    In jedem Rechengang waeren es bei einem Zehnminutentakt 144 Zeilen am
    Tag, und das ist dasselbe wie keine.

    Gezaehlt wird gegen die ZUORDNUNG, nicht gegen 'herkunft' allein: fuer
    tmin, tmax, rh_min, rh_max, wind, strahlung_wm2 und regen_tag
    ueberschreibt der Open-Meteo-Rueckfall in quellen.py die Herkunft,
    bevor der Grund gemerkt wird. Wer nur auf 'herkunft' sieht, kann "nie
    eingerichtet" nicht von "eingerichtet und stumm" unterscheiden - genau
    diese Verwechslung hat den Befund oben so lange verdeckt.

    Rueckgabe: True, wenn eine Zeile geschrieben wurde.
    """
    herkunft = abbild.get("herkunft") or {}
    heute = str(abbild.get("datum") or "")
    if not herkunft or not heute:
        return False
    stand = json_lesen(DATEI_ZUSTAND)
    if stand.get("stationstag") == heute:
        return False

    felder = (json_lesen(DATEI_QUELLEN) or {}).get("felder") or {}
    eingerichtet = sorted(g for g, f in felder.items()
                          if isinstance(f, dict) and f.get("weg"))
    liefern = sorted(g for g in eingerichtet if herkunft.get(g) == "station")
    # Der GRUND gehoert in die Zeile. "tmin, tmax, wind" sagt, WELCHE
    # Groessen schweigen; erst "tmin (pfad_fehlt)" sagt, wonach zu suchen
    # ist. Ohne ihn ist "eingerichtet und stumm" von "nie eingerichtet"
    # nicht zu unterscheiden - genau daran hing der Geraetebefund vom
    # 06.09.2026 sechseinhalb Stunden lang.
    gruende = abbild.get("herkunft_grund") or {}
    stumm = ["%s (%s)" % (g, gruende[g]) if gruende.get(g) else g
             for g in eingerichtet if g not in liefern]

    if not eingerichtet:
        _LOG.info("Eigene Messquellen: keine eingerichtet - gerechnet wird "
                  "mit dem Modell.")
    elif not liefern:
        _LOG.warning("Eigene Messquellen: %d eingerichtet, KEIN einziger Wert "
                     "uebernommen (%s) - gerechnet wird mit dem Modell. "
                     "Die Zuordnung im Reiter Quellen passt nicht mehr zu "
                     "dem, was die Station sendet.",
                     len(eingerichtet), ", ".join(stumm))
    elif stumm:
        _LOG.info("Eigene Messquellen: %d von %d liefern; ohne Wert: %s.",
                  len(liefern), len(eingerichtet), ", ".join(stumm))
    else:
        _LOG.info("Eigene Messquellen: alle %d liefern.", len(eingerichtet))

    stand["stationstag"] = heute
    json_schreiben(DATEI_ZUSTAND, stand)
    return True


# ---------------------------------------------------------------- Dateien

# Die Rueckgabecodes der MQTT-Anmeldung, damit die Meldung den Grund
# nennt statt einer Zahl. Quelle: MQTT 3.1.1, Abschnitt 3.2.2.3.
# Am Geraet gemessen (06.09.2026, mosquitto mit allow_anonymous false):
# ein falsches Kennwort wird mit 5 abgewiesen, NICHT mit 4. Mosquitto
# fasst "Kennwort falsch" und "gar keine Anmeldung" zu einem Code
# zusammen. Der Text zu 5 muss deshalb beide Faelle nennen - bis 0.9.20
# nannte er nur den selteneren und schickte den Anwender damit an die
# falsche Stelle.
CONNACK_TEXT = {
    1: "Protokollfassung abgelehnt",
    2: "Kennung abgelehnt",
    3: "Broker nicht verfuegbar",
    # 4 benutzt mosquitto nicht; andere Broker schon.
    4: "Benutzername oder Kennwort falsch",
    5: "nicht berechtigt - Benutzername oder Kennwort falsch, oder der "
       "Broker verlangt eine Anmeldung",
}


class _Uebersprungen(Exception):
    """Kein Fehler: dieser Takt wurde ausgelassen, weil ein anderer Lauf
    gerade rechnet. Eigene Klasse, damit der Auffangzweig sie nicht als
    "Rechengang fehlgeschlagen" protokolliert und keine Stoerung meldet."""


class Rechensperre:
    """Verhindert, dass Dienstschleife und "Jetzt rechnen" zugleich rechnen.

    json_schreiben() ist unteilbar (Nebendatei, fsync, os.replace) - eine
    halb geschriebene Datei kann nicht entstehen. Ein VERLORENES Schreiben
    schon: zwei Laeufe lesen denselben Verlauf, beide schreiben, und die
    Gieß-Rueckmeldung des ersten ist fort. Gemessen mit verschraenkten
    Lese-/Schreibfolgen am 06.09.2026.

    Die Sperre faellt OFFEN aus: gibt es kein fcntl (Bau-Rechner, Windows)
    oder laesst sich die Datei nicht anlegen, wird gerechnet wie bisher.
    Ein Schutz, der den Dienst anhaelt, waere schlimmer als der Schaden.
    Das Betriebssystem gibt die Sperre beim Prozessende von selbst frei;
    eine liegengebliebene Sperrdatei blockiert deshalb nichts.
    """

    def __init__(self, warte_s: float = 0.0) -> None:
        self.warte_s = float(warte_s)
        self._f = None

    def __enter__(self) -> bool:
        try:
            import fcntl
        except ImportError:
            return True
        try:
            os.makedirs(DATADIR, exist_ok=True)
            self._f = open(os.path.join(DATADIR, "rechnen.lock"), "w")
        except OSError:
            self._f = None
            return True
        ende = time.time() + self.warte_s
        while True:
            try:
                fcntl.flock(self._f.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                return True
            except OSError:
                if time.time() >= ende:
                    return False
                time.sleep(0.5)

    def __exit__(self, *_a) -> None:
        if self._f is not None:
            try:
                self._f.close()
            except OSError:
                pass
            self._f = None


def json_lesen(p: str) -> dict:
    """Eine JSON-Datei lesen - und einen Schaden nicht verschweigen.

    Bis 0.9.18 gaben "gibt es nicht" und "ist Muell" dasselbe zurueck:
    ein leeres Verzeichnis, ohne eine Zeile im Protokoll. Eine
    beschaedigte verlauf.json liess damit jede Zone mit Fuellstand 100 %
    und Bedarf 0 dastehen, und der naechste Lauf schrieb die Datei mit
    einem einzigen Tag neu - die Vorgeschichte war endgueltig weg.

    Eine unlesbare Datei wird deshalb beiseitegelegt und gemeldet. Fehlt
    sie oder ist sie leer, ist das der Normalfall des ersten Laufs und
    bleibt still.
    """
    try:
        with open(p, "r", encoding="utf-8") as fh:
            d = json.load(fh)
        return d if isinstance(d, dict) else {}
    except OSError:
        return {}
    except ValueError as f:
        beiseite = "%s.kaputt.%s" % (p, time.strftime("%Y%m%d_%H%M%S"))
        try:
            os.replace(p, beiseite)
            _LOG.error("%s ist unlesbar (%s) und liegt jetzt als %s "
                       "daneben.", os.path.basename(p), f,
                       os.path.basename(beiseite))
        except OSError as g:
            _LOG.error("%s ist unlesbar (%s) und liess sich nicht "
                       "beiseitelegen: %s", os.path.basename(p), f, g)
        return {}


def json_schreiben(p: str, d: Any, rechte: int | None = None) -> bool:
    """Nebendatei schreiben, dann umbenennen - os.replace ist unteilbar.

    Der Name der Nebendatei traegt die Prozessnummer. Ohne sie hiess sie
    schlicht <datei>.tmp, und die ist nicht eindeutig: der Dienst schreibt
    abbild.json im Takt, und derselbe Code laeuft ein zweites Mal, sobald
    jemand im Reiter Test auf 'Jetzt rechnen' klickt (dienst.sh einmal).
    Beide schrieben dann in dieselbe Nebendatei, und was am Ende umbenannt
    wurde, war eine Mischung aus zwei JSON-Dokumenten - also keines.

    fsync vor dem Umbenennen: ohne ihn steht nach einem Stromausfall zwar
    ein Dateiname da, aber womoeglich noch kein Inhalt. Beim Verlauf des
    Wasserhaushalts waere das der Unterschied zwischen 'Bilanz laeuft
    weiter' und 'faengt bei null an'.
    """
    tmp = "%s.tmp.%d" % (p, os.getpid())
    try:
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(d, fh, ensure_ascii=False, indent=1)
            fh.flush()
            os.fsync(fh.fileno())
        if rechte is not None:
            os.chmod(tmp, rechte)
        os.replace(tmp, p)
        return True
    except (OSError, TypeError, ValueError) as f:
        # TypeError/ValueError: ein nicht serialisierbarer Wert im Abbild.
        # Ohne diesen Zweig bliebe eine halbe Nebendatei liegen und der
        # Fehler flöge bis in die Hauptschleife.
        _LOG.error("Konnte %s nicht schreiben: %s", p, f)
        try:
            os.unlink(tmp)
        except OSError:
            pass
        return False


def config() -> dict:
    c = dict(VORGABEN)
    c.update(json_lesen(DATEI_CONFIG))
    return c


def vorlagen() -> dict:
    for k in (DATEI_VORLAGEN, str(HIER.parent / "templates" / "quellen.json")):
        d = json_lesen(k)
        if d.get("groessen"):
            return d
    return {"groessen": {}, "vorlagen": {}, "einheiten": {}}


def pflanzen() -> dict:
    for k in (DATEI_PFLANZEN, str(HIER.parent / "templates" / "pflanzen.json")):
        d = json_lesen(k)
        if d.get("bepflanzung"):
            return d
    return {"bepflanzung": {}, "boden": {}, "regner": {}}


def zonen() -> list[dict]:
    d = json_lesen(DATEI_ZONEN)
    z = d.get("zonen")
    return z if isinstance(z, list) else []


# Eine Funktion zonen_speichern() stand hier bis 0.9.6 und wurde von keiner
# Zeile aufgerufen. Sie ist entfernt, nicht bloss auskommentiert: eine
# Schreibfunktion im Dienst, die aussieht, als schriebe der Dienst den
# Zonenstand zurueck, ist eine falsche Faehrte. Der Zonenstand 'dr' wird
# bewusst NICHT fortgeschrieben - die Bilanz entsteht bei jedem Lauf neu aus
# dem Verlauf, und zwei Quellen fuer dieselbe Zahl liefen zwangslaeufig
# auseinander.


# ------------------------------------------------------------------- MQTT

def mqtt_gateway() -> dict:
    """Das MQTT-Gateway ist seit LoxBerry 3 Bestandteil des Systems.

    Massgeblich ist 'Gatewayautostart', nicht 'Brokerhost': letzterer steht ab
    Werk auf 'localhost' und sagt deshalb nichts darueber aus, ob das Gateway
    ueberhaupt laeuft.
    """
    d = json_lesen(os.path.join(HOME, "config", "system", "general.json"))
    m = d.get("Mqtt") or d.get("MQTT") or {}
    if not isinstance(m, dict):
        return {"gefunden": 0}
    def hol(gross, klein):
        return m.get(gross, m.get(klein, ""))

    return {
        "gefunden": 1,
        "autostart": 1 if str(hol("Gatewayautostart", "gatewayautostart")) in ("1", "true", "True") else 0,
        "udpport": int(hol("Udpinport", "udpinport") or 0),
        "broker": str(hol("Brokerhost", "brokerhost") or ""),
        "brokerport": int(hol("Brokerport", "brokerport") or 1883),
        # Die Anmeldedaten des Brokers. Die PHP-Seite liest sie seit jeher,
        # der Dienst nicht - und verband sich deshalb anonym. Verlangt der
        # Broker eine Anmeldung, kam nie eine Nachricht an, und im Protokoll
        # stand 'Broker nicht erreichbar'.
        "user": str(hol("Brokeruser", "brokeruser") or ""),
        "pw": str(hol("Brokerpass", "brokerpass") or ""),
    }


# Welche Themen zurueckbehalten werden.
#
# Hausstandard seit 03.09.2026: Zustaende retained, Messwerte mit Zeitbezug
# nicht, das Lebenszeichen nie. Zustand ist hier alles, was einen Sollwert
# oder ein Flag traegt - nach einem Neustart des Miniservers oder des
# Gateways muss es sofort wieder dastehen. Messwerte (et0, liter, minuten,
# fuellstand, bedarf, defizit, gegossen) gehen bewusst OHNE Retain hinaus,
# damit nach einem Ausfall kein alter Wert als aktuell erscheint; ebenso
# 'alter', 'ts' und 'zaehler'.
#
# Bis 0.9.21 ging KEIN einziges Thema retained hinaus. Ueber Gateway v1
# heisst das UDP-Verb dafuer 'retain' statt 'publish' - gemessen am
# 06.09.2026 im Quelltext des Geraets (mqttgateway.pl:293: der UDP-Eingang
# kennt genau publish, retain, reconnect, save_relayed_states).
RETAINED_GLOBAL = {
    "ok", "giessen", "reicht", "gesperrt", "sperrgrund", "plan_fest",
    "deckt", "durchlaeufe", "noetige_durchlaeufe",
}
RETAINED_ZONE = ("ok", "sekunden", "durchlaeufe")


def mqtt_senden(paare: dict, praefix: str, retained: set | None = None) -> int:
    """Ueber den UDP-Eingang des Gateways veroeffentlichen.

    Der Weg ueber UDP braucht keine Zugangsdaten - das Gateway setzt sie
    selbst. Ein eigener Broker-Anmeldeversuch waere ein zweiter Ort, an dem
    ein Kennwort liegt.

    'retained' nennt die Themen (ohne Praefix), die mit dem Verb 'retain'
    statt 'publish' hinausgehen sollen.
    """
    g = mqtt_gateway()
    if not g.get("gefunden") or not g.get("udpport"):
        return 0
    gesendet = 0
    s = None
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        for name, wert in paare.items():
            # 'publish ' bzw. 'retain ' davor - das ist die Form, die der
            # UDP-Eingang des LoxBerry-Gateways erwartet und die auch die
            # uebrigen Plugins dieser Reihe benutzen. Bis 0.9.0 fehlte das
            # Verb hier als einzigem Plugin.
            verb = "retain" if (retained and name in retained) else "publish"
            zeile = "%s %s/%s %s" % (
                verb, _mqtt_thema(praefix.strip("/")), _mqtt_thema(name),
                mqtt_wert_saeubern(_mqtt_sauber(wert)))
            s.sendto(zeile.encode("utf-8"), ("127.0.0.1", int(g["udpport"])))
            gesendet += 1
    except OSError as f:
        # Die schon gesendeten Themen werden GENANNT. Bis 0.9.21 gab die
        # Funktion hier 0 zurueck, und das Protokoll meldete "0 Themen
        # gesendet", obwohl die Haelfte draussen war.
        _LOG.warning("MQTT-Gateway nicht erreichbar nach %d Thema/Themen: %s",
                     gesendet, f)
        return gesendet
    finally:
        # In einem finally, nicht hinter der Schleife: brach sendto ab,
        # blieb der Dateizeiger bis zum Verlassen der Funktion offen.
        if s is not None:
            try:
                s.close()
            except OSError:
                pass
    return gesendet


_ZAEHLER = -1


def _lauf_zaehler() -> int:
    """Das Lebenszeichen: 0...999, umlaufend, eins weiter je Vollversand.

    Nie retained (Hausstandard): ein zurueckbehaltenes Lebenszeichen zeigt
    nach einem Ausfall fuer immer "lebt". Wer in Loxone eine Ausfallerkennung
    baut, sieht an einer stehenden Zahl, dass nichts mehr kommt.
    """
    global _ZAEHLER
    _ZAEHLER = 0 if _ZAEHLER >= 999 else _ZAEHLER + 1
    return _ZAEHLER


def stoerung_veroeffentlichen(cfg: dict) -> int:
    """Nach einem gescheiterten Rechengang wenigstens 'ok=0' hinausgeben.

    Bis 0.9.21 stand veroeffentlichen() im selben try wie rechnen(): warf
    der Rechengang, wurde gar nichts gesendet, und der Broker behielt das
    letzte 'ok=1'. Die eine Zahl, an der Loxone eine Stoerung erkennen soll,
    fehlte ausgerechnet im Stoerungsfall.
    """
    if not int(cfg.get("mqtt_ein") or 0):
        return 0
    return mqtt_senden({"ok": 0, "ts": int(time.time()),
                        "zaehler": _lauf_zaehler()},
                       str(cfg.get("mqtt_topic") or "bewaesserung"),
                       {"ok"})


def _mqtt_sauber(wert: Any) -> str:
    """Zeilenumbrueche und Steuerzeichen entfernen.

    Der UDP-Eingang des Gateways wertet einen Zeilenumbruch als Ende des
    Befehls: ein mehrzeiliger Wert zerfaellt dort in Bruchstuecke, aus denen
    das Gateway erfundene Themen bildet.

    Hier sind die Werte zwar durchweg Zahlen - aber die Themennamen kommen
    aus dem Zonenschluessel, und der stammt aus der Konfiguration. Ein
    Leerzeichen darin wuerde die Trennung zwischen Thema und Wert verschieben.
    """
    t = str(wert)
    for z in ("\r\n", "\r", "\n", "\t"):
        t = t.replace(z, " ")
    t = "".join(c for c in t if c >= " ")
    while "  " in t:
        t = t.replace("  ", " ")
    return t.strip()


def _mqtt_thema(teil: Any) -> str:
    """Einen Themenbestandteil bereinigen.

    Strenger als beim Wert: im Thema darf ueberhaupt kein Leerzeichen stehen,
    denn genau daran trennt das Gateway Thema und Nutzlast. Ein Zonenname wie
    'Rasen hinten' wuerde die Zeile sonst mitten im Thema abschneiden, und
    Loxone bekaeme das Thema 'bewaesserung/Rasen' mit dem Wert 'hinten'.
    """
    t = _mqtt_sauber(teil)
    for z in (" ", "+", "#"):        # + und # sind MQTT-Platzhalter
        t = t.replace(z, "_")
    return t or "unbenannt"


# ------------------------------------------------------------ Der Rechengang

def verlauf_lesen() -> dict:
    d = json_lesen(DATEI_VERLAUF)
    t = d.get("tage")
    return {"tage": t if isinstance(t, dict) else {}}


def verlauf_ergaenzen(datum: str, eintrag: dict) -> None:
    """Einen Tag in den Verlauf schreiben - ohne die Bewaesserung zu verlieren.

    Die ausgebrachte Menge je Zone steht unter 'bewaesserung' im selben
    Tageseintrag. Sie wird beim Fortschreiben UEBERNOMMEN, wenn der neue
    Eintrag keine mitbringt: der Rechengang laeuft mehrmals am Tag, und
    beim zweiten Lauf duerfte die Bewaesserung des ersten nicht verschwinden.
    """
    v = verlauf_lesen()
    alt = v["tage"].get(datum) or {}
    if "bewaesserung" not in eintrag and isinstance(alt.get("bewaesserung"), dict):
        eintrag = dict(eintrag, bewaesserung=alt["bewaesserung"])
    v["tage"][datum] = eintrag
    # Ein Jahr reicht: laenger zurueck rechnet niemand die Bilanz nach.
    schluessel = sorted(v["tage"])
    for alt_tag in schluessel[:-400]:
        v["tage"].pop(alt_tag, None)
    json_schreiben(DATEI_VERLAUF, v)


def verlauf_luecken_fuellen(nach_datum: dict, heute_s: str) -> list:
    """Fehlende Tage aus den Vergangenheitstagen von Open-Meteo nachtragen.

    Nur Tage, die GAR NICHT dastehen, und nur Tage VOR heute. Ein vorhandener
    Eintrag wird nie ueberschrieben - er kann von der eigenen Station stammen,
    und die schlaegt das Modell.

    Rueckgabe: die Liste der nachgetragenen Daten, damit das Protokoll sie
    nennen kann. Eine stille Ergaenzung waere hier falsch: sie aendert das
    Defizit, und wer die Zahl hinterher nicht erklaeren kann, glaubt ihr nicht.
    """
    v = verlauf_lesen()
    neu = []
    for datum in sorted(nach_datum):
        if datum >= heute_s:
            continue
        vorhanden = v["tage"].get(datum)
        # Ein Tag, der DASTEHT, aber kein 'et0' traegt, ist eine Luecke.
        #
        # Bis 0.9.21 stand hier nur "datum in v['tage']". Der Rechengang
        # legt fuer einen Tag ohne ET0 absichtlich einen Eintrag OHNE den
        # Schluessel an (siehe rechnen(), Abschnitt "Verlauf") - eigens
        # damit der Lueckenfueller ihn nachtragen kann. Genau das tat er
        # nicht: der Tag stand da, und giessplan.py las ihn dauerhaft als
        # 0,0 mm Verdunstung. Der Fehler ging in dieselbe Richtung wie die
        # Luecke selbst - zu wenig Wasser.
        if vorhanden is not None and vorhanden.get("et0") is not None:
            continue
        t = nach_datum[datum]
        if t.get("et0") is None:
            continue
        # Der vorhandene Eintrag wird ERGAENZT, nicht ersetzt: die
        # Gieß-Rueckmeldung des Tages ('bewaesserung') steht darin und
        # laesst sich nicht wiederbeschaffen.
        eintrag = dict(vorhanden or {})
        eintrag["et0"] = float(t["et0"])
        eintrag["nachgetragen"] = 1
        # Regen aus dem Modell nur, wenn der Tag keinen gemessenen traegt.
        # Der Eintrag eines Tages ohne ET0 setzt 'regen' auf 0.0, ohne dass
        # das jemand gemessen haette - das ist dieselbe stille Behauptung.
        if vorhanden is None or str(vorhanden.get("quelle") or "") in \
                ("", "keine", "unlesbar"):
            eintrag["regen"] = float(t.get("regen") or 0.0)
            eintrag["quelle"] = "open-meteo"
            eintrag["guete"] = "modell"
        v["tage"][datum] = eintrag
        neu.append(datum)
    if neu:
        schluessel = sorted(v["tage"])
        for alt_tag in schluessel[:-400]:
            v["tage"].pop(alt_tag, None)
        json_schreiben(DATEI_VERLAUF, v)
    return neu


def giesswerte_einsammeln(sammler, zonenliste: list, cfg: dict) -> dict:
    """Was Loxone in dieser Nacht ausgebracht hat - je Zone in Millimetern.

    Der Weg ist derselbe, den das Plugin ohnehin benutzt: ein MQTT-Thema je
    Zone. Ein schreibender Endpunkt kaeme nicht in Frage - der unangemeldete
    Bereich darf nichts schreiben, und ein Endpunkt, der die Wasserbilanz
    verstellen kann, waere eine Angriffsflaeche ohne Gegenwert.

    Drei Lesarten, weil Loxone drei Dinge liefern kann:

      minuten       Laufzeit der Zone seit Mitternacht
      durchlaeufe   Zahl der fertigen Durchlaeufe seit Mitternacht
      mm            die Hoehe unmittelbar, falls jemand sie selbst rechnet

    Aus Minuten und Durchlaeufen wird die Hoehe mit der **gemessenen**
    Niederschlagsrate gerechnet. Ohne Becherprobe gibt es keine Rueckmeldung:
    eine erfundene Rate waere je nach Regner um den Faktor sechzehn falsch,
    und dieser Fehler ginge unmittelbar in die Bilanz.

    Rueckgabe: {zonenschluessel: mm}. Zonen ohne Thema fehlen darin - das
    ist der Regelfall und kein Mangel.
    """
    aus = {}
    if sammler is None:
        return aus
    hoechstalter = float(cfg.get("hoechstalter") or 3600)
    wirkungsgrad = max(0.3, min(1.0, float(cfg.get("wirkungsgrad") or 0.75)))
    for z in zonenliste:
        s = str(z.get("schluessel") or "")
        thema = str(z.get("giess_thema") or "").strip()
        if not s or not thema:
            continue
        eintrag = sammler.mqtt.get(thema)
        if eintrag is None:
            continue
        nutzlast, ts = eintrag
        if time.time() - ts > hoechstalter:
            continue
        roh = quellen.zahl(nutzlast)
        if roh is None or roh < 0:
            continue
        art = str(z.get("giess_art") or "minuten")
        rate = float(z.get("rate_mmh") or 0.0)
        if art == "mm":
            mm = roh
        elif rate <= 0 or not z.get("rate_gemessen"):
            # Fail closed: lieber keine Rueckmeldung als eine geratene.
            continue
        elif art == "durchlaeufe":
            dauer = float(z.get("dauer_s") or cfg.get("zonendauer_s") or 240)
            mm = roh * rate * wirkungsgrad * (dauer / 3600.0)
        else:
            mm = (roh / 60.0) * rate * wirkungsgrad
        aus[s] = round(max(0.0, mm), 2)
    return aus


def zonenfeuchte(sammler, zone: dict, cfg: dict,
                 allgemein: float | None = None) -> tuple[float | None, str]:
    """Die Bodenfeuchte einer Zone - mit Altersgrenze.

    Bis 0.9.6 wurde sie unmittelbar aus 'sammler.mqtt' gelesen und damit an
    der Verfallspruefung vorbei, die fuer jede andere Messgroesse gilt. Ein
    ausgefallener Fuehler lieferte seinen letzten Wert dadurch unbegrenzt
    lange weiter - und weil der Wert das gerechnete Defizit mit dem Gewicht
    0,5 zu sich zieht, haette ein bei 'nass' stehengebliebener Fuehler die
    Bewaesserung auf Dauer abgeschaltet.

    Rueckfall auf die allgemeine Groesse 'bodenfeuchte' aus dem Reiter
    Quellen, falls die Zone kein eigenes Thema hat. Bis 0.9.6 war diese
    Groesse zuordenbar und wurde von keiner Zeile Code gelesen.
    """
    hoechstalter = float(cfg.get("hoechstalter") or 3600)
    thema = str(zone.get("feuchte_thema") or "").strip()
    if sammler is not None and thema:
        eintrag = sammler.mqtt.get(thema)
        if eintrag is None:
            return None, "kein_empfang"
        nutzlast, ts = eintrag
        if time.time() - ts > hoechstalter:
            return None, "veraltet"
        bf = quellen.zahl(nutzlast)
        if bf is None:
            return None, "unlesbar"
        return bf, "thema"
    if allgemein is not None:
        return allgemein, "allgemein"
    return None, ""


def rechnen(cfg: dict, sammler: quellen.Sammler | None = None) -> dict:
    """Einmal alles rechnen: Messwerte, ET0, Bilanz je Zone, Plan."""
    heute = datetime.date.today()
    jetzt_dt = datetime.datetime.now()
    standort = {"breite": cfg["breite"], "laenge": cfg["laenge"],
                "hoehe": cfg["hoehe"], "wind_hoehe": cfg["wind_hoehe"],
                "kuestennah": cfg["kuestennah"]}

    # --- online holen ---
    online = {"ok": 0, "tage": []}
    online_fehler = ""
    if abs(float(cfg["breite"])) > 0.001 or abs(float(cfg["laenge"])) > 0.001:
        try:
            online = quellen.open_meteo(float(cfg["breite"]), float(cfg["laenge"]),
                                        rueckwaerts=10,
                                        vorwaerts=max(2, int(cfg["vorschautage"]) + 1))
        except Exception as f:
            online_fehler = str(f)
            _LOG.warning("Open-Meteo antwortet nicht: %s", f)
    else:
        online_fehler = "Kein Standort eingetragen."

    nach_datum = {t["datum"]: t for t in (online.get("tage") or [])}
    heute_s = heute.isoformat()
    online_heute = nach_datum.get(heute_s)

    # --- Luecken im Verlauf schliessen (neu in 0.9.7) ---
    #
    # Die Vergangenheitstage sind bereits abgeholt (past_days=10) und wurden
    # bis 0.9.6 weggeworfen. Ein fehlender Tag faellt sonst ersatzlos aus der
    # Bilanz - und zwar nach unten: das Plugin verlangt dann zu wenig Wasser.
    nachgetragen = []
    if int(cfg.get("luecken_fuellen") or 0) and nach_datum:
        nachgetragen = verlauf_luecken_fuellen(nach_datum, heute_s)
        if nachgetragen:
            _LOG.info("Verlauf ergaenzt: %d fehlende Tage aus Open-Meteo (%s)",
                      len(nachgetragen), ", ".join(nachgetragen))

    # --- eigene Station ---
    if sammler is None:
        sammler_lokal = quellen.Sammler({}, vorlagen())
    else:
        sammler_lokal = sammler
        # Die Einstellung "Groesstes Alter eines Stationswerts" gilt ab
        # 0.9.22 auch fuer die Wetterwerte. Bis 0.9.21 stand sie in der
        # Oberflaeche, liess sich zwischen 300 und 86400 s stellen - und
        # wirkte nur auf die Gieß-Rueckmeldung und die Bodenfeuchte.
        sammler_lokal.hoechstalter = float(cfg.get("hoechstalter") or 3600)
        sammler.http_abholen()
        # Den Tagesverlauf fortschreiben, BEVOR die Werte gelesen werden -
        # sonst fehlt dem heutigen Tag genau der letzte Messpunkt.
        sammler.beobachten(heute_s)
        json_schreiben(DATEI_EXTREME, sammler.tag)
        # Was zuletzt wirklich angekommen ist - fuer den Reiter Quellen.
        #
        # Zwei Vorlagen in templates/quellen.json sagen woertlich zu: "Der
        # Reiter Quellen zeigt die Rohantwort - daran laesst sich jeder Pfad
        # in einer Minute richtigstellen" und "Der Reiter Quellen zeigt, was
        # zuletzt angekommen ist". Bis 0.9.6 zeigte er das nicht, und die
        # dafuer vorgesehene Datei roh.json wurde nie geschrieben. Das
        # Werkzeug, mit dem der Anwender seine Pfade richtigstellen soll,
        # gab es also nicht.
        #
        # Die Nutzlasten werden auf 2000 Zeichen gekuerzt: eine Wetterstation
        # kann sehr lange JSON-Antworten liefern, und die Datei soll die
        # Oberflaeche nicht lahmlegen.
        json_schreiben(DATEI_ROH, {
            "ts": int(time.time()),
            "http_url": sammler.http_url,
            "http_fehler": sammler.letzter_http_fehler,
            "http": (json.dumps(sammler.roh_http, ensure_ascii=False)[:2000]
                     if sammler.roh_http is not None else ""),
            "mqtt": {t: {"nutzlast": str(w[0])[:2000],
                         "alter_s": max(0, int(time.time() - w[1]))}
                     for t, w in sorted(sammler.mqtt.items())},
        })
    zus = quellen.messwerte_zusammenstellen(sammler_lokal, online_heute,
                                            standort, heute_s)

    m = dict(zus["messwerte"])
    # Das Jahr gehoert dazu: in einem Schaltjahr waere der Tagesindex
    # sonst ab dem 1. Maerz um eins zu klein (siehe fao56.tagesnummer).
    m["monat"], m["tag"], m["jahr"] = heute.month, heute.day, heute.year
    et0_eigen = None
    et0_fehler = ""
    if m.get("tmin") is not None and m.get("tmax") is not None:
        try:
            et0_eigen = fao56.et0_aus_messwerten(m)
        except Exception as f:
            et0_fehler = str(f)
    else:
        et0_fehler = "Ohne Tiefst- und Hoechsttemperatur laesst sich ET0 nicht rechnen."

    # Deckt die eigene Messreihe den Tag ueberhaupt ab?
    #
    # Am 18.08.2026 um 21:20 hat eine frisch eingerichtete Anlage aus EINEM
    # Momentanwert eine Tagesverdunstung von 0,39 mm gerechnet und als
    # "gemessen" in den Verlauf geschrieben - an einem Tag, fuer den das
    # Modell rund 3,8 mm nennt. Die Rechnung war richtig, die Eingangsgroessen
    # waren es auch; falsch war der ZEITBEZUG. Nachts ist die Strahlung 0 und
    # die Temperaturspanne ebenfalls, also faellt ET0 in sich zusammen.
    #
    # Seit 0.9.7 bildet der Sammler Tagesextremwerte - aber am ersten Tag,
    # nach jedem Neustart und bei jeder frischen Einrichtung ist die Reihe
    # noch kurz. Genau dann darf die eigene Zahl NICHT als Tageswert gelten.
    #
    # Die Grenze ist dieselbe wie beim Tagesmittel (18 Stunden). Darunter
    # gilt das Modell, und die Oberflaeche sagt warum. Ohne Modell bleibt die
    # eigene Zahl - dann aber mit der Guete 'momentaufnahme', damit niemand
    # sie fuer eine Tagesverdunstung haelt.
    et0_abdeckung_h = 0.0
    if sammler is not None:
        et0_abdeckung_h = max(sammler.abdeckung_stunden("tmin"),
                              sammler.abdeckung_stunden("tmax"))
    tag_gedeckt = et0_abdeckung_h >= quellen.MITTEL_MINDESTSTUNDEN
    et0_verworfen = ""
    if (et0_eigen is not None and not tag_gedeckt
            and online_heute and online_heute.get("et0") is not None):
        et0_verworfen = ("Die eigene Messreihe deckt erst %.1f Stunden ab. "
                         "Bis 18 Stunden gilt das Modell." % et0_abdeckung_h)
        _LOG.info("Eigene ET0 (%.2f mm) verworfen: nur %.1f h Abdeckung - "
                  "es gilt Open-Meteo (%.2f mm).",
                  et0_eigen["et0"], et0_abdeckung_h, float(online_heute["et0"]))
        et0_eigen = None

    # Welche Zahl gilt heute? Die eigene, wenn es sie gibt.
    if et0_eigen is not None:
        et0_heute = et0_eigen["et0"]
        et0_quelle = "station" if zus["herkunft"].get("tmax") == "station" else "gemischt"
        et0_guete = et0_eigen["guete"] if tag_gedeckt else "momentaufnahme"
        # 'gemessen' darf nur draufstehen, wenn die Strahlung wirklich von
        # einem Messfuehler kam. Kommt sie aus dem Modell, ist sie gerechnet -
        # ein Modellwert ist keine Messung, auch wenn er eine Zahl ist.
        if (et0_guete == "gemessen"
                and zus["herkunft"].get("strahlung_wm2") != "station"):
            et0_guete = "modellstrahlung"
    elif online_heute and online_heute.get("et0") is not None:
        et0_heute = float(online_heute["et0"])
        et0_quelle = "open-meteo"
        et0_guete = "modell"
    else:
        et0_heute = None
        et0_quelle = "keine"
        et0_guete = "keine"

    regen_heute = None
    w, woher = (sammler.wert("regen_tag") if sammler else (None, "fehlt"))
    if w is not None:
        regen_heute = w
    elif online_heute and online_heute.get("regen") is not None:
        regen_heute = float(online_heute["regen"])

    # --- Was hat Loxone ausgebracht? (neu in 0.9.7) ---
    zonenliste = zonen()
    gegossen = giesswerte_einsammeln(sammler, zonenliste, cfg)

    if et0_heute is not None or gegossen:
        # Ohne ET0 wird der SCHLUESSEL weggelassen, nicht 0.0 eingetragen.
        # Eine 0.0 ist fuer die Bilanz ein Tag ohne jede Verdunstung, und
        # der Lueckenfueller trug ihn nie nach, weil er "dasteht" - der
        # Fehler ging in dieselbe Richtung wie die Luecke selbst: zu wenig
        # Wasser.
        eintrag = {"regen": regen_heute or 0.0,
                   "quelle": et0_quelle, "guete": et0_guete}
        if et0_heute is not None:
            eintrag["et0"] = et0_heute
        if gegossen:
            # Der groessere Wert gilt: die Rueckmeldung ist ein Tagesstand,
            # und ein zweiter Rechengang darf sie nicht kleiner machen.
            alt = (verlauf_lesen()["tage"].get(heute_s) or {}).get("bewaesserung") or {}
            eintrag["bewaesserung"] = {k: max(float(alt.get(k) or 0.0), v)
                                       for k, v in gegossen.items()}
            for k, w in alt.items():
                eintrag["bewaesserung"].setdefault(k, float(w or 0.0))
        verlauf_ergaenzen(heute_s, eintrag)

    # --- Bilanz je Zone ---
    v = verlauf_lesen()["tage"]
    letzte = sorted(v)[-14:]
    vorschau = [nach_datum[d] for d in sorted(nach_datum)
                if d > heute_s][:int(cfg["vorschautage"])]

    # Wind und Luftfeuchte des Tages fuer die Klimaanpassung von Kc
    # [FAO-56, Gl. 62]. Sie greift nur bei Zonen mit eingetragener
    # Pflanzenhoehe - ohne die aendert sich nichts.
    wetter = None
    if et0_eigen is not None and m.get("rh_min") is not None:
        wetter = {"u2": et0_eigen.get("u2"), "rh_min": m.get("rh_min")}

    ergebnisse = {}
    for z in zonenliste:
        s = str(z.get("schluessel") or "")
        if not s:
            continue
        zz = dict(z)
        # Der Verlauf je Zone: dieselben Tage, aber mit DER Bewaesserung,
        # die diese Zone bekommen hat. Ohne Rueckmeldung steht dort 0 - also
        # genau das, was bis 0.9.6 immer galt.
        verlauf_liste = []
        for tag_s in letzte:
            eintrag_t = dict(v[tag_s], datum=tag_s)
            bew = eintrag_t.get("bewaesserung")
            eintrag_t["bewaesserung"] = float((bew or {}).get(s, 0.0)) \
                if isinstance(bew, dict) else 0.0
            verlauf_liste.append(eintrag_t)
        # Bodenfeuchte je Zone - mit Altersgrenze, seit 0.9.7
        bf, bf_woher = zonenfeuchte(sammler, z, cfg, m.get("bodenfeuchte"))
        if bf is not None:
            zz["bodenfeuchte"] = bf
        ergebnisse[s] = giessplan.zone_rechnen(zz, verlauf_liste, vorschau,
                                               cfg, wetter)
        ergebnisse[s]["feuchte_herkunft"] = bf_woher
        ergebnisse[s]["gegossen_mm"] = gegossen.get(s)
        if ergebnisse[s].get("ok"):
            ergebnisse[s]["liter"] = giessplan.mm_zu_litern(
                ergebnisse[s]["bedarf_mm"], float(z.get("flaeche") or 0.0))
            ergebnisse[s]["minuten"] = giessplan.mm_zu_minuten(
                ergebnisse[s]["bedarf_mm"], float(z.get("rate_mmh") or 0.0),
                float(cfg["wirkungsgrad"]))
            ergebnisse[s]["rate_gemessen"] = 1 if z.get("rate_gemessen") else 0

    plan = giessplan.plan_bauen(zonenliste, ergebnisse, cfg)

    # --- Sperren (neu in 0.9.7) ---
    #
    # Sie stehen NACH dem Plan, nicht davor: der Anwender soll sehen, was
    # noetig WAERE, und daneben, warum es heute Nacht trotzdem ausfaellt.
    # Ein Plan, der bei Frost einfach 'kein Bedarf' meldet, waere eine
    # stille Falschaussage.
    sperre = giessplan.sperren_pruefen(
        vorschau[0] if vorschau else None, cfg, m.get("regen_stunde"))
    plan["gesperrt"] = sperre["aktiv"]
    if sperre["aktiv"]:
        plan["durchlaeufe_ohne_sperre"] = plan["durchlaeufe"]
        plan["durchlaeufe"] = 0
        plan["grund"] = sperre["grund"]
        for jz in plan.get("je_zone", {}).values():
            jz["durchlaeufe"] = 0
            # Auch die Ventilzeit. Bis 0.9.18 blieb sekunden_soll stehen
            # und ging als <zone>/sekunden voll hinaus: wer die Zeit an
            # Tv haengt und den Start anderswoher nimmt, goss bei Frost.
            jz["sekunden_soll"] = 0

    abbild = {
        "ok": 1 if et0_heute is not None else 0,
        "ts": int(time.time()), "datum": heute_s,
        "et0": et0_heute, "et0_quelle": et0_quelle, "et0_guete": et0_guete,
        "et0_fehler": et0_fehler,
        "et0_abdeckung_h": round(et0_abdeckung_h, 1),
        "et0_verworfen": et0_verworfen,
        "et0_teile": et0_eigen or {},
        "regen_heute": regen_heute,
        "herkunft": zus["herkunft"],
        # 'herkunft_grund' steht NEBEN 'herkunft': warum eine eingerichtete
        # Groesse nichts geliefert hat ('pfad_fehlt', 'mqtt_veraltet',
        # 'mqtt_kein_json', 'unlesbar', ...). Bis 0.9.21 ueberschrieb der
        # Open-Meteo-Rueckfall die Herkunft, und die Oberflaeche zeigte
        # "Open-Meteo", wo in Wahrheit ein Pfad fehlte.
        "herkunft_grund": zus.get("grund") or {},
        "online_ok": online.get("ok", 0), "online_fehler": online_fehler,
        "vorschau": vorschau,
        "zonen": ergebnisse,
        "plan": plan,
        "sperre": sperre,
        "gegossen": gegossen,
        "nachgetragen": nachgetragen,
        "abdeckung": ({g: round(sammler_lokal.abdeckung_stunden(g), 1)
                       for g in ("tmin", "tmax", "strahlung_wm2", "wind")}
                      if sammler is not None else {}),
    }

    # --- Nachtplan festhalten (neu in 0.9.7) ---
    abbild["nachtplan"] = nachtplan_pflegen(abbild, cfg, jetzt_dt)
    return abbild


def nachtplan_pflegen(abbild: dict, cfg: dict, jetzt_dt) -> dict:
    """Den Plan der Nacht zur Rechenzeit einfrieren.

    Der Konfigurationsschluessel 'rechenzeit' stand seit 0.9.0 mit dem
    Kommentar "wann der Plan fuer die Nacht steht" in der Vorgabeliste - und
    wurde von keiner Zeile gelesen. Gerechnet wurde im Takt, rund um die Uhr.

    Das ist nicht bloss unordentlich: der Plan, den Loxone um 22:00 liest,
    konnte ein beliebiger Zwischenstand sein, und ein neuer Modelllauf um
    01:00 aenderte die Zahl mitten in der Nacht - waehrend der Zaehler in
    Loxone schon lief.

    Ab der eingestellten Uhrzeit steht die Zahl fuer diesen Tag. Die
    Oberflaeche rechnet weiter und zeigt beides.

    AUS ab Werk: es aendert das Verhalten, und niemand hat es bestellt.
    """
    if not int(cfg.get("plan_festhalten") or 0):
        return {}
    zeit = str(cfg.get("rechenzeit") or "20:00")
    try:
        st, mi = zeit.split(":")
        grenze = int(st) * 60 + int(mi)
        if not (0 <= int(st) <= 23 and 0 <= int(mi) <= 59):
            raise ValueError
    except (ValueError, AttributeError):
        return {}
    jetzt_min = jetzt_dt.hour * 60 + jetzt_dt.minute
    fest = json_lesen(DATEI_NACHTPLAN)
    # Der Plan gehoert zu der NACHT, die an diesem Tag beginnt. Nach
    # Mitternacht gilt deshalb noch der von gestern - sonst faellt die
    # eingefrorene Zahl mitten im Giessen auf einen neuen Stand.
    tag = abbild["datum"]
    if jetzt_min < grenze:
        tag = (datetime.date.fromisoformat(abbild["datum"])
               - datetime.timedelta(days=1)).isoformat()
        if fest.get("tag") == tag:
            return fest
        return {}
    if fest.get("tag") == tag:
        return fest
    plan = abbild.get("plan") or {}
    fest = {"tag": tag, "ts": int(time.time()), "zeit": zeit,
            "durchlaeufe": int(plan.get("durchlaeufe") or 0),
            "noetige_durchlaeufe": int(plan.get("noetige_durchlaeufe") or 0),
            "reicht": int(plan.get("reicht") or 0),
            "grund": str(plan.get("grund") or ""),
            "je_zone": {k: {"sekunden_soll": w.get("sekunden_soll", 0),
                            "durchlaeufe": w.get("durchlaeufe", 0)}
                        for k, w in (plan.get("je_zone") or {}).items()}}
    json_schreiben(DATEI_NACHTPLAN, fest)
    _LOG.info("Nachtplan fuer %s festgehalten: %d Durchlaeufe (Rechenzeit %s)",
              tag, fest["durchlaeufe"], zeit)
    return fest


def veroeffentlichen(abbild: dict, cfg: dict) -> int:
    """Die Zahlen in den Broker legen.

    Drei Berichtigungen gegenueber 0.9.6, alle drei aus derselben Familie -
    ein Wert, der etwas anderes sagt, als sein Name verspricht:

    1. 'alter' stand fest auf 0. Als retained-Wert im Broker meldete das
       Thema damit fuer immer "gerade eben gerechnet", auch wenn der Dienst
       seit Tagen stand. Auf dem HTTP-Weg wurde dieselbe Zahl korrekt
       gebildet. Jetzt hier auch.
    2. 'et0' wurde bei fehlgeschlagener Rechnung als 0 gesendet. Eine
       erfundene Null sieht in Loxone aus wie ein Tag ohne Verdunstung. Die
       Regel steht im PHP-Zweig woertlich - fehlender Wert, nichts senden -
       und gilt hier genauso.
    3. '<zone>/defizit_mm' trug den BEDARF, waehrend das gleichnamige Feld
       am HTTP-Endpunkt das DEFIZIT fuehrt. Zwei Wege, ein Name, zwei
       Zahlen; gemessen lagen sie um den Faktor 2,6 auseinander.

    Punkt 3 wird ausdruecklich NICHT durch Umbenennen geloest. Das Thema
    haengt auf jeder bestehenden Anlage an einem virtuellen Eingang, und ein
    stiller Bedeutungswechsel waere schlimmer als die Unklarheit. Stattdessen
    kommen zwei eindeutig benannte Themen daneben: 'bedarf_mm' (dasselbe wie
    bisher 'defizit_mm') und 'dr_mm' (das wirkliche Defizit).
    """
    if not int(cfg.get("mqtt_ein") or 0):
        return 0
    p = {}
    plan = abbild.get("plan") or {}
    sperre = abbild.get("sperre") or {}
    fest = abbild.get("nachtplan") or {}
    p["ok"] = int(abbild.get("ok") or 0)
    if abbild.get("et0") is not None:
        p["et0"] = round(float(abbild["et0"]), 2)
    # Der Nachtplan geht vor, sobald es einen fuer heute gibt.
    # Geklammert: "or" bindet staerker als der Bedingungsausdruck. Bis
    # 0.9.18 stand hier int(fest.get(...) if fest else ... or 0) - eine
    # vorhandene, aber unvollstaendige nachtplan.json ergab int(None) und
    # damit einen TypeError mitten im Veroeffentlichen. In diesem Takt
    # ging dann gar nichts hinaus.
    if fest:
        durchlaeufe = int(fest.get("durchlaeufe") or 0)
    else:
        durchlaeufe = int(plan.get("durchlaeufe") or 0)
    # Eine Sperre schlaegt auch den eingefrorenen Plan. Steht um 20:00 ein
    # Plan fest und zieht um 23:00 Frost auf, gingen sonst "gesperrt=1"
    # und "giessen=1" gleichzeitig hinaus, und welche der beiden Zahlen
    # der Miniserver befolgt, entscheidet die Verdrahtung.
    if int(sperre.get("aktiv") or 0):
        durchlaeufe = 0
    p["durchlaeufe"] = durchlaeufe
    p["noetige_durchlaeufe"] = int(plan.get("noetige_durchlaeufe") or 0)
    p["reicht"] = int(plan.get("reicht") or 0)
    p["giessen"] = 1 if durchlaeufe > 0 else 0
    p["alter"] = max(0, int(time.time()) - int(abbild.get("ts") or 0))
    # 'ts' und 'zaehler' stehen NEBEN 'alter', nicht an seiner Stelle.
    #
    # 'alter' rechnet richtig, misst hier aber nichts: veroeffentlichen()
    # laeuft unmittelbar hinter rechnen(), und rechnen() setzt abbild['ts']
    # auf die aktuelle Zeit - die Differenz ist immer 0. Gemessen am
    # 06.09.2026 ueber drei Rechengaenge: dreimal 0; dasselbe Abbild zwei
    # Stunden alt ergibt richtig 7200. Ueber MQTT war ein toter Dienst damit
    # von einem gesunden nicht zu unterscheiden, waehrend der HTTP-Weg
    # dieselbe Zahl richtig bildet (er liest das Abbild von der Platte).
    #
    # Das Thema 'alter' haengt auf jeder bestehenden Anlage an einem
    # virtuellen Eingang. Es behaelt deshalb Namen und Bedeutung, und die
    # brauchbare Zahl kommt eindeutig benannt daneben: 'ts' ist der
    # Zeitpunkt des Rechengangs in Unix-Sekunden, 'zaehler' das
    # Lebenszeichen.
    p["ts"] = int(abbild.get("ts") or 0)
    p["zaehler"] = _lauf_zaehler()
    p["gesperrt"] = int(sperre.get("aktiv") or 0)
    p["sperrgrund"] = str(sperre.get("grund") or "")
    p["plan_fest"] = 1 if fest else 0
    # 'deckt' fehlte auf dem MQTT-Weg, waehrend der HTTP-Weg es seit jeher
    # als DECKT fuehrt. Ein reiner MQTT-Anwender bekam ausgerechnet die
    # Zahl nicht, die eine gedeckelte Ventilzeit sichtbar macht.
    p["deckt"] = int(plan.get("ventilzeit_deckt") or 0)
    for s, e in (abbild.get("zonen") or {}).items():
        # Der eingefrorene Plan gilt AUCH je Zone.
        #
        # Bis 0.9.21 kam 'durchlaeufe' oben aus 'fest', die Zahlen hier aus
        # 'plan'. Ein neuer Modelllauf um 01:00 aenderte damit die
        # Ventilzeit mitten in der Nacht, obwohl der Plan festgehalten war,
        # und '<zone>/durchlaeufe' widersprach 'durchlaeufe' im selben Takt.
        # Eine Zone, die es beim Einfrieren noch nicht gab, faellt auf den
        # frischen Plan zurueck - sonst bekaeme sie gar keine Ventilzeit.
        jz = {}
        if fest:
            jz = (fest.get("je_zone") or {}).get(s) or {}
        if not jz:
            jz = (plan.get("je_zone") or {}).get(s) or {}
        # '<zone>/ok' geht IMMER hinaus, auch wenn die Zone nicht rechnet.
        #
        # Bis 0.9.21 sprang die Schleife bei 'ok=0' heraus, und die Zone
        # sendete gar nichts. Der virtuelle Eingang behielt seine letzte
        # Ventilzeit, und Loxone goss weiter mit einer Zahl aus einem
        # Rechengang, der seither jedes Mal scheiterte. Die uebrigen
        # Zonenthemen bleiben in diesem Fall bewusst aus - sie behalten
        # ihren Stand, und '<zone>/ok' sagt, was davon zu halten ist.
        p["%s/ok" % s] = 1 if e.get("ok") else 0
        if not e.get("ok"):
            continue
        p["%s/defizit_mm" % s] = round(e["bedarf_mm"], 1)   # unveraendert
        p["%s/bedarf_mm" % s] = round(e["bedarf_mm"], 1)
        p["%s/dr_mm" % s] = round(e["dr"], 1)
        p["%s/fuellstand" % s] = round(e["fuellstand"], 0)
        p["%s/liter" % s] = round(e.get("liter") or 0.0, 0)
        p["%s/minuten" % s] = round(e.get("minuten") or 0.0, 0)
        p["%s/sekunden" % s] = int(jz.get("sekunden_soll") or 0)
        # Eine Sperre schlaegt auch die Zahl JE ZONE.
        #
        # Oben setzt die Sperre 'durchlaeufe' auf 0. Ohne diese Zeile stuende
        # daneben '<zone>/durchlaeufe = 4' - dieselbe Klasse Widerspruch im
        # selben Takt, nur eine Ebene tiefer. Die Ventilzeit
        # ('<zone>/sekunden') bleibt stehen: sie ist ein Sollwert, kein
        # Befehl, und Tv1..Tv8 sollen nicht bei jedem Frost auf 0 fallen.
        p["%s/durchlaeufe" % s] = 0 if int(sperre.get("aktiv") or 0)             else int(jz.get("durchlaeufe") or 0)
        if e.get("gegossen_mm") is not None:
            p["%s/gegossen_mm" % s] = round(float(e["gegossen_mm"]), 1)
    behalten = set(RETAINED_GLOBAL)
    for s in (abbild.get("zonen") or {}):
        for f in RETAINED_ZONE:
            behalten.add("%s/%s" % (s, f))
    return mqtt_senden(p, str(cfg.get("mqtt_topic") or "bewaesserung"),
                       behalten)


# --------------------------------------------------------------- Betrieb

def _themen_sammeln(sammler, zonenliste: list, zuordnung: dict | None = None) -> set:
    """Alle Themen, die der Dienst abonnieren muss.

    Vier Quellen: die Messgroessen aus dem Reiter Quellen, das Feuchtethema
    je Zone, das Rueckmeldethema je Zone - und seit 0.9.11 das **Horchthema**.

    Das Horchthema loest ein Henne-Ei-Problem: der Vorschlag aus dem Broker
    kann nur zeigen, was der Dienst empfangen hat, und empfangen kann er nur,
    was er abonniert hat. Bis 0.9.10 musste man dafuer erst eine Groesse von
    Hand auf MQTT stellen - also genau die Zuordnung vornehmen, die der
    Vorschlag ersparen soll. Jetzt genuegt das Thema an einer Stelle.
    """
    themen = set(sammler.mqtt_themen())
    horch = str((zuordnung or {}).get("mqtt_thema") or "").strip()
    if horch:
        themen.add(horch)
    for z in zonenliste:
        for feld in ("feuchte_thema", "giess_thema"):
            t = str(z.get(feld) or "").strip()
            if t:
                themen.add(t)
    return themen


def _stand_der_dateien() -> tuple:
    """Zeitstempel der Dateien, die die Abonnements bestimmen.

    Bis 0.9.6 las der Dienst die Quellenzuordnung genau einmal beim Start.
    Wer im Reiter Quellen ein Thema aenderte oder eine Zone mit Feuchtethema
    anlegte, aenderte damit gar nichts - bis jemand den Dienst neu startete.
    Gesagt hat das niemand; die Meldung lautete schlicht 'gespeichert'.
    """
    aus = []
    for p in (DATEI_QUELLEN, DATEI_ZONEN):
        try:
            aus.append(os.path.getmtime(p))
        except OSError:
            aus.append(0.0)
    return tuple(aus)


class Dienst:
    def __init__(self) -> None:
        self.laeuft = True
        self.themen: set = set()
        self.themen_neu = False
        # Merker fuer eine vom Broker ABGELEHNTE Anmeldung (CONNACK != 0).
        # Er steht hier und nicht erst vor dem Verbindungsaufbau, damit der
        # Auffangzweig ihn auch dann lesen kann, wenn schon das Anlegen des
        # Klienten scheitert.
        self.abgewiesen = False

    def anhalten(self, *_a) -> None:
        self.laeuft = False

    async def laufen(self) -> int:
        cfg = config()
        vor = vorlagen()
        zuordnung = json_lesen(DATEI_QUELLEN)
        sammler = quellen.Sammler(zuordnung, vor)
        # Den Tagesverlauf vom letzten Lauf uebernehmen. Ohne das verloere
        # ein Neustart um die Mittagszeit den Tagestiefstwert der Nacht -
        # und Tmin waere dann die Mittagstemperatur.
        sammler.tag_laden(json_lesen(DATEI_EXTREME))
        if sammler.tag.get("datum"):
            _LOG.info("Tagesverlauf uebernommen: %s, %d Groessen",
                      sammler.tag["datum"], len(sammler.tag.get("werte") or {}))
        self.themen = _themen_sammeln(sammler, zonen(), zuordnung)
        self.themen_neu = True
        # Der Horcher wird IMMER gestartet, auch wenn beim Start kein Thema
        # dasteht.
        #
        # Bis 0.9.21 stand hier "if self.themen:". mqtt_horchen() hat genau
        # eine Aufrufstelle - diese. Wer den Dienst laufen liess und danach
        # im Reiter Quellen seine Station eintrug, bekam die Protokollzeile
        # "Zuordnung geaendert: n Themen, wird neu abonniert" und trotzdem
        # nie einen Wert, weil der Horcher nie anlief. Er wartet jetzt auf
        # Themen, statt sie vorauszusetzen.
        _LOG.info("MQTT-Themen beim Start: %d", len(self.themen))
        asyncio.ensure_future(self.mqtt_horchen(sammler))

        letzte_rechnung = 0.0
        stand = _stand_der_dateien()
        takt = max(60, min(3600, int(cfg.get("takt") or 300)))
        while self.laeuft:
            try:
                cfg = config()
                # Der Takt wird in JEDEM Durchgang neu gebildet.
                #
                # Bis 0.9.21 stand die Zeile vor der Schleife. 'cfg' wurde
                # zwar jedes Mal neu gelesen, 'takt' nie - wer den Takt in
                # der Oberflaeche aenderte, wartete bis zum naechsten
                # Dienstneustart weiter mit dem alten Wert, ohne Hinweis.
                takt = max(60, min(3600, int(cfg.get("takt") or 300)))
                jetzt = time.time()

                # Hat jemand in der Oberflaeche etwas geaendert? Dann die
                # Zuordnung neu lesen und gegebenenfalls neu abonnieren -
                # ohne Neustart des Dienstes.
                stand_jetzt = _stand_der_dateien()
                if stand_jetzt != stand:
                    stand = stand_jetzt
                    zuordnung = json_lesen(DATEI_QUELLEN)
                    # Der Tagesspeicher gehoert zur ALTEN Zuordnung: Weg,
                    # Pfad und Einheit stehen nicht darin. Wer mittags von
                    # HTTP (metrisch) auf MQTT (imperial) umstellt, fuehrte
                    # sonst Kleinst-, Groesst- und Summenwert desselben
                    # Tages aus zwei Einheiten fort.
                    if ((zuordnung or {}).get("felder") or {}) != sammler.felder:
                        sammler.tag = {"datum": "", "werte": {}}
                        _LOG.info("Zuordnung geaendert - der Tagesverlauf "
                                  "beginnt neu.")
                    sammler.felder = (zuordnung or {}).get("felder") or {}
                    sammler.http_url = str((zuordnung or {}).get("http_url") or "")
                    neue = _themen_sammeln(sammler, zonen(), zuordnung)
                    if neue != self.themen:
                        self.themen = neue
                        self.themen_neu = True
                        _LOG.info("Zuordnung geaendert: %d Themen, wird neu abonniert",
                                  len(neue))
                    else:
                        _LOG.info("Zuordnung neu gelesen (Themen unveraendert).")
                    letzte_rechnung = 0.0      # sofort neu rechnen

                if jetzt - letzte_rechnung >= max(600, takt):
                    # Der ganze Rechengang steht unter einer Sperre.
                    #
                    # json_schreiben() ist unteilbar - eine halbe Datei kann
                    # nicht entstehen. Ein VERLORENES Schreiben schon: der
                    # Dienst und "Jetzt rechnen" lesen denselben Verlauf,
                    # beide schreiben, und die Gieß-Rueckmeldung des einen
                    # ist fort. Ohne Warten: bekommt die Schleife die Sperre
                    # nicht, hat der Anwender gerade selbst rechnen lassen -
                    # dann ist der Stand frisch, und der naechste Takt kommt.
                    with Rechensperre(0.0) as frei:
                        if not frei:
                            _LOG.info("Ein anderer Lauf rechnet gerade - "
                                      "dieser Takt wird ausgelassen.")
                            letzte_rechnung = jetzt
                            raise _Uebersprungen()
                        abbild = rechnen(cfg, sammler)
                        json_schreiben(DATEI_ABBILD, abbild)
                        alt_stand = json_lesen(DATEI_ZUSTAND)
                        json_schreiben(DATEI_ZUSTAND, {
                            "ok": abbild["ok"], "ts": abbild["ts"],
                            "et0": abbild.get("et0"),
                            "durchlaeufe": (abbild.get("plan") or {}).get("durchlaeufe", 0),
                            "gesperrt": (abbild.get("sperre") or {}).get("aktiv", 0),
                            "meldezaehler": alt_stand.get("meldezaehler") or {},
                            # Die beiden TAGESMARKEN werden uebernommen.
                            #
                            # Bis 0.9.21 ersetzte diese Zeile sie: 'stationstag'
                            # war nach jedem Rechengang fort, und die Zeile
                            # "Eigene Messquellen", die genau einmal am Tag
                            # erscheinen soll, stand in JEDEM Rechengang im
                            # Protokoll - bei Zehnminutentakt 144-mal am Tag.
                            # Gemessen: drei Rechengaenge desselben Tages, drei
                            # Zeilen; einmal() machte es schon richtig und kam
                            # im selben Versuch auf eine.
                            "meldetag": alt_stand.get("meldetag") or "",
                            "stationstag": alt_stand.get("stationstag") or "",
                            "fehler": abbild.get("et0_fehler") or abbild.get("online_fehler") or ""})
                        n = veroeffentlichen(abbild, cfg)
                        meldungen_pruefen(abbild, cfg)
                        # Unabhaengig von 'melden_ein' und genau einmal
                        # je Tag - siehe die Funktion selbst.
                        stationslage_protokollieren(abbild)
                        sp = abbild.get("sperre") or {}
                        _LOG.info("Gerechnet: ET0 %s mm (%s), %d Durchlaeufe, "
                                  "%d Themen gesendet%s",
                                  ("%.2f" % abbild["et0"]) if abbild.get("et0") is not None else "-",
                                  abbild.get("et0_quelle"),
                                  (abbild.get("plan") or {}).get("durchlaeufe", 0), n,
                                  (" - GESPERRT (%s)" % sp.get("grund")) if sp.get("aktiv") else "")
                        letzte_rechnung = jetzt
            except _Uebersprungen:
                pass
            except Exception as f:
                # exc_info: ein KeyError erschien bis 0.9.21 als eine einzige
                # Zeile mit einem Schluesselnamen - ohne Typ, ohne
                # Rueckverfolgung, ohne Zeilennummer.
                _LOG.error("Rechengang fehlgeschlagen: %s", f, exc_info=True)
                # Der Meldezaehler wird UEBERNOMMEN. Bis 0.9.18 ersetzte
                # diese Zeile die ganze Datei: ausgerechnet die Lage, die
                # zum Melden fuehren soll, setzte den Zaehler auf null
                # zurueck, sobald dabei etwas schiefging. Seit 0.9.22 stehen
                # beide Tagesmarken daneben, aus demselben Grund.
                alt_stand = json_lesen(DATEI_ZUSTAND)
                json_schreiben(DATEI_ZUSTAND, {
                    "ok": 0, "ts": int(time.time()), "fehler": str(f),
                    "meldezaehler": alt_stand.get("meldezaehler") or {},
                    "meldetag": alt_stand.get("meldetag") or "",
                    "stationstag": alt_stand.get("stationstag") or ""})
                # ... und die Stoerung geht auch nach aussen.
                try:
                    stoerung_veroeffentlichen(cfg)
                except Exception as f2:
                    _LOG.warning("Stoerungsmeldung nicht absetzbar: %s", f2)
            for _ in range(takt * 2):
                if not self.laeuft:
                    break
                await asyncio.sleep(0.5)
        return 0

    async def mqtt_horchen(self, sammler: quellen.Sammler) -> None:
        """Auf den Broker horchen - wenn das Paket da ist.

        paho-mqtt ist FREIWILLIG. Fehlt es, laeuft alles Uebrige weiter; nur
        die MQTT-Quellen bleiben leer, und das steht dann auch im Reiter Test.
        """
        try:
            import paho.mqtt.client as mqtt
        except ImportError:
            _LOG.info("Paket paho-mqtt fehlt - MQTT-Quellen bleiben leer. "
                      "Alles Uebrige laeuft weiter.")
            return
        g = mqtt_gateway()
        broker = g.get("broker") or "localhost"
        if broker in ("localhost", ""):
            broker = "127.0.0.1"
        warte = 60
        while self.laeuft:
            try:
                # Fassungsfest: paho-mqtt ab 2.0 verlangt die Angabe der
                # Rueckruf-Schnittstelle und wirft sonst einen ValueError,
                # der unten als "Broker nicht erreichbar" erschiene - eine
                # Meldung, die auf Netz und Anmeldung zeigt, waehrend das
                # Paket gemeint ist. postinstall.sh pinnt nichts.
                try:
                    c = mqtt.Client(mqtt.CallbackAPIVersion.VERSION1)
                except AttributeError:
                    c = mqtt.Client()
                if g.get("user"):
                    c.username_pw_set(str(g["user"]), str(g.get("pw") or ""))

                def bei_verbindung(client, _u=None, _flags=None, rc=0, *_a):
                    # Der Rueckgabecode wird GELESEN. Bis 0.9.18 fiel er in
                    # *_a, und ein Broker, der die Anmeldung mit CONNACK 5
                    # abweist, erzeugte dieselbe Zeile "Mit dem Broker
                    # verbunden" wie ein gelungener Anlauf. Es kam nie eine
                    # Nachricht an, und das Protokoll sagte das Gegenteil.
                    # "laeuft" ist nicht "angemeldet".
                    code = int(getattr(rc, "value", rc) or 0)
                    if code != 0:
                        _LOG.error("Der Broker hat die Verbindung abgelehnt "
                                   "(CONNACK %d: %s). Es wird NICHTS "
                                   "abonniert.", code,
                                   CONNACK_TEXT.get(code, "unbekannter Grund"))
                        try:
                            client.disconnect()
                        except Exception:
                            pass
                        # Merker statt 'return'.
                        #
                        # Bis 0.9.21 kehrte der Rueckruf hier einfach zurueck.
                        # Eine Ausnahme flog dabei nicht, die innere Schleife
                        # lief weiter in ihrem sleep(1), und der aeussere
                        # Wiederversuch griff nie: nach EINER abgelehnten
                        # Anmeldung blieb der Dienst bis zum Neustart stumm.
                        # An dieser Anlage ist der Fall erreichbar - der
                        # Broker laeuft mit allow_anonymous false und weist
                        # ein falsches Kennwort mit CONNACK 5 ab.
                        self.abgewiesen = True
                        return
                    for t in sorted(self.themen):
                        client.subscribe(t)
                    self.themen_neu = False
                    _LOG.info("Mit dem Broker verbunden, %d Themen abonniert",
                              len(self.themen))

                def bei_nachricht(_c, _u, msg):
                    sammler.mqtt_setzen(msg.topic,
                                        msg.payload.decode("utf-8", "replace"))

                abonniert = set(self.themen)
                self.abgewiesen = False
                c.on_connect = bei_verbindung
                c.on_message = bei_nachricht
                c.connect(broker, int(g.get("brokerport") or 1883), 60)
                c.loop_start()
                while self.laeuft and not self.abgewiesen:
                    await asyncio.sleep(1)
                    if self.themen_neu:
                        # Weggefallene Themen abbestellen: ein entferntes
                        # Thema blieb sonst abonniert und schrieb bis zum
                        # Neustart weiter frische Zeitstempel in den
                        # Sammler.
                        for t in sorted(abonniert - self.themen):
                            try:
                                c.unsubscribe(t)
                            except Exception:
                                pass
                            sammler.mqtt.pop(t, None)
                        abonniert = set(self.themen)
                        # Nachtraeglich abonnieren statt die Verbindung
                        # abzureissen - ein Broker-Neuaufbau kostet die
                        # bereits empfangenen retained-Werte.
                        for t in sorted(self.themen):
                            c.subscribe(t)
                        self.themen_neu = False
                        _LOG.info("Abonnement erneuert: %d Themen", len(self.themen))
                c.loop_stop()
                c.disconnect()
            except Exception as f:
                # Die Meldung nennt, OB eine Anmeldung mitging - sonst sucht
                # man bei einer abgelehnten Anmeldung im Netz.
                _LOG.warning("Broker %s:%s nicht erreichbar (%s: %s) - "
                             "Anmeldung %s, neuer Versuch in %d s",
                             broker, g.get("brokerport"), type(f).__name__, f,
                             ("als '%s'" % g["user"]) if g.get("user") else "ohne Benutzer",
                             warte)
            # Nachfassen erst nach einer Minute, dann immer seltener,
            # hoechstens alle fuenf Minuten (Hausstandard).
            #
            # Bis 0.9.21 waren es fest 30 s. Zusammen mit dem Merker oben
            # waere daraus bei falschem Kennwort eine Protokollzeile alle
            # 30 Sekunden geworden - rund 2 900 Zeilen in der Nacht, bei
            # einer Rotationsmarke von 512 000 Byte. Der Ausfall haette das
            # ganze uebrige Protokoll aus der Datei gerollt.
            if self.abgewiesen:
                _LOG.warning("Anmeldung am Broker abgelehnt - neuer Versuch "
                             "in %d s.", warte)
            for _ in range(warte * 2):
                if not self.laeuft:
                    return
                await asyncio.sleep(0.5)
            warte = min(300, warte * 2)


def einmal() -> int:
    cfg = config()
    zuordnung = json_lesen(DATEI_QUELLEN)
    s = quellen.Sammler(zuordnung, vorlagen())
    # Den Tagesverlauf des laufenden Dienstes uebernehmen.
    #
    # Bis 0.9.6 legte "Jetzt rechnen" einen frischen Sammler an, dessen
    # MQTT-Speicher naturgemaess leer ist - der laufende Dienst haelt seine
    # empfangenen Werte im eigenen Prozess. Der Knopf ersetzte damit ein
    # Ergebnis aus Stationswerten durch ein reines Modellergebnis und stellte
    # ausgerechnet die Spalte "Zuletzt von" auf "Open-Meteo" um. Also genau
    # die Anzeige, an der man ablesen soll, ob die eigene Zuordnung greift.
    #
    # Vollstaendig loesen laesst sich das nicht - die letzten Nutzlasten
    # liegen im anderen Prozess. Die Tagesextremwerte aber liegen auf der
    # Platte, und sie sind es, aus denen Tmin und Tmax entstehen.
    s.tag_laden(json_lesen(DATEI_EXTREME))
    # Dieselbe Einstellung wie im Dienst - sonst rechnete "Jetzt rechnen"
    # mit einer anderen Altersgrenze als der Takt daneben.
    s.hoechstalter = float(cfg.get("hoechstalter") or 3600)
    # "Jetzt rechnen" WARTET auf die Sperre, es laesst nicht aus: der
    # Anwender hat gerade gedrueckt und will ein Ergebnis sehen. Zwanzig
    # Sekunden reichen fuer einen Rechengang der Dienstschleife; danach
    # wird ohne Sperre gerechnet und gesagt, dass zwei Laeufe zugleich
    # geschrieben haben koennten.
    with Rechensperre(20.0) as frei:
        if not frei:
            print("Hinweis: der Dienst rechnet gerade selbst. Es wird "
                  "trotzdem gerechnet - der Verlauf koennte dabei einen "
                  "Eintrag verlieren.")
        a = rechnen(cfg, s)
        json_schreiben(DATEI_ABBILD, a)
        # Die drei Tagesmarken werden UEBERNOMMEN, nicht ersetzt. Bis 0.9.20
        # schrieb diese Zeile eine frische Zustandsdatei: ein Druck auf
        # "Jetzt rechnen" setzte den Meldezaehler und die Tagesmarke der
        # Stationslage auf null zurueck. Dieselbe Klasse wie der Fehler, den
        # 0.9.19 in der Dienstschleife behoben hat.
        alt = json_lesen(DATEI_ZUSTAND)
        json_schreiben(DATEI_ZUSTAND, {"ok": a["ok"], "ts": a["ts"],
                                       "et0": a.get("et0"),
                                       "durchlaeufe": (a.get("plan") or {}).get("durchlaeufe", 0),
                                       "meldezaehler": alt.get("meldezaehler") or {},
                                       "meldetag": alt.get("meldetag") or "",
                                       "stationstag": alt.get("stationstag") or "",
                                       "fehler": a.get("et0_fehler") or ""})
        stationslage_protokollieren(a)
        n = veroeffentlichen(a, cfg)
    plan = a.get("plan") or {}
    print("ET0 heute: %s mm (%s, %s)" % (
        ("%.2f" % a["et0"]) if a.get("et0") is not None else "-",
        a.get("et0_quelle"), a.get("et0_guete")))
    print("Plan: %d von %d noetigen Durchlaeufen%s"
          % (plan.get("durchlaeufe", 0), plan.get("noetige_durchlaeufe", 0),
             "" if plan.get("reicht") else "  -- die Anlage kann den Bedarf nicht decken"))
    for s2, e in (a.get("zonen") or {}).items():
        if e.get("ok"):
            print("  %-16s Defizit %5.1f mm, Fuellstand %3.0f %%, Bedarf %5.1f mm"
                  % (s2, e["dr"], e["fuellstand"], e["bedarf_mm"]))
    sp = a.get("sperre") or {}
    if sp.get("aktiv"):
        print("GESPERRT: %s - heute Nacht wird nicht gegossen." % sp.get("grund"))
    if a.get("nachgetragen"):
        print("Verlauf ergaenzt: %s" % ", ".join(a["nachgetragen"]))
    if a.get("gegossen"):
        print("Rueckmeldung aus Loxone: %s"
              % ", ".join("%s %.1f mm" % (k, v) for k, v in sorted(a["gegossen"].items())))
    print("%d Themen ueber MQTT gesendet." % n)
    return 0 if a["ok"] else 1


def selbsttest() -> int:
    z: list[tuple[int, str]] = []
    z.append((1, "Python %s" % sys.version.split()[0]))
    # Welcher Interpreter laeuft hier eigentlich? Das ist die Frage, die man
    # sich stellt, wenn paho-mqtt 'fehlt', obwohl es installiert wurde: es
    # liegt dann in der virtuellen Umgebung, waehrend der Dienst mit dem
    # System-Python laeuft.
    in_venv = "/venv/" in sys.executable
    z.append((1, "Interpreter: %s (%s)" % (
        sys.executable,
        "virtuelle Umgebung" if in_venv
        else "System-Python - paho-mqtt muesste dann systemweit installiert sein")))
    try:
        import paho.mqtt.client  # noqa: F401
        z.append((1, "Paket paho-mqtt geladen (MQTT-Quellen moeglich)"))
    except ImportError:
        z.append((-1, "Paket paho-mqtt fehlt - nur Online- und HTTP-Quellen. "
                      "Alles Uebrige laeuft weiter." + ("" if in_venv else
                      " Achtung: dieser Lauf benutzt den System-Python. Wurde das "
                      "Paket in die virtuelle Umgebung installiert, sieht er es "
                      "nicht.")))
    for name, p in (("Konfiguration", CONFIGDIR), ("Daten", DATADIR), ("Log", LOGDIR)):
        os.makedirs(p, exist_ok=True)
        z.append((1 if os.access(p, os.W_OK) else 0,
                  "Ordner %s beschreibbar: %s" % (name, p)))
    c = config()
    hat_ort = abs(float(c["breite"])) > 0.001 or abs(float(c["laenge"])) > 0.001
    z.append((1 if hat_ort else 0,
              ("Standort: %.4f, %.4f" % (c["breite"], c["laenge"])) if hat_ort
              else "Kein Standort eingetragen - ohne ihn gibt es keine Strahlung "
                   "und keine Vorhersage."))
    zl = zonen()
    z.append((1 if zl else 0, "%d Zonen eingerichtet" % len(zl) if zl
              else "Noch keine Zone eingerichtet."))
    ohne_messung = [x.get("name") for x in zl if not x.get("rate_gemessen")]
    if ohne_messung:
        z.append((-1, "Niederschlagsrate noch nicht gemessen: %s. Liter und "
                      "Minuten sind dort geschaetzt." % ", ".join(map(str, ohne_messung))))
    g = mqtt_gateway()
    if not g.get("gefunden"):
        z.append((0, "Kein MQTT-Abschnitt in der general.json gefunden."))
    elif not g.get("autostart"):
        z.append((0, "MQTT-Gateway nicht auf Autostart - unter System, "
                     "MQTT Gateway einschalten."))
    else:
        z.append((1, "MQTT-Gateway auf Autostart, UDP-Eingang %d" % g["udpport"]))
        z.append((1, "Broker %s:%d, Anmeldung %s"
                  % (g.get("broker") or "127.0.0.1", g.get("brokerport") or 1883,
                     ("als '%s'" % g["user"]) if g.get("user")
                     else "ohne Benutzer (Broker muss anonym zulassen)")))
    a = json_lesen(DATEI_ABBILD)
    z.append((1 if a.get("ts") else -1,
              "Letzte Rechnung: %s" % datetime.datetime.fromtimestamp(
                  a["ts"]).strftime("%d.%m.%Y %H:%M") if a.get("ts")
              else "Noch nie gerechnet - 'Jetzt rechnen' im Reiter Test."))

    print("Selbsttest der Bewaesserung")
    fehlt = 0
    for stand, text in z:
        print({1: "[OK]   ", 0: "[FEHL] ", -1: "[INFO] "}[stand] + text)
        fehlt += 1 if stand == 0 else 0
    print()
    for name, modul in (("Verdunstung nach FAO-56", fao56),
                        ("Giessplan", giessplan),
                        ("Messwertbezug", quellen)):
        print("%s:" % name)
        for ok, text in modul.selbstpruefung():
            print(("  [OK]   " if ok else "  [FEHL] ") + text)
            fehlt += 0 if ok else 1
    print()
    print("Nicht geprueft, weil dafuer echte Hardware noetig ist:")
    print("  - ob die Themen und Pfade zu IHRER Wetterstation passen")
    print("  - ob die Bodenfeuchtesensoren plausible Werte liefern")
    print("  - ob die Niederschlagsrate der Regner stimmt (Becherprobe!)")
    return 1 if fehlt else 0


def main() -> int:
    # Der zweite Protokollkanal nur dort, wo die Ausgabe wirklich auf den
    # Bildschirm gehoert. Im Dauerbetrieb leitet dienst.sh die
    # Standardausgabe in dieselbe Datei um - siehe log_einrichten().
    auf_bildschirm = "--selbsttest" in sys.argv or "--einmal" in sys.argv
    log_einrichten(auf_bildschirm)
    if "--selbsttest" in sys.argv:
        return selbsttest()
    if "--einmal" in sys.argv:
        return einmal()
    os.makedirs(DATADIR, exist_ok=True)
    with open(DATEI_PID, "w", encoding="utf-8") as fh:
        fh.write(str(os.getpid()))
    d = Dienst()
    signal.signal(signal.SIGTERM, d.anhalten)
    signal.signal(signal.SIGINT, d.anhalten)
    _LOG.info("Dienst gestartet (PID %d).", os.getpid())
    try:
        return asyncio.run(d.laufen())
    finally:
        _LOG.info("Dienst beendet.")
        try:
            os.remove(DATEI_PID)
        except OSError:
            pass


if __name__ == "__main__":
    sys.exit(main())
