<?php
/**
 * Bewaesserung vorausschauend - gemeinsame Bibliothek
 *
 * Liegt unter webfrontend/html/, weil der Loxone-Endpunkt sie ebenso braucht
 * wie die Oberflaeche. EINE Datei statt zweier Kopien, die auseinanderlaufen.
 *
 * Diese Bibliothek rechnet NICHTS. Gerechnet wird in bin/fao56.py und
 * bin/giessplan.py - dort steht die FAO-56-Rechnung mit ihren Belegen und
 * ihrer Selbstpruefung. Hier wird nur gelesen, geprueft und angezeigt.
 *
 * Praefix 'bw_', weil LBWeb::lbheader() SDK-Globale setzt.
 * Kompatibel mit PHP 7.4 und PHP 8.x (LoxBerry 3.x/4.x).
 */

/* Zeitzone ausdruecklich setzen.
 *
 * Ohne das richtet sich date() nach date.timezone in der php.ini - und die
 * steht auf manchen Systemen auf UTC. Der Python-Dienst schreibt seine
 * Protokollzeilen dagegen in Ortszeit. Beide schreiben in DIESELBE Datei;
 * mit zwei Stunden Versatz nebeneinander ist sie fuer die Fehlersuche
 * wertlos, weil sich die Reihenfolge der Ereignisse nicht mehr ablesen
 * laesst.
 *
 * Genommen wird die Zeitzone des Systems, nicht eine fest eingetragene:
 * wer seinen LoxBerry auf Wien stellt, will Wien - nicht Berlin.
 */
if (!ini_get('date.timezone')) {
    $bw_tz = @trim((string) @file_get_contents('/etc/timezone'));
    if ($bw_tz === '' || @date_default_timezone_set($bw_tz) === false) {
        @date_default_timezone_set('Europe/Berlin');
    }
    unset($bw_tz);
}

if (!function_exists('bw_e')) {
    function bw_e($s) { return htmlspecialchars((string) $s, ENT_QUOTES, 'UTF-8'); }
}

function bw_paths()
{
    static $p = null;
    if ($p !== null) { return $p; }
    $home = getenv('LBHOMEDIR');
    if (!$home || !is_dir($home)) {
        foreach (array('/opt/loxberry', '/home/loxberry/loxberry') as $k) {
            if (is_dir($k)) { $home = $k; break; }
        }
    }
    // Pluginordner aus dem Ablageort DIESER Datei - nicht ueber den
    // MD5-Schluessel der plugindatabase.json, der sich bei jedem Fork aendert.
    $dir = basename(dirname(__FILE__));
    if ($home && !is_dir($home . '/config/plugins/' . $dir)) {
        foreach (array(getenv('LBPPLUGINDIR'), 'bewaesserung') as $kand) {
            if ($kand && is_dir($home . '/config/plugins/' . $kand)) { $dir = $kand; break; }
        }
    }
    if ($home) {
        $p = array(
            'home' => $home, 'plugin' => $dir,
            'configdir' => $home . '/config/plugins/' . $dir,
            'config'    => $home . '/config/plugins/' . $dir . '/bewaesserung.json',
            'zonen'     => $home . '/config/plugins/' . $dir . '/zonen.json',
            'quellen'   => $home . '/config/plugins/' . $dir . '/quellen_zuordnung.json',
            'sicherung' => $home . '/config/plugins/' . $dir . '.backup.json',
            'datadir'   => $home . '/data/plugins/' . $dir,
            'bindir'    => $home . '/bin/plugins/' . $dir,
            'logdir'    => $home . '/log/plugins/' . $dir,
            'log'       => $home . '/log/plugins/' . $dir . '/bewaesserung.log',
            'vorlagen'  => $home . '/templates/plugins/' . $dir . '/quellen.json',
            'pflanzen'  => $home . '/templates/plugins/' . $dir . '/pflanzen.json',
        );
    } else {
        $b = dirname(dirname(__DIR__));
        $p = array('home' => '', 'plugin' => $dir,
            'configdir' => $b . '/config', 'config' => $b . '/config/bewaesserung.json',
            'zonen' => $b . '/config/zonen.json', 'quellen' => $b . '/config/quellen_zuordnung.json',
            'sicherung' => $b . '/config/bewaesserung.backup.json',
            'datadir' => $b . '/data', 'bindir' => $b . '/bin', 'logdir' => $b . '/log',
            'log' => $b . '/log/bewaesserung.log',
            'vorlagen' => $b . '/templates/quellen.json',
            'pflanzen' => $b . '/templates/pflanzen.json');
    }
    return $p;
}

/** Muss zu VORGABEN in bin/bewaesserung_dienst.py passen. */
function bw_vorgaben()
{
    return array(
        'breite' => 0.0, 'laenge' => 0.0, 'hoehe' => 0.0, 'wind_hoehe' => 2.0,
        'kuestennah' => 0, 'vorlage' => 'online', 'rechenzeit' => '20:00',
        'vorschautage' => 2, 'regen_anteil' => 0.7, 'wirkungsgrad' => 0.75,
        'zonendauer_s' => 240, 'pause_min' => 45,
        'fenster_von' => '22:00', 'fenster_bis' => '08:00', 'max_durchlaeufe' => 8,
        'mqtt_ein' => 1, 'mqtt_topic' => 'bewaesserung',
        'aktionstoken' => '', 'takt' => 300,
    );
}

function bw_json_lesen($pfad)
{
    if (!is_file($pfad)) { return array(); }
    $d = json_decode((string) @file_get_contents($pfad), true);
    return is_array($d) ? $d : array();
}

/**
 * JSON unteilbar schreiben.
 *
 * Der Name der Nebendatei traegt seit 0.9.1 die Prozessnummer und einen
 * Zufallsanteil. '<datei>.tmp' war nicht eindeutig: die Oberflaeche und der
 * Python-Dienst schreiben teils dieselben Dateien, und zwei gleichzeitige
 * Schreibvorgaenge haetten sich in derselben Nebendatei ueberlagert.
 *
 * Dass json_encode geprueft wird, war schon richtig - bei ungueltigem UTF-8
 * gibt es false zurueck, und file_put_contents machte daraus eine leere
 * Datei mit der Rueckgabe 0, also nicht false.
 */
function bw_json_schreiben($pfad, $daten, $rechte = null)
{
    $o = dirname($pfad);
    if (!is_dir($o) && !@mkdir($o, 0775, true) && !is_dir($o)) { return false; }
    $j = json_encode($daten, JSON_PRETTY_PRINT | JSON_UNESCAPED_UNICODE | JSON_UNESCAPED_SLASHES);
    if ($j === false) {
        bw_log('Schreibfehler ' . basename($pfad) . ': ' . json_last_error_msg()
             . ' - die Datei bleibt unveraendert.');
        return false;
    }
    $tmp = $pfad . '.tmp.' . getmypid() . '.' . bin2hex(random_bytes(4));
    if (@file_put_contents($tmp, $j) !== strlen($j)) { @unlink($tmp); return false; }
    if ($rechte !== null) { @chmod($tmp, $rechte); }
    if (!@rename($tmp, $pfad)) { @unlink($tmp); return false; }
    return true;
}

function bw_config()
{
    $p = bw_paths();
    $roh = is_file($p['config']) ? trim((string) @file_get_contents($p['config'])) : '';
    if (($roh === '' || $roh === '{}') && is_file($p['sicherung'])) {
        @mkdir($p['configdir'], 0775, true);
        @copy($p['sicherung'], $p['config']);
    }
    return array_merge(bw_vorgaben(), bw_json_lesen($p['config']));
}

function bw_config_speichern($cfg)
{
    $p = bw_paths();
    // 0600, nicht 0644: in dieser Datei steht das Aktionstoken, mit dem der
    // Miniserver den unangemeldeten Endpunkt erreicht.
    if (!bw_json_schreiben($p['config'], $cfg, 0600)) { return false; }
    @copy($p['config'], $p['sicherung']);
    @chmod($p['sicherung'], 0600);
    return true;
}

function bw_vorlagen()
{
    static $t = null;
    if ($t !== null) { return $t; }
    $p = bw_paths();
    foreach (array($p['vorlagen'], dirname(dirname(__DIR__)) . '/templates/quellen.json') as $k) {
        $d = bw_json_lesen($k);
        if (!empty($d['groessen'])) { $t = $d; return $t; }
    }
    $t = array('groessen' => array(), 'vorlagen' => array(), 'einheiten' => array());
    return $t;
}

function bw_pflanzen()
{
    static $t = null;
    if ($t !== null) { return $t; }
    $p = bw_paths();
    foreach (array($p['pflanzen'], dirname(dirname(__DIR__)) . '/templates/pflanzen.json') as $k) {
        $d = bw_json_lesen($k);
        if (!empty($d['bepflanzung'])) { $t = $d; return $t; }
    }
    $t = array('bepflanzung' => array(), 'boden' => array(), 'regner' => array());
    return $t;
}

function bw_zonen()
{
    $d = bw_json_lesen(bw_paths()['zonen']);
    return isset($d['zonen']) && is_array($d['zonen']) ? $d['zonen'] : array();
}

function bw_zonen_speichern($liste)
{
    $d = bw_json_lesen(bw_paths()['zonen']);
    $d['zonen'] = array_values($liste);
    $d['geaendert'] = time();
    return bw_json_schreiben(bw_paths()['zonen'], $d);
}

function bw_zone($schluessel)
{
    foreach (bw_zonen() as $z) {
        if (isset($z['schluessel']) && $z['schluessel'] === $schluessel) { return $z; }
    }
    return null;
}

function bw_quellen()      { return bw_json_lesen(bw_paths()['quellen']); }
function bw_quellen_speichern($q) { return bw_json_schreiben(bw_paths()['quellen'], $q); }
function bw_abbild()       { return bw_json_lesen(bw_paths()['datadir'] . '/abbild.json'); }
function bw_zustand()      { return bw_json_lesen(bw_paths()['datadir'] . '/zustand.json'); }
function bw_verlauf()      { return bw_json_lesen(bw_paths()['datadir'] . '/verlauf.json'); }

function bw_alter()
{
    $a = bw_abbild();
    return isset($a['ts']) ? max(0, time() - (int) $a['ts']) : -1;
}

/* ---------------- Token ---------------- */

function bw_token_erzeugen($laenge = 24)
{
    $zeichen = 'abcdefghijkmnpqrstuvwxyz23456789';
    $t = '';
    for ($i = 0; $i < $laenge; $i++) { $t .= $zeichen[random_int(0, strlen($zeichen) - 1)]; }
    return $t;
}

/**
 * Das Aktionstoken holen, bei Bedarf erzeugen - hinter einer Dateisperre.
 *
 * Ohne Sperre koennen zwei gleichzeitige Aufrufe je ein eigenes Token
 * erzeugen und nacheinander speichern. Der zuerst angezeigte Wert waere dann
 * schon ueberholt, und die daraus gebaute Loxone-Vorlage traege ein Token,
 * das nicht mehr gilt - der Miniserver bekaeme spaeter HTTP 403.
 *
 * Nach dem Sperren wird die Konfiguration ERNEUT gelesen: wer die Sperre vor
 * uns hatte, hat womoeglich schon eines geschrieben.
 *
 * Zur Einordnung: der Endpunkt index.php ruft diese Funktion NIE auf. Er
 * liest das Token aus der Konfiguration und antwortet mit 403, solange
 * keines da ist. Das Rennen laeuft also zwischen zwei Aufrufen der
 * angemeldeten Oberflaeche - zwei offene Reiter genuegen -, nicht zwischen
 * Abfragen des Miniservers.
 */
function bw_token()
{
    $cfg = bw_config();
    if (trim((string) $cfg['aktionstoken']) !== '') {
        return (string) $cfg['aktionstoken'];
    }
    $p = bw_paths();
    if (!is_dir($p['datadir'])) { @mkdir($p['datadir'], 0775, true); }
    $fp = @fopen($p['datadir'] . '/token.lock', 'c+');
    if ($fp === false) {
        // Lieber ohne Sperre eines erzeugen als gar keines - ohne Token
        // laeuft der Endpunkt ueberhaupt nicht.
        bw_log('Die Sperrdatei fuer das Token liess sich nicht anlegen - '
             . 'es wird ohne Sperre erzeugt.');
        $cfg['aktionstoken'] = bw_token_erzeugen();
        bw_config_speichern($cfg);
        return (string) $cfg['aktionstoken'];
    }
    if (@flock($fp, LOCK_EX)) {
        $cfg = bw_config();                       // zweiter Blick unter der Sperre
        if (trim((string) $cfg['aktionstoken']) === '') {
            $cfg['aktionstoken'] = bw_token_erzeugen();
            if (!bw_config_speichern($cfg)) {
                bw_log('Das neu erzeugte Aktionstoken liess sich NICHT speichern. '
                     . 'Beim naechsten Aufruf entsteht ein anderes - die Adressen '
                     . 'in Loxone muessten dann erneut uebernommen werden.');
            }
        }
        @flock($fp, LOCK_UN);
    }
    fclose($fp);
    return (string) $cfg['aktionstoken'];
}

/* ---------------- Becherprobe ----------------
 *
 * Die einzige ehrliche Art, an die Niederschlagsrate zu kommen: Becher
 * aufstellen, Zone eine bekannte Zeit laufen lassen, nachmessen.
 *
 *     Rate [mm/h] = gemessene mm / Laufzeit [h]
 *
 * Alles andere ist ein Katalogwert, und Katalogwerte weichen je nach Duesen,
 * Druck und Verlegeabstand regelmaessig um die Haelfte ab.
 */
function bw_becherprobe($mm, $minuten)
{
    $mm = (float) $mm;
    $minuten = (float) $minuten;
    if ($mm <= 0 || $minuten <= 0) { return null; }
    return $mm / ($minuten / 60.0);
}

/** Zaehlt, wie viele Zonen ihre Rate noch nicht gemessen haben. */
function bw_ungemessen()
{
    $n = 0;
    foreach (bw_zonen() as $z) {
        if (empty($z['rate_gemessen']) && !empty($z['im_zyklus'])) { $n++; }
    }
    return $n;
}

/* ---------------- Felder fuer Loxone ---------------- */

function bw_status_felder()
{
    return array(
        'OK'           => array('',   'BW_FELD.OK'),
        'ET0'          => array('mm', 'BW_FELD.ET0'),
        'GIESSEN'      => array('',   'BW_FELD.GIESSEN'),
        'DURCHLAEUFE'  => array('',   'BW_FELD.DURCHLAEUFE'),
        'NOETIG'       => array('',   'BW_FELD.NOETIG'),
        'REICHT'       => array('',   'BW_FELD.REICHT'),
        'ALTER'        => array('s',  'BW_FELD.ALTER'),
    );
}

function bw_statuszeile()
{
    $a = bw_abbild();
    $plan = isset($a['plan']) && is_array($a['plan']) ? $a['plan'] : array();
    return sprintf('BEWAESSERUNG;OK=%d;ET0=%.2f;GIESSEN=%d;DURCHLAEUFE=%d;NOETIG=%d;REICHT=%d;ALTER=%d',
        (int) (!empty($a['ok'])),
        isset($a['et0']) && $a['et0'] !== null ? (float) $a['et0'] : 0.0,
        (int) ((int) (isset($plan['durchlaeufe']) ? $plan['durchlaeufe'] : 0) > 0),
        (int) (isset($plan['durchlaeufe']) ? $plan['durchlaeufe'] : 0),
        (int) (isset($plan['noetige_durchlaeufe']) ? $plan['noetige_durchlaeufe'] : 0),
        (int) (isset($plan['reicht']) ? $plan['reicht'] : 0),
        bw_alter());
}

/**
 * Die Zeile fuer eine Zone - oder ein NAMED Grund, warum es keine gibt.
 *
 * Bis 0.9.0 gab diese Funktion in beiden Faellen null zurueck: wenn es die
 * Zone nicht gibt UND wenn ihre Berechnung fehlgeschlagen ist. Der Endpunkt
 * meldete daraufhin beide Male ZONE_UNBEKANNT. Wer das in Loxone sah, suchte
 * einen Tippfehler im Zonennamen - waehrend in Wahrheit der Boden
 * unmoeglich eingetragen war oder noch nie gerechnet wurde.
 *
 * Rueckgabe: die Zeile, oder array('_grund' => …) mit einem der Gruende
 *   ZONE_UNBEKANNT       diesen Schluessel gibt es nicht
 *   NOCH_NICHT_GERECHNET es liegt ueberhaupt kein Abbild vor
 *   BERECHNUNGSFEHLER    die Zone gibt es, aber sie liess sich nicht rechnen
 */
function bw_zonenzeile($schluessel)
{
    $a = bw_abbild();
    $z = isset($a['zonen'][$schluessel]) ? $a['zonen'][$schluessel] : null;
    if (!is_array($z)) {
        // Steht der Schluessel wenigstens in der Zonenliste? Dann ist es kein
        // falscher Name, sondern ein fehlendes Ergebnis.
        foreach (bw_zonen() as $bekannt) {
            if ((string) $bekannt['schluessel'] === (string) $schluessel) {
                return array('_grund' => empty($a['ts'])
                    ? 'NOCH_NICHT_GERECHNET' : 'BERECHNUNGSFEHLER',
                    '_text' => empty($a['ts'])
                        ? 'Die Zone ist eingerichtet, aber es hat noch kein Rechengang '
                          . 'stattgefunden. Reiter Test, Knopf "Jetzt rechnen".'
                        : 'Die Zone ist eingerichtet, liess sich aber nicht rechnen. '
                          . 'Der Grund steht im Reiter Logdateien.');
            }
        }
        return array('_grund' => 'ZONE_UNBEKANNT',
                     '_text' => 'Diesen Zonenschluessel gibt es nicht. Die gueltigen '
                              . 'stehen im Reiter Zonen.');
    }
    if (empty($z['ok'])) {
        return array('_grund' => 'BERECHNUNGSFEHLER',
                     '_text' => trim((string) (isset($z['meldung']) ? $z['meldung'] : ''))
                              ?: 'Die Zone liess sich nicht rechnen - Einzelheiten im '
                               . 'Reiter Logdateien.');
    }
    return sprintf('ZONE;OK=1;DEFIZIT=%.1f;FUELLSTAND=%.0f;BEDARF=%.1f;LITER=%.0f;MINUTEN=%.0f;GEMESSEN=%d',
        (float) $z['dr'], (float) $z['fuellstand'], (float) $z['bedarf_mm'],
        (float) (isset($z['liter']) ? $z['liter'] : 0),
        (float) (isset($z['minuten']) ? $z['minuten'] : 0),
        (int) (isset($z['rate_gemessen']) ? $z['rate_gemessen'] : 0));
}

function bw_selbsttest_ausgabe()
{
    $p = bw_paths();
    $s = $p['bindir'] . '/dienst.sh';
    if (!is_file($s)) { return 'dienst.sh nicht gefunden: ' . $s; }
    $a = array(); $c = 0;
    // escapeshellarg statt escapeshellcmd: letzteres laesst ein Leerzeichen
    // im Pfad unangetastet, und der Aufruf zerfiele in zwei Worte.
    @exec(escapeshellarg($s) . ' selbsttest 2>&1', $a, $c);
    return implode("\n", $a);
}

function bw_jetzt_rechnen()
{
    $p = bw_paths();
    $s = $p['bindir'] . '/dienst.sh';
    if (!is_file($s)) { return array(0, 'dienst.sh nicht gefunden.'); }
    $a = array(); $c = 0;
    @exec(escapeshellarg($s) . ' einmal 2>&1', $a, $c);
    return array($c === 0 ? 1 : 0, implode("\n", $a));
}

function bw_vorlage()
{
    $p = bw_paths();
    $host = isset($_SERVER['HTTP_HOST']) && $_SERVER['HTTP_HOST'] !== ''
        ? preg_replace('/[^A-Za-z0-9\.\-:]/', '', (string) $_SERVER['HTTP_HOST'])
        : (gethostname() ?: 'loxberry');
    $token = bw_token();
    $cmds = array();
    foreach (bw_status_felder() as $feld => $info) {
        $cmds[] = array(
            'title'   => 'BEW_' . $feld,
            'comment' => trim(strip_tags(html_entity_decode(bw_t($info[1]), ENT_QUOTES, 'UTF-8')))
                       . ($info[0] !== '' ? ' [' . $info[0] . ']' : ''),
            'check'   => '\i' . $feld . '=\i\v',
        );
    }
    return array('bewaesserung_status.xml', bw_xml_virtual_in_http(array(
        'title'   => 'Bewaesserung vorausschauend',
        'address' => 'http://' . $host . '/plugins/' . $p['plugin']
                   . '/index.php?token=' . $token . '&aktion=status',
        'polling' => '300',
        'comment' => 'Erzeugt vom LoxBerry-Plugin Bewaesserung (' . date('d.m.Y') . ')',
    ), $cmds));
}


/**
 * Eine Zeile ins Protokoll.
 *
 * LOCK_EX ist Pflicht: in diese eine Datei schreiben der Python-Dienst, die
 * Oberflaeche und der Miniserver-Endpunkt. Ohne Sperre koennen sich zwei
 * Zeilen ineinander schieben, und im Log stehen Bruchstuecke.
 *
 * Die Rotation macht dieses Skript nur dann, wenn der Dienst NICHT laeuft.
 * Das ist kein Geiz, sondern notwendig: der Python-Dienst haelt die Datei
 * ueber einen RotatingFileHandler dauerhaft geoeffnet und schreibt an eine
 * gemerkte Stelle. Wuerde PHP die Datei unter ihm kuerzen, schriebe Python
 * weiter an die alte Stelle - die Datei bekaeme davor ein Loch aus
 * Null-Bytes und waere im Log-Betrachter unlesbar. Laeuft der Dienst, ist
 * die Rotation ohnehin seine Aufgabe; er tut sie bei derselben Groesse.
 */
function bw_log($text)
{
    $p = bw_paths();
    if (!is_dir($p['logdir'])) {
        @mkdir($p['logdir'], 0775, true);
    }
    if (is_file($p['log']) && filesize($p['log']) > 512000 && bw_dienst_pid() === 0) {
        $fp = @fopen($p['log'], 'c+');
        if ($fp !== false) {
            if (@flock($fp, LOCK_EX)) {
                clearstatcache(true, $p['log']);
                if (filesize($p['log']) > 512000) {
                    $inhalt = stream_get_contents($fp, -1, 0);
                    $rest = array_slice(explode("\n", (string) $inhalt), -400);
                    ftruncate($fp, 0);
                    rewind($fp);
                    fwrite($fp, implode("\n", $rest) . "\n");
                    fflush($fp);
                }
                @flock($fp, LOCK_UN);
            }
            fclose($fp);
        }
    }
    @file_put_contents($p['log'], '[' . date('Y-m-d H:i:s') . '] ' . $text . "\n",
                       FILE_APPEND | LOCK_EX);
}

/** Dieselbe Meldung hoechstens einmal je Zeitfenster - sonst wird die
 *  Logdatei durch eine Dauerstoerung unlesbar. */
function bw_log_gebremst($schluessel, $text, $sekunden = 3600)
{
    $f = bw_paths()['datadir'] . '/.meld_' . preg_replace('/[^a-z0-9_]/i', '', $schluessel);
    $letzte = is_file($f) ? (int) @file_get_contents($f) : 0;
    if (time() - $letzte >= $sekunden) {
        @file_put_contents($f, (string) time());
        bw_log($text);
    }
}

/* ---------------- Dienst ---------------- */



function bw_dienst_pid()
{
    $f = bw_paths()['datadir'] . '/dienst.pid';
    if (!is_file($f)) {
        return 0;
    }
    $pid = (int) trim((string) @file_get_contents($f));
    if ($pid <= 0 || !is_dir('/proc/' . $pid)) {
        return 0;
    }
    $cmd = (string) @file_get_contents('/proc/' . $pid . '/cmdline');
    return strpos($cmd, 'bewaesserung_dienst.py') !== false ? $pid : 0;
}

function bw_dienst_soll()
{
    return is_file(bw_paths()['datadir'] . '/soll_laufen') ? 1 : 0;
}

/** $befehl ist 'start', 'stop' oder 'restart'. Rueckgabe: array(ok, Ausgabe) */
function bw_dienst($befehl)
{
    if (!in_array($befehl, array('start', 'stop', 'restart'), true)) {
        return array(0, 'Unbekannter Befehl.');
    }
    $skript = bw_paths()['bindir'] . '/dienst.sh';
    if (!is_file($skript)) {
        return array(0, 'dienst.sh nicht gefunden: ' . $skript);
    }
    $ausgabe = array();
    $code = 0;
    @exec(escapeshellcmd($skript) . ' ' . escapeshellarg($befehl) . ' 2>&1', $ausgabe, $code);
    return array($code === 0 ? 1 : 0, implode("\n", $ausgabe));
}

/* ---------------- Befehlswarteschlange ----------------
 *
 * Sowohl der Miniserver-Endpunkt als auch der Reiter Test setzen Befehle ueber
 * diese eine Funktion ab. Zwei Kopien derselben Logik laufen zwangslaeufig
 * auseinander.
 *
 * Rueckgabe: array(ok, Meldung). ok = 1 erledigt, 0 abgelehnt,
 * 2 eingereiht, aber ohne Antwort in der Wartezeit - Ergebnis unbekannt.
 * Es wird nie ein Erfolg gemeldet, den niemand geprueft hat.
 */


function bw_mqtt_zustand()
{
    $p = bw_paths();
    $leer = array('gefunden' => 0, 'autostart' => 0, 'udpport' => 0, 'broker' => '',
                  'brokerport' => '', 'user' => '', 'pw' => '', 'lokal' => 0);
    if ($p['home'] === '') {
        return $leer;
    }
    $gen = bw_json_lesen($p['home'] . '/config/system/general.json');
    $m = array();
    if (isset($gen['Mqtt']) && is_array($gen['Mqtt'])) {
        $m = $gen['Mqtt'];
    } elseif (isset($gen['mqtt']) && is_array($gen['mqtt'])) {
        $m = $gen['mqtt'];
    }
    if (!$m) {
        return $leer;
    }
    $hol = function ($gross, $klein) use ($m) {
        if (isset($m[$gross])) {
            return $m[$gross];
        }
        return isset($m[$klein]) ? $m[$klein] : '';
    };
    return array(
        'gefunden'   => 1,
        'autostart'  => in_array((string) $hol('Gatewayautostart', 'gatewayautostart'), array('1', 'true'), true) ? 1 : 0,
        'udpport'    => (int) $hol('Udpinport', 'udpinport'),
        'broker'     => (string) $hol('Brokerhost', 'brokerhost'),
        'brokerport' => (string) $hol('Brokerport', 'brokerport'),
        'user'       => (string) $hol('Brokeruser', 'brokeruser'),
        'pw'         => (string) $hol('Brokerpass', 'brokerpass'),
        'lokal'      => in_array((string) $hol('Uselocalbroker', 'uselocalbroker'), array('1', 'true'), true) ? 1 : 0,
    );
}

/**
 * Werte ueber das LoxBerry-Gateway veroeffentlichen.
 *
 * Bewusst ueber den UDP-Eingang des Gateways und nicht mit einem eigenen
 * MQTT-Client: so muss das Plugin ueberhaupt keine Broker-Zugangsdaten
 * kennen, um zu senden. Das Gateway hat sie ohnehin.
 */
function bw_mqtt_senden(array $paare, $praefix)
{
    $z = bw_mqtt_zustand();
    if (!$z['udpport']) {
        bw_log_gebremst('mqtt_kein_port', 'MQTT: kein UDP-Eingangsport in der general.json gefunden - nichts gesendet.');
        return false;
    }
    if (!$z['autostart']) {
        bw_log_gebremst('mqtt_aus', 'MQTT: das Gateway ist nicht auf Autostart gestellt '
            . '(System, MQTT Gateway). Es wird gesendet, aber vermutlich hoert niemand zu.');
    }
    $s = @socket_create(AF_INET, SOCK_DGRAM, SOL_UDP);
    if (!$s) {
        bw_log_gebremst('mqtt_socket', 'MQTT: Socket nicht moeglich.');
        return false;
    }
    foreach ($paare as $k => $v) {
        if ($v === null || $v === '') {
            continue;   // fehlender Wert: nichts senden statt eine erfundene 0
        }
        $msg = 'publish ' . $praefix . '/' . $k . ' ' . $v;
        @socket_sendto($s, $msg, strlen($msg), 0, '127.0.0.1', $z['udpport']);
    }
    socket_close($s);
    return true;
}

/* ==================================================================
 * Loxone-Vorlagen
 *
 * Nachbau der Bausteine aus LoxBerry::LoxoneTemplateBuilder; das Modul gibt es
 * nur in Perl. Attributreihenfolge, CRLF als Zeilenende und der Tabulator vor
 * den Kindelementen entsprechen dem Original. Wortgleich uebernommen aus
 * LoxBerry-Plugin-APC-UPS-1.0.0 (ap_xml_virtual_in_http) - nicht neu
 * geschrieben, weil die Fassung dort geprueft ist.
 * ================================================================== */



function bw_x($s)
{
    return htmlspecialchars((string) $s, ENT_QUOTES | ENT_XML1, 'UTF-8');
}

function bw_xml_virtual_in_http($kopf, $cmds)
{
    $crlf = "\r\n";
    $o = '<?xml version="1.0" encoding="utf-8"?>' . $crlf;
    $o .= '<VirtualInHttp ';
    $o .= 'Title="' . bw_x($kopf['title']) . '" ';
    $o .= 'Comment="' . bw_x(isset($kopf['comment']) ? $kopf['comment'] : '') . '" ';
    $o .= 'Address="' . bw_x(isset($kopf['address']) ? $kopf['address'] : '') . '" ';
    $o .= 'PollingTime="' . bw_x(isset($kopf['polling']) ? $kopf['polling'] : '60') . '"';
    $o .= '>' . $crlf;
    foreach ($cmds as $c) {
        $o .= "\t" . '<VirtualInHttpCmd ';
        $o .= 'Title="' . bw_x($c['title']) . '" ';
        $o .= 'Comment="' . bw_x(isset($c['comment']) ? $c['comment'] : '') . '" ';
        $o .= 'Check="' . bw_x(isset($c['check']) ? $c['check'] : ' ') . '" ';
        $o .= 'Signed="true" ';
        $o .= 'Analog="true" ';
        $o .= 'SourceValLow="0" ';
        $o .= 'DestValLow="0" ';
        $o .= 'SourceValHigh="100" ';
        $o .= 'DestValHigh="100" ';
        $o .= 'DefVal="0" ';
        $o .= 'MinVal="-2147483647" ';
        $o .= 'MaxVal="2147483647"';
        $o .= '/>' . $crlf;
    }
    $o .= '</VirtualInHttp>' . $crlf;
    return $o;
}

/* ==================================================================
 * Sprache (Pflicht: Deutsch und Englisch)
 *
 * Englisch ist die Rueckfallebene, nicht Deutsch: wer eine dritte Sprache
 * eingestellt hat, versteht eher Englisch. Deshalb muss language_en.ini immer
 * vollstaendig sein.
 *
 * Die Funktion setzt kein bw_paths() voraus, damit derselbe Block in jedes
 * Plugin passt. Der Pfad wird zweistufig gesucht:
 *   installiert: <home>/templates/plugins/<ordner>/lang
 *   Archiv:      <pluginwurzel>/templates/lang
 * ================================================================== */



function bw_sprache()
{
    $sprache = 'de';
    if (class_exists('LBSystem', false) && method_exists('LBSystem', 'lblanguage')) {
        $sprache = LBSystem::lblanguage();
    } elseif (getenv('LBLANG')) {
        $sprache = getenv('LBLANG');
    }
    $sprache = strtolower(substr((string) $sprache, 0, 2));
    return in_array($sprache, array('de', 'en'), true) ? $sprache : 'en';
}

function bw_t($schluessel)
{
    static $texte = null;
    if ($texte === null) {
        $home = getenv('LBHOMEDIR');
        if (!$home || !is_dir($home)) {
            foreach (array('/opt/loxberry', '/home/loxberry/loxberry') as $k) {
                if (is_dir($k)) {
                    $home = $k;
                    break;
                }
            }
        }
        $ordner = basename(dirname(__FILE__));
        $pfad = $home . '/templates/plugins/' . $ordner . '/lang';
        if (!is_dir($pfad)) {
            $pfad = dirname(dirname(dirname(__FILE__))) . '/templates/lang';
        }
        $texte = @parse_ini_file($pfad . '/language_' . bw_sprache() . '.ini', true, INI_SCANNER_RAW);
        if (!is_array($texte)) {
            $texte = array();
        }
        $rueck = @parse_ini_file($pfad . '/language_en.ini', true, INI_SCANNER_RAW);
        if (is_array($rueck)) {
            $texte = array_replace_recursive($rueck, $texte);
        }
        // INI_SCANNER_RAW liefert die Werte samt der Anfuehrungszeichen
        // zurueck, in die sie in der Datei stehen muessen. Die gehoeren nicht
        // in die Ausgabe.
        foreach ($texte as $ab => $paare) {
            if (!is_array($paare)) {
                continue;
            }
            foreach ($paare as $s => $w) {
                $texte[$ab][$s] = trim((string) $w, '"');
            }
        }
    }
    $teile = array_pad(explode('.', $schluessel, 2), 2, '');
    return isset($texte[$teile[0]][$teile[1]]) ? $texte[$teile[0]][$teile[1]] : $schluessel;
}

/* ==================================================================
 * Dashboard-eigene Teile
 * ================================================================== */

/** Die Adresse, die auf das Wandtablet gehoert. */
