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


def _home() -> str:
    h = os.environ.get("LBHOMEDIR", "")
    if h and os.path.isdir(h):
        return h
    for k in ("/opt/loxberry", "/home/loxberry/loxberry"):
        if os.path.isdir(k):
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
}

_LOG = logging.getLogger("bewaesserung")


def log_einrichten() -> None:
    os.makedirs(LOGDIR, exist_ok=True)
    _LOG.setLevel(logging.INFO)
    if _LOG.handlers:
        return
    h = logging.handlers.RotatingFileHandler(DATEI_LOG, maxBytes=512000,
                                             backupCount=2, encoding="utf-8")
    h.setFormatter(logging.Formatter("[%(asctime)s] %(levelname)s %(message)s",
                                     "%Y-%m-%d %H:%M:%S"))
    _LOG.addHandler(h)
    k = logging.StreamHandler(sys.stdout)
    k.setFormatter(logging.Formatter("%(levelname)s %(message)s"))
    _LOG.addHandler(k)


# ---------------------------------------------------------------- Dateien

def json_lesen(p: str) -> dict:
    try:
        with open(p, "r", encoding="utf-8") as fh:
            d = json.load(fh)
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError):
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


def zonen_speichern(liste: list[dict]) -> bool:
    d = json_lesen(DATEI_ZONEN)
    d["zonen"] = liste
    d["geaendert"] = int(time.time())
    return json_schreiben(DATEI_ZONEN, d)


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
    return {
        "gefunden": 1,
        "autostart": 1 if str(m.get("Gatewayautostart", "0")) in ("1", "true", "True") else 0,
        "udpport": int(m.get("Udpinport") or 0),
        "broker": str(m.get("Brokerhost") or ""),
        "brokerport": int(m.get("Brokerport") or 1883),
    }


def mqtt_senden(paare: dict, praefix: str) -> int:
    """Ueber den UDP-Eingang des Gateways veroeffentlichen.

    Der Weg ueber UDP braucht keine Zugangsdaten - das Gateway setzt sie
    selbst. Ein eigener Broker-Anmeldeversuch waere ein zweiter Ort, an dem
    ein Kennwort liegt.
    """
    g = mqtt_gateway()
    if not g.get("gefunden") or not g.get("udpport"):
        return 0
    gesendet = 0
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        for name, wert in paare.items():
            # 'publish ' davor - das ist die Form, die der UDP-Eingang des
            # LoxBerry-Gateways erwartet und die auch die uebrigen Plugins
            # dieser Reihe benutzen. Bis 0.9.0 fehlte das Verb hier als
            # einzigem Plugin.
            zeile = "publish %s/%s %s" % (
                _mqtt_thema(praefix.strip("/")), _mqtt_thema(name),
                _mqtt_sauber(wert))
            s.sendto(zeile.encode("utf-8"), ("127.0.0.1", int(g["udpport"])))
            gesendet += 1
        s.close()
    except OSError as f:
        _LOG.warning("MQTT-Gateway nicht erreichbar: %s", f)
        return 0
    return gesendet


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
    v = verlauf_lesen()
    v["tage"][datum] = eintrag
    # Ein Jahr reicht: laenger zurueck rechnet niemand die Bilanz nach.
    schluessel = sorted(v["tage"])
    for alt in schluessel[:-400]:
        v["tage"].pop(alt, None)
    json_schreiben(DATEI_VERLAUF, v)


def rechnen(cfg: dict, sammler: quellen.Sammler | None = None) -> dict:
    """Einmal alles rechnen: Messwerte, ET0, Bilanz je Zone, Plan."""
    heute = datetime.date.today()
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

    # --- eigene Station ---
    if sammler is not None:
        sammler.http_abholen()
        zus = quellen.messwerte_zusammenstellen(sammler, online_heute, standort)
    else:
        zus = quellen.messwerte_zusammenstellen(
            quellen.Sammler({}, vorlagen()), online_heute, standort)

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

    # Welche Zahl gilt heute? Die eigene, wenn es sie gibt.
    if et0_eigen is not None:
        et0_heute = et0_eigen["et0"]
        et0_quelle = "station" if zus["herkunft"].get("tmax") == "station" else "gemischt"
        et0_guete = et0_eigen["guete"]
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

    if et0_heute is not None:
        verlauf_ergaenzen(heute_s, {"et0": et0_heute, "regen": regen_heute or 0.0,
                                    "quelle": et0_quelle, "guete": et0_guete})

    # --- Bilanz je Zone ---
    v = verlauf_lesen()["tage"]
    letzte = sorted(v)[-14:]
    verlauf_liste = [dict(v[d], datum=d) for d in letzte]
    vorschau = [nach_datum[d] for d in sorted(nach_datum)
                if d > heute_s][:int(cfg["vorschautage"])]

    ergebnisse = {}
    for z in zonen():
        s = str(z.get("schluessel") or "")
        if not s:
            continue
        zz = dict(z)
        # Bodenfeuchte je Zone aus dem Broker, wenn eingerichtet
        if sammler is not None and z.get("feuchte_thema"):
            eintrag = sammler.mqtt.get(str(z["feuchte_thema"]))
            if eintrag is not None:
                bf = quellen.zahl(eintrag[0])
                if bf is not None:
                    zz["bodenfeuchte"] = bf
        ergebnisse[s] = giessplan.zone_rechnen(zz, verlauf_liste, vorschau, cfg)
        if ergebnisse[s].get("ok"):
            ergebnisse[s]["liter"] = giessplan.mm_zu_litern(
                ergebnisse[s]["bedarf_mm"], float(z.get("flaeche") or 0.0))
            ergebnisse[s]["minuten"] = giessplan.mm_zu_minuten(
                ergebnisse[s]["bedarf_mm"], float(z.get("rate_mmh") or 0.0),
                float(cfg["wirkungsgrad"]))
            ergebnisse[s]["rate_gemessen"] = 1 if z.get("rate_gemessen") else 0

    plan = giessplan.plan_bauen(zonen(), ergebnisse, cfg)

    return {
        "ok": 1 if et0_heute is not None else 0,
        "ts": int(time.time()), "datum": heute_s,
        "et0": et0_heute, "et0_quelle": et0_quelle, "et0_guete": et0_guete,
        "et0_fehler": et0_fehler,
        "et0_teile": et0_eigen or {},
        "regen_heute": regen_heute,
        "herkunft": zus["herkunft"],
        "online_ok": online.get("ok", 0), "online_fehler": online_fehler,
        "vorschau": vorschau,
        "zonen": ergebnisse,
        "plan": plan,
    }


def veroeffentlichen(abbild: dict, cfg: dict) -> int:
    if not int(cfg.get("mqtt_ein") or 0):
        return 0
    p = {}
    plan = abbild.get("plan") or {}
    p["ok"] = int(abbild.get("ok") or 0)
    p["et0"] = round(float(abbild["et0"]), 2) if abbild.get("et0") is not None else 0
    p["durchlaeufe"] = int(plan.get("durchlaeufe") or 0)
    p["noetige_durchlaeufe"] = int(plan.get("noetige_durchlaeufe") or 0)
    p["reicht"] = int(plan.get("reicht") or 0)
    p["giessen"] = 1 if int(plan.get("durchlaeufe") or 0) > 0 else 0
    p["alter"] = 0
    for s, e in (abbild.get("zonen") or {}).items():
        if not e.get("ok"):
            continue
        p["%s/defizit_mm" % s] = round(e["bedarf_mm"], 1)
        p["%s/fuellstand" % s] = round(e["fuellstand"], 0)
        p["%s/liter" % s] = round(e.get("liter") or 0.0, 0)
        p["%s/minuten" % s] = round(e.get("minuten") or 0.0, 0)
    return mqtt_senden(p, str(cfg.get("mqtt_topic") or "bewaesserung"))


# --------------------------------------------------------------- Betrieb

class Dienst:
    def __init__(self) -> None:
        self.laeuft = True

    def anhalten(self, *_a) -> None:
        self.laeuft = False

    async def laufen(self) -> int:
        cfg = config()
        vor = vorlagen()
        zuordnung = json_lesen(DATEI_QUELLEN)
        sammler = quellen.Sammler(zuordnung, vor)
        themen = set(sammler.mqtt_themen())
        for z in zonen():
            if z.get("feuchte_thema"):
                themen.add(str(z["feuchte_thema"]))
        if themen:
            _LOG.info("MQTT-Themen abonniert: %d", len(themen))
            asyncio.ensure_future(self.mqtt_horchen(sammler, sorted(themen)))

        letzte_rechnung = 0.0
        takt = max(60, min(3600, int(cfg.get("takt") or 300)))
        while self.laeuft:
            try:
                cfg = config()
                jetzt = time.time()
                if jetzt - letzte_rechnung >= max(600, takt):
                    abbild = rechnen(cfg, sammler)
                    json_schreiben(DATEI_ABBILD, abbild)
                    json_schreiben(DATEI_ZUSTAND, {
                        "ok": abbild["ok"], "ts": abbild["ts"],
                        "et0": abbild.get("et0"),
                        "durchlaeufe": (abbild.get("plan") or {}).get("durchlaeufe", 0),
                        "fehler": abbild.get("et0_fehler") or abbild.get("online_fehler") or ""})
                    n = veroeffentlichen(abbild, cfg)
                    _LOG.info("Gerechnet: ET0 %s mm (%s), %d Durchlaeufe, %d Themen gesendet",
                              ("%.2f" % abbild["et0"]) if abbild.get("et0") is not None else "-",
                              abbild.get("et0_quelle"),
                              (abbild.get("plan") or {}).get("durchlaeufe", 0), n)
                    letzte_rechnung = jetzt
            except Exception as f:
                _LOG.error("Rechengang fehlgeschlagen: %s", f)
                json_schreiben(DATEI_ZUSTAND, {"ok": 0, "ts": int(time.time()),
                                               "fehler": str(f)})
            for _ in range(takt * 2):
                if not self.laeuft:
                    break
                await asyncio.sleep(0.5)
        return 0

    async def mqtt_horchen(self, sammler: quellen.Sammler, themen: list[str]) -> None:
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
        while self.laeuft:
            try:
                c = mqtt.Client()

                def bei_verbindung(client, *_a):
                    for t in themen:
                        client.subscribe(t)
                    _LOG.info("Mit dem Broker verbunden, %d Themen abonniert", len(themen))

                def bei_nachricht(_c, _u, msg):
                    sammler.mqtt_setzen(msg.topic,
                                        msg.payload.decode("utf-8", "replace"))

                c.on_connect = bei_verbindung
                c.on_message = bei_nachricht
                c.connect(broker, int(g.get("brokerport") or 1883), 60)
                c.loop_start()
                while self.laeuft:
                    await asyncio.sleep(1)
                c.loop_stop()
                c.disconnect()
            except Exception as f:
                _LOG.warning("Broker nicht erreichbar (%s) - neuer Versuch in 30 s", f)
                for _ in range(60):
                    if not self.laeuft:
                        return
                    await asyncio.sleep(0.5)


def einmal() -> int:
    cfg = config()
    zuordnung = json_lesen(DATEI_QUELLEN)
    s = quellen.Sammler(zuordnung, vorlagen())
    a = rechnen(cfg, s)
    json_schreiben(DATEI_ABBILD, a)
    json_schreiben(DATEI_ZUSTAND, {"ok": a["ok"], "ts": a["ts"],
                                   "et0": a.get("et0"),
                                   "durchlaeufe": (a.get("plan") or {}).get("durchlaeufe", 0),
                                   "fehler": a.get("et0_fehler") or ""})
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
    log_einrichten()
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
