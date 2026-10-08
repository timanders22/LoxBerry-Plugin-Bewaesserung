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
list($bw_rc, $bw_zeile) = ansage_cli(json_encode(array('text' => $bw_text)), bw_tts(bw_config(false)),
                                     bw_ansage_k());
echo $bw_zeile, "\n";
exit($bw_rc);
