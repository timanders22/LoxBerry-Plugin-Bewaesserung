# LoxBerry-Plugin: Bewässerung vorausschauend

Gießen nach **Wasserbilanz** statt nach Zeitplan. Das Plugin rechnet nach dem
Standardverfahren **FAO-56**, wie viel Wasser der Boden je Zone verloren hat,
zieht den erwarteten Regen der nächsten Tage ab und sagt Loxone, wie viele
Durchläufe heute Nacht nötig sind.

> **Fassung 0.9.26 — ungeprüft im Betrieb.** Die Rechnung selbst ist gegen das
> veröffentlichte Rechenbeispiel aus FAO-56 geprüft; ob die Messwertzuordnung
> zu Ihrer Wetterstation passt, zeigt erst der Betrieb. Diese Angabe stand bis
> 0.9.6 auf „0.9.0“ und bis 0.9.18 auf „0.9.7“ — sechs
> und dann elf Fassungen lang. Sie gehört zu den vier Stellen, die
> `Werkzeuge/fassung_setzen.py` mitzieht.

## Neu in 0.9.24

### Der Dienst konnte sein Protokoll verlieren, ohne dass es auffiel

`log/plugins` liegt auf einer Ramdisk (`/dev/zram0`). Wird sie geleert — beim
Neustart, durch LoxBerrys `log_maint`, oder von Hand —, ist die Datei fort. Ein
`RotatingFileHandler`, der sie beim Start **einmal** geöffnet hat, schreibt
danach bis zum nächsten Neustart in einen gelöschten Inode: keine
Fehlermeldung, keine Datei, kein Hinweis. Auch die Rotation greift dann nicht
mehr.

Diese Fassung benutzt deshalb `WachsameRotation` in `bin/bewaesserung_dienst.py` — einen
umlaufenden Handler, der vor jeder Zeile Gerätenummer und Inode vergleicht und
nötigenfalls neu öffnet. Die Standardbibliothek hat für den einen Fall den
`WatchedFileHandler` und für den anderen den `RotatingFileHandler`, aber
nichts, was beides kann; deshalb die eigene Klasse.

Auf dem LoxBerry geeicht, vier Prüfungen und in beide Richtungen: schreiben,
nach dem Löschen weiterschreiben, Umlauf bei Überlänge, nach dem Umlauf erneut
löschen. Mit dem alten Handler ist die Zeile nach dem Löschen verloren und
bleibt es, mit dem neuen steht sie in der wieder angelegten Datei. Auf einem
Windows-Arbeitsplatz lässt sich das nicht messen — dort kann eine offene Datei
gar nicht gelöscht werden.

Aufgefallen ist die Bauart am Heimkino-Plugin, dessen Dienst sieben Stunden
ohne Protokolldatei lief, und am laufenden Gerät belegt: der
Midea2Lox-Dienst hielt `midea2lox.log (deleted)` offen, während unter
demselben Namen längst eine neue Datei fortgeschrieben wurde — von außen sah
das Plugin gesund aus. Elf Linien tragen dieselbe Bauart; alle elf sind am
06.09.2026 nachgezogen worden.

**Die zweite Hälfte gehört dem Startskript.** `bin/dienst.sh` hängte die
Ausgabe des Dienstes mit `nohup … >> "$LOGDATEI"` an **dieselbe** Datei, die
der Handler führt. Damit hält die Shell einen zweiten, anhängenden Deskriptor
darauf — und der bleibt auf der gelöschten Datei stehen, gleich wie gut das
Programm nachfasst. Am Gerät gemessen (06.09.2026): sieben laufende Dienste
hielten so eine gelöschte Protokolldatei offen. Die Ausgabe geht jetzt in
`bewaesserung_start.log`, das bei jedem Start geleert wird; das Protokoll gehört
allein dem Handler. Übernommen von AnkerSolix, das es seit 0.9.6 so macht.

Im Sandkasten am Gerät geprüft, in beide Richtungen: mit dem alten Skript
steht die Dienstausgabe im Protokoll und es gibt keine Startdatei, mit dem
neuen ist es umgekehrt — Start, Startdatei, unberührtes Protokoll und Stopp
je sechs von sechs.


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
aufstellen, Zone laufen lassen, Höhe messen, eintragen. Bis dahin sind alle
Liter- und Minutenangaben mit einem Stern als geschätzt markiert — auch am
Endpunkt (`geschaetzt: 1`).

**Der Durchmesser der Behälter ist gleichgültig.** Das Plugin rechnet
`Rate = Höhe / Laufzeit` — es nimmt die Höhe, nicht das Volumen, und in einem
geraden Gefäß kürzt sich die Öffnungsfläche heraus. Ein breiter Becher fängt
mehr Wasser und verteilt es über entsprechend mehr Fläche.

Entscheidend ist stattdessen dreierlei:

* **Senkrechte Wände.** Ein konischer Eimer fängt über die weite Öffnung und
  sammelt in einen engeren Querschnitt: die Höhe liest sich zu hoch, die Rate
  kommt zu hoch heraus, und das Plugin gießt dauerhaft zu wenig — derselbe
  Fehler wie gar keine Messung, nur unsichtbar.
* **Genug Millimeter.** Der Ablesefehler liegt bei etwa 0,5 mm, unabhängig von
  der Bechergröße. Bei 5 mm sind das ±10 %, bei 2,5 mm ±20 %. Richtwerte:
  Sprühdüsen 15 Minuten, Viereck-, Impuls- und Versenkregner 30.
* **Mehrere Becher**, über die Zone verteilt, auf Pflanzenhöhe, waagerecht,
  nicht unmittelbar neben dem Regner — und der Mittelwert wird eingetragen.

Bei **Perlschlauch und Tropfern** taugt die Becherprobe nicht, es fällt nichts
von oben. Dort wird der Durchfluss gemessen und auf die Fläche umgerechnet:
ein Liter je Quadratmeter ist genau ein Millimeter, also
`Rate [mm/h] = Durchfluss [l/h] / Fläche [m²]`. Das Ergebnis als Höhe mit
60 Minuten Laufzeit eintragen.

Wer nur einen Messbecher mit Milliliter-Strichen hat, braucht den Durchmesser
doch — dann gilt `Höhe [mm] = 10 · Volumen [ml] / Fläche [cm²]` mit
`Fläche = π · (d/2)²`. Bei 10 cm Durchmesser sind das 78,5 cm², ein Millimeter
also 7,85 ml.

## Aufbau

    bin/fao56.py              Verdunstung und Bodenwasserhaushalt,
                              mit Selbstprüfung gegen FAO-56 Beispiel 18
    bin/giessplan.py          Bedarf, Vorschau, Plan unter den Anlagengrenzen
    bin/quellen.py            Messwertbezug: MQTT, HTTP-JSON, Open-Meteo
    bin/bewaesserung_dienst.py  Dienst
    templates/quellen.json    Messgrößen, Vorlagen, Einheiten — EINE Datei
    templates/pflanzen.json   Kc, Zr, p, Bodenkennwerte, Regnertypen
    webfrontend/htmlauth/     Oberfläche (acht Reiter)
    webfrontend/html/         Endpunkt (nur lesend) + Bibliothek

Kein Pflichtpaket. `paho-mqtt` ist freiwillig und nur für MQTT-Quellen nötig.

## Der Endpunkt kann nichts schalten

Er liefert Werte und sonst nichts. Ein Endpunkt im unangemeldeten Bereich, der
Wasser aufdrehen kann, wäre eine Angriffsfläche ohne Gegenwert — geschaltet
wird vom Bewässerungsbaustein im Miniserver.

## Neu in 0.9.23 — zwei Punkte aus einer Messung an der Anlage

* **Der Name der Vorlage wird nur noch übernommen, wenn wenigstens eine Größe
  aus ihr stammt.** Bis 0.9.22 wurde er bedingungslos gesetzt: Wer eine zweite
  Vorlage wählte, obwohl schon alles eingerichtet war, änderte damit **nur den
  Namen** — die Oberfläche nannte danach eine Vorlage, von der keine einzige
  Größe kam, und der Reiter Test las daraus eine falsche Ursache ab. Genau
  dieser Stand lag am 06.09.2026 auf der Anlage: eingetragen war
  `ecowitt_mqtt_direkt`, hinterlegt waren acht HTTP-Pfade, gelesen wurden
  0 von 8 Größen. Die Größen selbst überschreibt eine Vorlage schon lange nicht
  mehr (in 0.9.16 nachgemessen, dem ältesten hier vorliegenden Archiv) — es war
  allein der Name, der log.
* **Der Reiter „Quellen" zieht die Herkunft jetzt zusammen:** „Bei der letzten
  Rechnung (Zeitpunkt) kamen *N* von *M* eingerichteten Messgrößen von der
  Station." Je Größe stand „unlesbar" schon immer da; am 06.09.2026 standen
  acht davon untereinander, monatelang, und es ist niemandem aufgefallen —
  **eine Zahl fällt auf, eine Spalte nicht.** Kommt keine einzige Größe von der
  Station, sagt die Zeile ausdrücklich, dass mit Open-Meteo gerechnet wurde.
  Sie beurteilt die **letzte Rechnung**, nicht den Augenblick, und nennt deren
  Zeitpunkt mit — sonst stünde sie unmittelbar nach einer Änderung falsch da.

Beides ist Anzeige und Eingabepfad; an der Rechnung, am Dienst und am
MQTT-Weg ist nichts geändert.

## Neu in 0.9.22 — eine vollständige Durchsicht, 36 Befunde

0.9.22 ist keine neue Funktion, sondern eine Durchsicht: am 06.09.2026 wurde
die Fassung 0.9.21 von Grund auf gegengelesen und gemessen — beide
PHP-Fassungen, die Dienstschleife, der Installateur, der MQTT-Weg. Alles
Folgende ist gemessen, nicht vermutet.

**Was im Betrieb wirkt**

* **Ein gedeckelter Plan meldet nicht mehr „reicht".** Trug eine Zone eine
  eigene Laufzeit über der längsten zugelassenen Ventilzeit, kürzte das Plugin
  die Ventilzeit — und meldete an Loxone trotzdem `REICHT=1`. Über 720
  zulässige Einstellungen gemessen: 274 solche Fälle, im schlimmsten bekam die
  Zone 1,5 von 20 mm und galt als versorgt.
* **Sperre und Ventilzeit sagen auf beiden Wegen dasselbe.** Bei Frost, Wind
  oder Regen gingen über HTTP `GESPERRT=1` **und** `GIESSEN=1` gleichzeitig
  hinaus, während über MQTT `giessen=0` stand. Ebenso beim eingefrorenen
  Nachtplan: die Gesamtzahl kam aus dem eingefrorenen Plan, die Ventilzeit je
  Zone aus dem frisch gerechneten — sie änderte sich also mitten in der Nacht,
  obwohl der Plan festgehalten war.
* **Zustände gehen retained hinaus.** Bis 0.9.21 ging kein einziges Thema
  zurückbehalten hinaus; nach einem Neustart des Miniservers oder des Gateways
  standen alle Eingänge leer, bis der nächste Vollversand kam — frühestens
  zehn Minuten später. Jetzt gehen die Zustände zurückbehalten hinaus: neun der
  dreizehn allgemeinen Themen (`ok`, `giessen`, `reicht`, `gesperrt`,
  `sperrgrund`, `plan_fest`, `deckt`, `durchlaeufe`, `noetige_durchlaeufe`) und
  drei der zehn Themen je Zone (`ok`, `sekunden`, `durchlaeufe`). Die übrigen
  vier allgemeinen (`et0`, `alter`, `ts`, `zaehler`) und sieben je Zone sind
  Messwerte mit Zeitbezug und gehen bewusst ohne Retain hinaus.
* **Ausfall ist erkennbar.** Neu sind `ts` (Zeitpunkt des Rechengangs) und
  `zaehler` (Lebenszeichen, 0…999). Das bisherige `alter` behält Name und
  Bedeutung, war über MQTT aber immer 0 — es entsteht im selben Augenblick wie
  der Zeitstempel, gegen den es rechnet. Ein gescheiterter Rechengang sendet
  jetzt `ok=0`, statt zu schweigen; eine Zone, die nicht rechnet, sendet
  `<zone>/ok = 0`, statt ihre alte Ventilzeit stehen zu lassen.
* **Der Broker wird wieder versucht.** Wies er die Anmeldung ab (falsches
  Kennwort, CONNACK 5), blieb der Dienst bis zum Neustart stumm. Jetzt wird
  erneut versucht — nach einer Minute, dann immer seltener, höchstens alle
  fünf Minuten.
* **Ein Thema, das später eingetragen wird, wird auch abonniert.** Wer den
  Dienst laufen ließ und danach seine Station einrichtete, las im Protokoll
  „wird neu abonniert" und bekam nie einen Wert.
* **Der Lückenfüller trägt einen Tag ohne ET0 wirklich nach.** Er übersprang
  ihn, weil der Tag „dasteht" — die Bilanz rechnete ihn dauerhaft als Tag ohne
  jede Verdunstung, also in Richtung zu wenig Wasser.
* **„Größtes Alter eines Stationswerts" wirkt.** Die Einstellung galt bisher
  nur für die Gießrückmeldung und die Bodenfeuchte; für Temperatur, Wind,
  Strahlung, Regen und Luftfeuchte galten unverändert 3600 s.
* **Der Takt wirkt sofort**, nicht erst nach einem Neustart des Dienstes.

**Beim Aktualisieren**

* **`postinstall.sh` prüfte die Konfiguration nie wirklich.** Die Prüfung, ob
  die vorhandene Datei lesbar ist, benutzte den Python-Pfad 59 Zeilen vor
  seiner Zuweisung — sie schlug also immer fehl, und die Zweitschrift wurde
  bedingungslos darüber kopiert. Gemessen: eine heile Konfiguration wurde von
  einer überholten Sicherung ersetzt.
* **`preupgrade.sh` bricht jetzt wirklich ab**, wenn es nicht sichern kann.
  Sein `exit 1` war für den Installateur nur eine Fehlerzeile; das Löschen der
  alten Installation lief danach trotzdem. Zusätzlich wird am Ende nachgezählt,
  ob wirklich gesichert wurde.
* **`postupgrade.sh` ist entfallen.** Es rief `postinstall.sh` ein zweites Mal
  auf — der Installateur ruft es ohnehin bei jedem Lauf.
* Die Rettung der Langzeitwerte bleibt liegen, wenn das Zurückholen scheiterte,
  statt weggeworfen zu werden. Die Fehlerausgabe des minütlichen Wächters geht
  ins Protokoll statt nach `/dev/null`.

**In der Oberfläche**

* Im Auswahlfeld „Regnertyp" stand ein Rest Quelltext — 48-mal in der Seite.
* Der Reiter „Einbindung in Loxone" zeigte zwei verschiedene Suchmuster für
  dasselbe Feld (die abzuschreibende Tabelle ohne Semikolon, die Bausteinliste
  darunter mit) und zwei verschiedene Namen für denselben virtuellen Eingang.
  Beides kommt jetzt aus einer Quelle. Dazu zwei neue Schritte
  (Ausfallerkennung, Gegenprobe) und der Satz, dass Loxone Config beim Import
  neu anlegt.
* Vier Bausteine hießen anders als im Loxone-Katalog — „Vergleicher" gibt es
  dort nicht.
* Die Spalte „Herkunft" nennt jetzt den Grund: bisher zeigte sie „Open-Meteo",
  auch wenn die Größe eingerichtet war und nur ein Pfad fehlte.
* Die Anzeigetexte der Tabellen (Bepflanzung, Boden, Regner, Messgrößen,
  Vorlagen) sind zweisprachig und in richtiger deutscher Schreibweise; bisher
  waren sie durchgehend deutsch und in Umschrift.
* Knopffarben nach Hausstandard, Dienststart grün, Vorlage-Knopf grau,
  „Jetzt rechnen" unter eigener Überschrift, die achtspaltige Standtabelle
  scrollbar.
* Drei neue Prüfzeilen im Reiter Test: Themenliste gegen Sendecode,
  Suchmuster mit Trennzeichen, Bausteinnamen gegen die Vorlagentitel.

**Sonst**

* Eine zurückgespielte Sicherungsdatei wird jetzt gegen dieselben
  Wertebereiche geprüft wie das Formular. Vorher wurden elf von elf
  unmöglichen Werten angenommen, darunter ein Breitengrad von 999.
* `zonen.json` wird mit 0600 geschrieben wie seine beiden Nachbarn.
* Dienstschleife und „Jetzt rechnen" rechnen nicht mehr gleichzeitig.

## Neu in 0.9.21 — drei Dinge, die eine Messung am Gerät gefunden hat

Am 05./06.09.2026 lief 0.9.19 zum ersten Mal seit 0.9.11 auf einer echten
Anlage und wurde dort nachgemessen. Drei Befunde, drei Korrekturen.

**1. Das Protokoll sagt jetzt einmal am Tag, ob die eigene Station greift.**
Auf der gemessenen Anlage lief das Plugin sechseinhalb Stunden mit
eingerichteter Wetterstation, empfing ihre Nachrichten im Minutentakt — und
übernahm **keinen einzigen Wert**. Jede Größe kam aus dem Modell, die eigene
Rechnung wurde in jedem Durchgang verworfen, und im Protokoll stand davon
nichts. Den Wächter dafür gab es, aber er hing an den Benachrichtigungen, und
die sind ab Werk aus. Jetzt steht die Lage im Protokoll, unabhängig davon —
genau einmal je Tag:

    Eigene Messquellen: 3 eingerichtet, KEIN einziger Wert uebernommen
    (rh_mittel, taupunkt, regen_stunde) - gerechnet wird mit dem Modell.
    Die Zuordnung im Reiter Quellen passt nicht mehr zu dem, was die
    Station sendet.

Gezählt wird gegen die **Zuordnung**, nicht gegen die angezeigte Herkunft: für
Tmin, Tmax, Feuchte, Wind, Strahlung und Tagesregen überschreibt der Rückfall
auf das Modell die Herkunft, bevor der Grund gemerkt wird. Wer nur dorthin
sieht, kann „nie eingerichtet" nicht von „eingerichtet und stumm"
unterscheiden — und genau das hat den Befund monatelang verdeckt. Dazu:
**„Jetzt rechnen" wirft die Tagesmarken nicht mehr weg.** Bis 0.9.20 setzte
der Knopf Meldezähler und Tagesmarke zurück; dieselbe Fehlerklasse, die 0.9.19
in der Dienstschleife behoben hat.

**2. Die Zweitschrift des Verlaufs steht auf 0600.** Beim Update sichert das
Plugin die Konfiguration neben den Ordner, damit der Installer sie nicht
mitlöscht. Für die drei Konfigurationsdateien wurde dabei ausdrücklich 0600
gesetzt — für den Verlauf nicht, und `cp -p` erbt die Rechte der Quelle. Am
Gerät gemessen: von vier Zweitschriften dieser Linie stand genau diese eine auf
0664. Im Verlauf steht kein Zugangsdatum und kein Token, aber der
Konfigurationszweig ist 0600, und eine Ausnahme, die niemand beabsichtigt hat,
ist keine.

**3. Die Meldung bei abgelehnter Broker-Anmeldung nennt den richtigen Grund.**
Gemessen mit einem einzigen Anmeldeversuch mit falschem Kennwort: der Broker
antwortet mit **CONNACK 5**, nicht mit 4 — mosquitto fasst „Kennwort falsch"
und „gar keine Anmeldung" zu einem Code zusammen. Der Text zu 5 fragte bisher
nur „verlangt der Broker eine Anmeldung?" und schickte damit an die falsche
Stelle, während der passende Text unter 4 stand und nie erreicht wurde. Jetzt
nennt die Zeile beide Fälle.

Für bestehende Anlagen ändert sich nichts an der Rechnung und nichts an den
MQTT-Themen.

## Neu in 0.9.20

Die erzeugte Loxone-Vorlage nannte das Plugin „Bewaesserung"; sie sagt jetzt
„Bewässerung", und der Titel in der Plugin-Verwaltung ebenso. Das MQTT-Thema
`loxone/bewaesserung/rasen` bleibt **unverändert** — ein umbenanntes Thema
bräche jeden virtuellen Eingang in Loxone und jeden gespeicherten Wert im
Broker, die daran hängen.

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
kleine Verdunstung — und zwar still, gekennzeichnet als „“ statt als
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
| ohne Rückmeldung | 63,2 mm | 40 % | 24,3 mm | 8 von 49 — „“ |
| mit 4 mm je Nacht | 10,5 mm | 90 % | 0,0 mm | „“ |

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
  stand buchstäblich „“. Ausgerechnet der Fall, den der
  Quelltext als den gefährlichsten des Moduls bezeichnet. Und die Zonen ohne
  Niederschlagsrate werden jetzt mit Namen genannt, wie es seit 0.9.1 zugesagt
  war.
- **Die feste Rechenzeit gibt es wirklich.** Der Schlüssel `rechenzeit` stand
  seit 0.9.0 mit dem Kommentar „“ in der
  Vorgabeliste und wurde von keiner Zeile gelesen.
- **Ein Bodenfeuchtefühler altert jetzt.** Er wurde am Verfallsdatum vorbei
  gelesen, das für jede andere Messgröße gilt; ein bei „“ stehengebliebener
  Fühler hätte die Bewässerung auf Dauer abgeschaltet. Dasselbe für die
  HTTP-Quelle, die gar keine Altersgrenze hatte.
- **Zwei Eingaben ohne Wirkung sind jetzt erreichbar:** der
  Oberflächenabfluss-Anteil je Zone (Hanglage) und das Sensorgewicht. Beide
  wurden von der Rechnung gelesen und hatten kein Eingabefeld.
- **Das Datum der Becherprobe überlebt das Speichern.** Es wurde geschrieben
  und beim nächsten Speichern der Zonentabelle still gelöscht.
- **MQTT:** `alter` stand fest auf 0 und meldete als retained-Wert für immer
  „“. `et0` wurde bei fehlgeschlagener Rechnung als 0
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

Diese Datei sprang von 0.9.1 auf 0.9.7. Die Anmerkungen zu 0.9.2 bis 0.9.6
stehen hier in Kurzform; für **0.9.8 bis 0.9.16** stehen sie
ausschließlich auf den Release-Seiten des Repositoriums. Der Satz
„damit die Reihe vollständig ist“ stand hier bis 0.9.18 und
war seit 0.9.8 falsch — eine Zusage, die zehn Fassungen lang niemand
eingelöst hat.

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

**0.9.6 — Textpflege, keine Verhaltensänderung.** Die damals
betroffenen Umschreibungen durch echte Umlaute ersetzt; nur Sprachdateien.
(Vollständig war das nicht: zehn Wertzeilen blieben stehen und sind
erst in 0.9.19 nachgezogen worden. Der Satz hier nannte zwei Wörter
als Beispiel, die beide noch dastanden.) Dazu eine
Richtigstellung in der `LICENSE`, die als Urheber „“
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
  den Themennamen entfernt — eine Zone namens „“ hätte das Thema
  sonst mitten im Namen abgeschnitten.
- **Ein Zonenfehler heißt nicht mehr „“.** Der Endpunkt
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
  Dienst ein zweiter Lauf über „“ schrieb. Python macht zusätzlich
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
  0 gilt als „“, nicht als „“.
- **Der Dienst läuft jetzt auch ohne virtuelle Python-Umgebung.**
  `postinstall.sh` sagte zu: „Das Plugin läuft trotzdem — dann aber ohne
  MQTT-Quellen“, falls sich die Umgebung nicht anlegen lässt (etwa ohne das
  Paket `python3-venv`). `dienst.sh` hielt sich nicht daran: es bestand auf
  `venv/bin/python3` und verweigerte den Start mit „“.
  Die Installation meldete also Erfolg, und der Dienst lief nie an — auch der
  Reiter Test schlug fehl, mit einem Hinweis auf die falsche Ursache. Jetzt ist
  der System-Python die Rückfallebene, und der Selbsttest nennt, welcher
  Interpreter läuft und wo `paho-mqtt` dann liegen müsste.

## Fassung 0.9.19 — die Durchsicht vom 04./05.09.2026

Eine vollstaendige Gegenlesung der Fassung 0.9.18. Der Reihe nach, mit dem,
was gemessen wurde:

**Der Endpunkt legt nichts mehr an.** `bw_config()` las die Konfiguration und
holte sie dabei aus der Zweitschrift zurueck — auch aus dem
unangemeldeten Bereich, und zwar **vor** der Tokenpruefung. Ein Aufruf ohne
Token aus dem Netz hat damit Verzeichnis und Konfigurationsdatei erzeugt
(gemessen in neun Lagen unter PHP 7.4 und 8.4). Der Endpunkt ruft jetzt
`bw_config(false)`, und der Kopfkommentar der Datei sagt wieder die Wahrheit.

**Eine beschaedigte Konfiguration wird erkannt.** Bisher gaben „gibt es
nicht“ und „ist unlesbar“ dasselbe zurueck: ein leeres Feld,
ohne eine Zeile im Protokoll. Der Endpunkt antwortete dann dauerhaft
`KEIN_TOKEN_GESETZT`, und der naechste Speichervorgang kopierte die
Werkseinstellungen ueber die Zweitschrift. Jetzt wird die kaputte Datei als
`.kaputt.<Zeitstempel>` beiseitegelegt, einmal gemeldet und — wenn die
Zweitschrift ein Aktionstoken traegt — daraus wiederhergestellt. Der
Reiter Test hat dafuer eine neue Pflichtzeile mit fuenf Ausgaengen.

**Der Aktualisierungsfall ist kein Schaden mehr.** Eine Konfiguration, die nur
`{}` enthaelt, ist der Zustand jeder bestehenden Anlage nach einem Update.
Bisher wurde sie durch die Zweitschrift ersetzt; entschieden wird jetzt nach
dem Inhalt, nicht nach der Form.

**Die Sicherungsdatei wird auf ihre Werte geprueft.** Bisher wurden nur die
Schluessel angesehen. Gemessen gingen ein Feld, ein `null`, ein
Zeilenumbruch, 100 000 Zeichen und `"sofort"` als Taktzeit anstandslos durch
— sieben von vierzehn Faellen. Und eine Datei ohne `aktionstoken` setzte
es beim Zurueckspielen auf leer, womit jede im Miniserver eingetragene
Adresse stumm ungueltig wurde; das laufende Token wird jetzt behalten.

**Die Anmeldung am Broker wird ausgewertet.** Der Rueckgabecode des
MQTT-Verbindungsaufbaus fiel bisher unter den Tisch: ein Broker, der die
Anmeldung ablehnt (CONNACK 4 oder 5), erzeugte dieselbe Protokollzeile
„Mit dem Broker verbunden“ wie ein gelungener Anlauf. Es kam nie
eine Nachricht an, und das Protokoll sagte das Gegenteil.

**Die Tageswerte ueberleben das Update wirklich.** `postinstall.sh` startete
den Dienst, **bevor** `tagesextreme.json` zurueckgelegt wurde. Der Dienst
liest die Datei beim Anlauf und schreibt sie im ersten Rechengang zurueck
— die Rettung war damit wirkungslos. Der Block steht jetzt vor dem
Dienststart, und `nachtplan.json` und `zustand.json` werden mitgerettet.

**Ein MQTT-Feld ohne Pfad wird abgewiesen.** Traegt die Nachricht mehrere
Werte (JSON oder die Feldliste des Ecowitt-Uploadprotokolls) und ist kein
Pfad eingetragen, ging bisher die ganze Zeichenkette an die Zahlenauswertung
— gemessen wurde daraus `123.0`, gelesen aus `PASSKEY=ABC123`. Jetzt
gibt es dafuer den Grund `pfad_fehlt`.

**Die Selbstpruefung laeuft nur im offenen Reiter.** Sie ruft den eigenen
Endpunkt ueber das Netz auf, mit fuenf Sekunden Zeitgrenze, und lief bei
jedem Seitenaufbau — gemessen 3,5 s je Aufruf des Reiters Einstellungen.

**Sperren wirken auch auf die Ventilzeit.** Bei Frost wurden die Durchlaeufe
auf null gesetzt, die Ventilzeit je Zone aber unveraendert veroeffentlicht.
Und ein eingefrorener Nachtplan schlug die Sperre: `gesperrt=1` und
`giessen=1` standen gleichzeitig in der Meldung.

Dazu 16 kleinere Berichtigungen, darunter der zerbrochene
Bestaetigungsdialog am Knopf „neues Token“ (die Rueckfrage entfiel
ersatzlos), Zonen ab der neunten, die jedes Speichern still verlor, drei
CSS-Klassen ohne Definition, zehn Zeilen mit ASCII-Umschrift in der
deutschen Sprachdatei und eine Beispieladresse aus dem Heimnetz.

Neu im Reiter Test: **Ist die Konfiguration heil?**, **Tragen alle Formulare
das Merkmal gegen fremde Absender?**, **Nennt jede Legende genau die
Knopffarben ihres Reiters?** und **Ist die erzeugbare Loxone-Vorlage
wohlgeformt?** — die dritte ersetzt eine Pruefung, die das Hauswerkzeug
an dieser Linie nicht durchfuehren kann, weil sie eine andere
Klassenschreibweise benutzt.

**Nicht geprueft:** nichts davon ist an einer Anlage gemessen. Die letzte
Fassung, die auf echter Hardware lief, ist 0.9.11.

## Fassung 0.9.17 — der Stat-Zwischenspeicher
Die Protokollkappung (512 000 Byte) stand in
`webfrontend/html/bw_lib.php:570`, `webfrontend/html/bw_lib.php:575`. PHP
merkt sich aber die Antworten von `stat()`: innerhalb **eines** Prozesses
sieht `filesize()` die erste Größe und danach nie wieder eine neue —
`file_put_contents(…, FILE_APPEND)` macht den Eintrag nicht ungültig. Die
Kappung fällt dann still aus.

Gemessen am 29.08.2026, 20 000 Zeilen im selben Prozess:

| | ohne `clearstatcache` | mit |
|---|---|---|
| PHP 7.4.33 | 1 220 000 Byte, **nicht gekappt** | 220 332 Byte, gekappt |
| PHP 8.4.24 | 220 332 Byte, gekappt | 220 332 Byte, gekappt |

Die beiden PHP-Fassungen verhalten sich also verschieden — und LoxBerry 3.x
fährt 7.4. Wer nur unter 8.4 misst, sieht den Fehler nie. Folgen hatte das
hier nicht: die Aufrufer sind kurzlebig, und ein **frischer** Prozess kappt
richtig. Eine Funktion darf aber nicht davon abhängen, wer sie wie oft ruft.

Ein `clearstatcache` stand hier schon **unter der Sperre** — erreicht wurde
es nur nie, weil bereits das äußere Tor am veralteten Wert hängenblieb.
Gemessen mit genau diesem Bau: 1 220 000 Byte, ungekappt.

Abhilfe: `clearstatcache(true, …)` **vor** dem Tor; der zweite Parameter
beschränkt das Leeren auf diese eine Datei. Dasselbe Muster tragen Robonect,
Saugroboter, SignalBot, Octopus, Sprachsteuerung und WärmepumpeCloud schon
länger — es ist am 29.08.2026 im ganzen Bestand nachgezogen worden.

## Grundlage

FAO Irrigation and Drainage Paper 56 (Allen, Pereira, Raes, Smith), Kapitel 4
und 8. Vorhersagedaten von Open-Meteo — kostenlos und ohne Schlüssel für nicht
gewerbliche Nutzung, ebenfalls nach FAO-56 Penman-Monteith gerechnet.

