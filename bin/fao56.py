#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Der Rechenkern: Verdunstung und Bodenwasserhaushalt nach FAO-56.

Alles hier folgt dem Standardwerk:

  [F] Allen, Pereira, Raes, Smith: "Crop evapotranspiration - Guidelines for
      computing crop water requirements", FAO Irrigation and Drainage Paper 56.
      Die Gleichungsnummern in den Kommentaren sind die des Papiers.

Es wird nichts geraten. Jede Konstante steht mit ihrer Gleichungsnummer dabei,
und die Selbstpruefung am Ende rechnet **Beispiel 18 aus [F], Kapitel 4**
nach - ein vollstaendig durchgerechneter Tag in Uccle (Bruessel) mit dem
veroeffentlichten Ergebnis 3,88 mm/Tag. Weicht der Quelltext davon ab, ist der
Quelltext falsch, nicht das Beispiel.

Warum das so wichtig ist: eine Verdunstungsformel liefert immer eine Zahl.
Ob es die richtige ist, sieht man ihr nicht an.

Zwei Wege zur Strahlung, je nachdem, was die Wetterstation kann:

  gemessen   Viele Stationen (Ecowitt WS90, Davis, WeatherFlow, ...) liefern
             die Globalstrahlung in W/m2. Das ist der genauere Weg:
             Rs [MJ m-2 d-1] = Mittelwert [W/m2] * 0,0864
  gerechnet  Ohne Strahlungsmesser aus der Sonnenscheindauer [F, Gl. 35] oder,
             wenn auch die fehlt, aus der Temperaturspanne [F, Gl. 50].
             Die dritte Naeherung ist deutlich unsicherer und wird im Ergebnis
             ausdruecklich als solche gekennzeichnet.
"""

from __future__ import annotations

import math
from typing import Any

# --- Konstanten aus [F] ---------------------------------------------------
GSC = 0.0820          # Solarkonstante [MJ m-2 min-1], [F, Gl. 21]
SIGMA = 4.903e-9      # Stefan-Boltzmann [MJ K-4 m-2 d-1], [F, Gl. 39]
ALBEDO = 0.23         # Albedo der Grasreferenz, [F, Gl. 38]
AS_ANGSTROM = 0.25    # [F, Gl. 35]
BS_ANGSTROM = 0.50    # [F, Gl. 35]


# --------------------------------------------------------------------------
# Einzelne Groessen
# --------------------------------------------------------------------------

def luftdruck(hoehe_m: float) -> float:
    """P [kPa] aus der Hoehe ueber dem Meer. [F, Gl. 7]"""
    return 101.3 * ((293.0 - 0.0065 * hoehe_m) / 293.0) ** 5.26


def psychrometerkonstante(p_kpa: float) -> float:
    """gamma [kPa/C]. [F, Gl. 8]"""
    return 0.000665 * p_kpa


def saettigungsdampfdruck(t_c: float) -> float:
    """e0(T) [kPa]. [F, Gl. 11]"""
    return 0.6108 * math.exp(17.27 * t_c / (t_c + 237.3))


def steigung_dampfdruckkurve(t_c: float) -> float:
    """Delta [kPa/C]. [F, Gl. 13]"""
    return 4098.0 * saettigungsdampfdruck(t_c) / ((t_c + 237.3) ** 2)


def dampfdruck_ist(tmin: float, tmax: float, rh_min: float | None,
                   rh_max: float | None, rh_mittel: float | None = None,
                   taupunkt: float | None = None) -> tuple[float, str]:
    """ea [kPa] - der beste verfuegbare Weg, und welcher es war.

    Reihenfolge nach [F], Kapitel 3: Taupunkt ist am genauesten, dann
    RHmax/RHmin [Gl. 17], dann RHmax allein [Gl. 18], dann RHmittel [Gl. 19].
    """
    if taupunkt is not None:
        return saettigungsdampfdruck(taupunkt), "taupunkt"
    e_tmin = saettigungsdampfdruck(tmin)
    e_tmax = saettigungsdampfdruck(tmax)
    if rh_max is not None and rh_min is not None:
        return (e_tmin * rh_max / 100.0 + e_tmax * rh_min / 100.0) / 2.0, "rh_max_min"
    if rh_max is not None:
        return e_tmin * rh_max / 100.0, "rh_max"
    if rh_mittel is not None:
        return rh_mittel / 100.0 * (e_tmax + e_tmin) / 2.0, "rh_mittel"
    raise ValueError("Ohne Luftfeuchte oder Taupunkt laesst sich ea nicht bestimmen.")


def wind_auf_2m(u_z: float, hoehe_m: float) -> float:
    """Windgeschwindigkeit auf 2 m umrechnen. [F, Gl. 47]

    Wird oft vergessen: die meisten Wetterstationen messen in 2 m, viele
    Fertigmasten aber in 10 m. Der Unterschied betraegt rund 25 Prozent.
    """
    if abs(hoehe_m - 2.0) < 1e-9:
        return u_z
    return u_z * 4.87 / math.log(67.8 * hoehe_m - 5.42)


def tagesnummer(monat: int, tag: int, jahr: int = 2001) -> int:
    """J, der laufende Tag im Jahr. [F, Gl. 24 benutzt ihn]

    Das Jahr gehoert uebergeben. Ohne Angabe wird 2001 genommen - ein Jahr
    ohne Schalttag, damit das Rechenbeispiel aus [F] reproduzierbar bleibt.

    Warum das nicht gleichgueltig ist: in einem Schaltjahr liegt jeder Tag ab
    dem 1. Maerz um eine Nummer hoeher. Rechnet man mit dem Kalender von 2001
    weiter, ist J um einen Tag zu klein, und Ra weicht dadurch um bis zu
    1,6 Prozent ab. Das ist kein Absturz und faellt niemandem auf - genau
    deshalb steht es hier.

    NICHT geaendert wurde der Teiler 365 in Gleichung 24. [F] definiert ihn
    so, fuer jedes Jahr. Ihn in Schaltjahren auf 366 zu setzen waere eine
    Abweichung vom Standardwerk und wuerde das nachgerechnete Beispiel 18
    verfehlen - der Fehler waere dann groesser, nicht kleiner.
    """
    import datetime
    return datetime.date(int(jahr), int(monat), int(tag)).timetuple().tm_yday


def extraterrestrische_strahlung(breite_grad: float, j: int) -> tuple[float, float]:
    """Ra [MJ m-2 d-1] und die astronomische Tageslaenge N [h].

    [F, Gl. 21] mit dr [Gl. 23], delta [Gl. 24], omega_s [Gl. 25], N [Gl. 34].
    """
    phi = math.radians(breite_grad)
    dr = 1.0 + 0.033 * math.cos(2.0 * math.pi * j / 365.0)
    delta = 0.409 * math.sin(2.0 * math.pi * j / 365.0 - 1.39)
    # Am Polarkreis kann das Argument den Bereich verlassen - dann geht die
    # Sonne gar nicht bzw. nicht unter. Abschneiden statt abstuerzen.
    x = -math.tan(phi) * math.tan(delta)
    x = max(-1.0, min(1.0, x))
    omega_s = math.acos(x)
    ra = (24.0 * 60.0 / math.pi) * GSC * dr * (
        omega_s * math.sin(phi) * math.sin(delta)
        + math.cos(phi) * math.cos(delta) * math.sin(omega_s))
    n = 24.0 / math.pi * omega_s
    return ra, n


def strahlung_aus_sonnenschein(n_stunden: float, n_moeglich: float, ra: float) -> float:
    """Rs [MJ m-2 d-1] aus der Sonnenscheindauer. [F, Gl. 35]"""
    if n_moeglich <= 0:
        return 0.0
    return (AS_ANGSTROM + BS_ANGSTROM * (n_stunden / n_moeglich)) * ra


def strahlung_aus_temperaturspanne(tmax: float, tmin: float, ra: float,
                                   kuestennah: bool = False) -> float:
    """Rs aus der Temperaturspanne - die Notloesung. [F, Gl. 50]

    krs = 0,16 im Binnenland, 0,19 an der Kueste. Diese Naeherung liegt
    regelmaessig um mehrere Zehntel mm/Tag daneben. Sie wird deshalb im
    Ergebnis gekennzeichnet, damit niemand sie fuer eine Messung haelt.
    """
    krs = 0.19 if kuestennah else 0.16
    return krs * math.sqrt(max(0.0, tmax - tmin)) * ra


def strahlung_wolkenlos(ra: float, hoehe_m: float) -> float:
    """Rso [MJ m-2 d-1]. [F, Gl. 37]"""
    return (0.75 + 2e-5 * hoehe_m) * ra


def nettostrahlung(rs: float, rso: float, tmax: float, tmin: float,
                   ea: float) -> float:
    """Rn [MJ m-2 d-1] = Rns - Rnl. [F, Gl. 38, 39, 40]"""
    rns = (1.0 - ALBEDO) * rs
    tmax_k = tmax + 273.16
    tmin_k = tmin + 273.16
    verhaeltnis = rs / rso if rso > 0 else 0.0
    # [F] begrenzt Rs/Rso auf hoechstens 1,0 - Messfehler koennen es
    # ueberschreiten, physikalisch geht das nicht.
    verhaeltnis = max(0.0, min(1.0, verhaeltnis))
    rnl = (SIGMA * ((tmax_k ** 4 + tmin_k ** 4) / 2.0)
           * (0.34 - 0.14 * math.sqrt(max(0.0, ea)))
           * (1.35 * verhaeltnis - 0.35))
    return rns - rnl


def et0_tag(tmin: float, tmax: float, ea: float, u2: float, rn: float,
            hoehe_m: float, g: float = 0.0) -> float:
    """ET0 [mm/Tag] nach FAO Penman-Monteith. [F, Gl. 6]

    G, der Bodenwaermestrom, ist im Tagesschritt vernachlaessigbar
    [F, Gl. 42] und deshalb ab Werk 0.
    """
    tmean = (tmax + tmin) / 2.0
    delta = steigung_dampfdruckkurve(tmean)
    gamma = psychrometerkonstante(luftdruck(hoehe_m))
    es = (saettigungsdampfdruck(tmax) + saettigungsdampfdruck(tmin)) / 2.0
    defizit = max(0.0, es - ea)
    zaehler = (0.408 * delta * (rn - g)
               + gamma * (900.0 / (tmean + 273.0)) * u2 * defizit)
    nenner = delta + gamma * (1.0 + 0.34 * u2)
    return zaehler / nenner


# --------------------------------------------------------------------------
# Ein ganzer Tag am Stueck
# --------------------------------------------------------------------------

def et0_aus_messwerten(m: dict) -> dict:
    """ET0 aus allem, was die Wetterstation hergibt.

    Erwartet in 'm' (fehlende Werte einfach weglassen):
        tmin, tmax        [C]        Pflicht
        rh_min, rh_max    [%]        oder rh_mittel oder taupunkt
        wind              [m/s]      auf 'wind_hoehe' Metern gemessen
        wind_hoehe        [m]        Vorgabe 2
        strahlung_wm2     [W/m2]     Tagesmittel der Globalstrahlung
        sonnenstunden     [h]
        breite, laenge    [Grad]     Pflicht
        hoehe             [m]        Vorgabe 0
        monat, tag                   Pflicht
        jahr                         empfohlen (Schaltjahr, siehe tagesnummer)

    Rueckgabe: dict mit et0, allen Zwischenwerten und - wichtig - 'guete':
    'gemessen', 'sonnenschein' oder 'geschaetzt'. Die Guete wandert bis in die
    Oberflaeche durch, damit niemand eine Schaetzung fuer eine Messung haelt.
    """
    tmin = float(m["tmin"])
    tmax = float(m["tmax"])
    if tmax < tmin:
        tmin, tmax = tmax, tmin
    hoehe = float(m.get("hoehe") or 0.0)
    breite = float(m["breite"])
    # Das Jahr wird durchgereicht, wenn es dasteht. Ohne Angabe gilt 2001 -
    # in einem Schaltjahr waere J dann ab dem 1. Maerz um eins zu klein.
    j = tagesnummer(int(m["monat"]), int(m["tag"]), int(m.get("jahr") or 2001))

    ea, ea_weg = dampfdruck_ist(
        tmin, tmax,
        _f(m.get("rh_min")), _f(m.get("rh_max")),
        _f(m.get("rh_mittel")), _f(m.get("taupunkt")))

    u2 = wind_auf_2m(float(m.get("wind") or 2.0), float(m.get("wind_hoehe") or 2.0))
    # [F], Kapitel 3: fehlt der Wind ganz, ist 2 m/s ein brauchbarer Ersatz.
    # Das ist eine Annahme und wird als solche gemeldet.
    wind_geschaetzt = m.get("wind") is None

    ra, n_moeglich = extraterrestrische_strahlung(breite, j)
    if m.get("strahlung_wm2") is not None:
        # 1 W/m2 ueber 24 h = 0,0864 MJ/m2 (86400 s * 1e-6)
        rs = float(m["strahlung_wm2"]) * 0.0864
        guete = "gemessen"
    elif m.get("sonnenstunden") is not None:
        rs = strahlung_aus_sonnenschein(float(m["sonnenstunden"]), n_moeglich, ra)
        guete = "sonnenschein"
    else:
        rs = strahlung_aus_temperaturspanne(tmax, tmin, ra,
                                            bool(m.get("kuestennah")))
        guete = "geschaetzt"

    rso = strahlung_wolkenlos(ra, hoehe)
    rn = nettostrahlung(rs, rso, tmax, tmin, ea)
    et0 = et0_tag(tmin, tmax, ea, u2, rn, hoehe)
    return {
        "et0": max(0.0, et0), "ra": ra, "rs": rs, "rso": rso, "rn": rn,
        "ea": ea, "ea_weg": ea_weg, "u2": u2, "n_moeglich": n_moeglich,
        "guete": guete, "wind_geschaetzt": 1 if wind_geschaetzt else 0,
    }


def _f(x: Any) -> float | None:
    if x is None or x == "":
        return None
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


# --------------------------------------------------------------------------
# Boden und Pflanze
# --------------------------------------------------------------------------

def kc_klimaanpassung(kc_tabelle: float, u2: float, rh_min: float,
                      hoehe_pflanze_m: float) -> float:
    """Kc an trockene Luft und Wind anpassen. [F, Gl. 62]

        Kc = Kc_Tab + [0,04 (u2 - 2) - 0,004 (RHmin - 45)] (h/3)^0,3

    Die Tabellenwerte in [F, Tab. 12] gelten fuer ein halbfeuchtes Klima mit
    RHmin um 45 Prozent und Wind um 2 m/s. Bei trockener Luft oder viel Wind
    liegen sie zu niedrig - die Pflanze verdunstet dann mehr, als die Tabelle
    unterstellt.

    [F] begrenzt die Gleichung ausdruecklich auf
        1 m/s <= u2 <= 6 m/s  und  20 % <= RHmin <= 80 %.
    Ausserhalb wird auf den Rand gesetzt, nicht extrapoliert: die Gleichung
    ist dort nicht geeicht, und eine Zahl aus einer nicht geeichten Formel
    sieht genauso aus wie eine gemessene.

    Ohne Pflanzenhoehe gibt es keine Anpassung. Das ist Absicht und kein
    Mangel: (h/3)^0,3 ist der Hebel der ganzen Gleichung, und ihn zu raten
    hiesse, die Anpassung selbst zu raten. Wer die Hoehe nicht eintraegt,
    bekommt den Tabellenwert - also genau das, was bis 0.9.6 galt.
    """
    if hoehe_pflanze_m is None or hoehe_pflanze_m <= 0:
        return kc_tabelle
    u = max(1.0, min(6.0, float(u2)))
    r = max(20.0, min(80.0, float(rh_min)))
    h = max(0.05, min(10.0, float(hoehe_pflanze_m)))
    return kc_tabelle + (0.04 * (u - 2.0) - 0.004 * (r - 45.0)) * (h / 3.0) ** 0.3


def taw(theta_fc: float, theta_wp: float, zr_m: float) -> float:
    """Nutzbare Feldkapazitaet im Wurzelraum [mm]. [F, Gl. 82]"""
    return 1000.0 * (theta_fc - theta_wp) * zr_m


def p_angepasst(p_tabelle: float, etc_mm: float) -> float:
    """p an die Verdunstungsleistung anpassen. [F, Kapitel 8]

        p = p_Tabelle + 0,04 (5 - ETc),  begrenzt auf 0,1 <= p <= 0,8
    """
    p = p_tabelle + 0.04 * (5.0 - etc_mm)
    return max(0.1, min(0.8, p))


def raw(taw_mm: float, p: float) -> float:
    """Leicht verfuegbares Bodenwasser [mm]. [F, Gl. 83]"""
    return p * taw_mm


def ks(dr_mm: float, taw_mm: float, raw_mm: float) -> float:
    """Trockenstress-Beiwert. [F, Gl. 84]

    Solange Dr <= RAW ist, gibt es keinen Stress (Ks = 1). Danach faellt die
    tatsaechliche Verdunstung linear ab - die Pflanze verdunstet weniger, als
    das Wetter hergaebe. Wer das weglaesst, ueberschaetzt den Wasserbedarf in
    einer Trockenperiode systematisch.
    """
    if dr_mm <= raw_mm:
        return 1.0
    nenner = taw_mm - raw_mm
    if nenner <= 0:
        return 0.0
    return max(0.0, (taw_mm - dr_mm) / nenner)


def wasserbilanz(dr_vorher: float, niederschlag: float, bewaesserung: float,
                 etc: float, taw_mm: float,
                 abfluss_anteil: float = 0.0) -> dict:
    """Ein Tag Bodenwasserbilanz. [F, Gl. 85 und 86]

        Dr,i = Dr,i-1 - (P - RO) - I - CR + ETc + DP,   0 <= Dr <= TAW

    CR (kapillarer Aufstieg) wird zu 0 gesetzt: er spielt nur bei hohem
    Grundwasserstand eine Rolle, und den kennt hier niemand.

    DP (Tiefensickerung) ergibt sich von selbst: alles, was Dr unter Null
    druecken wuerde, ist versickert und damit verloren. Genau das ist der
    Grund, warum ein Starkregen nicht 'auf Vorrat' zaehlt.
    """
    ro = max(0.0, niederschlag * max(0.0, min(1.0, abfluss_anteil)))
    wirksam = max(0.0, niederschlag - ro)
    roh = dr_vorher - wirksam - bewaesserung + etc
    versickert = max(0.0, -roh)          # was unter Null faellt, ist weg
    dr = max(0.0, min(taw_mm, roh))
    return {"dr": dr, "versickert": versickert, "abfluss": ro,
            "wirksamer_niederschlag": wirksam}


def dr_aus_bodenfeuchte(theta: float, theta_fc: float, zr_m: float) -> float:
    """Das Defizit aus einer gemessenen Bodenfeuchte. [F, Gl. 87]

        Dr = 1000 (theta_FC - theta) Zr

    Damit laesst sich der gerechnete Stand an einem echten Messwert
    nachziehen. Der Rechenweg haelt den Haushalt, der Sensor korrigiert ihn -
    nicht umgekehrt: ein einzelner Sensor misst einen Punkt, die Bilanz gilt
    fuer die Flaeche.
    """
    return max(0.0, 1000.0 * (theta_fc - theta) * zr_m)


# --------------------------------------------------------------------------
# Selbstpruefung gegen das veroeffentlichte Rechenbeispiel
# --------------------------------------------------------------------------

def selbstpruefung() -> list[tuple[bool, str]]:
    """Rechnet Beispiel 18 aus [F], Kapitel 4, Schritt fuer Schritt nach.

    Uccle (Bruessel), 6. Juli, 50 Grad 48 Minuten Nord, 100 m ue. NN.
    Jeder Zwischenwert steht im Papier - deshalb wird jeder einzeln geprueft
    und nicht nur das Ergebnis. Ein richtiges Endergebnis aus zwei sich
    aufhebenden Fehlern waere sonst nicht zu erkennen.
    """
    e: list[tuple[bool, str]] = []

    def pruefe(name, ist, soll, tol):
        ok = abs(ist - soll) <= tol
        e.append((ok, "%-46s ist %8.3f   soll %8.3f  (+-%.3f)"
                  % (name, ist, soll, tol)))

    tmax, tmin = 21.5, 12.3
    rh_max, rh_min = 84.0, 63.0
    hoehe = 100.0
    breite = 50 + 48 / 60.0          # 50 Grad 48 Minuten = 50,80
    j = tagesnummer(7, 6)
    pruefe("Tagesnummer J (6. Juli)", j, 187, 0)

    u2 = wind_auf_2m(2.78, 10.0)
    pruefe("u2 aus 2,78 m/s in 10 m [Gl. 47]", u2, 2.078, 0.01)

    p = luftdruck(hoehe)
    pruefe("Luftdruck P [Gl. 7]", p, 100.1, 0.1)

    tmean = (tmax + tmin) / 2.0
    pruefe("Tmittel", tmean, 16.9, 0.05)

    d = steigung_dampfdruckkurve(tmean)
    pruefe("Delta [Gl. 13]", d, 0.122, 0.001)

    g = psychrometerkonstante(p)
    pruefe("gamma [Gl. 8]", g, 0.0666, 0.0002)

    pruefe("e0(Tmax) [Gl. 11]", saettigungsdampfdruck(tmax), 2.564, 0.002)
    pruefe("e0(Tmin) [Gl. 11]", saettigungsdampfdruck(tmin), 1.431, 0.002)

    es = (saettigungsdampfdruck(tmax) + saettigungsdampfdruck(tmin)) / 2.0
    pruefe("es", es, 1.997, 0.002)

    ea, weg = dampfdruck_ist(tmin, tmax, rh_min, rh_max)
    pruefe("ea aus RHmax und RHmin [Gl. 17]", ea, 1.409, 0.002)
    e.append((weg == "rh_max_min", "ea ueber den Weg 'rh_max_min' bestimmt"))
    pruefe("Saettigungsdefizit es - ea", es - ea, 0.589, 0.003)

    ra, n_moeglich = extraterrestrische_strahlung(breite, j)
    pruefe("Ra [Gl. 21]", ra, 41.09, 0.05)
    pruefe("Tageslaenge N [Gl. 34]", n_moeglich, 16.1, 0.1)

    rs = strahlung_aus_sonnenschein(9.25, n_moeglich, ra)
    pruefe("Rs aus 9,25 Sonnenstunden [Gl. 35]", rs, 22.07, 0.15)

    rso = strahlung_wolkenlos(ra, hoehe)
    pruefe("Rso [Gl. 37]", rso, 30.90, 0.05)

    rn = nettostrahlung(rs, rso, tmax, tmin, ea)
    pruefe("Rn [Gl. 40]", rn, 13.28, 0.15)

    et0 = et0_tag(tmin, tmax, ea, u2, rn, hoehe)
    pruefe("ET0 [Gl. 6]  <-- das veroeffentlichte Ergebnis", et0, 3.88, 0.05)

    # Der ganze Weg noch einmal ueber die Sammelfunktion
    erg = et0_aus_messwerten({
        "tmin": tmin, "tmax": tmax, "rh_min": rh_min, "rh_max": rh_max,
        "wind": 2.78, "wind_hoehe": 10.0, "sonnenstunden": 9.25,
        "breite": breite, "hoehe": hoehe, "monat": 7, "tag": 6})
    pruefe("ET0 ueber et0_aus_messwerten()", erg["et0"], 3.88, 0.05)
    e.append((erg["guete"] == "sonnenschein",
              "Guete richtig als 'sonnenschein' gemeldet: %s" % erg["guete"]))

    # --- Schaltjahr: der Tagesindex muss dem echten Kalender folgen ---
    import datetime as _dt
    versatz = 0
    for _m in range(1, 13):
        for _t in (1, 15, 28):
            echt = _dt.date(2024, _m, _t).timetuple().tm_yday
            if tagesnummer(_m, _t, 2024) != echt:
                versatz += 1
    e.append((versatz == 0,
              "Schaltjahr: Tagesindex folgt dem echten Kalender (36 Stichtage 2024)"))
    e.append((tagesnummer(12, 31, 2024) == 366 and tagesnummer(12, 31, 2025) == 365,
              "31.12. ergibt 366 im Schaltjahr und 365 sonst"))
    # Und der Fehler, den ein falsches Jahr anrichten wuerde - nachgemessen,
    # damit die Groessenordnung belegt ist und nicht behauptet.
    ra_richtig, _ = extraterrestrische_strahlung(48.5, tagesnummer(3, 1, 2024))
    ra_falsch, _ = extraterrestrische_strahlung(48.5, tagesnummer(3, 1, 2001))
    e.append((abs(ra_richtig - ra_falsch) > 0.01,
              "Ein Tag Versatz aendert Ra messbar: %.3f gegen %.3f MJ/m2"
              % (ra_richtig, ra_falsch)))

    # --- Klimaanpassung von Kc [F, Gl. 62] ---
    #
    # Zuerst der Fall, der jede bestehende Anlage betrifft: OHNE Angabe der
    # Pflanzenhoehe darf sich nichts aendern. Waere das nicht so, rechnete
    # jede Zone ab dieser Fassung anders, ohne dass jemand etwas eingetragen
    # haette.
    for _h in (None, 0, 0.0, -1):
        e.append((kc_klimaanpassung(0.95, 5.0, 20.0, _h) == 0.95,
                  "Ohne Pflanzenhoehe (%r) bleibt Kc unveraendert" % (_h,)))
    # Der Normfall der Tabelle (u2 = 2 m/s, RHmin = 45 %) aendert nichts.
    pruefe("Kc bei Normbedingungen 2 m/s und 45 %",
           kc_klimaanpassung(0.95, 2.0, 45.0, 0.10), 0.95, 0.0001)
    # Trockene Luft und Wind heben Kc, feuchte Luft und Windstille senken ihn.
    trocken = kc_klimaanpassung(0.95, 3.0, 25.0, 0.10)
    feucht = kc_klimaanpassung(0.95, 1.0, 75.0, 0.10)
    e.append((feucht < 0.95 < trocken,
              "Kc steigt bei trocken/windig (%.3f) und faellt bei feucht/still (%.3f)"
              % (trocken, feucht)))
    # Gegen die Gleichung von Hand nachgerechnet: h = 0,60 m, u2 = 3, RHmin = 25
    #   (0,60/3)^0,3 = 0,6170 ; 0,04*1 - 0,004*(-20) = 0,12 ; 0,12*0,6170 = 0,0740
    pruefe("Kc 1,15 -> 1,224 bei h 0,60 m, 3 m/s, RHmin 25 % [Gl. 62]",
           kc_klimaanpassung(1.15, 3.0, 25.0, 0.60), 1.224, 0.002)
    # Die Groesse haengt an der Pflanzenhoehe - ein Rasen wird weniger
    # angehoben als eine Tomate. Genau dafuer steht der Hoehenterm da.
    e.append((kc_klimaanpassung(1.0, 3.0, 25.0, 0.10)
              < kc_klimaanpassung(1.0, 3.0, 25.0, 0.60),
              "Hohe Pflanze wird staerker angepasst als niedrige"))
    # Ausserhalb des Geltungsbereichs wird auf den Rand gesetzt, nicht
    # extrapoliert - sonst entstuende aus 20 m/s Sturm ein Kc von 1,7.
    e.append((kc_klimaanpassung(1.0, 20.0, 5.0, 0.60)
              == kc_klimaanpassung(1.0, 6.0, 20.0, 0.60),
              "Ausserhalb 1-6 m/s und 20-80 % wird begrenzt, nicht extrapoliert"))

    # --- Boden: Beispiel aus [F], Kapitel 8 ---
    t = taw(0.32, 0.12, 0.8)
    pruefe("TAW = 1000(0,32-0,12)*0,8 [Gl. 82]", t, 160.0, 0.01)
    pruefe("RAW bei p = 0,6 [Gl. 83]", raw(130.0, 0.6), 78.0, 0.01)
    pruefe("p angepasst bei ETc = 5 [Kap. 8]", p_angepasst(0.4, 5.0), 0.40, 0.001)
    pruefe("p angepasst bei ETc = 2,5", p_angepasst(0.4, 2.5), 0.50, 0.001)
    pruefe("p bleibt bei 0,8 stehen", p_angepasst(0.8, 0.0), 0.8, 0.001)

    e.append((ks(50, 160, 80) == 1.0, "Ks = 1, solange Dr <= RAW [Gl. 84]"))
    pruefe("Ks bei Dr genau zwischen RAW und TAW", ks(120, 160, 80), 0.5, 0.001)
    e.append((ks(200, 160, 80) == 0.0, "Ks = 0, wenn Dr >= TAW"))

    # --- Wasserbilanz ---
    b = wasserbilanz(dr_vorher=30.0, niederschlag=0.0, bewaesserung=0.0,
                     etc=4.0, taw_mm=160.0)
    pruefe("Bilanz: trockener Tag erhoeht das Defizit", b["dr"], 34.0, 0.001)
    b = wasserbilanz(30.0, 50.0, 0.0, 4.0, 160.0)
    e.append((b["dr"] == 0.0 and abs(b["versickert"] - 16.0) < 0.001,
              "Starkregen: Defizit 0, 16 mm versickert (zaehlen NICHT als Vorrat)"))
    b = wasserbilanz(30.0, 20.0, 0.0, 4.0, 160.0, abfluss_anteil=0.25)
    pruefe("Bilanz mit 25 % Oberflaechenabfluss", b["dr"], 19.0, 0.001)
    pruefe("Defizit aus Bodenfeuchte [Gl. 87]",
           dr_aus_bodenfeuchte(0.22, 0.32, 0.8), 80.0, 0.001)

    return e


if __name__ == "__main__":
    fehlt = 0
    for ok, text in selbstpruefung():
        print(("[OK]   " if ok else "[FEHL] ") + text)
        fehlt += 0 if ok else 1
    print()
    print("Grundlage: FAO Irrigation and Drainage Paper 56, Beispiel 18 (Kapitel 4)")
    print("und die Gleichungen 82 bis 87 (Kapitel 8).")
    raise SystemExit(1 if fehlt else 0)
