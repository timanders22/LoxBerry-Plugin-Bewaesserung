<?php
/**
 * Bewaesserung vorausschauend - Bruecke des Dienstes zur gemeinsamen Sprachausgabe
 *
 * Aufruf:  php bw_ansage.php <Pluginordner>   (Auftrag als JSON auf der Standardeingabe)
 *
 * Der Dienst ist in Python geschrieben; die gemeinsame Sprachausgabe der Plugins
 * dieses Hauses (sprachausgabe.php, Nr. 36 b, Stufe 2) gibt es nur in PHP. Dieses
 * Stueck laedt die Bibliothek der Linie (bw_lib.php, daneben die Abschrift der
 * Sprachausgabe), baut aus dem Anlass den Satz aus der Sprachdatei (Abschnitt
 * [SPRECHEN], deutsch oder englisch wie die Oberflaeche) und spricht ihn ueber
 * ansage_cli() mit dem Block tts der Konfiguration. Bauform wie bw_notify.php.
 *
 * Der Auftrag kommt auf der STANDARDEINGABE, nie auf der Kommandozeile: dort saehe
 * ihn jeder in der Prozessliste. Er traegt nur den Anlass und Namen, nie ein Token:
 *   {"anlass": "ende",   "zonen": <Zahl>, "vollstaendig": 0|1}
 *   {"anlass": "ventil", "zone": "<Name>", "ventil": "<Geraetename>", "befehl": "oeffnen"|"schliessen"}
 *   {"anlass": "sperre", "grund": "frost"|"wind"|"beide"}   (0.9.49)
 * Ob ein Anlass angesagt wird (Haken, Wiederholsperre), entscheidet der Dienst.
 *
 * Antwort: EINE Zeile ANSAGE;STAND=..;ART=..;KENNUNG=..;HTTP=..;ZEICHEN=.. (ansage_cli(),
 * ASCII, ohne Text und Token). Rueckgabewert wie ansage_cli(): 0 gesendet,
 * 1 gescheitert (auch: Bibliothek fehlt), 3 nichts gesendet ohne Fehler (etwa
 * Sprachausgabe aus), 2 Aufruf falsch.
 *
 * Der Pluginordner wird mitgegeben wie bei bw_notify.php: dem Dienst koennen die
 * LoxBerry-Umgebungsvariablen fehlen, und bei einer Zweitinstallation heisst der
 * Ordner bewaesserung_01.
 */

error_reporting(E_ALL & ~E_DEPRECATED & ~E_NOTICE);

if (PHP_SAPI !== 'cli') {
    http_response_code(403);
    echo "ANSAGE;STAND=0;KENNUNG=KEIN_ENDPUNKT\n";
    exit;
}

/* Den LoxBerry-Wurzelordner bestimmen - dieselbe Regel wie bw_notify.php. */
function bw_ansage_wurzel()
{
    $d = __DIR__;
    for ($i = 0; $i < 8; $i++) {
        if (is_dir($d . '/config/plugins') && is_dir($d . '/data/plugins')
            && is_file($d . '/config/system/general.json')) {
            return $d;
        }
        $eltern = dirname($d);
        if ($eltern === $d) { break; }
        $d = $eltern;
    }
    return '';
}

$bw_home = (string) getenv('LBHOMEDIR');
if ($bw_home === '' || !is_dir($bw_home . '/config/plugins') || !is_dir($bw_home . '/data/plugins')) {
    $bw_home = bw_ansage_wurzel();
}
$bw_ordner = isset($argv[1]) ? preg_replace('/[^A-Za-z0-9_\-]/', '', (string) $argv[1]) : '';
if ($bw_ordner === '') {
    $bw_ordner = preg_replace('/[^A-Za-z0-9_\-]/', '', basename(rtrim((string) getenv('LBPPLUGINDIR'), '/')));
}
if ($bw_ordner === '') { $bw_ordner = 'bewaesserung'; }

/* Die Bibliothek ueber eine Kandidatenliste (Regeln/03): installiert ueber die
 * Wurzel, aus dem eigenen Ort abgeleitet (bin/plugins/<ordner> -> drei Ebenen hoch),
 * entpacktes Archiv (bin/ neben webfrontend/). */
$bw_kandidaten = array();
if ($bw_home !== '') {
    $bw_kandidaten[] = $bw_home . '/webfrontend/html/plugins/' . $bw_ordner . '/bw_lib.php';
}
$bw_kandidaten[] = dirname(dirname(dirname(__DIR__))) . '/webfrontend/html/plugins/' . basename(__DIR__) . '/bw_lib.php';
$bw_kandidaten[] = dirname(__DIR__) . '/webfrontend/html/bw_lib.php';
$bw_gefunden = false;
foreach ($bw_kandidaten as $bw_k) {
    if (is_file($bw_k)) { require_once $bw_k; $bw_gefunden = true; break; }
}
if (!$bw_gefunden || !function_exists('ansage_cli') || !function_exists('bw_ansage_text')) {
    fwrite(STDERR, "bw_lib.php oder die Sprachausgabe nicht gefunden, gesucht in: "
                   . implode(', ', $bw_kandidaten) . "\n");
    echo "ANSAGE;STAND=0;KENNUNG=BIBLIOTHEK_FEHLT\n";
    exit(1);
}
/* Das SDK nur fuer die Sprache der Oberflaeche (LBSystem::lblanguage()). */
$bw_p = bw_paths();
if ($bw_p['home'] !== '' && is_file($bw_p['home'] . '/libs/phplib/loxberry_system.php')) {
    require_once $bw_p['home'] . '/libs/phplib/loxberry_system.php';
}

$bw_roh = stream_get_contents(STDIN);
$bw_auftrag = is_string($bw_roh) && strlen($bw_roh) <= 4096 ? json_decode($bw_roh, true) : null;
$bw_text = is_array($bw_auftrag) ? bw_ansage_text($bw_auftrag) : '';
if ($bw_text === '') {
    fwrite(STDERR, "Auftrag fehlt, ist kein JSON oder nennt keinen bekannten Anlass.\n");
    echo "ANSAGE;STAND=0;KENNUNG=AUFRUF\n";
    exit(2);
}
/* Nachtwelle N9 (0.9.45, Entwurf Sprachmodul 1.2.0 E-E7 [V], N3): der Dienst beendet diese Bruecke nach
 * ANSAGE_ZEITGRENZE_S = 20 s (bin/bewaesserung_dienst.py); jede Einzelfrist des Moduls (10 s, Sonos4Lox/SonoX
 * 30 s) wird deshalb auf 20 - 5 = 15 s gekappt. Seit Stamm 1.2.1 (Welle Mehrfach-Ziele, Befund B3) gilt 'frist' in
 * jedem Weg - mit EINEM Ziel und mit den weiteren Zielen der Tabelle, die gleichzeitig sprechen. Die Antwortzeile
 * traegt dann zusaetzlich ;ZIELE=x/y; der Dienst nimmt nur Rueckgabewert und Zeile (B8). */
/* 0.9.46: Nachtruhe, Sperre und Schalter stehen im Stamm; gesprochen wird in einem eigenen Vorgang (bw_ansage_senden()). Ein gestoertes Ventil spricht auch nachts. */
/* 0.9.49: waehrend einer Aktualisierung schreibt die Bruecke nichts mehr (Konfiguration, Warteschlange). */
list($bw_mk_liegt, $bw_mk_gilt) = bw_upgrade_marke();
if ($bw_mk_gilt) {
    echo "ANSAGE;STAND=-2;KENNUNG=AKTUALISIERUNG\n";
    exit(3);
}
$bw_cf = bw_config(false);
if (bw_tts($bw_cf)['mode'] === 'aus') {
    echo "ANSAGE;STAND=-2;KENNUNG=AUS\n";
    exit(3);
}
$bw_anl = (string) $bw_auftrag['anlass'];
/* 0.9.49: 'sperre' geht in der Nachtruhe gar nicht erst in die Warteliste, der Sender wuerde sie verwerfen.
 * Rueckgabe 3 sagt dem Dienst: nicht merken, der naechste Rechengang fragt wieder. */
if ($bw_anl === 'sperre' && ansage_nachtruhe(bw_ansage_regeln($bw_cf), time())) {
    echo "ANSAGE;STAND=-2;KENNUNG=NACHTRUHE\n";
    exit(3);
}
bw_ansage_token_pflegen($bw_cf);
bw_ansage_legen(array(array('schluessel' => $bw_anl . ($bw_anl === 'sperre' ? '|' . (string) $bw_auftrag['grund'] : '') . ($bw_anl === 'ventil' ? '|' . (isset($bw_auftrag['ventil']) ? (string) $bw_auftrag['ventil'] : '') . '|' . (isset($bw_auftrag['befehl']) ? (string) $bw_auftrag['befehl'] : '') : ''),
                              'text' => $bw_text, 'dringend' => $bw_anl === 'ventil')));
echo "ANSAGE;STAND=1;KENNUNG=GELEGT\n";
exit(0);
