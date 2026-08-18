# LoxBerry-Plugin: Bewässerung vorausschauend

Gießen nach **Wasserbilanz** statt nach Zeitplan. Das Plugin rechnet nach dem
Standardverfahren **FAO-56**, wie viel Wasser der Boden je Zone verloren hat,
zieht den erwarteten Regen der nächsten Tage ab und sagt Loxone, wie viele
Durchläufe heute Nacht nötig sind.

> **Fassung 0.9.7 — ungeprüft im Betrieb.** Die Rechnung selbst ist gegen das
> veröffentlichte Rechenbeispiel aus FAO-56 geprüft; ob die Messwertzuordnung
> zu Ihrer Wetterstation passt, zeigt erst der Betrieb. Diese Angabe stand bis
> 0.9.6 auf „0.9.0" — sechs Fassungen lang.

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

## Neu in 0.9.7

**Zuerst die einzige Änderung, die ohne Ihr Zutun greift.** Der neue Schalter
*Fehlende Tage im Verlauf nachtragen* steht ab Werk auf **an**. Grund: eine
Lücke im Verlauf ist kein Geschmack, sondern ein Messfehler. Der Dienst
schrieb nur den jeweils heutigen Tag; war der LoxBerry aus oder das Netz weg,
fehlte der Tag für immer, und die Fortschreibung übersprang ihn stillschweigend.

Gemessen an einer Zone mit 105 mm Speicher, vierzehn Tage trocken bei
ET0 5 mm/Tag: fehlen fünf Tage, sinkt der gemeldete Bedarf von **24,3 auf
9,2 mm** — auf 200 m² sind das **3 000 Liter**, die niemand ausbringt, weil das
Plugin sie nicht verlangt. Die Daten dafür holt der Dienst bei jedem Lauf
ohnehin mit (`past_days=10`) und warf sie bis 0.9.6 weg. Nachgetragen werden
nur Tage, die **gar nicht** dastehen; ein vorhandener Tag wird nie
überschrieben. Abschalten im Reiter Einstellungen — die 0 überlebt jedes
weitere Speichern, und der Reiter Test sagt, was gilt.

Alle übrigen neuen Funktionen sind **ab Werk aus** und ändern an einer
bestehenden Anlage nichts. Nachgemessen: 280 Werte aus vier Wetterlagen und
vier FAO-Rechnungen sind gegenüber 0.9.6 unverändert.

### Der schwerste Befund: die eigene Station machte die Rechnung schlechter

**Alle vier mitgelieferten Stationsvorlagen** — Ecowitt lokal, ecowitt2mqtt,
WeeWX und WeatherFlow — zeigten `tmin` und `tmax` auf **dieselbe Quelle**. Eine
Wetterstation liefert einen Momentanwert; FAO-56 rechnet mit Tiefst- und
Höchstwert des Tages. In der Rechnung kam damit Tmax − Tmin = 0 heraus.

Gemessen für einen Sommertag von 12 bis 28 °C ohne Strahlungsmesser:

    richtige Spanne     ET0 = 5,40 mm    (Rs = 25,8 MJ)
    tmin = tmax = 22    ET0 = 1,95 mm    (Rs =  0,0 MJ, denn Wurzel aus 0 ist 0)

Wer seine eigene Station nach Vorlage einrichtete, bekam eine dreifach zu
kleine Verdunstung — und zwar still, gekennzeichnet als „geschätzt" statt als
Fehler. Die Auflösung braucht keine Umstellung: der Dienst merkt sich den
Tagesverlauf je Messgröße und gibt für `tmin` das Minimum und für `tmax` das
Maximum des Tages zurück. Das ist in beiden Fällen richtig — auch wenn Ihre
Station einen echten Tagestiefstwert liefert, denn dessen Minimum über den Tag
ist derselbe Wert. Wind und Strahlung werden gemittelt; deckt die Messreihe
weniger als 18 Stunden ab, gilt der Mittelwert als zu dünn und die Größe fällt
auf Open-Meteo zurück.

### Die Bilanz erfährt jetzt, was ausgebracht wurde

Die Bilanzgleichung hatte seit jeher ein Feld für die Bewässerung — gefüllt
hat es nichts. Das Plugin schrieb den Wasserhaushalt fort, als würde nie
gegossen. Gemessen, vierzehn Tage trocken:

| | Defizit | Füllstand | Bedarf | Plan |
|---|---|---|---|---|
| ohne Rückmeldung | 63,2 mm | 40 % | 24,3 mm | 8 von 49 — „die Anlage schafft es nicht" |
| mit 4 mm je Nacht | 10,5 mm | 90 % | 0,0 mm | „kein Bedarf" |

Tragen Sie im Reiter Zonen je Kreis ein **Rückmeldethema** ein und lassen Sie
Loxone dorthin die Laufminuten oder die fertigen Durchläufe der Nacht
schreiben. Kein neuer Endpunkt: der unangemeldete Bereich darf nichts
schreiben, und ein Endpunkt, der die Wasserbilanz verstellen kann, wäre eine
Angriffsfläche ohne Gegenwert. **Ohne Becherprobe bleibt die Rückmeldung
wirkungslos** — aus Laufzeit wird nur mit gemessener Rate eine Höhe, und eine
erfundene wäre je nach Regner um den Faktor sechzehn falsch.

### Ventilzeit je Zone — die Zahl für Tv1 bis Tv8

Bis 0.9.6 galt **eine** Zonendauer für alle Kreise, und der Plan gab **eine**
Durchlaufzahl aus. Die mitgelieferte Regnertabelle reicht von 4 mm/h
(Tropfer) bis 35 mm/h (Sprühdüsen) — Faktor neun. Gemessen an zwei Zonen mit
je 13,9 mm Bedarf und 240 s Dauer:

    Rasen (35 mm/h)          bekam 21,0 mm   ->  50 Prozent zu viel
    Tropfschlauchbeet (5)    bekam  3,0 mm   ->  80 Prozent zu wenig

Jede Zone kann jetzt eine eigene Dauer tragen, und der Plan rechnet je Zone
eine **Ventilzeit**: die Sekunden je Durchlauf, mit denen genau diese Zone
nach der geplanten Zahl von Durchläufen ihren Bedarf gedeckt hat. Für dasselbe
Beispiel: 239 s für die Sprühdüsen, 1 674 s für den Tropfschlauch. Das ist die
Zahl, die auf Tv1 bis Tv8 des Bewässerungsbausteins gehört. Reicht die längste
erlaubte Ventilzeit nicht, wird die Zone **benannt** statt beschönigt.

### Frost, Sturm, Starkregen — drei Sperren, alle ab Werk aus

Jeder Vorschautag trug bereits Tiefsttemperatur und Wind; gelesen wurden nur
Verdunstung und Regen. Die Messgröße *Regenrate* war im Reiter Quellen
zuordenbar und wurde von **keiner Zeile Code** gelesen. Alle drei Sperren
lassen sich jetzt einschalten; eingeschaltet setzen sie die Durchläufe auf
null und nennen den Grund — was ohne die Sperre nötig gewesen wäre, steht
daneben. **Ohne Daten wird nie gesperrt:** eine Sperre aus einem Netzausfall
abzuleiten hieße, den Garten trockenzulegen.

### Weiteres

- **Der Dienst läuft nach einem Update wieder an.** `preupgrade.sh` hielt ihn
  über `dienst.sh stop` an, und `stop` entfernt den Sollmerker, an dem der
  minütliche Wächter hängt. `postinstall.sh` rief niemals `start`. Nach **jedem**
  Update stand das Plugin still, bis jemand die Oberfläche öffnete — und weil
  der Endpunkt weiter den letzten Stand auslieferte, sah das in Loxone nicht
  nach einem Defekt aus, sondern nach einem ruhigen Garten. Ein bewusst
  angehaltener Dienst bleibt angehalten.
- **Reiter Verlauf.** Die Verlaufsdatei hält bis zu 400 Tage und wurde bis
  0.9.6 an genau einer Stelle benutzt: um die Tage zu *zählen*. Jetzt stehen
  Verdunstung, Regen und ausgebrachte Menge Tag für Tag da, mit Summen.
- **`?selftest=1` am Endpunkt** — die Tokenprobe des Hausstandards, ohne jede
  Wirkung. Und der **Reiter Test ruft den eigenen Endpunkt wirklich auf**, mit
  drei Ausgängen: Haken, Kreuz mit Code, und *Hinweis* statt Kreuz, wenn gar
  keine Antwort kommt — ein Webserver, der eine Anfrage zugleich bearbeitet,
  kann sich beim Seitenaufbau nicht selbst aufrufen.
- **Der Reiter Quellen zeigt, was zuletzt angekommen ist.** Zwei Vorlagen
  sagten das seit jeher zu; die dafür vorgesehene Datei wurde nie geschrieben.
- **Drei Gründe hatten keinen Satz.** `rate_fehlt`, `rate_fehlt_teilweise` und
  `fenster_ungueltig` fehlten in **beiden** Sprachdateien — im Reiter Test
  stand buchstäblich „GRUND.RATE_FEHLT". Ausgerechnet der Fall, den der
  Quelltext als den gefährlichsten des Moduls bezeichnet. Und die Zonen ohne
  Niederschlagsrate werden jetzt mit Namen genannt, wie es seit 0.9.1 zugesagt
  war.
- **Die feste Rechenzeit gibt es wirklich.** Der Schlüssel `rechenzeit` stand
  seit 0.9.0 mit dem Kommentar „wann der Plan für die Nacht steht" in der
  Vorgabeliste und wurde von keiner Zeile gelesen.
- **Ein Bodenfeuchtefühler altert jetzt.** Er wurde am Verfallsdatum vorbei
  gelesen, das für jede andere Messgröße gilt; ein bei „nass" stehengebliebener
  Fühler hätte die Bewässerung auf Dauer abgeschaltet. Dasselbe für die
  HTTP-Quelle, die gar keine Altersgrenze hatte.
- **Zwei Eingaben ohne Wirkung sind jetzt erreichbar:** der
  Oberflächenabfluss-Anteil je Zone (Hanglage) und das Sensorgewicht. Beide
  wurden von der Rechnung gelesen und hatten kein Eingabefeld.
- **Das Datum der Becherprobe überlebt das Speichern.** Es wurde geschrieben
  und beim nächsten Speichern der Zonentabelle still gelöscht.
- **MQTT:** `alter` stand fest auf 0 und meldete als retained-Wert für immer
  „gerade eben gerechnet". `et0` wurde bei fehlgeschlagener Rechnung als 0
  gesendet. Und `<zone>/defizit_mm` trug den *Bedarf*, während das gleichnamige
  Feld am HTTP-Endpunkt das *Defizit* führt — gemessen lagen sie um den Faktor
  5,4 auseinander. Das Thema behält seine Bedeutung; daneben stehen jetzt die
  eindeutig benannten `bedarf_mm` und `dr_mm`.
- **Der Pflanzenbeiwert lässt sich an trockene Luft und Wind anpassen**
  (FAO-56, Gl. 62) — nur mit eingetragener Pflanzenhöhe, sonst ändert sich
  nichts. Die Größenordnung, gerechnet: +4,6 % beim Rasen, +6,4 % bei Tomaten
  an einem heißen, trockenen, windigen Tag.
- **Meldungen** über den Benachrichtigungsbereich von LoxBerry, wenn die
  Anlage mehrere Tage nicht nachkommt oder die Station schweigt. Ab Werk aus.
- **Der Dienst liest Änderungen ohne Neustart.** Wer im Reiter Quellen ein
  Thema änderte, änderte bis 0.9.6 nichts, bis jemand den Dienst neu startete.
- **Das Protokoll stand doppelt in der Datei** — ein Aufnehmer auf die
  Logdatei und einer auf die Standardausgabe, die `dienst.sh` in dieselbe
  Datei umleitet.

### Wie das geprüft wurde

- Die Selbstprüfungen der drei Rechenmodule laufen durch (FAO-56 Beispiel 18
  unverändert bei 3,88 mm/Tag).
- 41 Wirkungsprüfungen gegen den vollständigen Rechengang, gegen einen
  nachgebauten LoxBerry-Baum und mit fester statt echter Wetterantwort.
- Acht Prüfungen für Installation und Update, samt der Gegenfälle.
- **Und jede der sechzehn Korrekturen ist geeicht:** einzeln zurückgebaut,
  und die zugehörige Prüfung wird rot. Eine Prüfung, die auch ohne die
  Korrektur grün bleibt, prüft nichts — zwei Zeilen sind dabei aufgeflogen und
  wieder entfernt worden, weil sie beweisbar wirkungslos waren.
- 280 Werte aus 0.9.6 und 0.9.7 Zahl für Zahl verglichen: null Abweichungen.

### Was diese Fassung *nicht* beantwortet

Alles hier ist gegen Prüfstände gemessen, nicht an einer laufenden Anlage. Ob
die Rückmeldung aus **Ihrem** Miniserver ankommt, ob die Themen zu **Ihrer**
Wetterstation passen und ob die Ventilzeiten Ihre Regner richtig treffen, zeigt
erst der Betrieb.

## Die Fassungen dazwischen

Diese Datei sprang bisher von 0.9.1 auf 0.9.7. Die Anmerkungen zu den
Fassungen dazwischen stehen auf den Release-Seiten des Repositoriums; hier
in Kurzform, damit die Reihe vollständig ist.

**0.9.2 — übersetzbare Hilfe.** Die Hilfeseite trug ihren Text fest
verdrahtet in `help.html`, auf Deutsch. Wer das Plugin auf Englisch benutzte,
bekam die Hilfe trotzdem auf Deutsch. Jetzt stehen dort nur noch Platzhalter,
der Text in `templates/lang/help_de.ini` und `help_en.ini`.

**0.9.3 — Deinstallation ohne fest verdrahteten Systempfad.** Fand das
Deinstallationsskript die LoxBerry-Wurzel weder über das fünfte Argument noch
über die Umgebung, fiel es auf einen festen Pfad zurück — der ins Leere zeigt,
sobald LoxBerry anderswo installiert ist, und zwar beim Aufräumen, also genau
dann, wenn niemand mehr hinsieht.

**0.9.4 wurde nie veröffentlicht.** Die Nummer fehlt in der Release-Reihe.

**0.9.5 — Sprachdateien nach Hausstandard neu erzeugt.** Jeder Wert in
doppelten Anführungszeichen, damit `parse_ini_file` an einem Semikolon nichts
abschneidet, und kein Schlüssel doppelt im selben Abschnitt.

**0.9.6 — Textpflege, keine Verhaltensänderung.** Umschreibungen wie `laeuft`
und `heisst` durch echte Umlaute ersetzt; nur Sprachdateien. Dazu eine
Richtigstellung in der `LICENSE`, die als Urheber „Sprache Plugin Authors"
nannte — ein Übernahmefehler aus einer Vorlage.

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
