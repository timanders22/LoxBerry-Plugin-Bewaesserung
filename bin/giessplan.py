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

import datetime
import math
from typing import Any

import fao56


# --------------------------------------------------------------------------
# Eine Zone rechnen
# --------------------------------------------------------------------------

def _datum_oder_none(wert) -> datetime.date | None:
    """Ein Datum JJJJ-MM-TT lesen; alles andere ergibt None (0.9.49)."""
    if not isinstance(wert, str) or len(wert) != 10:
        return None
    try:
        return datetime.date.fromisoformat(wert)
    except ValueError:
        return None


def pflanzdatum_lesen(wert, heute: datetime.date) -> datetime.date | None:
    """Das Datum Aussaat/Pflanzung einer Zone (0.9.49): JJJJ-MM-TT, hoechstens
    ein Jahr in der Zukunft (dieselbe Regel wie bw_pflanzdatum_pruefen() im
    Formular). Alles andere gilt als leer."""
    d = _datum_oder_none(wert)
    if d is None or (d - heute).days > 366:
        return None
    return d


def pflanzdatum_ungueltig(wert, heute: datetime.date) -> bool:
    """Steht etwas im Feld, das nicht gilt? Leer ist kein Fehler (0.9.49)."""
    return wert not in (None, "") and pflanzdatum_lesen(wert, heute) is None


def zone_rechnen(zone: dict, verlauf: list[dict], vorschau: list[dict],
                 cfg: dict, wetter: dict | None = None,
                 heute: datetime.date | None = None) -> dict:
    """Wasserhaushalt einer Zone fortschreiben und den Bedarf bestimmen.

    'verlauf'  Tage der Vergangenheit, je dict mit et0, regen, [bewaesserung],
               [datum]
    'vorschau' kommende Tage, je dict mit et0, regen, [regen_wahrsch], [datum]
    'wetter'   freiwillig: u2 und rh_min des Tages fuer die Klimaanpassung
               des Pflanzenbeiwerts [FAO-56, Gl. 62]. Fehlt es, bleibt Kc
               der Tabellenwert - also genau das, was bis 0.9.6 galt.
    'heute'    freiwillig (0.9.49): das Datum, zu dem der Kc der Zone gilt.

    0.9.49: traegt die Zone 'pflanzdatum' und 'phasen', gilt Kc je Tag nach
    FAO-56 Gl. 66. Das Ergebnis traegt dann 'kc_phase', 'kc_tag_nr', 'kc_durch';
    'kc' und 'kc_tabelle' sind die Werte von heute.
    """
    kc = float(zone.get("kc") or 1.0)
    # 0.9.49: 'heute' braucht nur eine Zone mit Datum Aussaat/Pflanzung.
    heute = heute or datetime.date.today()
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
    # --- Wachstumsphasen (neu in 0.9.49) ----------------------------------
    #
    # Nur mit gueltigem Datum UND Phasen der Bepflanzung. Sonst bleibt kc_tag
    # None, jeder Tag rechnet mit dem festen kc von oben, und das Ergebnis
    # traegt nicht einmal neue Schluessel: zahlengleich zu 0.9.48.
    kc_tag = None
    kc_heute_phase = None
    start = pflanzdatum_lesen(zone.get("pflanzdatum"), heute)
    phasen = fao56.phasen_lesen(zone.get("phasen")) if start else None
    if phasen:
        # Gl. 62 und 65 nur fuer Mitte und Ende; Kc Anfang bleibt der
        # Tabellenwert, die Interpolation laeuft zwischen den angepassten Werten.
        # Wie oben gilt das Wetter des Tages, nicht das Mittel der Phase.
        kc_mid, kc_end = phasen["kc_mid"], phasen["kc_end"]
        if h_pflanze > 0 and wetter and wetter.get("u2") is not None \
                and wetter.get("rh_min") is not None:
            kc_mid = fao56.kc_klimaanpassung(kc_mid, float(wetter["u2"]),
                                             float(wetter["rh_min"]), h_pflanze)
            kc_end = fao56.kc_klima_end(kc_end, float(wetter["u2"]),
                                        float(wetter["rh_min"]), h_pflanze)

        def kc_tag(datum: datetime.date) -> float:
            return fao56.kc_phase_tag((datum - start).days + 1, phasen["tage"],
                                      phasen["kc_ini"], kc_mid, kc_end)[0]

        kc = kc_tag(heute)
        kc_tabelle, kc_heute_phase = fao56.kc_phase_tag(
            (heute - start).days + 1, phasen["tage"], phasen["kc_ini"],
            phasen["kc_mid"], phasen["kc_end"])
        kc_klima = 1 if kc != kc_tabelle else 0
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
    #
    # Ohne Verlauf gibt es keine Bilanz. Bis 0.9.18 lief die Schleife
    # unten null Mal, dr blieb 0, und die Zone meldete Fuellstand 100 %
    # und Bedarf 0 - "ich weiss nichts" war von "der Boden ist voll"
    # nicht zu unterscheiden, und die Zahl ging als Messergebnis ueber
    # MQTT hinaus.
    unbelegt = not verlauf and float(zone.get("dr") or 0.0) <= 0.0
    dr = float(zone.get("dr") or 0.0)
    dr = max(0.0, min(taw_mm, dr))
    etc_letzter = 0.0
    for tag in verlauf:
        et0 = max(0.0, float(tag.get("et0") or 0.0))
        # 0.9.49: jeder Tag mit dem Kc SEINES Datums. Traegt ein Eintrag kein
        # lesbares Datum, gilt der Kc von heute.
        kc_t = kc
        if kc_tag is not None:
            d_t = _datum_oder_none(tag.get("datum"))
            if d_t is not None:
                kc_t = kc_tag(d_t)
        # Der Faktor greift an ETc, nicht an ET0: ET0 ist die Verdunstung der
        # Grasreferenz AM STANDORT und fuer alle Zonen dieselbe Zahl. Sie je
        # Zone zu verbiegen waere eine Falschaussage ueber das Wetter.
        etc_moeglich = kc_t * et0 * mikro
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
    etc_kommend = 0.0
    regen_kommend = 0.0
    for nr, tag in enumerate(vorschau[:tage]):
        et0_t = max(0.0, float(tag.get("et0") or 0.0))
        et0_kommend += et0_t
        if kc_tag is not None:
            # 0.9.49: auch die kommenden Tage mit dem Kc ihres Datums. Ohne Datum
            # im Eintrag: heute + 1, + 2, ... wie die Liste sortiert ist.
            d_t = _datum_oder_none(tag.get("datum")) or heute + datetime.timedelta(days=nr + 1)
            etc_kommend += kc_tag(d_t) * et0_t * mikro
        r = max(0.0, float(tag.get("regen") or 0.0))
        w = tag.get("regen_wahrsch")
        if w is not None:
            # Eine Vorhersage ist keine Zusage: die Menge wird mit der
            # Wahrscheinlichkeit gewichtet, bevor sie angerechnet wird.
            r = r * max(0.0, min(1.0, float(w) / 100.0))
        regen_kommend += r
    if kc_tag is None:
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

    ergebnis = {
        # Kein Verlauf UND kein fortgeschriebenes Defizit heisst: es ist
        # nichts bekannt. Bis 0.9.18 kam dabei "Fuellstand 100 %, Bedarf 0"
        # heraus - "ich weiss nichts" war von "der Boden ist voll" nicht zu
        # unterscheiden, und die Zahl ging als Messergebnis ueber MQTT
        # hinaus. Gerechnet wird trotzdem zu Ende, damit die Oberflaeche
        # TAW und RAW zeigen kann.
        "ok": 0 if unbelegt else 1,
        "grund": "kein_verlauf" if unbelegt else "",
        "meldung": ("Es gibt noch keinen Tagesverlauf, aus dem sich eine "
                    "Wasserbilanz ergeben koennte. Nach dem ersten vollen "
                    "Tag steht sie.") if unbelegt else "",
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
    # 0.9.49: nur mit Phasen, damit eine Zone ohne Datum unveraendert bleibt.
    if kc_heute_phase is not None:
        ergebnis["kc_phase"] = kc_heute_phase
        ergebnis["kc_tag_nr"] = (heute - start).days + 1
        ergebnis["kc_durch"] = 1 if kc_heute_phase == "durch" else 0
    return ergebnis


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
    # z.get(), nicht z[]: der Dienst ueberspringt Zonen ohne Schluessel
    # beim Rechnen, gibt aber die VOLLE Liste hierher. Ein fehlender
    # Schluessel ergab bis 0.9.18 einen KeyError, den der Sammelfang als
    # "Rechengang fehlgeschlagen" protokollierte - in jedem Takt neu und
    # ohne Hinweis auf die Zone.
    im_zyklus = [z for z in zonen if z.get("schluessel")
                 and int(z.get("im_zyklus") or 0)
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
    # C6 (Durchgang 30.09.2026): das Giessfenster ist eine HARTE Grenze
    # (Entscheidung Frage 16).
    #
    # Die Schleife oben senkt die Zahl der Durchlaeufe, aber nicht unter
    # eins. Passte schon EIN Durchlauf mit den gerechneten Ventilzeiten
    # nicht ins Fenster, stand bis 0.9.34 ein Plan da, der ueber das
    # Fensterende hinaus goss (Pruefbericht Code, C6). Jetzt werden die
    # Ventilzeiten ANTEILIG gekuerzt, bis Ventilzeiten und Pausen ins
    # Fenster passen, abgerundet auf ganze Sekunden. Das fehlende Wasser
    # bleibt als Defizit in der Bilanz (sie entsteht bei jedem Lauf neu
    # aus dem Verlauf und der Giess-Rueckmeldung), und der Plan sagt es:
    # fenster_gekuerzt = 1, reicht = 0, ventilzeit_deckt = 0, Grund
    # 'fenster_gekuerzt'.
    fenster_gekuerzt = 0
    fenster_anteil = 1.0
    # a1 (Verbesserungsbau 30.09.2026): um wie viele Minuten Ventilzeit der
    # Plan gekuerzt wurde - ueber alle Zonen und Durchlaeufe. Die Pausen
    # bleiben dabei gleich; die Zahl ist also zugleich die Zeit, um die der
    # ungekuerzte Plan das Fenster ueberzogen haette. 0 = nicht gekuerzt;
    # eine Kuerzung unter einer halben Minute zaehlt als 1, damit 0 nur
    # "nicht gekuerzt" heisst.
    fenster_gekuerzt_min = 0
    if durchlaeufe >= 1 and fenster_min > 0 and summe_s > 0:
        gesamt = durchlaeufe * (summe_s / 60.0) + (durchlaeufe - 1) * pause_min
        if gesamt > fenster_min:
            frei_s = (fenster_min - (durchlaeufe - 1) * pause_min) * 60.0 / durchlaeufe
            fenster_anteil = max(0.0, min(1.0, frei_s / summe_s))
            summe_vor_s = summe_s
            sekunden = {s2: float(math.floor(sek * fenster_anteil))
                        for s2, sek in sekunden.items()}
            summe_s = sum(sekunden.values())
            fenster_gekuerzt = 1
            fenster_gekuerzt_min = max(1, int(round(
                durchlaeufe * (summe_vor_s - summe_s) / 60.0)))
    # Ein gedeckelter Plan deckt den Bedarf NICHT - also sagt 'reicht' das.
    #
    # Hier stand bis 0.9.21 die Begruendung, ein 'if gedeckelt: reicht = 0'
    # sei "beweisbar wirkungslos": reichen die Durchlaeufe, so sei
    # bedarf <= durchlaeufe * rate * wg * dauer_s/3600 und damit
    # sekunden_soll <= dauer_s <= dauer_max_s. Der Beweis rechnet mit
    # 'dauer_s', der ALLGEMEINEN Zonendauer. Gedeckelt wird aber gegen die
    # EIGENE Dauer der Zone ('dauern[s]', seit 0.9.7, in der Oberflaeche bis
    # 3600 s zulaessig), und 'dauer_max_s' oben bildet das Maximum aus der
    # allgemeinen Dauer und 'zonendauer_max_s' - die eigene kommt darin gar
    # nicht vor. Liegt sie darueber, greift der Deckel, und 'reicht' blieb
    # trotzdem 1.
    #
    # Gemessen am 06.09.2026, nur mit Werten, die das Formular zulaesst:
    # eigene Dauer 2400 s, Deckel 1800 s (Werkseinstellung), Rate 2 mm/h,
    # Bedarf 2,47 mm -> 3 von 3 noetigen Durchlaeufen, sekunden_soll 1800,
    # ausgebracht 2,25 mm, REICHT = 1. Ueber 720 zulaessige Kombinationen:
    # 274 mit REICHT = 1 und ventilzeit_deckt = 0, groesster Fehlbetrag
    # 18,50 von 20,00 mm. Die Eichung blieb damals gruen, weil ihr
    # Pruefstueck eine Zone OHNE eigene Dauer benutzt - dort kommt der
    # Deckel nie zum Zuge.
    #
    # 'zonendauer_max_s' ist eine harte Grenze des Anwenders ("Die laengste
    # Ventilzeit, die das Plugin fuer eine Zone errechnen darf"). Sie wird
    # deshalb NICHT angehoben - die Zone bekommt weiter nur so viel, wie
    # der Anwender zulaesst. Berichtigt wird die AUSSAGE darueber.
    #
    # 'ventilzeit_gedeckelt' (WELCHE Zone) und 'ventilzeit_deckt' bleiben
    # daneben stehen: sie beantworten die feinere Frage.
    if gedeckelt:
        reicht = 0
    if fenster_gekuerzt:
        reicht = 0
    for s2, sek in sekunden.items():
        je_zone[s2]["sekunden_soll"] = round(sek)
        je_zone[s2]["durchlaeufe"] = durchlaeufe if sek > 0 else 0

    grund = ""
    if gedeckelt and not grund:
        # Der Grund wird benannt. "Es reicht nicht" ohne Grund schickt den
        # Anwender an die falsche Stelle - hier ist nicht das Giessfenster
        # zu kurz, sondern die laengste zugelassene Ventilzeit zu klein.
        grund = "ventilzeit_gedeckelt"
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
    # C6: die Kuerzung wird benannt, wo kein gewichtigerer Grund steht.
    # 'anlage_am_limit' bleibt - er sagt schon, dass es nicht reicht.
    if fenster_gekuerzt and grund in ("", "ventilzeit_gedeckelt"):
        grund = "fenster_gekuerzt"

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
        "ventilzeit_deckt": 0 if (gedeckelt or fenster_gekuerzt) else 1,
        "fenster_gekuerzt": fenster_gekuerzt,
        "fenster_anteil": round(fenster_anteil, 3),
        "fenster_gekuerzt_min": fenster_gekuerzt_min,
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
# 0.9.52: Pause (Befehl aus Loxone/MQTT) und Rangfolge bei knappem Wasservorrat
# --------------------------------------------------------------------------

def pause_einrechnen(sperre: dict | None, pause: dict | None, jetzt: float) -> dict:
    """Eine Pause wirkt wie eine Sperre - nur mit Enddatum.

    'pause' ist der Inhalt von data/.../pause.json (geschrieben von der
    Befehlsbruecke oder der Oberflaeche): bis_ts (Unix-Zeit, bis zu der nicht
    gegossen wird) und bis (Datum fuer die Anzeige). Eine abgelaufene oder
    fehlende Pause aendert nichts - die Pause endet von selbst.

    Eine Wettersperre behaelt ihren Grund (Frost ist Sachschaden); die Pause
    steht dann nur daneben ('pause' = 1). Ohne Wettersperre lautet der Grund
    'pause', und alles, was eine Sperre beachtet (Sendeweg, Nachtplan,
    GARDENA-Lauf), beachtet damit auch die Pause.
    """
    aus = dict(sperre or {})
    aus.setdefault("aktiv", 0)
    aus.setdefault("grund", "")
    aus["pause"] = 0
    aus["pause_bis"] = ""
    aus["pause_bis_ts"] = 0
    try:
        bis = int(float((pause or {}).get("bis_ts") or 0))
    except (TypeError, ValueError):
        bis = 0
    if bis > jetzt:
        aus["pause"] = 1
        aus["pause_bis_ts"] = bis
        aus["pause_bis"] = str((pause or {}).get("bis") or "")[:16]
        if not int(aus.get("aktiv") or 0):
            grund = "pause"
            aus["aktiv"] = 1
            aus["grund"] = grund
    return aus


# Wichtigkeit je Bepflanzung, wenn die Zone keine eigene traegt: 1 = zuerst,
# 3 = zuletzt. Gemuese, Kuebel und Erdbeeren vertrocknen in einer Nacht,
# Rasen erholt sich nach einer braunen Woche.
WICHTIGKEIT_BEPFLANZUNG = {
    "gemuese_klein": 1, "moehren": 1, "kohl": 1, "tomate": 1, "erdbeere": 1,
    "topf_kuebel": 1,
    "beerenstraucher": 2, "hecke_gehoelz": 2, "staudenbeet": 2,
    "rasen_kuehl": 3, "rasen_warm": 3, "rasen_sparsam": 3,
}
WICHTIGKEIT_VORGABE = 2


def _zahl_oder_null(w) -> float:
    try:
        z = float(w)
    except (TypeError, ValueError):
        return 0.0
    return z if z == z and z not in (float("inf"), float("-inf")) else 0.0


def wichtigkeit(zone: dict) -> int:
    """1, 2 oder 3. Leer oder 0 heisst 'automatisch aus der Bepflanzung'."""
    w = int(_zahl_oder_null(zone.get("wichtigkeit")))
    if 1 <= w <= 3:
        return w
    return WICHTIGKEIT_BEPFLANZUNG.get(str(zone.get("bepflanzung") or ""), WICHTIGKEIT_VORGABE)


def liter_je_nacht(zone: dict, sekunden: float, durchlaeufe: int) -> tuple:
    """Wie viel Wasser nimmt diese Zone heute Nacht aus dem Vorrat?

    Zuerst aus dem Durchfluss (Liter je Minute, an der Wasseruhr gemessen),
    sonst aus Becherprobe mal Flaeche (1 mm auf 1 m2 = 1 Liter). Eine Rate aus
    der Regnertabelle zaehlt nicht - geraten wird nichts. Rueckgabe
    (Liter, 'durchfluss'|'becherprobe') oder (None, '') wenn unbekannt.
    """
    if sekunden <= 0 or durchlaeufe <= 0:
        return 0.0, ""
    minuten = float(sekunden) * int(durchlaeufe) / 60.0
    d = _zahl_oder_null(zone.get("durchfluss_lmin"))
    if d > 0:
        return minuten * d, "durchfluss"
    rate = _zahl_oder_null(zone.get("rate_mmh"))
    flaeche = _zahl_oder_null(zone.get("flaeche"))
    if int(_zahl_oder_null(zone.get("rate_gemessen"))) and rate > 0 and flaeche > 0:
        return rate * flaeche * minuten / 60.0, "becherprobe"
    return None, ""


def zisterne_rangfolge(plan: dict, zonen: list, vorrat_l: float, reserve_l: float) -> dict:
    """Reicht der Vorrat nicht fuer alle geplanten Zonen, gehen die wichtigen vor.

    'plan' ist das Ergebnis von plan_bauen() und wird hier geaendert: eine
    ausgelassene Zone bekommt sekunden_soll = 0 und durchlaeufe = 0 (der alte
    Wert bleibt als sekunden_soll_ohne_zisterne stehen). Verbraucht wird
    hoechstens Vorrat minus Reserve.

    Reihenfolge: Wichtigkeit 1 vor 2 vor 3, bei gleicher Wichtigkeit die
    Reihenfolge der Zonentabelle. Innerhalb einer Wichtigkeit darf eine
    kleinere Zone noch nachruecken, wenn eine groessere nicht mehr passte;
    eine weniger wichtige Zone kommt dann aber nicht mehr dran - sonst bekaeme
    der Rasen Wasser, das dem Gemuese fehlt.

    Zonen ohne bekannte Menge (kein Durchfluss, keine Becherprobe mit Flaeche)
    werden nicht mitgezaehlt und laufen wie bisher - ausser der Vorrat liegt
    schon an oder unter der Reserve: dann gehen ALLE geplanten Zonen aus, denn
    jede nimmt Wasser.
    """
    je = plan.get("je_zone") if isinstance(plan.get("je_zone"), dict) else {}
    vorrat = max(0.0, _zahl_oder_null(vorrat_l))
    reserve = max(0.0, _zahl_oder_null(reserve_l))
    verfuegbar = max(0.0, vorrat - reserve)
    info = {"aktiv": 1, "vorrat_l": round(vorrat), "reserve_l": round(reserve),
            "verfuegbar_l": round(verfuegbar), "bedarf_l": 0, "bedient_l": 0,
            "ausgelassen": [], "ohne_menge": [], "reihenfolge": [], "knapp": 0,
            "an_reserve": 1 if verfuegbar <= 0 else 0}
    kand = []
    for i, z in enumerate(zonen if isinstance(zonen, list) else []):
        if not isinstance(z, dict):
            continue
        s = str(z.get("schluessel") or "")
        jz = je.get(s) if s else None
        if not isinstance(jz, dict):
            continue
        sek = _zahl_oder_null(jz.get("sekunden_soll"))
        n = int(_zahl_oder_null(jz.get("durchlaeufe")))
        if sek <= 0 or n <= 0:
            continue
        name = str(z.get("name") or s)
        liter, wie = liter_je_nacht(z, sek, n)
        if liter is None:
            if verfuegbar <= 0:
                kand.append((0, i, s, name, None, ""))
            else:
                info["ohne_menge"].append(name)
            continue
        kand.append((wichtigkeit(z), i, s, name, float(liter), wie))
    kand.sort(key=lambda k: (k[0], k[1]))
    rest = verfuegbar
    gesperrt_ab = None          # erste Wichtigkeit, in der eine Zone nicht mehr passte
    bedarf = 0.0
    bedient = 0.0
    for (w, _i, s, name, liter, wie) in kand:
        if liter is not None:
            bedarf += liter
        passt = (liter is not None and liter <= rest + 1e-6
                 and (gesperrt_ab is None or w <= gesperrt_ab))
        if passt:
            rest -= liter
            bedient += liter
            info["reihenfolge"].append({"zone": s, "name": name, "wichtigkeit": w,
                                        "liter": round(liter), "wie": wie, "bedient": 1})
            continue
        if gesperrt_ab is None or w < gesperrt_ab:
            gesperrt_ab = w
        jz = je[s]
        jz["sekunden_soll_ohne_zisterne"] = jz.get("sekunden_soll", 0)
        jz["sekunden_soll"] = 0
        jz["durchlaeufe"] = 0
        jz["zisterne_ausgelassen"] = 1
        info["ausgelassen"].append(name)
        info["reihenfolge"].append({"zone": s, "name": name, "wichtigkeit": w,
                                    "liter": round(liter) if liter is not None else None,
                                    "wie": wie, "bedient": 0})
    info["bedarf_l"] = round(bedarf)
    info["bedient_l"] = round(bedient)
    if info["ausgelassen"]:
        info["knapp"] = 1
        plan["reicht"] = 0
        if not any(int(_zahl_oder_null(j.get("durchlaeufe"))) > 0
                   for j in je.values() if isinstance(j, dict)):
            plan["durchlaeufe_ohne_zisterne"] = plan.get("durchlaeufe", 0)
            plan["durchlaeufe"] = 0
        if str(plan.get("grund") or "") in ("", "ventilzeit_gedeckelt", "fenster_gekuerzt",
                                             "rate_fehlt_teilweise"):
            grund = "zisterne_knapp"
            plan["grund"] = grund
    plan["zisterne"] = info
    return info


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
              "Der Grund bleibt hier der aus 0.9.6: '%s' - in DIESEM Fall "
              "ist die Anlage ohnehin am Limit, und dieser Grund geht vor"
              % pl_k["grund"]))

    # --- A5 (neu in 0.9.22): eigene Zonendauer UEBER dem Deckel -----------
    #
    # Die Pruefung darueber benutzt eine Zone OHNE eigene 'dauer_s'. Dort
    # kann der Deckel gar nicht mit der eigenen Dauer kollidieren, und
    # deshalb blieb sie gruen, waehrend 'reicht' in 274 von 720 zulaessigen
    # Kombinationen faelschlich 1 meldete. Diese Zeile misst genau den Fall,
    # den die andere nicht erreicht.
    # Der Bedarf wird hier unmittelbar gesetzt, nicht ueber zone_rechnen():
    # gemessen wurde der Fall mit 2,47 mm Bedarf - bei einem grossen Bedarf
    # ist die Anlage ohnehin am Limit, und dann misst die Zeile nicht mehr
    # den Deckel, sondern die Fenstergrenze.
    tief = {"schluessel": "tief", "name": "Tropfbeet", "rate_mmh": 2.0,
            "im_zyklus": 1, "dauer_s": 2400}
    e_t = {"tief": {"ok": 1, "bedarf_mm": 2.47, "dr": 2.47, "fuellstand": 10.0}}
    pl_t = plan_bauen([tief], e_t, dict(cfg_w, zonendauer_max_s=1800,
                                        zonendauer_s=240, pause_min=45,
                                        max_durchlaeufe=8, wirkungsgrad=0.75,
                                        fenster_von="22:00", fenster_bis="08:00"))
    e.append((pl_t["ventilzeit_deckt"] == 0 and pl_t["reicht"] == 0,
              "Eigene Zonendauer (2400 s) ueber dem Deckel (1800 s): "
              "reicht=%d, ventilzeit_deckt=%d - bis 0.9.21 stand hier "
              "reicht=1" % (pl_t["reicht"], pl_t["ventilzeit_deckt"])))
    e.append((pl_t["grund"] == "ventilzeit_gedeckelt",
              "... und der Grund benennt den Deckel: '%s'" % pl_t["grund"]))
    # GEGENPROBE: dieselbe Zone, eigene Dauer UNTER dem Deckel. Ohne diese
    # Zeile ginge eine Korrektur durch, die 'reicht' einfach immer auf 0
    # setzt.
    flach = dict(tief, schluessel="flach", dauer_s=1200)
    e_f = {"flach": {"ok": 1, "bedarf_mm": 2.47, "dr": 2.47, "fuellstand": 10.0}}
    pl_f = plan_bauen([flach], e_f, dict(cfg_w, zonendauer_max_s=1800,
                                         zonendauer_s=240, pause_min=45,
                                         max_durchlaeufe=8, wirkungsgrad=0.75,
                                         fenster_von="22:00", fenster_bis="08:00"))
    e.append((pl_f["ventilzeit_deckt"] == 1 and pl_f["reicht"] == 1,
              "GEGENPROBE eigene Zonendauer (1200 s) unter dem Deckel: "
              "reicht=%d, ventilzeit_deckt=%d" % (pl_f["reicht"],
                                                  pl_f["ventilzeit_deckt"])))
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

    # --- Wachstumsphasen (0.9.49) ---
    ph = {"tage": [30, 40, 45, 30], "kc_ini": 0.6, "kc_mid": 1.15, "kc_end": 0.8}
    tag0 = datetime.date(2026, 6, 15)
    # Nur et0 2 mm je Tag, ohne Regen: Tag der Kultur 29 bis 32 (zwei Tage
    # Anfang, zwei Entwicklung). Von Hand: 2*(0,6 + 0,6 + 0,61375 + 0,6275) = 4,8825 mm.
    v4 = [{"et0": 2.0, "regen": 0.0, "datum": (tag0 + datetime.timedelta(days=i)).isoformat()}
          for i in range(28, 32)]
    z_ph = dict(zone, kc=1.15, zr=1.0, theta_fc=0.27, theta_wp=0.13, dr=0.0,
                pflanzdatum=tag0.isoformat(), phasen=ph)
    r_ph = zone_rechnen(z_ph, v4, [], cfg, None, tag0 + datetime.timedelta(days=31))
    p("Kc je Tag in der Bilanz, Tag 29 bis 32 (von Hand)", r_ph["dr"], 4.8825, 0.0001)
    e.append((r_ph["kc_phase"] == "entwicklung" and r_ph["kc_tag_nr"] == 32
              and abs(r_ph["kc"] - 0.6275) < 1e-9,
              "Zone zeigt Phase und Kc von heute (%s, %.4f)" % (r_ph["kc_phase"], r_ph["kc"])))
    # Vorschau: Tag 71 und 72 sind Mitte, heute (Tag 70) noch Entwicklung-Ende.
    r_vs = zone_rechnen(z_ph, [{"et0": 0.0, "regen": 0.0}], [{"et0": 4.0}, {"et0": 4.0}],
                        cfg, None, tag0 + datetime.timedelta(days=69))
    p("etc_kommend mit Kc des kommenden Datums", r_vs["etc_kommend"], 9.2, 0.0001)
    # Ohne Datum, mit kaputtem Datum und ohne Phasen: das alte Ergebnis, Schluessel fuer Schluessel.
    z_alt = dict(zone, dr=0.0)
    r_alt = zone_rechnen(z_alt, vor7, [], cfg)
    e.append((zone_rechnen(dict(z_alt, pflanzdatum="", phasen=ph), vor7, [], cfg) == r_alt
              and zone_rechnen(dict(z_alt, pflanzdatum="2026-02-30", phasen=ph), vor7, [], cfg) == r_alt
              and zone_rechnen(dict(z_alt, pflanzdatum=tag0.isoformat()), vor7, [], cfg) == r_alt,
              "Leeres oder ungueltiges Datum und Bepflanzung ohne Phasen: Ergebnis unveraendert"))
    # Gl. 62 nicht in der Anfangsphase, wohl aber in der Mitte.
    w62 = {"u2": 3.0, "rh_min": 25.0}
    z62 = dict(z_ph, hoehe_pflanze=0.6)
    r_a = zone_rechnen(z62, [], [], cfg, w62, tag0 + datetime.timedelta(days=4))
    r_m = zone_rechnen(z62, [], [], cfg, w62, tag0 + datetime.timedelta(days=80))
    e.append((r_a["kc"] == 0.6 and r_a["kc_klima"] == 0
              and abs(r_m["kc"] - 1.224) < 0.002 and r_m["kc_klima"] == 1
              and r_m["kc_tabelle"] == 1.15,
              "Gl. 62 nur fuer Mitte und Ende: Anfang %.3f, Mitte %.3f" % (r_a["kc"], r_m["kc"])))
    e.append((pflanzdatum_lesen("2027-06-01", tag0) is not None
              and pflanzdatum_lesen("2027-06-17", tag0) is None
              and pflanzdatum_ungueltig("31.12.2026", tag0)
              and not pflanzdatum_ungueltig("", tag0),
              "Datum: bis ein Jahr voraus gilt, weiter oder unlesbar nicht"))

    # C6 (Durchgang 30.09.2026): Fenster 30 min, drei Zonen - die Summe aus
    # Ventilzeiten und Pausen bleibt im Fenster.
    z6 = [dict(zone, schluessel="c6_%d" % i, name="c6_%d" % i) for i in range(3)]
    erg6 = {z["schluessel"]: zone_rechnen(dict(z, dr=100.0), [],
            [{"et0": 6.0, "regen": 0.0}], cfg) for z in z6}
    pl6 = plan_bauen(z6, erg6, dict(cfg, fenster_von="22:00", fenster_bis="22:30",
                                    zonendauer_max_s=3600))
    min6 = (pl6["durchlaeufe"] * sum(j.get("sekunden_soll", 0)
                                     for j in pl6["je_zone"].values()) / 60.0
            + max(0, pl6["durchlaeufe"] - 1) * cfg["pause_min"])
    e.append((pl6["durchlaeufe"] >= 1 and 0 < min6 <= 30.0
              and pl6["fenster_gekuerzt"] == 1 and pl6["ventilzeit_deckt"] == 0
              and pl6["reicht"] == 0,
              "Fenster 30 min, drei Zonen: %.1f min Ventilzeit samt Pausen "
              "(hoechstens 30), anteilig gekuerzt" % min6))
    # a1 (Verbesserungsbau 30.09.2026): die gekuerzten Minuten sind die
    # Ueberziehung des ungekuerzten Plans. Derselbe Plan ohne Fenstergrenze
    # (00:00 bis 23:59) rechnet die Ventilzeiten ungekuerzt.
    pl6o = plan_bauen(z6, erg6, dict(cfg, fenster_von="00:00", fenster_bis="23:59",
                                     zonendauer_max_s=3600,
                                     max_durchlaeufe=pl6["durchlaeufe"]))
    ohne6 = (pl6o["durchlaeufe"] * sum(j.get("sekunden_soll", 0)
                                       for j in pl6o["je_zone"].values()) / 60.0)
    mit6 = (pl6["durchlaeufe"] * sum(j.get("sekunden_soll", 0)
                                     for j in pl6["je_zone"].values()) / 60.0)
    e.append((pl6o["durchlaeufe"] == pl6["durchlaeufe"]
              and pl6o["fenster_gekuerzt_min"] == 0
              and abs(pl6["fenster_gekuerzt_min"] - (ohne6 - mit6)) <= 1.0,
              "Gekuerzt: %d min (ungekuerzt %.1f, gekuerzt %.1f min Ventilzeit); "
              "ohne Kuerzung 0" % (pl6["fenster_gekuerzt_min"], ohne6, mit6)))

    # Anlage am Limit -> benannt, nicht beschoenigt
    erg4 = {z["schluessel"]: zone_rechnen(dict(z, dr=100.0), [],
            [{"et0": 6.0, "regen": 0.0}, {"et0": 6.0, "regen": 0.0}], cfg) for z in zonen}
    pl4 = plan_bauen(zonen, erg4, dict(cfg, max_durchlaeufe=2))
    e.append((pl4["reicht"] == 0 and pl4["grund"] == "anlage_am_limit",
              "Grosser Bedarf, harte Grenze: 'anlage_am_limit' statt Schoenrechnen "
              "(noetig %d, moeglich %d)" % (pl4["noetige_durchlaeufe"],
                                            pl4["moegliche_durchlaeufe"])))

    # 0.9.52: Pause wie eine Sperre, endet von selbst; Frost behaelt den Grund.
    pa = pause_einrechnen({"aktiv": 0, "grund": ""}, {"bis_ts": 2000, "bis": "2026-11-08"}, 1000)
    pb = pause_einrechnen({"aktiv": 0, "grund": ""}, {"bis_ts": 2000}, 2000)
    pc = pause_einrechnen({"aktiv": 1, "grund": "sperre_frost"}, {"bis_ts": 2000}, 1000)
    e.append((pa["aktiv"] == 1 and pa["grund"] == "pause" and pb["aktiv"] == 0 and pb["pause"] == 0
              and pc["grund"] == "sperre_frost" and pc["pause"] == 1,
              "Pause: greift bis zum Ende, endet von selbst, Frost behaelt den Grund"))
    # 0.9.52: Rangfolge - Gemuese vor Stauden vor Rasen, Reserve bleibt.
    zr = [{"schluessel": "g", "name": "Gemuese", "bepflanzung": "gemuese_klein", "durchfluss_lmin": 10},
          {"schluessel": "r", "name": "Rasen", "bepflanzung": "rasen_kuehl", "durchfluss_lmin": 30},
          {"schluessel": "s", "name": "Stauden", "bepflanzung": "staudenbeet", "durchfluss_lmin": 15}]
    plr = {"durchlaeufe": 1, "reicht": 1, "grund": "",
           "je_zone": {"g": {"sekunden_soll": 600, "durchlaeufe": 1},
                       "r": {"sekunden_soll": 600, "durchlaeufe": 1},
                       "s": {"sekunden_soll": 600, "durchlaeufe": 1}}}
    ir = zisterne_rangfolge(plr, zr, 400.0, 100.0)
    e.append((ir["ausgelassen"] == ["Rasen"] and plr["je_zone"]["r"]["sekunden_soll"] == 0
              and plr["je_zone"]["s"]["sekunden_soll"] == 600 and plr["grund"] == "zisterne_knapp"
              and ir["bedient_l"] == 250 and plr["reicht"] == 0,
              "Zisterne 400 l, Reserve 100 l: Gemuese 100 l und Stauden 150 l, Rasen 300 l aus"))
    return e


if __name__ == "__main__":
    fehlt = 0
    for ok, text in selbstpruefung():
        print(("[OK]   " if ok else "[FEHL] ") + text)
        fehlt += 0 if ok else 1
    raise SystemExit(1 if fehlt else 0)
