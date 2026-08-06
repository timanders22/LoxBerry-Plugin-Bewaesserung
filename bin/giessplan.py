#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Aus dem Wasserhaushalt einen Gie&szlig;plan machen.

Hier passiert das, was ein Bewaesserungsbaustein nicht kann: aus dem
Bodenwasserdefizit, der Vorhersage und den Grenzen der Anlage eine Anweisung
ableiten, die heute Nacht wirklich ausfuehrbar ist.

Drei Gedanken bestimmen den Entwurf:

1. **Vorausschauend heisst: den Regen von morgen abziehen, bevor gegossen
   wird.** Wer heute 12 mm gibt und morgen fallen 15 mm, hat 12 mm in den
   Untergrund geschickt. Deshalb wird der erwartete Niederschlag der
   Vorschautage vom Bedarf abgezogen - allerdings nur zu einem Anteil, denn
   eine Vorhersage ist keine Zusage.

2. **Die Anlage ist die Grenze, nicht der Bedarf.** Ein Brunnen mit
   Erholungspause kann eine Trockenperiode nicht aufholen. Der Plan sagt
   deshalb, was in dieser Nacht moeglich ist - und benennt es, wenn das
   weniger ist als noetig, statt eine Zahl auszugeben, die niemand liefern
   kann.

3. **Nicht giessen ist auch ein Ergebnis.** Solange das Defizit unter der
   leicht verfuegbaren Menge (RAW) liegt, hat die Pflanze keinen Stress. Dann
   lautet die Antwort null Durchlaeufe - und der Grund steht dabei.
"""

from __future__ import annotations

import math
from typing import Any

import fao56


# --------------------------------------------------------------------------
# Eine Zone rechnen
# --------------------------------------------------------------------------

def zone_rechnen(zone: dict, verlauf: list[dict], vorschau: list[dict],
                 cfg: dict) -> dict:
    """Wasserhaushalt einer Zone fortschreiben und den Bedarf bestimmen.

    'verlauf'  Tage der Vergangenheit, je dict mit et0, regen, [bewaesserung]
    'vorschau' kommende Tage, je dict mit et0, regen, [regen_wahrsch]
    """
    kc = float(zone.get("kc") or 1.0)
    zr = float(zone.get("zr") or 0.5)
    p_tab = float(zone.get("p") or 0.4)
    fc = float(zone.get("theta_fc") or 0.25)
    wp = float(zone.get("theta_wp") or 0.12)
    abfluss = float(zone.get("abfluss") or 0.0)

    taw_mm = fao56.taw(fc, wp, zr)
    if taw_mm <= 0:
        return {"ok": 0, "grund": "boden_unmoeglich",
                "meldung": "Feldkapazitaet und Welkepunkt ergeben keinen "
                           "nutzbaren Wasserspeicher. Bitte im Reiter Zonen pruefen."}

    # --- Vergangenheit fortschreiben ---
    dr = float(zone.get("dr") or 0.0)
    dr = max(0.0, min(taw_mm, dr))
    etc_letzter = 0.0
    for tag in verlauf:
        et0 = max(0.0, float(tag.get("et0") or 0.0))
        etc_moeglich = kc * et0
        # Trockenstress bremst die Verdunstung [FAO-56, Gl. 84]. Ohne das
        # waere der Bedarf in einer laengeren Trockenheit zu hoch gerechnet.
        p = fao56.p_angepasst(p_tab, etc_moeglich)
        raw_mm = fao56.raw(taw_mm, p)
        etc = etc_moeglich * fao56.ks(dr, taw_mm, raw_mm)
        b = fao56.wasserbilanz(dr, float(tag.get("regen") or 0.0),
                               float(tag.get("bewaesserung") or 0.0),
                               etc, taw_mm, abfluss)
        dr = b["dr"]
        etc_letzter = etc

    # --- Sensor: den gerechneten Stand nachziehen ---
    sensor = zone.get("bodenfeuchte")
    sensor_hinweis = ""
    dr_gerechnet = dr
    if sensor is not None:
        theta = float(sensor)
        # Manche Sensoren melden Prozent statt m3/m3.
        if theta > 1.0:
            theta = theta / 100.0
        dr_gemessen = fao56.dr_aus_bodenfeuchte(theta, fc, zr)
        gewicht = max(0.0, min(1.0, float(zone.get("sensor_gewicht") or 0.5)))
        dr = (1.0 - gewicht) * dr_gerechnet + gewicht * dr_gemessen
        abweichung = dr_gemessen - dr_gerechnet
        if abs(abweichung) > 0.35 * taw_mm:
            # Grosse Abweichung heisst fast immer: der Sensor steckt woanders,
            # als die Bilanz annimmt, oder er ist falsch kalibriert.
            sensor_hinweis = ("Sensor und Rechnung liegen %.0f mm auseinander. "
                              "Meist steckt der Sensor in einer anderen Tiefe "
                              "oder Bodenart als angenommen." % abweichung)

    dr = max(0.0, min(taw_mm, dr))

    # --- Wo stehen wir? ---
    p_jetzt = fao56.p_angepasst(p_tab, etc_letzter or kc * 3.0)
    raw_mm = fao56.raw(taw_mm, p_jetzt)

    # --- Vorschau: was kommt an Verdunstung und Regen? ---
    tage = max(1, min(7, int(cfg.get("vorschautage") or 2)))
    anteil = max(0.0, min(1.0, float(cfg.get("regen_anteil") or 0.7)))
    et0_kommend = 0.0
    regen_kommend = 0.0
    for tag in vorschau[:tage]:
        et0_kommend += max(0.0, float(tag.get("et0") or 0.0))
        r = max(0.0, float(tag.get("regen") or 0.0))
        w = tag.get("regen_wahrsch")
        if w is not None:
            # Eine Vorhersage ist keine Zusage: die Menge wird mit der
            # Wahrscheinlichkeit gewichtet, bevor sie angerechnet wird.
            r = r * max(0.0, min(1.0, float(w) / 100.0))
        regen_kommend += r
    etc_kommend = kc * et0_kommend
    regen_angerechnet = regen_kommend * anteil

    # --- Bedarf ---
    # Auffuellen bis Feldkapazitaet waere Verschwendung: der naechste Regen
    # liefe dann ab. Ziel ist deshalb, das Defizit unter RAW zu bringen und
    # den Bedarf der Vorschautage zu decken.
    bedarf = dr + etc_kommend - regen_angerechnet - raw_mm
    bedarf_mm = max(0.0, bedarf)

    # Nie mehr geben, als der Boden halten kann.
    if bedarf_mm > dr:
        bedarf_mm = dr

    noetig = dr >= raw_mm or bedarf_mm > 0.5

    return {
        "ok": 1,
        "taw": taw_mm, "raw": raw_mm, "p": p_jetzt,
        "dr": dr, "dr_gerechnet": dr_gerechnet,
        "fuellstand": max(0.0, min(100.0, 100.0 * (1.0 - dr / taw_mm))),
        "etc_kommend": etc_kommend, "regen_kommend": regen_kommend,
        "regen_angerechnet": regen_angerechnet,
        "bedarf_mm": bedarf_mm,
        "noetig": 1 if noetig else 0,
        "sensor_benutzt": 1 if sensor is not None else 0,
        "sensor_hinweis": sensor_hinweis,
    }


# --------------------------------------------------------------------------
# Aus Millimetern eine Anweisung
# --------------------------------------------------------------------------

def mm_zu_litern(mm: float, flaeche_m2: float) -> float:
    """1 mm = 1 Liter je Quadratmeter. Mehr ist es nicht."""
    return mm * max(0.0, flaeche_m2)


def mm_zu_minuten(mm: float, rate_mmh: float, wirkungsgrad: float = 0.75) -> float:
    """Minuten, die der Regner fuer diese Millimeter braucht.

    Der Wirkungsgrad faengt auf, was nie im Boden ankommt: Verwehung,
    Verdunstung im Flug, Ueberlappung. FAO-56 nennt fuer Sprinkleranlagen
    Werte um 0,7 bis 0,8; ab Werk 0,75. Wer nachts giesst, liegt eher am
    oberen Ende - deshalb ist es einstellbar.
    """
    if rate_mmh <= 0 or wirkungsgrad <= 0:
        return 0.0
    return (mm / (rate_mmh * wirkungsgrad)) * 60.0


def plan_bauen(zonen: list[dict], ergebnisse: dict, cfg: dict) -> dict:
    """Den Nachtplan bauen - unter den Grenzen der Anlage.

    Grenzen, die beachtet werden:
      zonendauer_s     wie lange eine Zone je Durchlauf laeuft
      pause_min        Erholung zwischen zwei Durchlaeufen (Brunnen!)
      fenster_von/bis  wann ueberhaupt gegossen werden darf
      max_durchlaeufe  harte Obergrenze
    """
    dauer_s = max(30, int(cfg.get("zonendauer_s") or 240))
    pause_min = max(0, int(cfg.get("pause_min") or 45))
    von = str(cfg.get("fenster_von") or "22:00")
    bis = str(cfg.get("fenster_bis") or "08:00")
    grenze = max(1, min(24, int(cfg.get("max_durchlaeufe") or 8)))
    wirkungsgrad = max(0.3, min(1.0, float(cfg.get("wirkungsgrad") or 0.75)))

    # Wie lange steht das Fenster offen?
    fenster_min = _fenster_minuten(von, bis)

    # Wie lange dauert ein Durchlauf? Nur Zonen, die im Zyklus mitlaufen.
    im_zyklus = [z for z in zonen if int(z.get("im_zyklus") or 0)
                 and ergebnisse.get(z["schluessel"], {}).get("ok")]
    lauf_min = len(im_zyklus) * dauer_s / 60.0
    takt_min = lauf_min + pause_min

    moeglich = grenze
    if takt_min > 0:
        # Der letzte Durchlauf muss noch ins Fenster passen, die Pause danach
        # nicht mehr.
        moeglich = int((fenster_min + pause_min) // takt_min) if takt_min > 0 else 0
        moeglich = max(0, min(grenze, moeglich))

    # Wie viele Durchlaeufe braucht die duerstigste Zone?
    noetig = 0
    je_zone = {}
    for z in im_zyklus:
        s = z["schluessel"]
        e = ergebnisse[s]
        rate = float(z.get("rate_mmh") or 0.0)
        mm_je_durchlauf = rate * wirkungsgrad * (dauer_s / 3600.0) if rate > 0 else 0.0
        n = 0
        if e["bedarf_mm"] > 0 and mm_je_durchlauf > 0:
            n = int(math.ceil(e["bedarf_mm"] / mm_je_durchlauf))
        je_zone[s] = {"mm_je_durchlauf": mm_je_durchlauf, "noetig": n}
        noetig = max(noetig, n)

    durchlaeufe = min(noetig, moeglich)
    reicht = 1 if durchlaeufe >= noetig else 0

    grund = ""
    if noetig == 0:
        grund = "kein_bedarf"
    elif moeglich == 0:
        grund = "fenster_zu_kurz"
    elif not reicht:
        grund = "anlage_am_limit"

    return {
        "durchlaeufe": durchlaeufe,
        "noetige_durchlaeufe": noetig,
        "moegliche_durchlaeufe": moeglich,
        "reicht": reicht,
        "grund": grund,
        "fenster_minuten": fenster_min,
        "durchlauf_minuten": lauf_min,
        "takt_minuten": takt_min,
        "wasserzeit_minuten": durchlaeufe * lauf_min,
        "je_zone": je_zone,
        "zonen_im_zyklus": len(im_zyklus),
    }


def _fenster_minuten(von: str, bis: str) -> float:
    """Laenge des Zeitfensters in Minuten, auch ueber Mitternacht."""
    def m(s):
        try:
            h, mi = s.split(":")
            return int(h) * 60 + int(mi)
        except (ValueError, AttributeError):
            return 0
    a, b = m(von), m(bis)
    return float(b - a if b > a else 24 * 60 - a + b)


# --------------------------------------------------------------------------
# Selbstpruefung
# --------------------------------------------------------------------------

def selbstpruefung() -> list[tuple[bool, str]]:
    e: list[tuple[bool, str]] = []

    def p(name, ist, soll, tol=0.01):
        e.append((abs(ist - soll) <= tol,
                  "%-52s ist %8.2f  soll %8.2f" % (name, ist, soll)))

    zone = {"schluessel": "rasen", "kc": 0.95, "zr": 0.75, "p": 0.40,
            "theta_fc": 0.27, "theta_wp": 0.13, "flaeche": 200.0,
            "rate_mmh": 10.0, "im_zyklus": 1, "dr": 0.0}
    cfg = {"vorschautage": 2, "regen_anteil": 0.7, "zonendauer_s": 240,
           "pause_min": 45, "fenster_von": "22:00", "fenster_bis": "08:00",
           "max_durchlaeufe": 8, "wirkungsgrad": 0.75}

    # TAW = 1000*(0,27-0,13)*0,75 = 105 mm
    r = zone_rechnen(zone, [], [], cfg)
    p("TAW aus Lehm und 0,75 m Wurzeltiefe", r["taw"], 105.0)

    # Sieben trockene Tage mit ET0 = 5 -> ETc = 4,75/Tag, gebremst durch Ks
    verlauf = [{"et0": 5.0, "regen": 0.0} for _ in range(7)]
    r = zone_rechnen(zone, verlauf, [], cfg)
    e.append((r["dr"] > 25.0 and r["dr"] < 34.0,
              "7 Tage trocken: Defizit %.1f mm (erwartet 25-34)" % r["dr"]))
    e.append((r["fuellstand"] < 100.0, "Fuellstand faellt: %.0f %%" % r["fuellstand"]))

    # Regen fuellt auf, Ueberschuss versickert
    r = zone_rechnen(zone, verlauf + [{"et0": 1.0, "regen": 60.0}], [], cfg)
    p("Starkregen setzt das Defizit auf 0", r["dr"], 0.0, 0.001)

    # Kein Bedarf, solange Dr unter RAW liegt
    r = zone_rechnen(dict(zone, dr=5.0), [], [{"et0": 2.0, "regen": 0.0}], cfg)
    e.append((r["noetig"] == 0 and r["bedarf_mm"] == 0.0,
              "Unter RAW: kein Bedarf (Dr %.1f, RAW %.1f)" % (r["dr"], r["raw"])))

    # Regen in der Vorschau senkt den Bedarf
    # Dr muss ueber RAW liegen, sonst gibt es zu Recht gar keinen Bedarf.
    trocken = zone_rechnen(dict(zone, dr=70.0), [],
                           [{"et0": 5.0, "regen": 0.0}, {"et0": 5.0, "regen": 0.0}], cfg)
    nass = zone_rechnen(dict(zone, dr=70.0), [],
                        [{"et0": 5.0, "regen": 15.0}, {"et0": 5.0, "regen": 0.0}], cfg)
    e.append((nass["bedarf_mm"] < trocken["bedarf_mm"],
              "Regenvorhersage senkt den Bedarf: %.1f statt %.1f mm"
              % (nass["bedarf_mm"], trocken["bedarf_mm"])))

    # Regenwahrscheinlichkeit wird gewichtet
    sicher = zone_rechnen(dict(zone, dr=70.0), [], [{"et0": 5.0, "regen": 10.0, "regen_wahrsch": 100}], cfg)
    unsicher = zone_rechnen(dict(zone, dr=70.0), [], [{"et0": 5.0, "regen": 10.0, "regen_wahrsch": 30}], cfg)
    e.append((unsicher["bedarf_mm"] > sicher["bedarf_mm"],
              "Unsicherer Regen wird weniger angerechnet: %.1f statt %.1f mm"
              % (unsicher["bedarf_mm"], sicher["bedarf_mm"])))

    # Sensor zieht den Stand nach
    ohne = zone_rechnen(dict(zone, dr=40.0), [], [], cfg)
    mit = zone_rechnen(dict(zone, dr=40.0, bodenfeuchte=0.27, sensor_gewicht=1.0), [], [], cfg)
    p("Sensor auf Feldkapazitaet setzt das Defizit auf 0", mit["dr"], 0.0, 0.001)
    e.append((ohne["dr"] == 40.0, "Ohne Sensor bleibt der gerechnete Stand"))
    halb = zone_rechnen(dict(zone, dr=40.0, bodenfeuchte=0.27, sensor_gewicht=0.5), [], [], cfg)
    p("Halbes Gewicht mittelt", halb["dr"], 20.0, 0.001)

    # Prozentangabe des Sensors wird erkannt
    proz = zone_rechnen(dict(zone, dr=40.0, bodenfeuchte=27.0, sensor_gewicht=1.0), [], [], cfg)
    p("Sensor in Prozent statt m3/m3 erkannt", proz["dr"], 0.0, 0.001)

    # Unmoeglicher Boden wird benannt, nicht gerechnet
    schlecht = zone_rechnen(dict(zone, theta_fc=0.10, theta_wp=0.20), [], [], cfg)
    e.append((schlecht["ok"] == 0 and schlecht["grund"] == "boden_unmoeglich",
              "Welkepunkt ueber Feldkapazitaet wird abgewiesen"))

    # --- Umrechnungen ---
    p("12 mm auf 200 m2 sind Liter", mm_zu_litern(12.0, 200.0), 2400.0)
    p("12 mm bei 10 mm/h und 0,75 Wirkungsgrad", mm_zu_minuten(12.0, 10.0, 0.75), 96.0)
    p("Regner mit Rate 0 ergibt 0 Minuten", mm_zu_minuten(12.0, 0.0), 0.0)

    # --- Plan ---
    zonen = [dict(zone, schluessel="z%d" % i) for i in range(1, 4)]
    erg = {}
    for z in zonen:
        erg[z["schluessel"]] = zone_rechnen(dict(z, dr=70.0), [],
                                            [{"et0": 5.0, "regen": 0.0}], cfg)
    pl = plan_bauen(zonen, erg, cfg)
    p("Fenster 22:00-08:00 sind Minuten", pl["fenster_minuten"], 600.0)
    p("Durchlauf: 3 Zonen a 240 s", pl["durchlauf_minuten"], 12.0)
    p("Takt mit 45 min Pause", pl["takt_minuten"], 57.0)
    e.append((pl["moegliche_durchlaeufe"] == 8,
              "Moegliche Durchlaeufe in 600 min bei Takt 57: %d (Grenze 8)"
              % pl["moegliche_durchlaeufe"]))
    e.append((pl["durchlaeufe"] > 0, "Bei Bedarf werden Durchlaeufe geplant: %d"
              % pl["durchlaeufe"]))

    # Kein Bedarf -> null Durchlaeufe mit Grund
    erg2 = {z["schluessel"]: zone_rechnen(dict(z, dr=2.0), [], [], cfg) for z in zonen}
    pl2 = plan_bauen(zonen, erg2, cfg)
    e.append((pl2["durchlaeufe"] == 0 and pl2["grund"] == "kein_bedarf",
              "Ohne Bedarf: 0 Durchlaeufe, Grund 'kein_bedarf'"))

    # Fenster zu kurz -> benannt
    # 20 Minuten reichen noch fuer EINEN Durchlauf von 12 Minuten.
    pl3a = plan_bauen(zonen, erg, dict(cfg, fenster_von="22:00", fenster_bis="22:20"))
    e.append((pl3a["moegliche_durchlaeufe"] == 1,
              "20-Minuten-Fenster laesst genau einen Durchlauf zu: %d"
              % pl3a["moegliche_durchlaeufe"]))
    # Kuerzer als ein Durchlauf: gar nichts geht, und das wird benannt.
    pl3 = plan_bauen(zonen, erg, dict(cfg, fenster_von="22:00", fenster_bis="22:05"))
    e.append((pl3["moegliche_durchlaeufe"] == 0 and pl3["grund"] == "fenster_zu_kurz",
              "5-Minuten-Fenster: 0 moeglich, Grund 'fenster_zu_kurz'"))

    # Was eine Nacht ueberhaupt liefern kann - die wichtigste Zahl der Anlage.
    mm_nacht = pl["moegliche_durchlaeufe"] * (
        float(zone["rate_mmh"]) * 0.75 * (cfg["zonendauer_s"] / 3600.0))
    e.append((2.0 < mm_nacht < 6.0,
              "Hoechstleistung der Anlage: %.1f mm je Nacht (8 Durchlaeufe a 4 min "
              "bei 10 mm/h) - ein heisser Sommertag verdunstet 4 bis 5 mm" % mm_nacht))

    # Anlage am Limit -> benannt, nicht beschoenigt
    erg4 = {z["schluessel"]: zone_rechnen(dict(z, dr=100.0), [],
            [{"et0": 6.0, "regen": 0.0}, {"et0": 6.0, "regen": 0.0}], cfg) for z in zonen}
    pl4 = plan_bauen(zonen, erg4, dict(cfg, max_durchlaeufe=2))
    e.append((pl4["reicht"] == 0 and pl4["grund"] == "anlage_am_limit",
              "Grosser Bedarf, harte Grenze: 'anlage_am_limit' statt Schoenrechnen "
              "(noetig %d, moeglich %d)" % (pl4["noetige_durchlaeufe"],
                                            pl4["moegliche_durchlaeufe"])))
    return e


if __name__ == "__main__":
    fehlt = 0
    for ok, text in selbstpruefung():
        print(("[OK]   " if ok else "[FEHL] ") + text)
        fehlt += 0 if ok else 1
    raise SystemExit(1 if fehlt else 0)
