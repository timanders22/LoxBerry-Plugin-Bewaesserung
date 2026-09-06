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

Neu in 0.9.7: **Tagesextremwerte.**

Eine Wetterstation liefert einen Momentanwert. FAO-56 rechnet mit Tmin und
Tmax des Tages - zwei verschiedene Dinge. Bis 0.9.6 zeigten deshalb ALLE
vier mitgelieferten Stationsvorlagen tmin und tmax auf dieselbe Quelle, und
in der Rechnung kam Tmax - Tmin = 0 heraus.

Gemessen am 18.08.2026 fuer einen Sommertag von 12 bis 28 Grad ohne
Strahlungsmesser:

    richtige Spanne   ET0 = 5,40 mm   (Rs = 25,8 MJ)
    tmin = tmax = 22  ET0 = 1,95 mm   (Rs =  0,0 MJ, denn sqrt(0) = 0)

Die eigene Station machte die Rechnung also schlechter als gar keine - und
zwar still, mit der Guete 'geschaetzt' statt einer Fehlermeldung.

Die Auflösung braucht keine Einstellung und keine neue Zuordnung: der
Sammler merkt sich je Groesse den Tagesverlauf und gibt fuer tmin das
**Minimum** und fuer tmax das **Maximum** des Tages zurueck. Das ist in
BEIDEN Faellen richtig:

  * Liefert die Station einen Momentanwert, ist das Minimum des Tages
    genau das gesuchte Tmin.
  * Liefert sie einen echten Tagestiefstwert, faellt der im Tagesverlauf
    monoton - sein Minimum ist derselbe Wert.

Deshalb greift die Aenderung auch auf bestehenden Anlagen, ohne dass jemand
etwas umstellen muss.
"""

from __future__ import annotations

import datetime
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


# Wie eine Groesse ueber den Tag zusammengefasst wird.
#
#   min/max   Tagestiefst- bzw. Tageshoechstwert. Fuer tmin/tmax und die
#             Luftfeuchte - das ist genau das, was FAO-56 verlangt.
#   mittel    Tagesmittel. Die Globalstrahlung geht als MITTELWERT in
#             Rs = Mittel * 0,0864 ein; ein Momentanwert um die Mittagszeit
#             waere um ein Vielfaches zu hoch, einer am Abend zu niedrig.
#             Beim Wind nennt [F] ebenfalls das Tagesmittel.
#   letzt     Der zuletzt eingetroffene Wert. Fuer alles, was eine Lage
#             beschreibt und keinen Tagesgang hat.
#   summe_max Ein Tageszaehler, der um Mitternacht auf 0 springt. Das
#             Maximum des Tages ist die Tagessumme; faellt der Wert, hat
#             der Zaehler zurueckgesetzt.
AGGREGAT = {
    "tmin": "min", "tmax": "max",
    "rh_min": "min", "rh_max": "max", "rh_mittel": "mittel",
    "taupunkt": "letzt",
    "wind": "mittel", "strahlung_wm2": "mittel",
    "sonnenstunden": "summe_max", "regen_tag": "summe_max",
    "regen_stunde": "letzt", "bodenfeuchte": "letzt",
}

# Ab wann gilt ein Tagesmittel als brauchbar?
#
# Die Globalstrahlung ueber einen halben Tag gemittelt ist keine
# Tagesmittelstrahlung - sie ist um den Faktor zwei daneben, je nachdem
# welche Haelfte. Deshalb wird ein Mittelwert erst herausgegeben, wenn die
# Messreihe den Tag hinreichend abdeckt; sonst faellt die Groesse auf
# Open-Meteo zurueck. Das ist dieselbe Regel wie ueberall hier: lieber das
# Modell als eine Zahl, die aussieht wie eine Messung.
MITTEL_MINDESTSTUNDEN = 18.0


# --------------------------------------------------------------------------
# Pfade in JSON
# --------------------------------------------------------------------------

def json_pfad(daten: Any, pfad: str) -> Any:
    """Einen punktgetrennten Pfad aus einer JSON-Antwort lesen.

    Beispiele:  'value'
                'result.temperature'
                'common_list[2].val'
                'common_list[id=0x02].val'      <- Auswahl je Kennung

    **Auswahl je Kennung, neu in 0.9.10.** Eine Stellungsangabe wie
    'common_list[3]' zeigt auf den vierten Eintrag - und der ist ein anderer,
    sobald ein Sensor dazukommt oder ausfaellt. Am 18.08.2026 zeigte deshalb
    an einer echten Anlage die Globalstrahlung auf den Dampfdruck: die
    mitgelieferte Vorlage traf die Anordnung eines anderen Geraets. Die
    Kennung dagegen bleibt, was sie ist.

    'common_list[id=0x02].val' sucht in der Liste den ersten Eintrag, dessen
    Feld 'id' den Wert '0x02' hat. Der Vergleich ist zeichengenau, aber ohne
    Beachtung von Gross- und Kleinschreibung - Gateways schreiben '0x02' und
    '0X02' gemischt.

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
        m = re.match(r"^([^\[]*)((?:\[[^\]]*\])*)$", teil.strip())
        if not m:
            return None
        name, klammern = m.group(1), m.group(2)
        if name:
            if not isinstance(stelle, dict) or name not in stelle:
                return None
            stelle = stelle[name]
        for inhalt in re.findall(r"\[([^\]]*)\]", klammern):
            if inhalt.isdigit():
                if not isinstance(stelle, (list, tuple)):
                    return None
                k = int(inhalt)
                if k >= len(stelle):
                    return None
                stelle = stelle[k]
                continue
            aw = re.match(r"^([A-Za-z_][A-Za-z0-9_]*)=(.*)$", inhalt)
            if not aw:
                return None
            feld, wert = aw.group(1), aw.group(2).strip().strip('"\'')
            if not isinstance(stelle, (list, tuple)):
                return None
            treffer = None
            for eintrag in stelle:
                if (isinstance(eintrag, dict)
                        and str(eintrag.get(feld, "")).lower() == wert.lower()):
                    treffer = eintrag
                    break
            if treffer is None:
                return None
            stelle = treffer
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

def _feldliste_lesen(text: str) -> dict | None:
    """Eine Nutzlast im Ecowitt-Uploadformat in ein Verzeichnis wandeln.

    Ein GW3000A, das ueber MQTT sendet, schickt **kein JSON**, sondern die
    Feldliste des Ecowitt-Uploadprotokolls:

        PASSKEY=...&stationtype=GW3000A_V1.2.2&tempf=63.50&humidity=88
        &windspeedmph=2.91&solarradiation=0.00&dailyrainin=0.358&...

    Ohne diese Umwandlung findet 'zahl()' darin die erste Zahl der ganzen
    Zeichenkette - also irgendetwas aus dem Wortzeichen - und haelt sie fuer
    einen Messwert. Das ist die stille Falschaussage in Reinform.

    Gemessen am 18.08.2026, 22:27, an einem GW3000A_V1.2.2.

    **Die Werte sind imperial, unabhaengig von den Einheiten-Einstellungen
    des Geraets.** Belegt gegen die Hersteller-App zum selben Zeitpunkt:
    dailyrainin 0,358 in = 9,09 mm gegen 9,1 mm in der App, eventrainin
    1,059 in = 26,90 mm gegen 26,9 mm, yearlyrainin 2,992 in = 76,00 mm
    gegen 76,0 mm. Die Einstellung 'Rain: mm' im Geraet gilt also nur fuer
    seine eigene Oberflaeche. Einzige Ausnahme: 'solarradiation' steht schon
    in W/m2.

    Rueckgabe: das Verzeichnis, oder None wenn es keine Feldliste ist.
    """
    if "=" not in text or len(text) > 20000:
        return None
    teile = [t for t in text.strip().split("&") if "=" in t]
    # Zwei Felder sind die Untergrenze: ein einzelnes 'a=1' kann alles sein.
    if len(teile) < 2:
        return None
    aus: dict[str, str] = {}
    for t in teile:
        k, _, v = t.partition("=")
        k = k.strip()
        if not k or " " in k:
            return None
        aus[k] = urllib.parse.unquote_plus(v)
    return aus


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
        self.roh_http_ts: float = 0.0
        self.letzter_http_fehler = ""
        # Tagesspeicher: datum -> groesse -> Kennzahlen (siehe beobachten()).
        self.tag: dict[str, Any] = {"datum": "", "werte": {}}

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
            # Kein JSON? Dann vielleicht eine Feldliste.
            d = _feldliste_lesen(nutzlast)
            if d is None:
                d = _KAPUTT
        self._geparst[thema] = d
        return d

    # ---- Abholen ----

    def http_abholen(self) -> None:
        if not self.http_url:
            return
        try:
            self.roh_http = http_holen(self.http_url)
            self.roh_http_ts = time.time()
            self.letzter_http_fehler = ""
        except Exception as f:
            # Die alte Antwort NICHT stehen lassen: bis 0.9.6 blieb
            # 'roh_http' beim naechsten Fehlschlag einfach erhalten und
            # wurde weiter als Stationswert ausgegeben - ohne jede
            # Altersgrenze, anders als beim MQTT-Weg. Ein eingefrorener
            # Endpunkt verdraengte damit das Modell auf Dauer.
            self.roh_http = None
            self.roh_http_ts = 0.0
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
            d = self.mqtt_json(str(f.get("thema") or ""), nutzlast)
            if f.get("pfad"):
                if d is _KAPUTT:
                    return None, "mqtt_kein_json"
                roh = json_pfad(d, str(f["pfad"]))
            elif isinstance(d, dict) and d:
                # Die Nachricht traegt MEHRERE Werte (JSON oder die
                # Feldliste des Ecowitt-Uploadprotokolls), aber es ist kein
                # Pfad eingetragen. Bis 0.9.18 ging die ganze Zeichenkette
                # an zahl(), und das nahm die erste Zahl darin - aus
                # "PASSKEY=ABC123&stationtype=GW3000A..." wurde ein
                # Messwert. Gemessen am 04.09.2026: 123.0, ohne jede
                # Fehlermeldung. Die Selbstpruefung dieses Moduls
                # beschreibt genau diesen Fall.
                return None, "pfad_fehlt"
        elif weg == "http":
            if self.roh_http is None:
                return None, "http_nichts"
            if time.time() - self.roh_http_ts > hoechstalter:
                return None, "http_veraltet"
            roh = json_pfad(self.roh_http, str(f.get("pfad") or ""))
        else:
            return None, "fehlt"

        z = zahl(roh)
        if z is None:
            return None, "unlesbar"
        return umrechnen(z, str(f.get("einheit_quelle") or ""), self.einheiten), weg


    # ---- Tagesverlauf ----

    def beobachten(self, datum: str, jetzt: float | None = None) -> int:
        """Den aktuellen Stand jeder eingerichteten Groesse in den Tag eintragen.

        Wird vom Dienst in jedem Takt gerufen. Je Groesse werden Kleinstwert,
        Groesstwert, Summe, Anzahl und die Zeitspanne der Reihe gefuehrt -
        daraus entstehen in 'tageswert' Tmin, Tmax und die Tagesmittel.

        Bei einem Datumswechsel faengt der Tag von vorn an. Das ist
        beabsichtigt: ein Tageshoechstwert, der den gestrigen mitschleppt,
        waere schlimmer als gar keiner.

        Rueckgabe: wie viele Groessen einen Wert beigesteuert haben.
        """
        jetzt = time.time() if jetzt is None else jetzt
        if self.tag.get("datum") != datum:
            self.tag = {"datum": datum, "werte": {}}
        n = 0
        for g in self.felder:
            w, _woher = self.wert(g)
            if w is None:
                continue
            n += 1
            k = self.tag["werte"].setdefault(
                g, {"min": w, "max": w, "summe": 0.0, "anzahl": 0,
                    "letzt": w, "erste_ts": jetzt, "letzte_ts": jetzt})
            k["min"] = min(k["min"], w)
            k["max"] = max(k["max"], w)
            k["summe"] += w
            k["anzahl"] += 1
            k["letzt"] = w
            k["letzte_ts"] = jetzt
        return n

    def tageswert(self, groesse: str, datum: str) -> tuple[float | None, str]:
        """Der Tageswert einer Groesse nach der Regel aus AGGREGAT.

        Rueckgabe: (Wert, Grund). Der Grund ist leer, wenn ein Wert kommt,
        sonst eine Kennung, die sagt WARUM keiner kommt - 'kein_tag',
        'nichts_gesehen' oder 'abdeckung_zu_kurz'.
        """
        if self.tag.get("datum") != datum:
            return None, "kein_tag"
        k = (self.tag.get("werte") or {}).get(groesse)
        if not k or not k.get("anzahl"):
            return None, "nichts_gesehen"
        art = AGGREGAT.get(groesse, "letzt")
        if art == "min":
            return k["min"], ""
        if art in ("max", "summe_max"):
            return k["max"], ""
        if art == "mittel":
            stunden = (k["letzte_ts"] - k["erste_ts"]) / 3600.0
            if stunden < MITTEL_MINDESTSTUNDEN:
                # Ein halber Tag Strahlung gemittelt ist kein Tagesmittel.
                return None, "abdeckung_zu_kurz"
            # Und die Spanne allein genuegt nicht: zwei Messpunkte,
            # achtzehn Stunden auseinander, bestanden die Pruefung bis
            # 0.9.18 und ergaben ein "Tagesmittel" aus zwei
            # Momentanwerten. Verlangt werden deshalb mindestens drei
            # Punkte und im Schnitt einer je vier Stunden. Enger geht es
            # nicht ohne die groesste Luecke mitzufuehren, und die stuende
            # nicht in tagesextreme.json - eine bestehende Anlage haette
            # sie nach dem Update nicht.
            if int(k["anzahl"]) < 3 or int(k["anzahl"]) * 4 < int(stunden):
                return None, "zu_wenige_messpunkte"
            return k["summe"] / k["anzahl"], ""
        return k["letzt"], ""

    def abdeckung_stunden(self, groesse: str) -> float:
        k = (self.tag.get("werte") or {}).get(groesse)
        if not k:
            return 0.0
        return max(0.0, (k["letzte_ts"] - k["erste_ts"]) / 3600.0)

    def tag_laden(self, gespeichert: dict | None) -> None:
        """Den Tagesspeicher aus der Datei uebernehmen.

        Ohne das verlöre ein Neustart um die Mittagszeit den Tagestiefstwert
        der Nacht - und Tmin waere dann die Mittagstemperatur.
        """
        if isinstance(gespeichert, dict) and gespeichert.get("datum"):
            werte = gespeichert.get("werte")
            if isinstance(werte, dict):
                self.tag = {"datum": str(gespeichert["datum"]), "werte": werte}


def messwerte_zusammenstellen(sammler: Sammler, online_heute: dict | None,
                              standort: dict, datum: str = "") -> dict:
    """Die Eingangsgroessen fuer fao56.et0_aus_messwerten zusammenstellen.

    Je Groesse gilt: erst die eigene Station, sonst Open-Meteo, sonst gar
    nicht. Die Herkunft wird mitgefuehrt und wandert bis in die Oberflaeche.

    Seit 0.9.7 wird zuerst der **Tageswert** genommen (Tagestiefstwert fuer
    tmin, Tageshoechstwert fuer tmax, Tagesmittel fuer Wind und Strahlung).
    Erst wenn es keinen gibt - etwa am ersten Tag nach dem Start, oder wenn
    die Messreihe den Tag nicht hinreichend abdeckt - gilt der Momentanwert.
    Ohne 'datum' verhaelt sich die Funktion wie bis 0.9.6.
    """
    herkunft: dict[str, str] = {}
    m: dict[str, Any] = {}

    fuer_online = {
        "tmin": "tmin", "tmax": "tmax", "rh_min": "rh_min", "rh_max": "rh_max",
    }
    for g in ("tmin", "tmax", "rh_min", "rh_max", "rh_mittel", "taupunkt",
              "wind", "strahlung_wm2", "sonnenstunden", "regen_tag",
              "regen_stunde", "bodenfeuchte"):
        w, woher = (sammler.tageswert(g, datum) if datum else (None, ""))
        if w is not None:
            m[g] = w
            herkunft[g] = "station"
            continue
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

    # --- Nutzlast im Ecowitt-Uploadformat (neu in 0.9.10) ---
    #
    # Woertlich die Nachricht eines GW3000A vom 18.08.2026, 22:27, gekuerzt.
    eco = ("PASSKEY=XXX&stationtype=GW3000A_V1.2.2&dateutc=2026-08-18%2020%3A27%3A42"
           "&tempinf=72.50&humidityin=40&tempf=63.50&humidity=88&winddir=197"
           "&windspeedmph=2.91&windgustmph=4.25&solarradiation=0.00&uv=0"
           "&rainratein=0.000&eventrainin=1.059&hourlyrainin=0.000"
           "&dailyrainin=0.358&weeklyrainin=1.059&monthlyrainin=1.728"
           "&yearlyrainin=2.992&freq=868M&model=GW3000A&interval=60")
    fl = _feldliste_lesen(eco)
    e.append((fl is not None and fl.get("tempf") == "63.50",
              "Feldliste erkannt: tempf = %s" % (fl or {}).get("tempf")))
    e.append((fl is not None and fl.get("dailyrainin") == "0.358",
              "und dailyrainin = %s" % (fl or {}).get("dailyrainin")))
    e.append((fl is not None and "2026-08-18 20:27:42" == fl.get("dateutc"),
              "Prozentkodierung aufgeloest: %r" % (fl or {}).get("dateutc")))
    # Der Grund, warum es diese Umwandlung braucht: ohne sie nimmt zahl()
    # die erste Zahl der GANZEN Zeichenkette.
    e.append((zahl(eco) == 3000.0,
              "Ohne Umwandlung ergaebe die rohe Nutzlast %s - eine Zahl aus dem "
              "Geraetenamen, die wie ein Messwert aussieht" % zahl(eco)))
    # Und was KEINE Feldliste ist, wird auch nicht dazu gemacht.
    for kein in ("einfach nur Text", "23.5", "", "a=1"):
        e.append((_feldliste_lesen(kein) is None,
                  "Keine Feldliste: %r" % kein))
    # Der ganze Weg ueber den Sammler, mit Umrechnung.
    s_eco = Sammler({"felder": {
        "tmax": {"weg": "mqtt", "thema": "ecowitt/GERAET", "pfad": "tempf",
                 "einheit_quelle": "F"},
        "regen_tag": {"weg": "mqtt", "thema": "ecowitt/GERAET",
                      "pfad": "dailyrainin", "einheit_quelle": "in"},
        "strahlung_wm2": {"weg": "mqtt", "thema": "ecowitt/GERAET",
                          "pfad": "solarradiation"}}},
        {"einheiten": {"F": {"faktor": 0.555556, "offset": -17.777778},
                       "in": {"faktor": 25.4, "offset": 0.0}}})
    s_eco.mqtt_setzen("ecowitt/GERAET", eco)
    t_wert = s_eco.wert("tmax")[0]
    r_wert = s_eco.wert("regen_tag")[0]
    e.append((t_wert is not None and abs(t_wert - 17.5) < 0.05,
              "63,50 F werden zu %.2f C (die App zeigte 17,8 C)" % (t_wert or -99)))
    e.append((r_wert is not None and abs(r_wert - 9.09) < 0.02,
              "0,358 in werden zu %.2f mm (die App zeigte 9,1 mm)" % (r_wert or -99)))
    e.append((s_eco.wert("strahlung_wm2")[0] == 0.0,
              "solarradiation steht schon in W/m2 und bleibt unveraendert"))

    # --- Auswahl je Kennung (neu in 0.9.10) ---
    #
    # Nachgebaut mit der Antwort eines GW3000A, wie sie am 18.08.2026
    # vorlag: die Stellung eines Eintrags haengt daran, welche Sensoren
    # angemeldet sind, die Kennung nicht.
    gw = {"common_list": [{"id": "0x02", "val": "18.3", "unit": "C"},
                          {"id": "0x07", "val": "89%"},
                          {"id": "5", "val": "0.231 kPa"},
                          {"id": "0x15", "val": "0.00 W/m2"}],
          "rain": [{"id": "0x0E", "val": "0.6 mm/Hr"},
                   {"id": "0x10", "val": "9.1 mm"}]}
    e.append((json_pfad(gw, "common_list[id=0x02].val") == "18.3",
              "Kennung 0x02 findet die Aussentemperatur, egal an welcher Stelle"))
    e.append((json_pfad(gw, "common_list[id=0x15].val") == "0.00 W/m2",
              "Kennung 0x15 findet die Globalstrahlung"))
    e.append((json_pfad(gw, "rain[id=0x10].val") == "9.1 mm",
              "Kennung 0x10 findet den Tagesregen"))
    e.append((json_pfad(gw, "common_list[id=0X15].val") == "0.00 W/m2",
              "Gross- und Kleinschreibung der Kennung ist gleichgueltig"))
    e.append((json_pfad(gw, "common_list[id=0x99].val") is None,
              "Eine Kennung, die es nicht gibt, ergibt None statt eines Nachbarn"))
    e.append((json_pfad(gw, "common_list[2].val") == "0.231 kPa",
              "Die Stellungsangabe funktioniert unveraendert weiter"))
    # Und der Fall, um den es geht: kommt ein Sensor dazu, verschiebt sich
    # die Stellung - die Kennung nicht.
    gw2 = {"common_list": [{"id": "0x01", "val": "neu"}] + gw["common_list"]}
    e.append((json_pfad(gw2, "common_list[id=0x15].val") == "0.00 W/m2"
              and json_pfad(gw2, "common_list[3].val") == "0.231 kPa",
              "Ein zusaetzlicher Sensor verschiebt die Stellung, nicht die Kennung"))

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
    s.roh_http_ts = time.time()      # seit 0.9.7 altern auch HTTP-Werte
    e.append((abs(s.wert("wind")[0] - 10.0) < 0.001, "HTTP-Wert samt Umrechnung"))

    # --- Tagesextremwerte (neu in 0.9.7) ---
    #
    # Der Fehler, den das aufloest: alle vier mitgelieferten Vorlagen zeigen
    # tmin und tmax auf DIESELBE Quelle. Bis 0.9.6 kam damit Tmax - Tmin = 0
    # heraus, und die Strahlungsnaeherung ueber die Temperaturspanne ergab
    # glatt 0 (sqrt(0)).
    st = Sammler({"felder": {"tmin": {"weg": "mqtt", "thema": "t"},
                             "tmax": {"weg": "mqtt", "thema": "t"},
                             "strahlung_wm2": {"weg": "mqtt", "thema": "s"}}},
                 {"einheiten": tab})
    # Ein Tag, wie ihn eine Station wirklich liefert: ein Momentanwert je Takt.
    t0 = time.time() - 22 * 3600
    for i, (grad, strahl) in enumerate([(12.0, 0.0), (15.0, 120.0), (22.0, 480.0),
                                        (28.0, 700.0), (24.0, 250.0), (17.0, 0.0)]):
        st.mqtt_setzen("t", str(grad))
        st.mqtt_setzen("s", str(strahl))
        st.beobachten("2026-07-15", t0 + i * 4 * 3600)
    e.append((st.tageswert("tmin", "2026-07-15")[0] == 12.0,
              "Tmin ist der Tagestiefstwert (12,0), nicht der letzte Messwert"))
    e.append((st.tageswert("tmax", "2026-07-15")[0] == 28.0,
              "Tmax ist der Tageshoechstwert (28,0)"))
    e.append((st.wert("tmin")[0] == 17.0,
              "Der Momentanwert bleibt daneben abrufbar (17,0)"))
    mittel = st.tageswert("strahlung_wm2", "2026-07-15")[0]
    e.append((mittel is not None and abs(mittel - 258.33) < 0.1,
              "Strahlung wird gemittelt, nicht als Momentanwert genommen: %.1f W/m2"
              % (mittel or -1)))
    # Ein echter Tagestiefstwert der Station faellt im Tagesverlauf - sein
    # Minimum ist derselbe Wert. Die Regel traegt also BEIDE Bauarten.
    st2 = Sammler({"felder": {"tmin": {"weg": "mqtt", "thema": "n"}}}, {"einheiten": tab})
    for i, grad in enumerate([18.0, 14.0, 12.0, 12.0]):
        st2.mqtt_setzen("n", str(grad))
        st2.beobachten("2026-07-15", t0 + i * 6 * 3600)
    e.append((st2.tageswert("tmin", "2026-07-15")[0] == 12.0,
              "Auch ein echter Tagestiefstwert der Station kommt richtig heraus"))
    # Ein halber Tag Strahlung ist kein Tagesmittel - dann lieber Open-Meteo.
    st3 = Sammler({"felder": {"strahlung_wm2": {"weg": "mqtt", "thema": "s"}}},
                  {"einheiten": tab})
    for i in range(4):
        st3.mqtt_setzen("s", "600")
        st3.beobachten("2026-07-15", t0 + i * 3600)
    w3, grund3 = st3.tageswert("strahlung_wm2", "2026-07-15")
    e.append((w3 is None and grund3 == "abdeckung_zu_kurz",
              "Vier Stunden Strahlung ergeben KEIN Tagesmittel, sondern '%s'" % grund3))
    # Der Tageswechsel raeumt auf.
    st.beobachten("2026-07-16", time.time())
    e.append((st.tageswert("tmax", "2026-07-15")[1] == "kein_tag",
              "Am neuen Tag gilt der gestrige Hoechstwert nicht mehr"))
    # Und der Neustart mitten am Tag verliert den Tiefstwert nicht.
    st4 = Sammler({"felder": {"tmin": {"weg": "mqtt", "thema": "t"}}}, {"einheiten": tab})
    st4.tag_laden(st2.tag)
    e.append((st4.tageswert("tmin", "2026-07-15")[0] == 12.0,
              "Nach einem Neustart steht der Tagestiefstwert wieder zur Verfuegung"))

    # --- HTTP-Werte altern jetzt auch ---
    s5 = Sammler({"felder": {"wind": {"weg": "http", "pfad": "w"}}}, {"einheiten": tab})
    s5.roh_http = {"w": 10.0}
    s5.roh_http_ts = time.time()
    e.append((s5.wert("wind")[0] == 10.0, "Frischer HTTP-Wert wird genommen"))
    s5.roh_http_ts = time.time() - 9999
    e.append((s5.wert("wind")[1] == "http_veraltet",
              "Veralteter HTTP-Wert wird verworfen statt endlos weitergereicht"))

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

    # Die beiden Groessen, die bis 0.9.6 in der Oberflaeche zuordenbar waren
    # und von keiner Zeile Code gelesen wurden.
    s6 = Sammler({"felder": {"regen_stunde": {"weg": "mqtt", "thema": "r"},
                             "bodenfeuchte": {"weg": "mqtt", "thema": "b"}}},
                 {"einheiten": tab})
    s6.mqtt_setzen("r", "2.4")
    s6.mqtt_setzen("b", "31")
    z6 = messwerte_zusammenstellen(s6, None, {"breite": 48.5})
    e.append((z6["messwerte"].get("regen_stunde") == 2.4
              and z6["herkunft"].get("regen_stunde") == "station",
              "regen_stunde wird gelesen (bis 0.9.6 eine Eingabe ohne Wirkung)"))
    e.append((z6["messwerte"].get("bodenfeuchte") == 31.0,
              "bodenfeuchte wird gelesen und kann Zonen ohne eigenes Thema versorgen"))

    # Und die Vorlagen selbst: dass tmin und tmax auf dieselbe Quelle zeigen,
    # ist ab 0.9.7 richtig - der Tagesspeicher macht daraus Extremwerte.
    st7 = Sammler({"felder": {"tmin": {"weg": "mqtt", "thema": "x"},
                              "tmax": {"weg": "mqtt", "thema": "x"}}},
                  {"einheiten": tab})
    for i, grad in enumerate([11.0, 27.0, 19.0]):
        st7.mqtt_setzen("x", str(grad))
        st7.beobachten("2026-07-15", time.time() - (20 - i * 8) * 3600)
    zz = messwerte_zusammenstellen(st7, None, {"breite": 48.5}, "2026-07-15")
    e.append((zz["messwerte"]["tmin"] == 11.0 and zz["messwerte"]["tmax"] == 27.0,
              "EIN Thema fuer tmin und tmax ergibt jetzt 11,0 und 27,0 statt zweimal 19,0"))
    return e


if __name__ == "__main__":
    fehlt = 0
    for ok, text in selbstpruefung():
        print(("[OK]   " if ok else "[FEHL] ") + text)
        fehlt += 0 if ok else 1
    raise SystemExit(1 if fehlt else 0)
