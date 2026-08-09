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

## Neu in 0.9.1

Eine Durchsicht hat neun Stellen zutage gefördert. Keine davon ändert das
Verhalten bei heilen Daten — die FAO-56-Rechnung liefert für das
veröffentlichte Beispiel 18 unverändert 3,88 mm/Tag.

**Die schwerwiegendste zuerst:** `postinstall.sh` setzte die Rechte der
Konfigurationsdateien, aber nie den **Eigentümer**. LoxBerry führt das Skript
als `root` aus; alles, was dabei entsteht — die mit `echo {} >` angelegten
Dateien ebenso wie die mit `cp -p` aus der Sicherung zurückgeholten — gehörte
danach `root`. Oberfläche und Dienst laufen als `loxberry` und konnten lesen,
aber nicht schreiben. Wer nach der Installation eine Zone anlegte und auf
Speichern klickte, verlor die Eingabe. Das betraf nicht nur das Update, sondern
schon die Erstinstallation. Jetzt steht dort ein `chown -R loxberry:loxberry`.

- **Eine Zone ohne gemessene Niederschlagsrate wird benannt, nicht
  verschwiegen.** Bisher ergab sie null nötige Durchläufe, und weil der Plan
  nur die größte Zahl nimmt, stand am Ende `kein_bedarf` — eine durstige Zone
  wurde als versorgt gemeldet. Jetzt lautet der Grund `rate_fehlt`, und die
  betroffene Zone steht mit Namen dabei. Geraten wird nichts: eine erfundene
  Laufzeit wäre je nach Regner um den Faktor sechzehn falsch.
- **Gleiche Anfangs- und Endzeit des Gießfensters ergibt 0 Minuten, nicht
  1440.** `08:00 bis 08:00` fiel bisher in den Mitternachtszweig und kam als
  volle 24 Stunden heraus. Die Oberfläche weist die Eingabe jetzt schon beim
  Speichern zurück und nennt die gemeinte Schreibweise (`00:00` bis `23:59`).
- **Der Tagesindex folgt dem echten Kalender.** Er wurde immer mit dem Jahr
  2001 gebildet; in einem Schaltjahr lag dadurch jeder Tag ab dem 1. März um
  eine Nummer zu niedrig, und die extraterrestrische Strahlung wich um bis zu
  1,4 Prozent ab. Der Teiler 365 in Gleichung 24 bleibt, wie er ist — so
  definiert ihn das Standardwerk, und ihn auf 366 zu setzen würde den Fehler
  vergrößern, nicht verkleinern.
- **`publish` vor der MQTT-Zeile.** Das Verb fehlte hier als einzigem Plugin
  dieser Reihe. Dazu werden Zeilenumbrüche aus den Werten und Leerzeichen aus
  den Themennamen entfernt — eine Zone namens „Rasen hinten" hätte das Thema
  sonst mitten im Namen abgeschnitten.
- **Ein Zonenfehler heißt nicht mehr „Zone unbekannt".** Der Endpunkt
  unterschied nicht zwischen einem falschen Zonenschlüssel und einer Zone, die
  sich nicht rechnen ließ. Wer das in Loxone sah, suchte einen Tippfehler, den
  es nicht gab. Jetzt gibt es `ZONE_UNBEKANNT`, `NOCH_NICHT_GERECHNET` und
  `BERECHNUNGSFEHLER`, jeweils mit Klartext.
- **Das Aktionstoken entsteht hinter einer Dateisperre**, das Protokoll wird
  mit `LOCK_EX` geschrieben, und die Zeitzone wird ausdrücklich gesetzt — sonst
  standen PHP- und Python-Zeilen mit Versatz nebeneinander in derselben Datei.
  Die Rotation überlässt PHP jetzt dem Dienst, solange dieser läuft: kürzte PHP
  die Datei unter dem offenen Dateizeiger des Dienstes, entstand davor ein Loch
  aus Null-Bytes.
- **Nebendateien beim atomaren Schreiben sind eindeutig** (Prozessnummer im
  Namen), in PHP wie in Python. `<datei>.tmp` kollidierte, sobald neben dem
  Dienst ein zweiter Lauf über „Jetzt rechnen" schrieb. Python macht zusätzlich
  ein `fsync`, bevor umbenannt wird.
- **Open-Meteo wirft nicht mehr durch.** Die Zeitgrenze wurde bereits im Dienst
  abgefangen; die Funktion gibt jetzt selbst ein leeres, wohlgeformtes Ergebnis
  zurück, damit sie auch von anderer Stelle gefahrlos aufrufbar ist.
- **Eingehende MQTT-Nutzlasten werden nur einmal zerlegt.** Gemessen: 100
  Abfragen auf dieselbe Nutzlast brauchen jetzt einen `json.loads`-Aufruf statt
  hundert. Der Zeitgewinn ist klein — der eigentliche ist, dass eine kaputte
  Nutzlast einmal als kaputt erkannt wird.

**Oberfläche nach Hausstandard:** 25 Bedienelemente hatten kein
`data-role="none"` und wurden vom jQuery-Mobile-Thema umgezeichnet; keines der
zehn Formulare hatte `action="index.php"`, sodass ein Klick auf Speichern bei
Aufruf über das Verzeichnis auf der LoxBerry-Startseite landete; die Reiter
waren `href="#"` und ohne JavaScript unerreichbar. Alle drei sind behoben.
Die drei `__pycache__`-Dateien sind aus dem Archiv entfernt.


### Nachtrag zu 0.9.1

- **Mikroklima-Faktor je Zone.** `ETc = Kc · ET0` unterstellt die freie Fläche
  der Grasreferenz; ein Garten ist das selten. Der Faktor korrigiert das
  optional: leer oder 1,0 ändert nichts, 0,8 Halbschatten, 0,6 Nordseite,
  0,4 dichter Vollschatten. Nach oben gilt dasselbe und wird meist vergessen:
  1,2 bis 1,3 vor einer Südmauer oder im Kiesbeet. Er wirkt auf ETc, nicht auf
  ET0 — die Referenzverdunstung am Standort bleibt für alle Zonen dieselbe
  Zahl, sie je Zone zu verbiegen wäre eine Falschaussage über das Wetter. Eine
  0 gilt als „nichts eingetragen", nicht als „verdunstet nie".
- **Der Dienst läuft jetzt auch ohne virtuelle Python-Umgebung.**
  `postinstall.sh` sagte zu: „Das Plugin läuft trotzdem — dann aber ohne
  MQTT-Quellen", falls sich die Umgebung nicht anlegen lässt (etwa ohne das
  Paket `python3-venv`). `dienst.sh` hielt sich nicht daran: es bestand auf
  `venv/bin/python3` und verweigerte den Start mit „Plugin neu installieren".
  Die Installation meldete also Erfolg, und der Dienst lief nie an — auch der
  Reiter Test schlug fehl, mit einem Hinweis auf die falsche Ursache. Jetzt ist
  der System-Python die Rückfallebene, und der Selbsttest nennt, welcher
  Interpreter läuft und wo `paho-mqtt` dann liegen müsste.

## Grundlage

FAO Irrigation and Drainage Paper 56 (Allen, Pereira, Raes, Smith), Kapitel 4
und 8. Vorhersagedaten von Open-Meteo — kostenlos und ohne Schlüssel für nicht
gewerbliche Nutzung, ebenfalls nach FAO-56 Penman-Monteith gerechnet.
