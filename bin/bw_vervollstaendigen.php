<?php
/**
 * Konfiguration vervollstaendigen - Kommandozeile (seit 0.9.56, Regeln/05).
 *
 * Aufgerufen vom Dienst beim Start (konfiguration_vervollstaendigen() in
 * bin/bewaesserung_dienst.py), bevor er die Konfiguration zum ersten Mal
 * liest. Geschrieben wird ausschliesslich ueber bw_config_vervollstaendigen()
 * in webfrontend/html/bw_lib.php - der Dienst schreibt die Datei nicht selbst
 * (ein Schreiber fuer ein Format). Bauart: LoxBerry-Plugin-BLE-Scanner-1.3.40
 * (bin/bl_vervollstaendigen.php).
 *
 * Aufruf: php bw_vervollstaendigen.php <pluginordner>
 * Ausgabe genau eine Zeile:
 *   VERVOLLSTAENDIGEN;STAND=<ruht|ohne_datei|ohne_merkwort|vollstaendig|ergaenzt|fehler>;SCHLUESSEL=a,b
 *   VERVOLLSTAENDIGEN;STAND=0;KENNUNG=<AUFRUF|WURZEL|MODUL_FEHLT>
 * Rueckgabe 0 bei ruht, ohne_datei, ohne_merkwort, vollstaendig, ergaenzt; sonst 1.
 * Die Zeile nennt nur Schluesselnamen, nie einen Wert.
 */
if (PHP_SAPI !== 'cli') {
    http_response_code(403);
    exit("Nur Kommandozeile.\n");
}
$bw_o = isset($argv[1]) ? (string) $argv[1] : '';
if (count($argv) !== 2 || preg_match('/^[A-Za-z0-9_-]{1,64}\z/', $bw_o) !== 1) {
    echo "VERVOLLSTAENDIGEN;STAND=0;KENNUNG=AUFRUF\n";
    exit(1);
}
$bw_wurzel = function ($h) {
    return is_string($h) && $h !== '' && is_dir($h . '/config/plugins') && is_dir($h . '/data/plugins')
        && is_file($h . '/config/system/general.json');
};
$bw_h = getenv('LBHOMEDIR');
if (!$bw_wurzel($bw_h)) {
    $bw_h = dirname(dirname(dirname(__DIR__)));
    if (!$bw_wurzel($bw_h)) {
        echo "VERVOLLSTAENDIGEN;STAND=0;KENNUNG=WURZEL\n";
        exit(1);
    }
}
$bw_h = rtrim($bw_h, '/');
$bw_lib = $bw_h . '/webfrontend/html/plugins/' . $bw_o . '/bw_lib.php';
if (!is_file($bw_lib)) {
    echo "VERVOLLSTAENDIGEN;STAND=0;KENNUNG=MODUL_FEHLT\n";
    exit(1);
}
putenv('LBHOMEDIR=' . $bw_h);
putenv('LBPPLUGINDIR=' . $bw_o);
require_once $bw_lib;
$bw_e = bw_config_vervollstaendigen();
echo 'VERVOLLSTAENDIGEN;STAND=' . $bw_e['stand'] . ';SCHLUESSEL=' . implode(',', $bw_e['schluessel']) . "\n";
exit(in_array($bw_e['stand'], array('ruht', 'ohne_datei', 'ohne_merkwort', 'vollstaendig', 'ergaenzt'), true) ? 0 : 1);
