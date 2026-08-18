<?php
/**
 * Bewaesserung vorausschauend - Meldung in den LoxBerry-Benachrichtigungsbereich
 *
 * Aufruf:  php bw_notify.php <Schwere 1-7> <Text> [Pluginordner]
 *
 * Der Messdienst ist in Python geschrieben; fuer Benachrichtigungen gibt es
 * dort keine LoxBerry-Schnittstelle. Deshalb dieses Zwischenstueck, das
 * notify_ext() aus libs/phplib/loxberry_log.php aufruft - derselbe Weg, den
 * das APC-UPS-Plugin dieser Reihe seit Langem geht (bin/apc_notify.php).
 *
 * Der Pluginordner wird als drittes Argument uebergeben, weil dem Dienst die
 * LoxBerry-Umgebungsvariablen fehlen koennen. Ohne ihn fiele dieses Skript
 * auf den fest eingetragenen Namen zurueck - wer das Plugin in einen anderen
 * Ordner installiert hat, faende seine Meldung dann unter einem Paketnamen,
 * den es nicht gibt, und damit gar nicht.
 *
 * Rueckgabewert 0 = abgelegt, 1 = nicht moeglich.
 */

error_reporting(E_ALL & ~E_DEPRECATED & ~E_NOTICE);

/* Den LoxBerry-Wurzelordner ohne festen Systempfad bestimmen - wortgleich
 * mit bw_lib.php, damit beide dasselbe finden. */
function bw_notify_wurzel()
{
    $d = __DIR__;
    for ($i = 0; $i < 8; $i++) {
        if (is_dir($d . '/config/plugins') && is_dir($d . '/webfrontend')) {
            return $d;
        }
        $eltern = dirname($d);
        if ($eltern === $d) { break; }
        $d = $eltern;
    }
    return '';
}

$home = getenv('LBHOMEDIR');
if (!$home || !is_dir($home)) {
    $home = bw_notify_wurzel();
}
$sdk = $home . '/libs/phplib/loxberry_log.php';
if (!$home || !file_exists($sdk)) {
    fwrite(STDERR, "LoxBerry-Bibliothek nicht gefunden: " . $sdk . "\n");
    exit(1);
}
require_once $home . '/libs/phplib/loxberry_system.php';
require_once $sdk;

$schwere = isset($argv[1]) && preg_match('/^[0-9]+$/', (string) $argv[1])
    ? (int) $argv[1] : 4;
if ($schwere < 1 || $schwere > 7) { $schwere = 4; }
$text = isset($argv[2]) ? (string) $argv[2] : '';
if (trim($text) === '') {
    fwrite(STDERR, "Kein Text angegeben.\n");
    exit(1);
}

/* Reihenfolge: was der Dienst mitgibt, dann die Umgebung, dann der feste
 * Name. Das dritte Argument ist der verlaessliche Weg - siehe Kopf. */
$paket = isset($argv[3])
    ? preg_replace('/[^A-Za-z0-9_\-]/', '', (string) $argv[3]) : '';
if ($paket === '') {
    $paket = (string) getenv('LBPPLUGINDIR');
}
if (!$paket) {
    $paket = 'bewaesserung';
}

/* Geprueft wird die AUFRUFFORM, nicht der Name: ein Kommentar, der die
 * Funktion erwaehnt, ist kein Beleg dafuer, dass es sie gibt. */
if (!function_exists('notify_ext')) {
    fwrite(STDERR, "notify_ext() steht in dieser LoxBerry-Fassung nicht bereit.\n");
    exit(1);
}

notify_ext(array(
    'PACKAGE'  => $paket,
    'NAME'     => 'Bewaesserung',
    'MESSAGE'  => $text,
    'SEVERITY' => $schwere,
));

exit(0);
