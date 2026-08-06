# LoxBerry-Plugin: Bewässerung vorausschauend

Gießen nach **Wasserbilanz** statt nach Zeitplan. Das Plugin rechnet nach dem
Standardverfahren **FAO-56**, wie viel Wasser der Boden je Zone verloren hat,
zieht den erwarteten Regen der nächsten Tage ab und sagt Loxone, wie viele
Durchläufe heute Nacht nötig sind.

> **Fassung 0.9.0 — ungeprüft im Betrieb.** Die Rechnung selbst ist gegen das
> veröffentlichte Rechenbeispiel aus FAO-56 geprüft; ob die Messwertzuordnung
> zu Ihrer Wetterstation passt, zeigt erst der Betrieb.

## Herstellerneutral — das ist der Kern

Das Plugin kennt **keine** Wetterstation. Es kennt Messgrößen und drei Wege:

| Weg | Wofür |
|---|---|
| `mqtt` | ein Thema je Größe — Ecowitt über ecowitt2mqtt, WeeWX, Zigbee2MQTT, Shelly, ESPHome, Eigenbau |
| `http` | eine JSON-Antwort abholen, Pfad punktgetrennt: `common_list[2].val` |
| `online` | Open-Meteo, kostenlos und ohne Schlüssel |

Vorlagen für Ecowitt (lokal und MQTT), WeeWX, WeatherFlow und freie Zuordnung
liegen bei. **Fehlt eine Größe, fällt genau diese einzeln auf Open-Meteo
zurück** — nicht die ganze Rechnung. Wer nur einen Regenmesser hat, bekommt
seinen echten Regen und den Rest aus dem Modell. Im Ergebnis steht je Größe,
woher sie kam.

## Was gerechnet wird

    ET0  = FAO-56 Penman-Monteith aus Temperatur, Feuchte, Wind, Strahlung
    ETc  = Kc × ET0                                     [FAO-56, Tab. 12]
    TAW  = 1000 (θFC − θWP) Zr                          [FAO-56, Gl. 82]
    RAW  = p × TAW,  p = p_Tab + 0,04 (5 − ETc)         [FAO-56, Gl. 83]
    Dr,i = Dr,i−1 − (P − RO) − I + ETc·Ks + DP          [FAO-56, Gl. 85]

Gegossen wird, wenn `Dr ≥ RAW`. Die Menge deckt das Defizit **bis RAW**, nicht
bis Feldkapazität — auffüllen bis obenhin hieße, dass der nächste Regen
abläuft.

## Der Trockenstress ist eingerechnet

Sobald `Dr > RAW`, bremst der Boden die Verdunstung (Ks, FAO-56 Gl. 84). Wer
das wegläßt, überschätzt den Bedarf in jeder längeren Trockenheit systematisch.

## Die Anlage ist die Grenze, nicht der Bedarf

Der Plan rechnet mit Zonendauer, Pause zwischen den Durchläufen und
Zeitfenster. Reicht das nicht, sagt er das (`REICHT=0`) — statt eine Zahl
auszugeben, die niemand liefern kann. Bei einem Brunnen mit Erholungspause ist
das der Regelfall an heißen Tagen, und man sollte es wissen.

## Millimeter kann es rechnen, Liter nur mit Messung

Für Liter und Minuten braucht es die Niederschlagsrate der Regner. Die steht in
keinem Katalog verlässlich. Deshalb gibt es die **Becherprobe**: Behälter
aufstellen, Zone 15 Minuten laufen lassen, Höhe messen, eintragen. Bis dahin
sind alle Liter- und Minutenangaben mit einem Stern als geschätzt markiert —
auch am Endpunkt (`geschaetzt: 1`).

## Aufbau

    bin/fao56.py              Verdunstung und Bodenwasserhaushalt,
                              mit Selbstprüfung gegen FAO-56 Beispiel 18
    bin/giessplan.py          Bedarf, Vorschau, Plan unter den Anlagengrenzen
    bin/quellen.py            Messwertbezug: MQTT, HTTP-JSON, Open-Meteo
    bin/bewaesserung_dienst.py  Dienst
    templates/quellen.json    Messgrößen, Vorlagen, Einheiten — EINE Datei
    templates/pflanzen.json   Kc, Zr, p, Bodenkennwerte, Regnertypen
    webfrontend/htmlauth/     Oberfläche (sieben Reiter)
    webfrontend/html/         Endpunkt (nur lesend) + Bibliothek

Kein Pflichtpaket. `paho-mqtt` ist freiwillig und nur für MQTT-Quellen nötig.

## Der Endpunkt kann nichts schalten

Er liefert Werte und sonst nichts. Ein Endpunkt im unangemeldeten Bereich, der
Wasser aufdrehen kann, wäre eine Angriffsfläche ohne Gegenwert — geschaltet
wird vom Bewässerungsbaustein im Miniserver.

## Grundlage

FAO Irrigation and Drainage Paper 56 (Allen, Pereira, Raes, Smith), Kapitel 4
und 8. Vorhersagedaten von Open-Meteo — kostenlos und ohne Schlüssel für nicht
gewerbliche Nutzung, ebenfalls nach FAO-56 Penman-Monteith gerechnet.
