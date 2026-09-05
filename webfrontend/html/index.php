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
 * Dazu die Tokenprobe des Hausstandards:
 *   ?selftest=1&token=<TOKEN>
 *
 *   richtiges Token:        SELFTEST;OK=1;TOKEN=OK
 *   falsches Token:         HTTP 403, SELFTEST;OK=0;ERR=TOKEN
 *   kein Token eingerichtet: HTTP 403, SELFTEST;OK=0;ERR=KEIN_TOKEN_EINGERICHTET
 *
 * Warum das eine Hausregel ist: am 15.08.2026 liess sich von sieben in
 * Loxone eingetragenen Token nur bei zweien feststellen, ob sie noch
 * stimmen. Hier waere das zwar harmlos - der Endpunkt liest ohnehin nur -,
 * aber die Antwort 'status' laesst sich nicht von 'Token falsch'
 * unterscheiden, wenn noch nie gerechnet wurde. Der Selbsttest beantwortet
 * genau eine Frage: stimmt das Token. Sonst nichts: gelesen wird die
 * Konfiguration, geschrieben wird NICHTS - kein Verzeichnis, keine Datei,
 * kein Protokolleintrag.
 *
 * Bis 0.9.18 stimmte dieser Satz nicht: bw_config() legte beim Lesen
 * Verzeichnis und Konfigurationsdatei aus der Zweitschrift an, und das
 * geschah VOR der Tokenpruefung. Ein Aufruf ohne Token aus dem Netz hat
 * damit die Konfiguration erzeugt (gemessen am 04.09.2026 unter PHP 7.4
 * und 8.4). Deshalb steht hier jetzt bw_config(false).
 *
 * Es gibt hier bewusst KEINE schaltende Aktion. Das Plugin oeffnet kein
 * Ventil - das macht der Bewaesserungsbaustein im Miniserver. Ein Endpunkt,
 * der Wasser aufdrehen kann, waere eine Angriffsflaeche ohne Gegenwert.
 */

error_reporting(E_ALL & ~E_DEPRECATED & ~E_NOTICE);
require_once __DIR__ . '/bw_lib.php';

$bw_cfg = bw_config(false);   // false = NICHTS anlegen, siehe oben
header('Cache-Control: no-store');

/* trim() wie in bw_token(): ein Token aus lauter Leerzeichen galt hier
 * als eingerichtet und in der Bibliothek gleichzeitig als fehlend -
 * zwei Stellen, zwei Urteile ueber denselben Wert. */
$bw_soll = trim((string) $bw_cfg['aktionstoken']);
$bw_ist = isset($_GET['token']) ? (string) $_GET['token'] : '';

/* Die Tokenprobe steht unmittelbar hinter dem Einlesen und VOR jeder
 * Aktion. Sie benutzt dieselbe Pruefung wie alles andere - ein Selbsttest
 * darf keine Abkuerzung an der Sicherheit vorbei sein. */
$bw_selftest = isset($_GET['selftest']) && (string) $_GET['selftest'] === '1';

if ($bw_soll === '') {
    http_response_code(403);
    header('Content-Type: text/plain; charset=utf-8');
    if ($bw_selftest) {
        echo "SELFTEST;OK=0;ERR=KEIN_TOKEN_EINGERICHTET\n";
        exit;
    }
    echo "FEHLER;OK=0;GRUND=KEIN_TOKEN_GESETZT\n";
    /* Warum es keines gibt, entscheidet die Lage der Konfiguration.
     * "Noch nie geoeffnet" auf eine beschaedigte Datei zu antworten,
     * schickt den Betreiber in die Grundeinrichtung, waehrend seine
     * Konfiguration in Truemmern daneben liegt. */
    if (bw_config_zustand() === 'kaputt') {
        echo "Die Konfiguration ist beschaedigt. Bitte die Plugin-Oberflaeche oeffnen - sie holt die Zweitschrift zurueck.\n";
    } else {
        echo "Die Plugin-Oberflaeche wurde noch nie geoeffnet - es gibt noch kein Token.\n";
    }
    exit;
}
if (!hash_equals($bw_soll, $bw_ist)) {
    http_response_code(403);
    header('Content-Type: text/plain; charset=utf-8');
    echo $bw_selftest ? "SELFTEST;OK=0;ERR=TOKEN\n" : "FEHLER;OK=0;GRUND=TOKEN\n";
    exit;
}
if ($bw_selftest) {
    header('Content-Type: text/plain; charset=utf-8');
    echo "SELFTEST;OK=1;TOKEN=OK\n";
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

/**
 * JSON ausgeben - und pruefen, ob es ueberhaupt eines geworden ist.
 *
 * json_encode gibt bei ungueltigem UTF-8 false zurueck. Ungeprueft waere die
 * Antwort eine voellig leere Seite mit Status 200 - und eine leere Antwort
 * mit Erfolgsmeldung ist das Schlechteste, was eine Schnittstelle liefern
 * kann: die Gegenstelle haelt sie fuer gueltig. Solche Bytes koennen aus der
 * Nutzlast einer Wetterstation stammen, die kein UTF-8 spricht.
 */
function bw_json_ausgeben($daten)
{
    $j = json_encode($daten, JSON_UNESCAPED_UNICODE | JSON_UNESCAPED_SLASHES);
    if ($j === false) {
        http_response_code(500);
        echo json_encode(array(
            'ok' => 0,
            'fehler' => 'Die Antwort liess sich nicht als JSON ausgeben: '
                      . json_last_error_msg(),
            'hinweis' => 'Vermutlich steht in einem Messwert ein Byte, das kein UTF-8 '
                       . 'ist. Der Reiter Logdateien zeigt, aus welcher Quelle es kam.',
        ));
        return;
    }
    echo $j;
}

if ($bw_aktion === 'roh') {
    header('Content-Type: application/json; charset=utf-8');
    bw_json_ausgeben(bw_abbild());
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
            // Der Mikroklima-Faktor gehoert in die Antwort: er erklaert, warum
            // zwei Zonen mit derselben Bepflanzung verschiedene Bedarfe haben.
            'mikroklima' => isset($e['mikroklima']) ? (float) $e['mikroklima'] : 1.0,
        );
    }
    bw_json_ausgeben(array('ok' => (int) (!empty($a['ok'])), 'zonen' => $aus));
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
    if (is_array($zeile)) {
        // Der Grund wird benannt. 'Zone unbekannt' fuer einen Rechenfehler zu
        // melden schickt den Anwender auf die Suche nach einem Tippfehler,
        // den es nicht gibt.
        http_response_code($zeile['_grund'] === 'ZONE_UNBEKANNT' ? 404 : 503);
        echo 'ZONE;OK=0;GRUND=' . $zeile['_grund'] . "\n";
        echo $zeile['_text'] . "\n";
        exit;
    }
    echo $zeile . "\n";
    exit;
}

header('Content-Type: text/plain; charset=utf-8');
echo bw_statuszeile() . "\n";
