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
                 cfg: dict, wetter: dict | None = None) -> dict:
    """Wasserhaushalt einer Zone fortschreiben und den Bedarf bestimmen.

    'verlauf'  Tage der Vergangenheit, je dict mit et0, regen, [bewaesserung]
    'vorschau' kommende Tage, je dict mit et0, regen, [regen_wahrsch]
    'wetter'   freiwillig: u2 und rh_min des Tages fuer die Klimaanpassung
               des Pflanzenbeiwerts [FAO-56, Gl. 62]. Fehlt es, bleibt Kc
               der Tabellenwert - also genau das, was bis 0.9.6 galt.
    """
    kc = float(zone.get("kc") or 1.0)
    # --- Klimaanpassung des Pflanzenbeiwerts (neu in 0.9.7) ---------------
    #
    # Sie greift NUR, wenn die Zone eine Pflanzenhoehe traegt UND Wind und
    # Luftfeuchte des Tages vorliegen. Beides fehlt in jeder bestehenden
    # Anlage, also aendert sich dort nichts. Das ist die Bedingung, unter
    # der eine neue Funktion ueberhaupt eingebaut werden darf.
    #
    # Warum nicht ohne Pflanzenhoehe geschaetzt wird, steht bei
    # fao56.kc_klimaanpassung: der Hoehenterm ist der Hebel der Gleichung.
    kc_tabelle = kc
    kc_klima = 0
    h_pflanze = zone.get("hoehe_pflanze")
    try:
        h_pflanze = float(h_pflanze) if h_pflanze not in (None, "") else 0.0
    except (TypeError, ValueError):
        h_pflanze = 0.0
    if h_pflanze > 0 and wetter:
        u2 = wetter.get("u2")
        rh_min = wetter.get("rh_min")
        if u2 is not None and rh_min is not None:
            kc = fao56.kc_klimaanpassung(kc, float(u2), float(rh_min), h_pflanze)
            kc_klima = 1
    zr = float(zone.get("zr") or 0.5)
    # Mikroklima-Faktor (ab 0.9.1).
    #
    # ETc = Kc * ET0 unterstellt die Bedingungen der Grasreferenz: freie
    # Fläche, freier Himmel, freier Wind. Ein Garten ist das selten. Hinter
    # der Nordwand des Hauses fehlt die halbe Einstrahlung; unter einer Hecke
    # fehlt sie fast ganz; im Kiesbeet vor einer Sued-Mauer kommt Waerme von
    # der Wand dazu.
    #
    # [F] behandelt das in Kapitel 9 als Anpassung von Kc an nicht
    # standardgemaesse Bedingungen. Hier steht es als eigener Faktor daneben,
    # damit Kc weiterhin das ist, was in der Tabelle steht - wer beides
    # vermischt, weiss spaeter nicht mehr, was er warum eingetragen hat.
    #
    # Der Bereich geht ausdruecklich auch NACH OBEN. Ein Faktor unter 1 fuer
    # Schatten ist der bekannte Fall; die Hitzeecke ist der andere und wird
    # regelmaessig vergessen. Beide Richtungen kommen vor, also lassen wir
    # beide zu - 0,3 bis 1,5.
    #
    # Vorgabe 1,0: ohne Eintrag aendert sich nichts, und keine bestehende
    # Anlage rechnet ab dieser Fassung anders.
    # Die Null gilt als "nichts eingetragen", nicht als untere Grenze.
    #
    # Ein Faktor 0 wuerde bedeuten: diese Zone verdunstet nie. Sie braeuchte
    # dann nie Wasser, und das Plugin wuerde das ohne ein Wort so melden - die
    # gefaehrlichste Art von Fehleingabe. Sie auf 0,3 hochzuziehen waere
    # genauso stillschweigend falsch. Also wird sie wie ein leeres Feld
    # behandelt, so wie es kc, zr und p in denselben Zeilen darueber auch tun
    # (dort mit 'or'). Wer wirklich 0,3 will, traegt 0,3 ein.
    mikro = zone.get("mikroklima")
    try:
        mikro = float(mikro) if mikro not in (None, "") else 0.0
    except (TypeError, ValueError):
        mikro = 0.0
    mikro = 1.0 if mikro == 0.0 else max(0.3, min(1.5, mikro))
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
        # Der Faktor greift an ETc, nicht an ET0: ET0 ist die Verdunstung der
        # Grasreferenz AM STANDORT und fuer alle Zonen dieselbe Zahl. Sie je
        # Zone zu verbiegen waere eine Falschaussage ueber das Wetter.
        etc_moeglich = kc * et0 * mikro
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
    p_jetzt = fao56.p_angepasst(p_tab, etc_letzter or kc * mikro * 3.0)
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
    etc_kommend = kc * et0_kommend * mikro
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
        "mikroklima": mikro,
        "kc": kc, "kc_tabelle": kc_tabelle, "kc_klima": kc_klima,
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
      zonendauer_s     wie lange eine Zone je Durchlauf laeuft (allgemein)
      pause_min        Erholung zwischen zwei Durchlaeufen (Brunnen!)
      fenster_von/bis  wann ueberhaupt gegossen werden darf
      max_durchlaeufe  harte Obergrenze

    Neu in 0.9.7: **je Zone eine eigene Dauer**. Bis 0.9.6 galt eine einzige
    Zonendauer fuer alle Kreise. Die mitgelieferte Regnertabelle reicht aber
    von 4 mm/h (Tropfer) bis 35 mm/h (Spruehduesen) - Faktor neun. Gemessen
    an zwei Zonen mit je 13,9 mm Bedarf und 240 s Dauer bekam der Rasen
    21,0 mm und das Tropfschlauchbeet 3,0 mm: die eine Zone 50 Prozent zu
    viel, die andere 80 Prozent zu wenig.

    Dazu wird je Zone eine **Ventilzeit** gerechnet ('sekunden_soll'): die
    Sekunden je Durchlauf, mit denen genau diese Zone nach der geplanten
    Zahl von Durchlaeufen ihren Bedarf gedeckt hat. Das ist die Zahl, die im
    Loxone-Bewaesserungsbaustein auf Tv1 bis Tv8 gehoert.

    Ohne Eintrag aendert sich nichts: fehlt 'dauer_s' an allen Zonen, kommt
    dasselbe heraus wie bis 0.9.6.
    """
    dauer_s = max(30, int(cfg.get("zonendauer_s") or 240))
    dauer_max_s = max(dauer_s, int(cfg.get("zonendauer_max_s") or 1800))
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
    dauern = {z["schluessel"]: _zonendauer(z, dauer_s) for z in im_zyklus}
    lauf_min = sum(dauern.values()) / 60.0
    takt_min = lauf_min + pause_min

    moeglich = grenze
    if takt_min > 0:
        # Der letzte Durchlauf muss noch ins Fenster passen, die Pause danach
        # nicht mehr.
        moeglich = int((fenster_min + pause_min) // takt_min) if takt_min > 0 else 0
        moeglich = max(0, min(grenze, moeglich))

    # Wie viele Durchlaeufe braucht die duerstigste Zone?
    #
    # Ohne Niederschlagsrate laesst sich das NICHT ausrechnen. Bis 0.9.0 kam
    # in diesem Fall n = 0 heraus, und weil der Plan nur die groesste Zahl
    # nimmt, endete das bei 'kein_bedarf' - also bei der Aussage, die Zone
    # brauche kein Wasser. Das ist die schlimmste Art von Fehler: eine
    # durstige Zone wird als versorgt gemeldet.
    #
    # Geraten wird trotzdem nicht. Eine erfundene Zahl waere hier genauso
    # falsch, nur unauffaelliger: aus 'ein Durchlauf' wuerden je nach Regner
    # 0,5 mm oder 8 mm. Der Plan benennt die Luecke stattdessen, und die
    # Oberflaeche zeigt, welche Zone es betrifft.
    noetig = 0
    je_zone = {}
    ohne_rate = []
    for z in im_zyklus:
        s = z["schluessel"]
        e = ergebnisse[s]
        rate = float(z.get("rate_mmh") or 0.0)
        zdauer = dauern[s]
        mm_je_durchlauf = rate * wirkungsgrad * (zdauer / 3600.0) if rate > 0 else 0.0
        n = 0
        fehlt_rate = 0
        if e["bedarf_mm"] > 0 and mm_je_durchlauf > 0:
            n = int(math.ceil(e["bedarf_mm"] / mm_je_durchlauf))
        elif e["bedarf_mm"] > 0:
            # Bedarf ja, Rate nein: das ist keine Null, sondern eine Luecke.
            fehlt_rate = 1
            ohne_rate.append(str(z.get("name") or s))
        je_zone[s] = {"mm_je_durchlauf": mm_je_durchlauf, "noetig": n,
                      "rate_fehlt": fehlt_rate, "dauer_s": zdauer,
                      "eigene_dauer": 1 if zdauer != dauer_s else 0}
        noetig = max(noetig, n)

    durchlaeufe = min(noetig, moeglich)
    reicht = 1 if durchlaeufe >= noetig else 0

    # --- Ventilzeit je Zone (neu in 0.9.7) -------------------------------
    #
    # Bis hierher steht, WIE OFT gegossen wird. Jetzt kommt, WIE LANGE je
    # Zone - das ist die Zahl fuer Tv1 bis Tv8 im Bewaesserungsbaustein.
    #
    #     sekunden_soll = Bedarf / (Durchlaeufe * Rate * Wirkungsgrad) * 3600
    #
    # Eine laengere Ventilzeit verlaengert den Durchlauf und kann ihn aus dem
    # Fenster schieben. Deshalb wird danach nachgerechnet, ob der Plan noch
    # hineinpasst, und die Zahl der Durchlaeufe notfalls gesenkt - schrittweise
    # und begrenzt, nicht in einer Schleife, die niemand ueberblickt.
    #
    # Ohne gemessene Rate gibt es keine Ventilzeit. Geraten wird nichts: eine
    # erfundene Laufzeit waere je nach Regner um den Faktor sechzehn falsch.
    def _ventilzeiten(anzahl):
        ges = 0.0
        aus = {}
        deckel = []
        for z2 in im_zyklus:
            s2 = z2["schluessel"]
            e2 = ergebnisse[s2]
            rate2 = float(z2.get("rate_mmh") or 0.0)
            if anzahl > 0 and rate2 > 0 and e2["bedarf_mm"] > 0:
                sek = e2["bedarf_mm"] / (anzahl * rate2 * wirkungsgrad) * 3600.0
                if sek > float(dauer_max_s):
                    # Der Deckel wird gemerkt, nicht verschwiegen.
                    #
                    # Eine gedeckelte Ventilzeit heisst: diese Zone bekommt
                    # weniger, als sie braucht. Wer das abschneidet und
                    # trotzdem "reicht" meldet, baut genau die stille
                    # Falschaussage, gegen die der ganze Plan gerichtet ist -
                    # gemessen am 18.08.2026 an einem Tropfschlauchbeet, das
                    # 13,1 von 24,1 mm bekam und als versorgt galt.
                    deckel.append(str(z2.get("name") or s2))
                sek = max(30.0, min(float(dauer_max_s), sek))
            else:
                sek = 0.0
            aus[s2] = sek
            ges += sek
        return aus, ges, deckel

    sekunden, summe_s, gedeckelt = _ventilzeiten(durchlaeufe)
    gekuerzt = 0
    while durchlaeufe > 1 and fenster_min > 0:
        # Dauer eines Durchlaufs mit den gerechneten Ventilzeiten, dazu die
        # Pausen zwischen den Durchlaeufen (nach dem letzten keine mehr).
        gesamt = durchlaeufe * (summe_s / 60.0) + (durchlaeufe - 1) * pause_min
        if gesamt <= fenster_min:
            break
        durchlaeufe -= 1
        gekuerzt = 1
        sekunden, summe_s, gedeckelt = _ventilzeiten(durchlaeufe)
    # Ein 'if gedeckelt: reicht = 0' stand hier zwischenzeitlich und ist
    # wieder heraus: es ist beweisbar wirkungslos. Reichen die Durchlaeufe
    # (reicht = 1), so ist bedarf <= durchlaeufe * rate * wg * dauer_s/3600,
    # also sekunden_soll <= dauer_s <= dauer_max_s - der Deckel greift dann
    # gar nicht. Und die Kuerzungsschleife laeuft in diesem Fall ebenfalls
    # nicht an. Die Eichung hat es gezeigt: mit und ohne die Zeile blieb die
    # Pruefung gruen, also pruefte sie nichts.
    #
    # Was der Deckel wirklich beitraegt, steht in 'ventilzeit_gedeckelt'
    # (WELCHE Zone) und 'ventilzeit_deckt' (decken die gerechneten
    # Ventilzeiten den Bedarf) - beides ist geeicht.
    for s2, sek in sekunden.items():
        je_zone[s2]["sekunden_soll"] = round(sek)
        je_zone[s2]["durchlaeufe"] = durchlaeufe if sek > 0 else 0

    grund = ""
    if fenster_min <= 0:
        grund = "fenster_ungueltig"
    elif ohne_rate and noetig == 0:
        # Es GIBT Bedarf, er laesst sich nur nicht in Durchlaeufe umrechnen.
        grund = "rate_fehlt"
        reicht = 0
    elif noetig == 0:
        grund = "kein_bedarf"
    elif moeglich == 0:
        grund = "fenster_zu_kurz"
    elif durchlaeufe < noetig:
        # WOERTLICH die Bedingung aus 0.9.6. Bis dahin stand hier
        # 'elif not reicht', und 'reicht' war genau 'durchlaeufe >= noetig'.
        # Seit 0.9.7 setzt auch eine gedeckelte Ventilzeit 'reicht' auf 0 -
        # haette ich die alte Schreibweise stehen lassen, traege eine
        # bestehende Anlage ploetzlich einen anderen Grund, ohne dass sich
        # etwas geaendert hat. Der neue Grund kommt deshalb DAHINTER.
        grund = "anlage_am_limit"
    # Einen eigenen Grund 'ventilzeit_am_limit' gab es hier zwischenzeitlich.
    # Er ist wieder heraus, weil er NIE auftreten kann: der Deckel ist
    # 'max(zonendauer_s, zonendauer_max_s)', und solange die Durchlaeufe
    # reichen, liegt die gerechnete Ventilzeit hoechstens bei der
    # eingestellten Zonendauer - also stets unter dem Deckel. Nachgemessen
    # ueber 1944 Kombinationen aus Rate, Dauer, Deckel, Grenze, Pause,
    # Fenster und Anfangsdefizit: 1463 mit gedeckelter Ventilzeit, davon
    # 0 mit ausreichenden Durchlaeufen. Der Grund lautet in all diesen
    # Faellen zu Recht 'anlage_am_limit'; WELCHE Zone der Deckel getroffen
    # hat, steht in 'ventilzeit_gedeckelt'.
    elif ohne_rate:
        # Ein Teil der Zonen laesst sich rechnen, ein anderer nicht.
        grund = "rate_fehlt_teilweise"

    return {
        "durchlaeufe": durchlaeufe,
        "noetige_durchlaeufe": noetig,
        "moegliche_durchlaeufe": moeglich,
        "reicht": reicht,
        "grund": grund,
        "ohne_rate": ohne_rate,
        "fenster_minuten": fenster_min,
        "durchlauf_minuten": lauf_min,
        "takt_minuten": takt_min,
        "wasserzeit_minuten": durchlaeufe * lauf_min,
        "ventilzeit_minuten": summe_s / 60.0,
        "ventilzeit_gedeckelt": gedeckelt,
        # 'reicht' behaelt seine Bedeutung aus 0.9.6: reichen die
        # Durchlaeufe bei der EINGESTELLTEN Zonendauer? Diese Zahl haengt
        # auf bestehenden Anlagen an einem virtuellen Eingang.
        #
        # 'ventilzeit_deckt' beantwortet die andere Frage: decken die
        # GERECHNETEN Ventilzeiten den Bedarf? Wer mit Tv1 bis Tv8 arbeitet,
        # liest diese Zahl - sie kann 1 sein, waehrend 'reicht' 0 ist, denn
        # eine laengere Ventilzeit ersetzt mehrere kurze Durchlaeufe.
        "ventilzeit_deckt": 0 if gedeckelt else 1,
        "ventilzeit_gekuerzt": gekuerzt,
        "je_zone": je_zone,
        "zonen_im_zyklus": len(im_zyklus),
    }


def _zonendauer(zone: dict, vorgabe_s: int) -> int:
    """Die Laufzeit einer Zone je Durchlauf - eigene, sonst die allgemeine.

    Leer, 0 oder unlesbar heisst 'nichts eingetragen' und ergibt die
    allgemeine Dauer. Das ist dieselbe Behandlung wie beim Mikroklima-Faktor:
    eine 0 als 'laeuft nie' zu lesen waere die gefaehrlichste Auslegung, weil
    die Zone dann ohne ein Wort trocken bliebe.
    """
    w = zone.get("dauer_s")
    try:
        w = int(float(w)) if w not in (None, "") else 0
    except (TypeError, ValueError):
        w = 0
    if w <= 0:
        return int(vorgabe_s)
    return max(30, min(3600, w))


def _fenster_minuten(von: str, bis: str) -> float:
    """Laenge des Zeitfensters in Minuten, auch ueber Mitternacht.

    Gleiche Anfangs- und Endzeit ergibt 0, nicht 1440.

    Bis 0.9.0 fiel '08:00 bis 08:00' in den Mitternachtszweig und kam als
    volle 24 Stunden heraus. Gemeint ist das so gut wie nie - es ist der
    Tippfehler, der entsteht, wenn jemand die zweite Zeit vergisst zu
    aendern. Ein 24-Stunden-Fenster laesst sich weiterhin einstellen, nur
    eben nicht aus Versehen: '00:00 bis 23:59' sagt dasselbe und meint es
    auch.

    Der Plan meldet fuer 0 den Grund 'fenster_ungueltig', und die
    Oberflaeche weist die Eingabe schon beim Speichern zurueck. Es wird also
    an keiner Stelle stillschweigend nicht gegossen.
    """
    def m(s):
        try:
            h, mi = s.split(":")
            h, mi = int(h), int(mi)
        except (ValueError, AttributeError):
            return -1
        if not (0 <= h <= 23 and 0 <= mi <= 59):
            return -1
        return h * 60 + mi
    a, b = m(von), m(bis)
    if a < 0 or b < 0 or a == b:
        return 0.0
    return float(b - a if b > a else 24 * 60 - a + b)


# --------------------------------------------------------------------------
# Sperren - wann trotz Bedarf nicht gegossen wird
# --------------------------------------------------------------------------

def sperren_pruefen(nacht: dict | None, cfg: dict,
                    regen_stunde: float | None = None) -> dict:
    """Drei Gruende, aus denen eine Nacht ausfaellt, obwohl Bedarf besteht.

    Frost   Unter der eingestellten Grenze wird nicht gegossen. Nasse Wege
            werden zur Rutschbahn, und Wasser, das in Leitung oder Regner
            steht, sprengt sie beim Gefrieren. Das ist der einzige der drei
            Gruende, bei dem es um Sachschaden geht.
    Wind    Bei Sturm trifft der Regner alles ausser die Flaeche. Der feste
            Wirkungsgrad von 0,75 gilt dann nicht mehr, und die ausgebrachte
            Menge waere eine Behauptung.
    Regen   Es regnet gerade. Die Vorhersage steckt zwar schon im Bedarf,
            aber ein Gewitter zwei Stunden vor dem Fenster steht in keiner
            Tagesvorhersage.

    **Alle drei sind ab Werk AUS.** Ohne ausdruecklich gesetzten Schalter
    aendert sich an keiner bestehenden Anlage etwas - auch nicht beim ersten
    Aufruf nach dem Update, wo die Vorgabewerte greifen.

    'nacht' ist der Vorschautag der kommenden Nacht (tmin, wind_kmh), so wie
    ihn quellen.open_meteo liefert. Fehlt er, wird NICHT gesperrt: eine
    Sperre aus fehlenden Daten abzuleiten hiesse, bei jedem Netzausfall den
    Garten trockenzulegen.

    Rueckgabe: dict mit 'aktiv' (0/1), 'grund' und den Einzelbefunden. Der
    Grund ist eine Kennung, kein Satz - der Satz steht in der Sprachdatei.
    """
    aus = {"aktiv": 0, "grund": "", "frost": 0, "wind": 0, "regen": 0,
           "tmin": None, "wind_kmh": None, "regen_mmh": None,
           "geprueft": 0}

    def _z(x):
        try:
            return float(x)
        except (TypeError, ValueError):
            return None

    if int(cfg.get("frost_ein") or 0):
        aus["geprueft"] += 1
        grenze = _z(cfg.get("frost_c"))
        grenze = 2.0 if grenze is None else grenze
        tmin = _z((nacht or {}).get("tmin"))
        aus["tmin"] = tmin
        if tmin is not None and tmin <= grenze:
            aus["frost"] = 1

    if int(cfg.get("wind_ein") or 0):
        aus["geprueft"] += 1
        grenze = _z(cfg.get("wind_kmh_max"))
        grenze = 40.0 if grenze is None else grenze
        w = _z((nacht or {}).get("wind_kmh"))
        aus["wind_kmh"] = w
        if w is not None and w >= grenze:
            aus["wind"] = 1

    if int(cfg.get("regen_ein") or 0):
        aus["geprueft"] += 1
        grenze = _z(cfg.get("regen_mmh_max"))
        grenze = 0.5 if grenze is None else grenze
        r = _z(regen_stunde)
        aus["regen_mmh"] = r
        if r is not None and r >= grenze:
            aus["regen"] = 1

    # Reihenfolge nach Gewicht: Frost ist Sachschaden, Wind ist Verschwendung,
    # Regen ist nur ueberfluessig.
    for name in ("frost", "wind", "regen"):
        if aus[name]:
            aus["aktiv"] = 1
            aus["grund"] = "sperre_" + name
            break
    return aus


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

    # --- Mikroklima-Faktor (neu in 0.9.1) ---
    #
    # Der Faktor muss zwei Dinge leisten: er muss wirken, UND er darf ohne
    # Eintrag nichts aendern. Das zweite ist das wichtigere - sonst rechnet
    # jede bestehende Anlage ab dieser Fassung anders.
    vor7 = [{"et0": 5.0, "regen": 0.0} for _ in range(7)]
    ohne_f = zone_rechnen(dict(zone, dr=0.0), vor7, [], cfg)
    eins_f = zone_rechnen(dict(zone, dr=0.0, mikroklima=1.0), vor7, [], cfg)
    leer_f = zone_rechnen(dict(zone, dr=0.0, mikroklima=""), vor7, [], cfg)
    e.append((abs(ohne_f["dr"] - eins_f["dr"]) < 1e-9
              and abs(ohne_f["dr"] - leer_f["dr"]) < 1e-9,
              "Ohne Eintrag, mit 1,0 und mit leerem Feld: dasselbe Ergebnis (%.3f mm)"
              % ohne_f["dr"]))
    schatten = zone_rechnen(dict(zone, dr=0.0, mikroklima=0.6), vor7, [], cfg)
    hitze = zone_rechnen(dict(zone, dr=0.0, mikroklima=1.4), vor7, [], cfg)
    e.append((schatten["dr"] < ohne_f["dr"] < hitze["dr"],
              "7 Tage trocken: Schatten %.1f mm < normal %.1f mm < Hitzeecke %.1f mm"
              % (schatten["dr"], ohne_f["dr"], hitze["dr"])))
    # Die Groessenordnung muss stimmen: 0,6 statt 1,0 heisst rund 40 Prozent
    # weniger Verdunstung. Genau 40 sind es nicht, weil der Trockenstress
    # (Ks) die Verdunstung zusaetzlich bremst - und zwar erst bei hoeherem
    # Defizit, also beim unbeschatteten Beet frueher.
    verhaeltnis = schatten["dr"] / ohne_f["dr"] if ohne_f["dr"] > 0 else 0.0
    e.append((0.55 <= verhaeltnis <= 0.75,
              "Faktor 0,6 senkt das Defizit auf %.0f %% - nicht genau 60 %%, weil "
              "Ks unterschiedlich bremst" % (verhaeltnis * 100)))
    # Grenzen: es wird begrenzt, nicht abgewiesen - und nicht ins Absurde.
    e.append((zone_rechnen(dict(zone, mikroklima=99), [], [], cfg)["mikroklima"] == 1.5
              and zone_rechnen(dict(zone, mikroklima=0), [], [], cfg)["mikroklima"] == 1.0
              and zone_rechnen(dict(zone, mikroklima=-3), [], [], cfg)["mikroklima"] == 0.3
              and zone_rechnen(dict(zone, mikroklima="0,6"), [], [], cfg)["mikroklima"] == 1.0,
              "Faktor wird auf 0,3 bis 1,5 begrenzt; 0 und unlesbare Eingaben gelten "
              "als 'nichts eingetragen' (1,0), nicht als 'verdunstet nie'"))
    e.append((zone_rechnen(dict(zone, mikroklima=0.75), [], [], cfg)["mikroklima"] == 0.75,
              "Der Faktor steht im Ergebnis, damit die Oberflaeche ihn zeigen kann"))

    # --- Fehlende Niederschlagsrate wird BENANNT, nicht als "kein Bedarf"
    #     durchgereicht (neu in 0.9.1) ---
    #
    # Das ist die heikelste Stelle des ganzen Moduls: bis 0.9.0 ergab eine
    # Zone mit Bedarf, aber ohne Rate, null noetige Durchlaeufe - und weil der
    # Plan nur die groesste Zahl nimmt, stand am Ende 'kein_bedarf'. Eine
    # durstige Zone wurde also als versorgt gemeldet.
    ohne = dict(zone, schluessel="ohne", name="Ohne Rate", dr=70.0)
    ohne.pop("rate_mmh", None)
    e_ohne = {"ohne": zone_rechnen(ohne, [], [{"et0": 5.0, "regen": 0.0}], cfg)}
    pl_o = plan_bauen([ohne], e_ohne, cfg)
    e.append((e_ohne["ohne"]["bedarf_mm"] > 0, "Zone ohne Rate hat trotzdem Bedarf: %.1f mm"
              % e_ohne["ohne"]["bedarf_mm"]))
    e.append((pl_o["grund"] == "rate_fehlt" and pl_o["reicht"] == 0
              and pl_o["ohne_rate"] == ["Ohne Rate"],
              "Ohne Rate: Grund '%s' statt 'kein_bedarf', Zone benannt (%s)"
              % (pl_o["grund"], ", ".join(pl_o["ohne_rate"]))))
    e.append((pl_o["je_zone"]["ohne"]["rate_fehlt"] == 1,
              "Die Luecke steht auch je Zone im Plan"))
    # Gemischt: eine Zone rechenbar, eine nicht - der Plan geht auf, sagt aber
    # welche Zone fehlt.
    a_z = dict(zone, schluessel="a", name="A", dr=52.0, rate_mmh=10.0)
    b_z = dict(zone, schluessel="b", name="B", dr=52.0, rate_mmh=0.0)
    e_mix = {"a": zone_rechnen(a_z, [], [{"et0": 2.0, "regen": 0.0}], dict(cfg, vorschautage=1)),
             "b": zone_rechnen(b_z, [], [{"et0": 2.0, "regen": 0.0}], dict(cfg, vorschautage=1))}
    pl_m = plan_bauen([a_z, b_z], e_mix, dict(cfg, vorschautage=1))
    e.append((pl_m["grund"] == "rate_fehlt_teilweise" and pl_m["ohne_rate"] == ["B"],
              "Teils rechenbar: Grund '%s', fehlende Rate bei %s"
              % (pl_m["grund"], ", ".join(pl_m["ohne_rate"]))))
    # Und: keine Division durch Null, bei keiner Schreibweise der Null.
    ohne_absturz = True
    for r in (0.0, -1.0, None, ""):
        try:
            zx = dict(zone, schluessel="x", dr=70.0, rate_mmh=r)
            plan_bauen([zx], {"x": zone_rechnen(zx, [], [{"et0": 5.0, "regen": 0.0}], cfg)}, cfg)
        except ZeroDivisionError:
            ohne_absturz = False
    e.append((ohne_absturz, "Rate 0, -1, None und '' fuehren zu keiner Division durch Null"))

    # --- Zeitfenster (neu geprueft in 0.9.1) ---
    for von, bis, soll, txt in (
            ("22:00", "08:00", 600.0, "ueber Mitternacht"),
            ("08:00", "20:00", 720.0, "am Tag"),
            ("00:00", "23:59", 1439.0, "fast rund um die Uhr"),
            ("08:00", "08:00", 0.0, "gleiche Zeit ergibt 0, nicht 1440"),
            ("22:00", "22:00", 0.0, "gleiche Zeit auch abends"),
            ("25:00", "08:00", 0.0, "unmoegliche Stunde"),
            ("abc", "08:00", 0.0, "kein Zeitformat")):
        p("Fenster %s-%s (%s)" % (von, bis, txt), _fenster_minuten(von, bis), soll, 0.001)
    pl_f = plan_bauen(zonen, erg, dict(cfg, fenster_von="08:00", fenster_bis="08:00"))
    e.append((pl_f["grund"] == "fenster_ungueltig" and pl_f["durchlaeufe"] == 0,
              "Gleiche Anfangs- und Endzeit: 0 Durchlaeufe, Grund 'fenster_ungueltig'"))

    # --- Zonendauer je Zone (neu in 0.9.7) ---
    #
    # Die wichtigste Zeile zuerst: OHNE Eintrag muss dasselbe herauskommen
    # wie bis 0.9.6. Sonst rechnet jede bestehende Anlage ab dieser Fassung
    # anders, ohne dass jemand etwas eingetragen hat.
    e.append((_zonendauer({}, 240) == 240 and _zonendauer({"dauer_s": ""}, 240) == 240
              and _zonendauer({"dauer_s": 0}, 240) == 240
              and _zonendauer({"dauer_s": "abc"}, 240) == 240,
              "Ohne eigene Dauer gilt die allgemeine; 0 und Unlesbares ebenso"))
    e.append((_zonendauer({"dauer_s": 600}, 240) == 600
              and _zonendauer({"dauer_s": 99999}, 240) == 3600
              and _zonendauer({"dauer_s": 5}, 240) == 30,
              "Eigene Dauer wird uebernommen und auf 30 bis 3600 s begrenzt"))

    # Zwei sehr verschiedene Regner an einer gemeinsamen Dauer - der Fall,
    # der den Umbau ausgeloest hat. Gemessen am 18.08.2026: der Rasen bekam
    # 21,0 mm bei 13,9 mm Bedarf, das Tropfschlauchbeet 3,0 mm.
    schnell = dict(zone, schluessel="schnell", name="Spruehduesen", rate_mmh=35.0, dr=0.0)
    langsam = dict(zone, schluessel="langsam", name="Tropfschlauch", rate_mmh=5.0, dr=0.0)
    v10 = [{"et0": 5.0, "regen": 0.0} for _ in range(10)]
    vs = [{"et0": 5.0, "regen": 0.0}] * 2
    cfg_w = dict(cfg, max_durchlaeufe=24)
    erg_zwei = {z["schluessel"]: zone_rechnen(z, v10, vs, cfg_w) for z in (schnell, langsam)}
    pl_zwei = plan_bauen([schnell, langsam], erg_zwei, cfg_w)
    # Jede Zone bekommt eine eigene Ventilzeit, mit der SIE ihren Bedarf deckt.
    for z2 in (schnell, langsam):
        s2 = z2["schluessel"]
        sek = pl_zwei["je_zone"][s2]["sekunden_soll"]
        geg = (pl_zwei["durchlaeufe"] * float(z2["rate_mmh"])
               * cfg_w["wirkungsgrad"] * (sek / 3600.0))
        soll = erg_zwei[s2]["bedarf_mm"]
        e.append((soll <= 0 or abs(geg - soll) <= 0.35 * soll,
                  "Ventilzeit deckt den Bedarf von %s: %d s je Durchlauf ergeben "
                  "%.1f mm bei %.1f mm Bedarf" % (z2["name"], sek, geg, soll)))
    e.append((pl_zwei["je_zone"]["langsam"]["sekunden_soll"]
              > pl_zwei["je_zone"]["schnell"]["sekunden_soll"],
              "Der langsame Regner bekommt die laengere Ventilzeit (%d s gegen %d s)"
              % (pl_zwei["je_zone"]["langsam"]["sekunden_soll"],
                 pl_zwei["je_zone"]["schnell"]["sekunden_soll"])))
    # Eine eigene Dauer verlaengert den Durchlauf und damit den Takt.
    pl_kurz = plan_bauen(zonen, erg, cfg)
    pl_lang = plan_bauen([dict(z, dauer_s=480) for z in zonen], erg, cfg)
    e.append((pl_lang["durchlauf_minuten"] == 2 * pl_kurz["durchlauf_minuten"],
              "Doppelte Zonendauer verdoppelt den Durchlauf: %.0f statt %.0f min"
              % (pl_lang["durchlauf_minuten"], pl_kurz["durchlauf_minuten"])))
    e.append((pl_kurz["je_zone"]["z1"]["eigene_dauer"] == 0
              and pl_lang["je_zone"]["z1"]["eigene_dauer"] == 1,
              "Der Plan sagt je Zone, ob die Dauer eine eigene ist"))
    # Ohne gemessene Rate gibt es keine Ventilzeit - geraten wird nichts.
    e.append((pl_o["je_zone"]["ohne"]["sekunden_soll"] == 0,
              "Ohne Niederschlagsrate bleibt die Ventilzeit 0, statt geraten zu werden"))

    # Ein Bedarf, den die laengste erlaubte Ventilzeit nicht deckt, wird
    # BENANNT und nicht als gedeckt gemeldet. Ohne diese Zeile stand hier
    # 'reicht = 1' bei einer Zone, die 13,1 von 24,1 mm bekam.
    # Genug Durchlaeufe (lange Zonendauer), aber ein enger Deckel auf der
    # Ventilzeit - nur so zeigt sich, dass die Ventilzeit die Grenze ist.
    durstig = dict(zone, schluessel="durstig", name="Tropfbeet", rate_mmh=10.0,
                   dr=0.0, im_zyklus=1)
    cfg_d = dict(cfg_w, zonendauer_s=3600, zonendauer_max_s=600)
    e_d = {"durstig": zone_rechnen(durstig, v10, vs, cfg_d)}
    pl_d = plan_bauen([durstig], e_d, cfg_d)
    knapp = dict(zone, schluessel="knapp", name="Tropfbeet", rate_mmh=2.0,
                 dr=0.0, im_zyklus=1)
    e_k = {"knapp": zone_rechnen(knapp, v10, vs, cfg_w)}
    pl_k = plan_bauen([knapp], e_k, dict(cfg_w, zonendauer_max_s=600))
    e.append((pl_k["ventilzeit_gedeckelt"] == ["Tropfbeet"]
              and pl_k["reicht"] == 0 and pl_k["ventilzeit_deckt"] == 0,
              "Gedeckelte Ventilzeit: reicht=0, ventilzeit_deckt=0, Zone "
              "benannt (%s)" % ", ".join(pl_k["ventilzeit_gedeckelt"])))
    e.append((pl_k["grund"] == "anlage_am_limit",
              "Der Grund bleibt der aus 0.9.6: '%s' - ein eigener Grund fuer "
              "die Ventilzeit waere unerreichbar (1944 Faelle gemessen)"
              % pl_k["grund"]))
    # Gegenprobe mit einer Zone, deren Bedarf in die laengste Ventilzeit
    # hineinpasst: dort darf keine Beanstandung stehen. Ohne diese Zeile
    # wuerde eine Wache, die IMMER anschlaegt, als richtig durchgehen.
    satt = dict(zone, schluessel="satt", name="Rasen", rate_mmh=10.0,
                dr=0.0, im_zyklus=1)
    e_s = {"satt": zone_rechnen(satt, v10, vs, cfg_w)}
    pl_s = plan_bauen([satt], e_s, dict(cfg_w, zonendauer_max_s=1800))
    e.append((pl_s["ventilzeit_gedeckelt"] == [] and pl_s["ventilzeit_deckt"] == 1,
              "Eine Zone, die hineinpasst, wird NICHT beanstandet "
              "(%d s je Durchlauf, %d Durchlaeufe)"
              % (pl_s["je_zone"]["satt"]["sekunden_soll"], pl_s["durchlaeufe"])))
    # Und der Unterschied zwischen den beiden Zahlen, ausgeschrieben: die
    # Durchlaeufe reichen NICHT (28 waeren bei 240 s noetig), die gerechneten
    # Ventilzeiten decken den Bedarf trotzdem.
    e.append((pl_s["reicht"] == 0 and pl_s["ventilzeit_deckt"] == 1
              and pl_s["ventilzeit_gekuerzt"] == 1,
              "reicht=%d bei eingestellter Dauer (%d von %d Durchlaeufen), "
              "ventilzeit_deckt=%d mit gerechneter Ventilzeit - zwei Fragen, "
              "zwei Antworten"
              % (pl_s["reicht"], pl_s["durchlaeufe"], pl_s["noetige_durchlaeufe"],
                 pl_s["ventilzeit_deckt"])))

    # --- Sperren (neu in 0.9.7) ---
    #
    # Zuerst der Fall jeder bestehenden Anlage: alle Schalter fehlen in der
    # Konfiguration, also greifen die Vorgaben - und die sind AUS.
    leer = sperren_pruefen({"tmin": -8.0, "wind_kmh": 90.0}, {}, 12.0)
    e.append((leer["aktiv"] == 0 and leer["geprueft"] == 0,
              "Ab Werk sperrt nichts - auch nicht bei -8 Grad, Sturm und Starkregen"))
    # Jede Sperre einzeln, jeweils mit ihrem eigenen Schalter.
    frost = sperren_pruefen({"tmin": -2.0}, {"frost_ein": 1})
    e.append((frost["aktiv"] == 1 and frost["grund"] == "sperre_frost",
              "Frostsperre greift bei -2 Grad (Vorgabegrenze 2 Grad)"))
    e.append((sperren_pruefen({"tmin": 9.0}, {"frost_ein": 1})["aktiv"] == 0,
              "Frostsperre greift bei 9 Grad nicht"))
    wind = sperren_pruefen({"wind_kmh": 55.0}, {"wind_ein": 1})
    e.append((wind["aktiv"] == 1 and wind["grund"] == "sperre_wind",
              "Windsperre greift bei 55 km/h (Vorgabegrenze 40)"))
    regen = sperren_pruefen({}, {"regen_ein": 1}, 3.0)
    e.append((regen["aktiv"] == 1 and regen["grund"] == "sperre_regen",
              "Regensperre greift bei 3 mm/h (Vorgabegrenze 0,5)"))
    # Eigene Grenzen werden beachtet.
    e.append((sperren_pruefen({"tmin": 4.0}, {"frost_ein": 1, "frost_c": 5.0})["frost"] == 1
              and sperren_pruefen({"tmin": 4.0}, {"frost_ein": 1, "frost_c": 0.0})["frost"] == 0,
              "Die eingestellte Frostgrenze zaehlt, nicht die Vorgabe"))
    # Und der wichtigste Fall: FEHLENDE Daten sperren NICHT. Eine Sperre aus
    # einem Netzausfall abzuleiten hiesse, den Garten trockenzulegen.
    for lage, txt in ((None, "gar keine Vorschau"), ({}, "leere Vorschau"),
                      ({"tmin": None, "wind_kmh": None}, "Vorschau ohne Werte")):
        s3 = sperren_pruefen(lage, {"frost_ein": 1, "wind_ein": 1, "regen_ein": 1})
        e.append((s3["aktiv"] == 0,
                  "Ohne Daten wird nicht gesperrt (%s)" % txt))
    # Reihenfolge: Frost wiegt schwerer als Wind, Wind schwerer als Regen.
    alle = sperren_pruefen({"tmin": -3.0, "wind_kmh": 90.0},
                           {"frost_ein": 1, "wind_ein": 1, "regen_ein": 1}, 9.0)
    e.append((alle["grund"] == "sperre_frost" and alle["wind"] == 1 and alle["regen"] == 1,
              "Bei mehreren Sperren wird Frost genannt, die uebrigen stehen daneben"))

    # --- Klimaanpassung von Kc in der Zone (neu in 0.9.7) ---
    #
    # Wieder zuerst: ohne Pflanzenhoehe aendert sich nichts, und zwar auch
    # dann nicht, wenn Wind und Feuchte vorliegen.
    wetter = {"u2": 3.0, "rh_min": 25.0}
    ohne_h = zone_rechnen(dict(zone, dr=0.0), vor7, [], cfg, wetter)
    e.append((abs(ohne_h["dr"] - ohne_f["dr"]) < 1e-9 and ohne_h["kc_klima"] == 0,
              "Ohne Pflanzenhoehe bleibt es beim Tabellenwert (%.3f mm)" % ohne_h["dr"]))
    # Und ohne Wetter aendert eine eingetragene Hoehe ebenfalls nichts.
    ohne_w = zone_rechnen(dict(zone, dr=0.0, hoehe_pflanze=0.6), vor7, [], cfg, None)
    e.append((abs(ohne_w["dr"] - ohne_f["dr"]) < 1e-9 and ohne_w["kc_klima"] == 0,
              "Ohne Wind und Feuchte bleibt es ebenfalls beim Tabellenwert"))
    # Mit beidem greift sie - und hebt das Defizit, weil die Luft trocken ist.
    mit_h = zone_rechnen(dict(zone, dr=0.0, hoehe_pflanze=0.6), vor7, [], cfg, wetter)
    e.append((mit_h["kc_klima"] == 1 and mit_h["kc"] > mit_h["kc_tabelle"]
              and mit_h["dr"] > ohne_h["dr"],
              "Mit Hoehe und trockener Luft: Kc %.3f statt %.3f, Defizit %.1f statt %.1f mm"
              % (mit_h["kc"], mit_h["kc_tabelle"], mit_h["dr"], ohne_h["dr"])))

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
