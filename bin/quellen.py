#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Messwerte beziehen - ohne eine einzige Wetterstation zu kennen.

Das Plugin kennt nur Messgroessen und drei Bezugswege (siehe
templates/quellen.json). Welches Geraet dahinter steckt, ist ihm gleich:

    mqtt     ein Thema je Groesse. Alles, was in den Broker schreibt.
    http     eine JSON-Antwort abholen und einen Pfad daraus lesen.
    online   Open-Meteo.

Der wichtigste Entwurfsgedanke: **es faellt einzeln zurueck, nicht als
Ganzes.** Wer nur einen Regenmesser hat, bekommt seinen echten Regen und die
uebrigen Groessen aus dem Modell. Woher jede Groesse kam, steht im Ergebnis -
sonst weiss hinterher niemand, ob eine Zahl gemessen oder geraten war.

Open-Meteo ist kostenlos und ohne Schluessel nutzbar; der Anbieter nennt das
ausdruecklich fuer nicht gewerbliche Nutzung. Die Felder heissen
'et0_fao_evapotranspiration' (mm) und 'precipitation_sum' (mm) - dieselbe
FAO-56-Rechnung, die auch bin/fao56.py macht.
"""

from __future__ import annotations

import json
import logging
import re
import time
import urllib.parse
import urllib.request
from typing import Any

_LOG = logging.getLogger("bewaesserung.quellen")

OPEN_METEO = "https://api.open-meteo.com/v1/forecast"

# Merkmal fuer "diese Nutzlast ist kein JSON". Ein eigenes Objekt statt None,
# damit sich "noch nicht zerlegt" von "zerlegt, war aber Muell" unterscheiden
# laesst - None ist ein gueltiges JSON-Ergebnis.
_KAPUTT = object()


# --------------------------------------------------------------------------
# Pfade in JSON
# --------------------------------------------------------------------------

def json_pfad(daten: Any, pfad: str) -> Any:
    """Einen punktgetrennten Pfad aus einer JSON-Antwort lesen.

    Beispiele:  'value'
                'result.temperature'
                'common_list[2].val'

    Gibt None zurueck, wenn der Pfad ins Leere zeigt - und wirft nicht. Eine
    fehlende Groesse ist ein Normalfall, kein Fehler: sie faellt dann auf
    Open-Meteo zurueck.
    """
    if not pfad:
        return None
    stelle = daten
    for teil in pfad.split("."):
        if stelle is None:
            return None
        m = re.match(r"^([^\[]*)((?:\[\d+\])*)$", teil.strip())
        if not m:
            return None
        name, indizes = m.group(1), m.group(2)
        if name:
            if not isinstance(stelle, dict) or name not in stelle:
                return None
            stelle = stelle[name]
        for i in re.findall(r"\[(\d+)\]", indizes):
            if not isinstance(stelle, (list, tuple)):
                return None
            k = int(i)
            if k >= len(stelle):
                return None
            stelle = stelle[k]
    return stelle


def zahl(wert: Any) -> float | None:
    """Aus einem Rohwert eine Zahl machen.

    Wetterstationen liefern gern '21.4 C', '1013.2hPa' oder '--'. Es wird die
    erste Zahl genommen, die im Text steht; wo keine ist, gibt es None statt
    einer erfundenen Null. Eine falsche Null verdirbt die ganze Bilanz.
    """
    if wert is None:
        return None
    if isinstance(wert, bool):
        return None
    if isinstance(wert, (int, float)):
        return float(wert)
    m = re.search(r"-?\d+(?:[.,]\d+)?", str(wert))
    if not m:
        return None
    try:
        return float(m.group(0).replace(",", "."))
    except ValueError:
        return None


def umrechnen(wert: float, einheit: str, tabelle: dict) -> float:
    """In die Einheiten bringen, mit denen FAO-56 rechnet."""
    e = (tabelle or {}).get(einheit or "")
    if not isinstance(e, dict):
        return wert
    return wert * float(e.get("faktor", 1.0)) + float(e.get("offset", 0.0))


# --------------------------------------------------------------------------
# HTTP-Quelle
# --------------------------------------------------------------------------

def http_holen(url: str, zeit: int = 10) -> Any:
    """Eine JSON-Antwort abholen. Keine Zugangsdaten in der Adresse."""
    req = urllib.request.Request(url, headers={
        "User-Agent": "LoxBerry-Bewaesserung", "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=zeit) as a:
        roh = a.read().decode("utf-8", "replace")
    try:
        return json.loads(roh)
    except ValueError:
        # Manche Geraete schicken JSON mit fuehrendem Muell.
        i, j = roh.find("{"), roh.rfind("}")
        if 0 <= i < j:
            return json.loads(roh[i:j + 1])
        raise


# --------------------------------------------------------------------------
# Open-Meteo
# --------------------------------------------------------------------------

def open_meteo(breite: float, laenge: float, zeitzone: str = "auto",
               rueckwaerts: int = 7, vorwaerts: int = 7,
               zeit: int = 20) -> dict:
    """ET0 und Niederschlag, rueckwaerts und vorwaerts.

    'past_days' liefert die vergangenen Tage aus demselben Modelllauf - damit
    ist die Bilanz auch dann fortschreibbar, wenn der LoxBerry ein paar Tage
    aus war.
    """
    frage = {
        "latitude": "%.4f" % breite,
        "longitude": "%.4f" % laenge,
        "daily": ("et0_fao_evapotranspiration,precipitation_sum,"
                  "precipitation_probability_max,temperature_2m_max,"
                  "temperature_2m_min,wind_speed_10m_max,"
                  "shortwave_radiation_sum,relative_humidity_2m_max,"
                  "relative_humidity_2m_min"),
        "past_days": str(max(0, min(92, rueckwaerts))),
        "forecast_days": str(max(1, min(16, vorwaerts))),
        "timezone": zeitzone or "auto",
    }
    url = OPEN_METEO + "?" + urllib.parse.urlencode(frage)
    # Der Aufrufer im Dienst faengt Ausnahmen dieser Funktion bereits ab und
    # rechnet dann mit den Werten der eigenen Station weiter. Trotzdem wird
    # hier zusaetzlich gefangen: die Funktion soll auch dann brauchbar sein,
    # wenn sie einmal von anderer Stelle aufgerufen wird - etwa aus dem
    # Reiter Test. Ein leeres, aber wohlgeformtes Ergebnis ist an jeder
    # Stelle besser handhabbar als eine Ausnahme.
    try:
        d = http_holen(url, zeit)
    except Exception as f:            # noqa: BLE001 - Netz kann alles werfen
        _LOG.warning("Open-Meteo antwortet nicht (%s): %s", type(f).__name__, f)
        return {"ok": 0, "tage": [], "einheiten": {}, "hoehe": None,
                "zeitzone": None, "fehler": "%s: %s" % (type(f).__name__, f)}
    if not isinstance(d, dict):
        return {"ok": 0, "tage": [], "einheiten": {}, "hoehe": None,
                "zeitzone": None, "fehler": "Antwort ist kein JSON-Objekt."}
    tage = (d.get("daily") or {})
    zeiten = tage.get("time") or []
    aus = []
    for i, t in enumerate(zeiten):
        def g(feld):
            liste = tage.get(feld) or []
            return liste[i] if i < len(liste) else None
        aus.append({
            "datum": t,
            "et0": zahl(g("et0_fao_evapotranspiration")),
            "regen": zahl(g("precipitation_sum")),
            "regen_wahrsch": zahl(g("precipitation_probability_max")),
            "tmax": zahl(g("temperature_2m_max")),
            "tmin": zahl(g("temperature_2m_min")),
            "wind_kmh": zahl(g("wind_speed_10m_max")),
            "strahlung_mj": zahl(g("shortwave_radiation_sum")),
            "rh_max": zahl(g("relative_humidity_2m_max")),
            "rh_min": zahl(g("relative_humidity_2m_min")),
        })
    return {"ok": 1, "tage": aus, "einheiten": d.get("daily_units") or {},
            "hoehe": d.get("elevation"), "zeitzone": d.get("timezone")}


# --------------------------------------------------------------------------
# Alles zusammentragen
# --------------------------------------------------------------------------

class Sammler:
    """Traegt die Messgroessen aus allen eingerichteten Wegen zusammen.

    MQTT-Werte kommen nicht hier herein, sondern werden vom Dienst
    entgegengenommen und mit 'mqtt_setzen' abgelegt - ein Broker schiebt,
    er wird nicht gefragt.
    """

    def __init__(self, quellen: dict, tabelle: dict) -> None:
        self.felder = (quellen or {}).get("felder") or {}
        self.http_url = str((quellen or {}).get("http_url") or "")
        self.einheiten = (tabelle or {}).get("einheiten") or {}
        self.mqtt: dict[str, tuple[str, float]] = {}     # thema -> (rohtext, ts)
        self._geparst: dict[str, Any] = {}               # thema -> zerlegtes JSON
        self.roh_http: Any = None
        self.letzter_http_fehler = ""

    # ---- MQTT ----

    def mqtt_themen(self) -> list[str]:
        return sorted({str(f.get("thema")) for f in self.felder.values()
                       if f.get("weg") == "mqtt" and f.get("thema")})

    def mqtt_setzen(self, thema: str, nutzlast: str) -> None:
        """Eine Nachricht aus dem Broker ablegen.

        Der Rohtext wird aufgehoben, nicht sofort in eine Zahl gewandelt:
        derselbe Text kann fuer die eine Groesse eine blanke Zahl und fuer
        die andere ein JSON-Objekt mit eigenem Pfad sein. Zwei Felder duerfen
        auf dasselbe Thema zeigen und verschiedene Pfade daraus lesen - das
        ginge nicht mehr, wenn hier schon entschieden wuerde.

        Das Zerlegen des JSON wird stattdessen GEMERKT (siehe _geparst).
        Damit wird jede Nutzlast genau einmal zerlegt, egal wie oft danach
        gefragt wird - und die Bedeutung bleibt trotzdem unveraendert.
        """
        self.mqtt[thema] = (nutzlast, time.time())
        # Beim naechsten Zugriff neu zerlegen.
        self._geparst.pop(thema, None)

    def mqtt_json(self, thema: str, nutzlast: str) -> Any:
        """Die Nutzlast eines Themas als JSON - hoechstens einmal zerlegt.

        Ohne diesen Merker wuerde derselbe Text bei jedem Rechengang und fuer
        jede Groesse erneut durch json.loads laufen. Der Zeitgewinn ist klein
        (eine Nutzlast von hundert Zeichen kostet Mikrosekunden, nicht
        Millisekunden - die oft geaeusserte Sorge um die Rechenlast eines
        Raspberry Pi trifft hier nicht zu). Der eigentliche Gewinn ist ein
        anderer: eine kaputte Nutzlast wird einmal als kaputt erkannt und
        nicht bei jedem Zugriff aufs Neue.

        Rueckgabe: die zerlegten Daten oder das Sonderobjekt _KAPUTT.
        """
        merker = self._geparst.get(thema)
        if merker is not None:
            return merker
        try:
            d: Any = json.loads(nutzlast)
        except ValueError:
            d = _KAPUTT
        self._geparst[thema] = d
        return d

    # ---- Abholen ----

    def http_abholen(self) -> None:
        if not self.http_url:
            return
        try:
            self.roh_http = http_holen(self.http_url)
            self.letzter_http_fehler = ""
        except Exception as f:
            self.roh_http = None
            self.letzter_http_fehler = str(f)
            _LOG.warning("HTTP-Quelle antwortet nicht: %s", f)

    def wert(self, groesse: str, hoechstalter: float = 3600.0) -> tuple[float | None, str]:
        """Eine Messgroesse holen. Rueckgabe: (Wert, Herkunft)."""
        f = self.felder.get(groesse)
        if not isinstance(f, dict) or not f.get("weg"):
            return None, "fehlt"
        weg = f.get("weg")
        roh = None
        if weg == "mqtt":
            eintrag = self.mqtt.get(str(f.get("thema") or ""))
            if eintrag is None:
                return None, "mqtt_nichts_empfangen"
            nutzlast, ts = eintrag
            if time.time() - ts > hoechstalter:
                return None, "mqtt_veraltet"
            roh = nutzlast
            if f.get("pfad"):
                d = self.mqtt_json(str(f.get("thema") or ""), nutzlast)
                if d is _KAPUTT:
                    return None, "mqtt_kein_json"
                roh = json_pfad(d, str(f["pfad"]))
        elif weg == "http":
            if self.roh_http is None:
                return None, "http_nichts"
            roh = json_pfad(self.roh_http, str(f.get("pfad") or ""))
        else:
            return None, "fehlt"

        z = zahl(roh)
        if z is None:
            return None, "unlesbar"
        return umrechnen(z, str(f.get("einheit_quelle") or ""), self.einheiten), weg


def messwerte_zusammenstellen(sammler: Sammler, online_heute: dict | None,
                              standort: dict) -> dict:
    """Die Eingangsgroessen fuer fao56.et0_aus_messwerten zusammenstellen.

    Je Groesse gilt: erst die eigene Station, sonst Open-Meteo, sonst gar
    nicht. Die Herkunft wird mitgefuehrt und wandert bis in die Oberflaeche.
    """
    herkunft: dict[str, str] = {}
    m: dict[str, Any] = {}

    fuer_online = {
        "tmin": "tmin", "tmax": "tmax", "rh_min": "rh_min", "rh_max": "rh_max",
    }
    for g in ("tmin", "tmax", "rh_min", "rh_max", "rh_mittel", "taupunkt",
              "wind", "strahlung_wm2", "sonnenstunden", "regen_tag"):
        w, woher = sammler.wert(g)
        if w is not None:
            m[g] = w
            herkunft[g] = "station"
            continue
        if online_heute:
            if g in fuer_online and online_heute.get(fuer_online[g]) is not None:
                m[g] = online_heute[fuer_online[g]]
                herkunft[g] = "open-meteo"
                continue
            if g == "wind" and online_heute.get("wind_kmh") is not None:
                # Open-Meteo liefert die 10-m-Boe in km/h; fao56 rechnet sie
                # ueber wind_hoehe auf 2 m herunter.
                m["wind"] = float(online_heute["wind_kmh"]) / 3.6
                m["wind_hoehe"] = 10.0
                herkunft[g] = "open-meteo"
                continue
            if g == "strahlung_wm2" and online_heute.get("strahlung_mj") is not None:
                # MJ/m2 je Tag zurueck in ein Tagesmittel in W/m2
                m["strahlung_wm2"] = float(online_heute["strahlung_mj"]) / 0.0864
                herkunft[g] = "open-meteo"
                continue
            if g == "regen_tag" and online_heute.get("regen") is not None:
                m["regen_tag"] = online_heute["regen"]
                herkunft[g] = "open-meteo"
                continue
        herkunft[g] = woher if woher != "fehlt" else "keine"

    if "wind_hoehe" not in m:
        m["wind_hoehe"] = float(standort.get("wind_hoehe") or 2.0)
    m["breite"] = float(standort.get("breite") or 0.0)
    m["laenge"] = float(standort.get("laenge") or 0.0)
    m["hoehe"] = float(standort.get("hoehe") or 0.0)
    m["kuestennah"] = bool(standort.get("kuestennah"))
    return {"messwerte": m, "herkunft": herkunft}


# --------------------------------------------------------------------------
# Selbstpruefung (ohne Netz und ohne Broker)
# --------------------------------------------------------------------------

def selbstpruefung() -> list[tuple[bool, str]]:
    e: list[tuple[bool, str]] = []

    d = {"common_list": [{"id": "0x02", "val": "70.9"}, {"id": "0x07", "val": "55"}],
         "result": {"temperature": 21.4}, "leer": None}
    e.append((json_pfad(d, "common_list[0].val") == "70.9", "Pfad mit Listenindex"))
    e.append((json_pfad(d, "result.temperature") == 21.4, "Punktpfad"))
    e.append((json_pfad(d, "gibtsnicht") is None, "Fehlender Pfad ergibt None"))
    e.append((json_pfad(d, "common_list[9].val") is None, "Index ausserhalb ergibt None"))
    e.append((json_pfad(d, "leer.tiefer") is None, "Pfad durch None ergibt None"))

    e.append((zahl("21.4 C") == 21.4, "Zahl aus '21.4 C'"))
    e.append((zahl("21,4") == 21.4, "Komma als Dezimaltrenner"))
    e.append((zahl("-3.5hPa") == -3.5, "Negative Zahl mit Einheit"))
    e.append((zahl("--") is None, "'--' ergibt None, nicht 0"))
    e.append((zahl(None) is None, "None bleibt None"))
    e.append((zahl(True) is None, "Wahrheitswert ist keine Messung"))

    tab = {"F": {"faktor": 0.555556, "offset": -17.777778},
           "km/h": {"faktor": 0.277778, "offset": 0.0}}
    e.append((abs(umrechnen(70.9, "F", tab) - 21.611) < 0.01,
              "70,9 F sind 21,6 C: %.2f" % umrechnen(70.9, "F", tab)))
    e.append((abs(umrechnen(36.0, "km/h", tab) - 10.0) < 0.001,
              "36 km/h sind 10 m/s"))
    e.append((umrechnen(5.0, "unbekannt", tab) == 5.0,
              "Unbekannte Einheit bleibt unveraendert"))

    q = {"felder": {"tmax": {"weg": "mqtt", "thema": "w/t"},
                    "rh_mittel": {"weg": "mqtt", "thema": "w/j", "pfad": "value"},
                    "wind": {"weg": "http", "pfad": "result.wind",
                             "einheit_quelle": "km/h"}}}
    s = Sammler(q, {"einheiten": tab})
    e.append((s.mqtt_themen() == ["w/j", "w/t"], "Themenliste: %s" % s.mqtt_themen()))
    e.append((s.wert("tmax")[1] == "mqtt_nichts_empfangen",
              "Noch nichts empfangen wird benannt"))
    s.mqtt_setzen("w/t", "23.5")
    e.append((s.wert("tmax")[0] == 23.5, "MQTT-Wert gelesen"))
    s.mqtt_setzen("w/j", '{"value": 61}')
    e.append((s.wert("rh_mittel")[0] == 61.0, "MQTT mit JSON-Pfad gelesen"))
    s.mqtt_setzen("w/j", 'kein json')
    e.append((s.wert("rh_mittel")[1] == "mqtt_kein_json", "Kaputtes JSON wird benannt"))
    s.mqtt[("w/t")] = ("23.5", time.time() - 9999)
    e.append((s.wert("tmax")[1] == "mqtt_veraltet", "Veralteter Wert wird verworfen"))
    s.roh_http = {"result": {"wind": 36.0}}
    e.append((abs(s.wert("wind")[0] - 10.0) < 0.001, "HTTP-Wert samt Umrechnung"))

    online = {"tmin": 11.0, "tmax": 24.0, "rh_min": 40, "rh_max": 90,
              "wind_kmh": 18.0, "strahlung_mj": 22.0, "regen": 3.2}
    s2 = Sammler({"felder": {"tmax": {"weg": "mqtt", "thema": "a"}}}, {"einheiten": tab})
    s2.mqtt_setzen("a", "27.7")
    z = messwerte_zusammenstellen(s2, online, {"breite": 48.5, "hoehe": 400})
    e.append((z["messwerte"]["tmax"] == 27.7 and z["herkunft"]["tmax"] == "station",
              "Eigene Station hat Vorrang"))
    e.append((z["messwerte"]["tmin"] == 11.0 and z["herkunft"]["tmin"] == "open-meteo",
              "Fehlende Groesse faellt EINZELN auf Open-Meteo zurueck"))
    e.append((abs(z["messwerte"]["wind"] - 5.0) < 0.001 and z["messwerte"]["wind_hoehe"] == 10.0,
              "Wind aus Open-Meteo: km/h in m/s, Messhoehe 10 m gemerkt"))
    e.append((abs(z["messwerte"]["strahlung_wm2"] - 254.6) < 1.0,
              "22 MJ/m2 sind rund 255 W/m2 im Tagesmittel: %.0f"
              % z["messwerte"]["strahlung_wm2"]))

    z2 = messwerte_zusammenstellen(s2, None, {"breite": 48.5})
    e.append((z2["herkunft"]["tmin"] == "keine",
              "Ohne Station und ohne Netz: Herkunft 'keine', kein erfundener Wert"))
    e.append(("tmin" not in z2["messwerte"], "Fehlende Groesse wird nicht erfunden"))
    return e


if __name__ == "__main__":
    fehlt = 0
    for ok, text in selbstpruefung():
        print(("[OK]   " if ok else "[FEHL] ") + text)
        fehlt += 0 if ok else 1
    raise SystemExit(1 if fehlt else 0)
