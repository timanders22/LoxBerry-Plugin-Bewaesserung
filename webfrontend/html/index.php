<?php
/**
 * Bewaesserung vorausschauend - Endpunkt fuer den Miniserver
 *
 * Liegt im unangemeldeten Bereich, damit Loxone ihn ohne Zugangsdaten
 * erreicht, und ist deshalb durch ein Token geschuetzt. Verglichen wird mit
 * hash_equals, also in gleichbleibender Zeit.
 *
 *   /plugins/<ordner>/index.php?token=<TOKEN>&aktion=<Befehl>
 *
 * Nur LESENDE Aktionen:
 *   status              die Zustandszeile fuer virtuelle Eingaenge
 *   zone   &zone=...    eine Zone einzeln
 *   zonen               alle Zonen als JSON
 *   roh                 das vollstaendige Abbild als JSON
 *
 * Es gibt hier bewusst KEINE schaltende Aktion. Das Plugin oeffnet kein
 * Ventil - das macht der Bewaesserungsbaustein im Miniserver. Ein Endpunkt,
 * der Wasser aufdrehen kann, waere eine Angriffsflaeche ohne Gegenwert.
 */

error_reporting(E_ALL & ~E_DEPRECATED & ~E_NOTICE);
require_once __DIR__ . '/bw_lib.php';

$bw_cfg = bw_config();
header('Cache-Control: no-store');

$bw_soll = (string) $bw_cfg['aktionstoken'];
$bw_ist = isset($_GET['token']) ? (string) $_GET['token'] : '';
if ($bw_soll === '') {
    http_response_code(403);
    header('Content-Type: text/plain; charset=utf-8');
    echo "FEHLER;OK=0;GRUND=KEIN_TOKEN_GESETZT\n";
    echo "Die Plugin-Oberflaeche wurde noch nie geoeffnet - es gibt noch kein Token.\n";
    exit;
}
if (!hash_equals($bw_soll, $bw_ist)) {
    http_response_code(403);
    header('Content-Type: text/plain; charset=utf-8');
    echo "FEHLER;OK=0;GRUND=TOKEN\n";
    exit;
}

$bw_erlaubt = array('status', 'zone', 'zonen', 'roh');
$bw_aktion = isset($_GET['aktion']) ? (string) $_GET['aktion'] : 'status';
if (!in_array($bw_aktion, $bw_erlaubt, true)) {
    http_response_code(400);
    header('Content-Type: text/plain; charset=utf-8');
    echo "FEHLER;OK=0;GRUND=UNBEKANNTE_AKTION\n";
    echo 'Erlaubt sind: ' . implode(', ', $bw_erlaubt) . "\n";
    exit;
}

if ($bw_aktion === 'roh') {
    header('Content-Type: application/json; charset=utf-8');
    echo json_encode(bw_abbild(), JSON_UNESCAPED_UNICODE | JSON_UNESCAPED_SLASHES);
    exit;
}

if ($bw_aktion === 'zonen') {
    header('Content-Type: application/json; charset=utf-8');
    $a = bw_abbild();
    $aus = array();
    foreach (bw_zonen() as $z) {
        $s = (string) $z['schluessel'];
        $e = isset($a['zonen'][$s]) ? $a['zonen'][$s] : array();
        $aus[] = array(
            'schluessel' => $s,
            'name'       => (string) (isset($z['name']) ? $z['name'] : $s),
            'im_zyklus'  => (int) (isset($z['im_zyklus']) ? $z['im_zyklus'] : 0),
            'defizit_mm' => isset($e['dr']) ? round((float) $e['dr'], 1) : null,
            'fuellstand' => isset($e['fuellstand']) ? round((float) $e['fuellstand']) : null,
            'bedarf_mm'  => isset($e['bedarf_mm']) ? round((float) $e['bedarf_mm'], 1) : null,
            'liter'      => isset($e['liter']) ? round((float) $e['liter']) : null,
            'minuten'    => isset($e['minuten']) ? round((float) $e['minuten']) : null,
            // Ehrlichkeit bis in die Schnittstelle: ohne Becherprobe sind
            // Liter und Minuten geschaetzt, und das steht hier auch.
            'geschaetzt' => (int) empty($z['rate_gemessen']),
        );
    }
    echo json_encode(array('ok' => (int) (!empty($a['ok'])), 'zonen' => $aus),
                     JSON_UNESCAPED_UNICODE | JSON_UNESCAPED_SLASHES);
    exit;
}

if ($bw_aktion === 'zone') {
    header('Content-Type: text/plain; charset=utf-8');
    $bw_z = isset($_GET['zone']) ? (string) $_GET['zone'] : '';
    if (!preg_match('/^[a-z0-9_-]{1,40}$/', $bw_z)) {
        http_response_code(400);
        echo "FEHLER;OK=0;GRUND=ZONE_UNGUELTIG\n";
        echo "Ein Zonenschluessel besteht aus Kleinbuchstaben, Ziffern, Strich und Unterstrich.\n";
        exit;
    }
    $zeile = bw_zonenzeile($bw_z);
    if ($zeile === null) {
        http_response_code(404);
        echo "FEHLER;OK=0;GRUND=ZONE_UNBEKANNT\n";
        exit;
    }
    echo $zeile . "\n";
    exit;
}

header('Content-Type: text/plain; charset=utf-8');
echo bw_statuszeile() . "\n";
