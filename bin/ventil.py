# -*- coding: utf-8 -*-
"""GARDENA-Ventile direkt - der Verbraucher-Teil von Gardena-1 (ab Werk AUS).

Bis hierher rechnet die Bewaesserung nur den Plan; geschaltet hat der
Bewaesserungsbaustein im Miniserver. Mit der Einstellung "GARDENA-Ventile
direkt" (Reiter Einstellungen, ab Werk aus) und der Ausgabeart
"GARDENA-Ventil" je Zone (Reiter Zonen, ab Werk "ueber Loxone") oeffnet und
schliesst der Dienst die Ventile DIESER Zonen selbst - ueber die
Schnittstelle des Plugins GardenaSmartSystem (ab 1.2.13), nie ueber dessen
Dateien (vb_RAHMEN.md, D-Punkte):

    POST http://127.0.0.1:<Webserver-Port>/plugins/<ordner>/index.php
    action=ventil&token=<Ventil-Token>&ventil=<Geraetename>&befehl=oeffnen&minuten=<n>&quelle=bewaesserung
    ... befehl=schliessen   bzw.   befehl=zustand

Belegt in LoxBerry-Plugin-GardenaSmartSystem-1.2.14 (webfrontend/html/index.php,
Block "Schnittstelle fuer die Bewaesserung"; README, gleichnamiger Abschnitt)
und Pruefung-Durchgang-2026-09-29/GARDENA1_SCHNITTSTELLE.md.

SICHERHEIT - geoeffnet wird NIE ohne Dauer:
  - 'minuten' ist beim Oeffnen Pflicht (aufrufen() weist ein Oeffnen ohne
    gueltige Minuten ab, bevor eine Anfrage hinausgeht), und die Wolke
    schliesst das Ventil nach dieser Zeit SELBST - auch wenn danach weder
    dieser Dienst noch GARDENA noch das Netz antwortet.
  - Die Dauer ist die aufgerundete Restzeit des Schritts (hoechstens 59 s
    mehr) und nie mehr als die eingestellte Hoechstdauer; laengere
    Ventilzeiten werden in Abschnitte geteilt, jeder mit eigener Dauer.
  - Am Ende jedes Schritts, bei jeder Sperre, am Ende des Giessfensters, beim
    Ausschalten und beim Beenden des Dienstes geht 'schliessen' hinaus.

ZAEHLEN - kein falsches "erledigt":
  Als gegossen zaehlt nur ein Schritt, dessen Oeffnen mit HTTP 200 und OK=1
  (GESENDET=1 oder UNVERAENDERT=1) beantwortet wurde, und nur die Zeit bis
  zum Schliessen. Jede andere Antwort (409, 403, 404, 429, 502, 503, keine
  Antwort, Zeitueberschreitung) steht mit Code und GRUND im Protokoll und im
  Reiter Test, und die Zone gilt als NICHT gegossen - die Bilanz behaelt ihr
  Defizit fuer die naechste Nacht.

Die Zeitgrenze von 45 s und "bei Zeitablauf zustand fragen statt blind zu
wiederholen" stehen in GARDENA1_SCHNITTSTELLE.md, Abschnitt 4.
"""

from __future__ import annotations

import datetime
import math
import re
import socket
import time
import urllib.error
import urllib.parse
import urllib.request

BEFEHLE = ("oeffnen", "schliessen", "zustand")
# GARDENA1_SCHNITTSTELLE.md, Abschnitt 4: "Zeitgrenze im Verbraucher 45 s".
ZEITGRENZE_S = 45.0
# Beim Beenden des Dienstes: bin/dienst.sh schickt nach 10 s SIGKILL.
ZEITGRENZE_HALT_S = 8.0
# Nach einer Zeitueberschreitung nur kurz nachfragen - 'zustand' fragt die
# Wolke nicht, er liest das Abbild des letzten Takts.
ZEITGRENZE_ZUSTAND_S = 15.0
# Entscheidung 10 (30.09.2026): hoechstens 3 Stunden je Befehl.
HOECHST_MIN = 180
# Kuerzer wird nicht geoeffnet - ein Schritt unter einer halben Minute ist
# ein Rest, kein Giessen (dieselbe Untergrenze wie die Ventilzeit im Plan).
MINDEST_S = 30

MUSTER_ORDNER = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
# Das Ventil-Token ist 32 Hex-Zeichen lang (GARDENA1_SCHNITTSTELLE.md, Abschnitt 1).
MUSTER_TOKEN = re.compile(r"^[0-9A-Fa-f]{32}$")

# Antworten, die heissen "die Kopplung steht nicht" (Abschnitt 5, Punkt 3):
# dann gilt der Weg ueber Loxone, soweit die Zone dort angeschlossen ist.
KOPPLUNG_STEHT_NICHT = ("SCHNITTSTELLE_AUS", "PLUGIN_AUS", "KEIN_TOKEN", "TOKEN",
                        "KEINE_ZUGANGSDATEN", "NUR_LOKAL", "KEINE_GARDENA_ANTWORT",
                        "KEINE_VERBINDUNG", "TOKEN_FEHLT", "ORDNER_UNGUELTIG")


class _KeinUmleiten(urllib.request.HTTPRedirectHandler):
    """Eine Umleitung wird nie verfolgt - das Token steht im Rumpf und darf
    nirgendwohin mitwandern. urllib meldet die 3xx dann als HTTPError."""

    def redirect_request(self, *_a, **_k):  # noqa: D401
        return None


# Kein Proxy: die Anfrage geht an 127.0.0.1 und nur dorthin. Ein
# http_proxy in der Umgebung bekaeme sonst das Token zu sehen.
_OEFFNER = urllib.request.build_opener(urllib.request.ProxyHandler({}), _KeinUmleiten())


def ventil_name_taugt(name) -> bool:
    """Geraetename aus der GARDENA-App (oder Geraetekennung): 1 bis 100
    Zeichen, keine Steuerzeichen, kein Anfuehrungszeichen - wie die
    Textfelder der Zonentabelle. GARDENA nimmt bis 200 Zeichen."""
    s = str(name if name is not None else "")
    return 0 < len(s.strip()) <= 100 and re.search(r'[\x00-\x1f\x7f"]', s) is None


def antwort_lesen(http: int, text: str, befehl: str) -> dict:
    """Die Antwortzeile 'GARDENA_VENTIL;OK=..;..' lesen.

    Erfolg = HTTP 200 UND OK=1, beim Schalten dazu GESENDET=1 oder
    UNVERAENDERT=1 (Abschnitt 5, Punkt 3). Alles andere ist ein Fehler mit
    GRUND - bei einer Antwort ohne GARDENA-Zeile (etwa 404 des Webservers,
    weil das Plugin fehlt) KEINE_GARDENA_ANTWORT.
    """
    a = {"http": int(http), "felder": {}, "erfolg": False, "unveraendert": False,
         "grund": "", "befehl": befehl}
    zeile = ""
    for z in str(text or "").splitlines():
        if z.startswith("GARDENA_VENTIL;"):
            zeile = z.strip()
            break
    if not zeile:
        a["grund"] = "KEINE_GARDENA_ANTWORT" if http else "KEINE_ANTWORT"
        return a
    for teil in zeile.split(";")[1:]:
        k, gleich, v = teil.partition("=")
        if gleich and re.match(r"^[A-Z_]{1,40}$", k):
            a["felder"][k] = re.sub(r"[^A-Za-z0-9_.:,|\-]", "_", v)[:80]
    f = a["felder"]
    if int(http) == 200 and f.get("OK") == "1":
        if befehl == "zustand" or f.get("GESENDET") == "1" or f.get("UNVERAENDERT") == "1":
            a["erfolg"] = True
            a["unveraendert"] = f.get("UNVERAENDERT") == "1"
            return a
        a["grund"] = "OHNE_GESENDET"
        return a
    a["grund"] = f.get("GRUND") or ("HTTP_%d" % int(http))
    return a


def aufrufen(port: int, ordner: str, token: str, ventil: str, befehl: str,
             minuten=None, zeit: float | None = None) -> dict:
    """EIN Aufruf der Schnittstelle. Rueckgabe wie antwort_lesen(); ohne
    Antwort ist 'http' 0 und 'grund' ZEITUEBERSCHREITUNG oder
    KEINE_VERBINDUNG. Das Token steht in keiner Rueckgabe, in keiner Adresse
    und in keiner Meldung - nur im Rumpf des POST.
    """
    zeit = ZEITGRENZE_S if zeit is None else float(zeit)
    a = {"http": 0, "felder": {}, "erfolg": False, "unveraendert": False, "grund": "",
         "befehl": befehl}
    if befehl not in BEFEHLE:
        a["grund"] = "BEFEHL_INTERN"
        return a
    if not MUSTER_ORDNER.match(str(ordner or "")):
        a["grund"] = "ORDNER_UNGUELTIG"
        return a
    if not MUSTER_TOKEN.match(str(token or "")):
        a["grund"] = "TOKEN_FEHLT"
        return a
    if not ventil_name_taugt(ventil):
        a["grund"] = "VENTIL_UNGUELTIG"
        return a
    felder = {"action": "ventil", "token": str(token), "ventil": str(ventil).strip(),
              "befehl": befehl}
    if befehl == "oeffnen":
        # NIE ohne Dauer: ohne gueltige Minuten geht keine Anfrage hinaus.
        try:
            m = int(minuten)
        except (TypeError, ValueError):
            m = 0
        if not 1 <= m <= HOECHST_MIN:
            a["grund"] = "MINUTEN_INTERN"
            return a
        felder["minuten"] = str(m)
    felder["quelle"] = "bewaesserung"
    try:
        port = int(port)
    except (TypeError, ValueError):
        port = 80
    url = "http://127.0.0.1:%d/plugins/%s/index.php" % (port, ordner)
    req = urllib.request.Request(
        url, data=urllib.parse.urlencode(felder).encode("utf-8"), method="POST",
        headers={"Content-Type": "application/x-www-form-urlencoded",
                 "User-Agent": "LoxBerry-Bewaesserung"})
    try:
        with _OEFFNER.open(req, timeout=zeit) as r:
            code = int(getattr(r, "status", 200) or 200)
            text = r.read(4096).decode("utf-8", "replace")
    except urllib.error.HTTPError as f:
        code = int(f.code)
        try:
            text = f.read(4096).decode("utf-8", "replace")
        except Exception:                       # noqa: BLE001
            text = ""
    except (socket.timeout, TimeoutError):
        a["grund"] = "ZEITUEBERSCHREITUNG"
        return a
    except urllib.error.URLError as f:
        if isinstance(f.reason, (socket.timeout, TimeoutError)):
            a["grund"] = "ZEITUEBERSCHREITUNG"
        else:
            a["grund"] = "KEINE_VERBINDUNG"
            a["fehler"] = type(f.reason).__name__
        return a
    except Exception as f:                      # noqa: BLE001 - Netz kann alles werfen
        a["grund"] = "KEINE_VERBINDUNG"
        a["fehler"] = type(f).__name__
        return a
    return antwort_lesen(code, text, befehl)


def beschreiben(r: dict) -> str:
    """Kurzer Satz fuer Protokoll und Reiter Test - ohne Token, ohne Adresse."""
    if not r.get("http"):
        if r.get("grund") == "ZEITUEBERSCHREITUNG":
            return "keine Antwort (Zeitueberschreitung)"
        if r.get("grund") == "KEINE_VERBINDUNG":
            return "keine Verbindung (%s)" % (r.get("fehler") or "?")
        return "nicht gesendet (%s)" % (r.get("grund") or "?")
    f = r.get("felder") or {}
    t = "HTTP %d" % int(r["http"])
    if r.get("erfolg"):
        if r.get("unveraendert"):
            return t + ", UNVERAENDERT=1 (derselbe Befehl vor %s s, nichts gesendet)" % f.get("SEIT_S", "?")
        return t + (", GESENDET=1" if f.get("GESENDET") == "1" else ", OK=1")
    if r.get("grund") == "KEINE_GARDENA_ANTWORT":
        return t + " ohne GARDENA-Antwort (Plugin nicht installiert oder Ordner falsch?)"
    zusatz = "".join(";%s=%s" % (k, f[k]) for k in ("ANZAHL", "BIS", "ERLAUBT", "GRENZE", "HTTP")
                     if k in f)
    return t + ", GRUND=" + str(r.get("grund") or "?") + zusatz


def kurz(r: dict) -> dict:
    """Was vom Aufruf im Laufstand bleibt (fuer den Reiter Test)."""
    return {"http": int(r.get("http") or 0), "grund": str(r.get("grund") or ""),
            "ok": 1 if r.get("erfolg") else 0, "unveraendert": 1 if r.get("unveraendert") else 0,
            "text": beschreiben(r)}


def _minuten(s) -> int | None:
    try:
        h, m = str(s).split(":")
        h, m = int(h), int(m)
    except (ValueError, AttributeError):
        return None
    return h * 60 + m if 0 <= h <= 23 and 0 <= m <= 59 else None


def fenster(von, bis, ts: float):
    """Das Giessfenster, in dem 'ts' liegt: (beginn, ende) als Unix-Zeit,
    sonst None. Auch ueber Mitternacht; gleiche Zeiten sind kein Fenster
    (wie giessplan._fenster_minuten)."""
    a, b = _minuten(von), _minuten(bis)
    if a is None or b is None or a == b:
        return None
    lt = time.localtime(ts)
    heute = datetime.date(lt.tm_year, lt.tm_mon, lt.tm_mday)
    for zurueck in (0, 1):
        d = heute - datetime.timedelta(days=zurueck)
        beginn = datetime.datetime.combine(d, datetime.time(a // 60, a % 60)).timestamp()
        e_tag = d if b > a else d + datetime.timedelta(days=1)
        ende = datetime.datetime.combine(e_tag, datetime.time(b // 60, b % 60)).timestamp()
        if beginn <= ts < ende:
            return (beginn, ende)
    return None


def plan_gilt(abbild: dict, cfg: dict, jetzt: float) -> str:
    """'' wenn der Plan gilt, sonst der Grund. Dieselbe Regel wie der
    Endpunkt (bw_ok_gilt(), Entscheidung 4): ok=1 und nicht aelter als
    3 x max(600, Takt). Ein gehaltener Plan (Quellenausfall, ok=0) gilt
    NICHT - kein Giessen bei Quellenausfall."""
    if not isinstance(abbild, dict) or not abbild.get("plan"):
        return "kein Plan"
    if not int(abbild.get("ok") or 0):
        st = str(abbild.get("stoerung") or "").strip()
        return "Plan gilt nicht (ok=0%s)" % ((": " + st[:120]) if st else "")
    try:
        takt = max(60, min(3600, int(float(cfg.get("takt") or 300))))
    except (TypeError, ValueError):
        takt = 300
    grenze = 3 * max(600, takt)
    alter = jetzt - float(abbild.get("ts") or 0)
    if alter < -300:
        return "Plan aus der Zukunft (Uhrsprung)"
    if alter > grenze:
        # Ohne die Sekundenzahl: der Satz dient auch als Merker, ob schon
        # gemeldet wurde (Lauf.schritt), und darf sich nicht jede Sekunde aendern.
        return "Plan aelter als %d s" % grenze
    return ""


def gardena_zone(z) -> bool:
    return isinstance(z, dict) and str(z.get("ausgabe") or "loxone") == "gardena"


def fahrplan_bauen(cfg: dict, abbild: dict, zonenliste: list, beginn: float, ende: float,
                   max_min: int) -> tuple:
    """Die Schritte einer Nacht fuer die Zonen mit Ausgabeart GARDENA.

    Dieselben Zahlen wie fuer Loxone: der eingefrorene Nachtplan, sonst der
    laufende Plan; je Zone 'sekunden_soll' und 'durchlaeufe' (wie
    veroeffentlichen()). Eine Sperre setzt die Durchlaeufe auf 0.
    Die GARDENA-Zonen laufen ab Fensterbeginn nacheinander, zwischen zwei
    Durchlaeufen die eingestellte Pause. Kein Schritt ragt ueber das
    Fensterende (das Fenster ist eine harte Grenze); was nicht mehr
    hineinpasst, faellt weg und steht in 'gekuerzt'.
    Rueckgabe: (Schritte, Auskunft).
    """
    plan = abbild.get("plan") if isinstance(abbild.get("plan"), dict) else {}
    fest = abbild.get("nachtplan") if isinstance(abbild.get("nachtplan"), dict) else {}
    sperre = abbild.get("sperre") if isinstance(abbild.get("sperre"), dict) else {}
    durchl = int((fest.get("durchlaeufe") if fest else plan.get("durchlaeufe")) or 0)
    info = {"zonen": 0, "durchlaeufe": durchl, "grund": "", "gekuerzt": 0, "ohne_ventil": []}
    if int(sperre.get("aktiv") or 0):
        info["grund"] = "gesperrt: %s" % str(sperre.get("grund") or "")
        durchl = 0
    try:
        pause_s = max(0, int(float(cfg.get("pause_min") or 0))) * 60
    except (TypeError, ValueError):
        pause_s = 0
    max_s = max(1, min(HOECHST_MIN, int(max_min))) * 60
    gz = []
    for z in zonenliste if isinstance(zonenliste, list) else []:
        if not gardena_zone(z):
            continue
        info["zonen"] += 1
        s = str(z.get("schluessel") or "")
        ventil = str(z.get("gardena_ventil") or "").strip()
        if not s:
            continue
        if not ventil_name_taugt(ventil):
            info["ohne_ventil"].append(str(z.get("name") or s))
            continue
        if not int(z.get("im_zyklus") or 0):
            continue
        jz = {}
        if fest:
            jz = (fest.get("je_zone") or {}).get(s) or {}
        if not jz:
            jz = (plan.get("je_zone") or {}).get(s) or {}
        try:
            sek = int(round(float(jz.get("sekunden_soll") or 0)))
            n = int(jz.get("durchlaeufe") or 0)
        except (TypeError, ValueError):
            continue
        if sek <= 0 or n <= 0:
            continue
        gz.append((s, str(z.get("name") or s), ventil, sek, n))
    summe = sum(x[3] for x in gz)
    schritte = []
    nr = 0
    for d in range(durchl):
        t = beginn + d * (summe + pause_s)
        for (s, name, ventil, sek, n) in gz:
            if d >= n:
                t += sek
                continue
            teile = max(1, int(math.ceil(sek / float(max_s))))
            rest = sek
            for k in range(teile):
                dauer = int(math.ceil(rest / float(teile - k)))
                rest -= dauer
                b, e = t, t + dauer
                t = e
                if e > ende:
                    e = ende
                    info["gekuerzt"] += 1
                if e - b < MINDEST_S:
                    continue
                nr += 1
                schritte.append({"nr": nr, "zone": s, "name": name, "ventil": ventil,
                                 "durchlauf": d + 1, "teil": k + 1, "teile": teile,
                                 "beginn": int(b), "ende": int(e), "fenster_ende": int(ende),
                                 "stand": "geplant"})
    return schritte, info


class Lauf:
    """Der Ablauf einer Nacht - ein Schritt je Aufruf von schritt().

    Alles, was die Aussenwelt beruehrt, kommt herein:
      jetzt()                        Uhr
      lesen() -> (cfg|None, zonen, abbild)
      port() -> int                  Webserver-Port des LoxBerry
      rufen(port, ordner, token, ventil, befehl, minuten, zeit) -> dict (aufrufen())
      buchen(datum, zone, mm) -> bool   Wasser in den Verlauf schreiben
      laden() -> dict, speichern(dict) -> bool   Laufstand (ventil_lauf.json)
      melden(stufe, text)            Protokoll (logging-Stufe)
      ansagen(art, daten, cfg)       Nr. 36 b: Anlass fuer die Sprachausgabe ('ende', 'ventil',
                                     'ventil_ok'); wahlfrei, None = keine Ansagen
    """

    def __init__(self, jetzt, lesen, port, rufen, buchen, laden, speichern, melden, ansagen=None):
        self.jetzt = jetzt
        self.ansagen = ansagen
        self.lesen = lesen
        self.port = port
        self.rufen = rufen
        self.buchen = buchen
        self.speichern = speichern
        self.melden = melden
        z = laden()
        self.z = z if isinstance(z, dict) else {}
        # Erster Durchgang nach dem Start: ein als "offen" gemerkter Schritt
        # stammt aus einem frueheren Lauf - sein Ventil wird geschlossen.
        self.frisch = True

    # ------------------------------------------------------------ Helfer
    def _schritte(self) -> list:
        s = self.z.get("schritte")
        return s if isinstance(s, list) else []

    def _sichern(self) -> None:
        self.speichern(self.z)

    @staticmethod
    def _zone(zonen, schluessel):
        for z in zonen if isinstance(zonen, list) else []:
            if isinstance(z, dict) and str(z.get("schluessel") or "") == schluessel:
                return z
        return None

    def _zugang(self, cfg):
        if cfg is None:
            return ("", "")
        return (str(cfg.get("gardena_ordner") or "").strip(), str(cfg.get("gardena_token") or "").strip())

    def _abbruch(self, s, cfg, zonen, abbild, jetzt, halt):
        if halt:
            return "Dienst endet"
        if self.frisch:
            return "Dienst neu gestartet - Stand des Ventils unbekannt"
        if cfg is None:
            return "Konfiguration unbrauchbar"
        if int(cfg.get("gardena_ein") or 0) != 1:
            return "Einstellung GARDENA-Ventile direkt ausgeschaltet"
        z = self._zone(zonen, s.get("zone"))
        if not gardena_zone(z) or str(z.get("gardena_ventil") or "").strip() != s.get("ventil"):
            return "Zone nicht mehr auf diesem GARDENA-Ventil"
        sp = abbild.get("sperre") if isinstance(abbild.get("sperre"), dict) else {}
        if int(sp.get("aktiv") or 0):
            return "Sperre (%s)" % str(sp.get("grund") or "")
        if jetzt >= float(s.get("fenster_ende") or s.get("ende") or 0):
            return "Giessfenster zu Ende"
        return None

    def _vorher(self, s, cfg, zonen, abbild, jetzt):
        z = self._zone(zonen, s.get("zone"))
        if not gardena_zone(z) or str(z.get("gardena_ventil") or "").strip() != s.get("ventil"):
            return "Zone nicht mehr auf diesem GARDENA-Ventil"
        sp = abbild.get("sperre") if isinstance(abbild.get("sperre"), dict) else {}
        if int(sp.get("aktiv") or 0):
            return "Sperre (%s)" % str(sp.get("grund") or "")
        return plan_gilt(abbild, cfg, jetzt)

    def _hinweis(self, r):
        if r.get("grund") in KOPPLUNG_STEHT_NICHT:
            return (" Die Kopplung steht nicht; es gilt der Weg ueber Loxone, soweit die Zone "
                    "dort angeschlossen ist.")
        return ""

    def _ansage(self, art, daten, cfg) -> None:
        """Nr. 36 b: einen Anlass weitergeben. Eine Ansage haelt den Lauf nie auf;
        ob und wann gesprochen wird, entscheidet der Empfaenger (Haken, Sperre)."""
        if self.ansagen is None:
            return
        try:
            self.ansagen(art, daten, cfg)
        except Exception as f:                  # noqa: BLE001
            self.melden(30, "Ansage (%s) nicht moeglich: %s" % (art, type(f).__name__))

    def _ende_pruefen(self, cfg, halt) -> None:
        """Nr. 36 b: ist der GARDENA-Lauf dieser Nacht zu Ende? Dann der Anlass 'ende' -
        nur, wenn in dieser Nacht ein Ventil offen war, und nie beim Beenden des Dienstes
        (ein unterbrochener Lauf ist nicht zu Ende). Schritte frueherer Naechte zaehlen nicht."""
        if halt or self.ansagen is None:
            return
        schritte = [s for s in self._schritte() if isinstance(s, dict) and not s.get("alt")]
        if not schritte or any(s.get("stand") in ("geplant", "offen") for s in schritte):
            return
        if not any(s.get("geoeffnet") for s in schritte):
            return
        zonen = set(str(s.get("zone")) for s in schritte if s.get("stand") == "fertig")
        voll = all(s.get("stand") == "fertig" for s in schritte)
        self._ansage("ende", {"nacht": str(self.z.get("nacht") or ""), "zonen": len(zonen),
                              "vollstaendig": 1 if voll else 0}, cfg)

    # ------------------------------------------------------------ Ablauf
    def schritt(self, halt: bool = False) -> bool:
        """Einen faelligen Vorgang erledigen. True = es geschah etwas (der
        Aufrufer darf sofort weitermachen), False = nichts faellig."""
        jetzt = self.jetzt()
        cfg, zonen, abbild = self.lesen()
        abbild = abbild if isinstance(abbild, dict) else {}
        # 1) Offene Ventile: regulaeres Ende oder Abbruch - zuerst.
        for s in self._schritte():
            if not isinstance(s, dict) or s.get("stand") != "offen":
                continue
            grund = self._abbruch(s, cfg, zonen, abbild, jetzt, halt)
            if grund is None and jetzt < float(s.get("ende") or 0):
                continue
            self._schliessen(s, cfg, zonen, grund or "", halt)
            self._ende_pruefen(cfg, halt)
            self._sichern()
            return True
        self.frisch = False
        # 2) Liegengebliebene Buchungen nachholen.
        if self._buchen_nachholen():
            self._sichern()
        if halt or cfg is None or int(cfg.get("gardena_ein") or 0) != 1:
            return False
        fe = fenster(cfg.get("fenster_von"), cfg.get("fenster_bis"), jetzt)
        if fe is None:
            return False
        beginn, ende = fe
        nacht = time.strftime("%Y-%m-%dT%H:%M", time.localtime(beginn))
        if self.z.get("nacht") != nacht:
            # Der Fahrplan entsteht erst, wenn der Plan gilt - nach einem
            # Neustart im Fenster steht das Abbild oft noch nicht. Bis dahin
            # wird nichts geoeffnet (kein Giessen bei Quellenausfall); was
            # danach noch ins Fenster passt, laeuft wie geplant.
            grund = plan_gilt(abbild, cfg, jetzt)
            if grund:
                w = self.z.get("wartet") if isinstance(self.z.get("wartet"), dict) else {}
                if w.get("nacht") != nacht or w.get("grund") != grund:
                    self.z["wartet"] = {"nacht": nacht, "grund": grund, "ts": int(jetzt)}
                    self.melden(30, "GARDENA: noch kein Fahrplan fuer die Nacht ab %s - %s. Es wird "
                                    "nichts geoeffnet, bis der Plan gilt."
                                % (time.strftime("%H:%M", time.localtime(beginn)), grund))
                    self._sichern()
                    return True
                return False
            self._fahrplan(cfg, zonen, abbild, nacht, beginn, ende, jetzt)
            self._sichern()
            return True
        for s in self._schritte():
            if not isinstance(s, dict) or s.get("stand") != "geplant":
                continue
            if jetzt < float(s.get("beginn") or 0):
                return False
            self._oeffnen(s, cfg, zonen, abbild, jetzt)
            self._ende_pruefen(cfg, False)
            self._sichern()
            return True
        return False

    def _fahrplan(self, cfg, zonen, abbild, nacht, beginn, ende, jetzt):
        try:
            max_min = int(float(cfg.get("gardena_max_min") or 60))
        except (TypeError, ValueError):
            max_min = 60
        neu, info = fahrplan_bauen(cfg, abbild, zonen, beginn, ende, max_min)
        # Ein Schritt, dessen Wasser noch nicht im Verlauf steht, bleibt.
        behalten = [s for s in self._schritte()
                    if isinstance(s, dict) and (s.get("stand") == "offen" or s.get("gebucht") == 0)]
        for s in behalten:
            s["alt"] = 1
        self.z = {"nacht": nacht, "gebaut": int(jetzt), "fenster_beginn": int(beginn),
                  "fenster_ende": int(ende), "info": info, "schritte": behalten + neu}
        zonen_n = len(set(s["zone"] for s in neu))
        text = ("GARDENA: Fahrplan der Nacht ab %s: %d Schritte in %d Zonen, %d Durchlaeufe"
                % (time.strftime("%H:%M", time.localtime(beginn)), len(neu), zonen_n,
                   int(info.get("durchlaeufe") or 0)))
        if info.get("grund"):
            text += " - %s" % info["grund"]
        if not info.get("zonen"):
            text += " - keine Zone auf Ausgabeart GARDENA gestellt"
        if info.get("ohne_ventil"):
            text += " - ohne Ventilname: %s" % ", ".join(info["ohne_ventil"])
        if info.get("gekuerzt"):
            text += " - %d Schritte am Fensterende gekuerzt oder entfallen" % info["gekuerzt"]
        self.melden(20, text)

    def _oeffnen(self, s, cfg, zonen, abbild, jetzt):
        rest = float(s.get("ende") or 0) - jetzt
        wer = "Zone '%s' (Ventil '%s', Durchlauf %s%s)" % (
            s.get("name"), s.get("ventil"), s.get("durchlauf"),
            (", Abschnitt %s/%s" % (s.get("teil"), s.get("teile"))) if int(s.get("teile") or 1) > 1 else "")
        if rest < MINDEST_S:
            s["stand"] = "verpasst"
            s["grund"] = "Startzeit verpasst (Dienst lief nicht)"
            self.melden(30, "GARDENA: %s nicht geoeffnet - %s; gilt als nicht gegossen." % (wer, s["grund"]))
            return
        grund = self._vorher(s, cfg, zonen, abbild, jetzt)
        if grund:
            s["stand"] = "ausgelassen"
            s["grund"] = grund
            self.melden(30, "GARDENA: %s nicht geoeffnet - %s; gilt als nicht gegossen." % (wer, grund))
            return
        try:
            max_min = max(1, min(HOECHST_MIN, int(float(cfg.get("gardena_max_min") or 60))))
        except (TypeError, ValueError):
            max_min = 60
        minuten = min(max_min, max(1, int(math.ceil(rest / 60.0))))
        ordner, token = self._zugang(cfg)
        r = self.rufen(self.port(), ordner, token, s.get("ventil"), "oeffnen", minuten, ZEITGRENZE_S)
        t = self.jetzt()
        s["oeffnen"] = kurz(r)
        s["minuten"] = minuten
        if r.get("erfolg"):
            try:
                seit = int((r.get("felder") or {}).get("SEIT_S") or 0) if r.get("unveraendert") else 0
            except ValueError:
                seit = 0
            s["stand"] = "offen"
            s["geoeffnet"] = int(t)
            # Bis dahin laeuft das Ventil spaetestens - die Wolke schliesst selbst.
            s["bis"] = int(t - seit + minuten * 60)
            self._ansage("ventil_ok", {"ventil": s.get("ventil"), "befehl": "oeffnen"}, cfg)
            self.melden(20, "GARDENA: %s geoeffnet fuer %d min (%s); geschlossen wird um %s, die "
                            "Wolke schliesst spaetestens um %s."
                        % (wer, minuten, beschreiben(r),
                           time.strftime("%H:%M:%S", time.localtime(float(s["ende"]))),
                           time.strftime("%H:%M:%S", time.localtime(s["bis"]))))
            return
        s["stand"] = "fehler"
        s["grund"] = str(r.get("grund") or "")
        self._ansage("ventil", {"zone": s.get("name"), "ventil": s.get("ventil"),
                                "befehl": "oeffnen"}, cfg)
        self.melden(30, "GARDENA: %s NICHT geoeffnet: %s - gilt als nicht gegossen.%s"
                    % (wer, beschreiben(r), self._hinweis(r)))
        if r.get("grund") == "ZEITUEBERSCHREITUNG":
            # Abschnitt 4: nicht blind wiederholen - nachfragen und schliessen.
            z = self.rufen(self.port(), ordner, token, s.get("ventil"), "zustand", None,
                           ZEITGRENZE_ZUSTAND_S)
            f = z.get("felder") or {}
            s["zustand"] = kurz(z)
            self.melden(30, "GARDENA: %s Zustand nach der Zeitueberschreitung: %s, LETZTER_BEFEHL=%s, "
                            "LETZTE_MINUTEN=%s, VOR_S=%s." % (wer, beschreiben(z), f.get("LETZTER_BEFEHL", "?"),
                                                            f.get("LETZTE_MINUTEN", "?"),
                                                            f.get("LETZTER_BEFEHL_VOR_S", "?")))
            c = self.rufen(self.port(), ordner, token, s.get("ventil"), "schliessen", None, ZEITGRENZE_S)
            s["schliessen"] = kurz(c)
            self.melden(30 if not c.get("erfolg") else 20,
                        "GARDENA: %s vorsorglich geschlossen: %s. Kam das Oeffnen doch an, schliesst die "
                        "Wolke spaetestens nach %d min." % (wer, beschreiben(c), minuten))

    def _schliessen(self, s, cfg, zonen, grund, halt):
        ordner, token = self._zugang(cfg)
        zeit = ZEITGRENZE_HALT_S if halt else ZEITGRENZE_S
        r = self.rufen(self.port(), ordner, token, s.get("ventil"), "schliessen", None, zeit)
        t = self.jetzt()
        bis = float(s.get("bis") or t)
        lief = max(0, int(min(t, bis) - float(s.get("geoeffnet") or t)))
        s["schliessen"] = kurz(r)
        s["geschlossen"] = int(t)
        s["gegossen_s"] = lief
        s["stand"] = "abgebrochen" if grund else "fertig"
        if grund:
            s["grund"] = grund
        z = self._zone(zonen, s.get("zone")) or {}
        try:
            rate = float(z.get("rate_mmh") or 0.0) if int(z.get("rate_gemessen") or 0) else 0.0
            wg = max(0.3, min(1.0, float((cfg or {}).get("wirkungsgrad") or 0.75)))
        except (TypeError, ValueError):
            rate, wg = 0.0, 0.75
        s["datum"] = time.strftime("%Y-%m-%d", time.localtime(t))
        wer = "Zone '%s' (Ventil '%s')" % (s.get("name"), s.get("ventil"))
        mm = round(lief / 3600.0 * rate * wg, 2) if rate > 0 and lief > 0 else 0.0
        if mm > 0:
            s["mm"] = mm
            s["gebucht"] = 0
            buchung = "%.2f mm fuer den Verlauf" % mm
        else:
            s["mm"] = None
            s["gebucht"] = -1
            if lief <= 0:
                warum = "das Ventil lief nicht"
            elif rate <= 0:
                warum = "keine Becherprobe - ohne gemessene Rate keine Menge"
            else:
                warum = "weniger als 0,01 mm"
            buchung = "nichts verbucht: %s" % warum
        if r.get("erfolg"):
            self._ansage("ventil_ok", {"ventil": s.get("ventil"), "befehl": "schliessen"}, cfg)
            self.melden(20, "GARDENA: %s geschlossen nach %d s%s (%s); %s."
                        % (wer, lief, (" - Abbruch: " + grund) if grund else "", beschreiben(r), buchung))
        else:
            if not halt:
                self._ansage("ventil", {"zone": s.get("name"), "ventil": s.get("ventil"),
                                        "befehl": "schliessen"}, cfg)
            self.melden(30, "GARDENA: %s Schliessen gescheitert%s: %s.%s Die Wolke schliesst das Ventil "
                            "spaetestens um %s (Dauer beim Oeffnen). Gezaehlt sind %d s; %s."
                        % (wer, (" (" + grund + ")") if grund else "", beschreiben(r), self._hinweis(r),
                           time.strftime("%H:%M:%S", time.localtime(bis)), lief, buchung))
        self._buchen_nachholen()

    def _buchen_nachholen(self) -> bool:
        getan = False
        for s in self._schritte():
            if not isinstance(s, dict) or s.get("gebucht") != 0:
                continue
            try:
                ok = self.buchen(str(s.get("datum")), str(s.get("zone")), float(s.get("mm") or 0.0))
            except Exception as f:                  # noqa: BLE001
                ok = False
                self.melden(30, "GARDENA: Buchung in den Verlauf gescheitert (%s) - neuer Versuch."
                            % type(f).__name__)
            if ok:
                s["gebucht"] = 1
                getan = True
        return getan
