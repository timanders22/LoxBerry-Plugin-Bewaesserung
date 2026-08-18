<?php
/**
 * Bewaesserung vorausschauend - die Pruefungen des Reiters Test.
 *
 * Jede Zeile beantwortet eine Frage und nennt bei einem Kreuz die Abhilfe
 * mit. Ein "Fehler" ohne Hinweis, was zu tun ist, hilft niemandem.
 */

function bw_pruefzeile($stand, $frage, $befund)
{
    $z = array(1 => array('&#10003;', '#1a7f1a'), 0 => array('&#10007;', '#b00000'),
               -1 => array('&#8226;', '#888'));
    $s = isset($z[$stand]) ? $z[$stand] : $z[-1];
    return '<tr><td style="color:' . $s[1] . ';font-weight:700;width:22px;text-align:center">'
         . $s[0] . '</td><td>' . $frage . '</td><td>' . $befund . '</td></tr>';
}

/**
 * Den eigenen Endpunkt WIRKLICH aufrufen.
 *
 * Bis 0.9.6 las jede der elf Pruefzeilen nur Dateien; der Endpunkt, den
 * Loxone abfragt, wurde nie angefasst. Genau daran sind in dieser Reihe
 * schon zwei Plugins gestorben, ohne dass es jemand merkte - der Miniserver
 * liest kein Protokoll, und ein Endpunkt mit HTTP 500 sieht in Loxone aus
 * wie ein ruhiger Garten.
 *
 * Gerufen wird 127.0.0.1, nicht der Name aus HTTP_HOST: die Adresse, die ein
 * Programm benutzt, und die, die ein Mensch anklickt, sind zwei verschiedene
 * Dinge.
 *
 * DREI Ausgaenge, nicht zwei - der dritte ist der wichtige:
 *   HTTP 200 und die erwartete Kennung        Haken
 *   eine andere Antwort (etwa 500, leer)      Kreuz, mit Code und Rumpfanfang
 *   gar keine Antwort                         HINWEIS, kein Kreuz
 *
 * Ein Webserver, der nur eine Anfrage zugleich bearbeitet, kann sich
 * waehrend des Seitenaufbaus nicht selbst aufrufen. Ein Kreuz waere dort
 * ein Kreuz, das nichts bedeutet - und man sucht dann an der falschen Stelle.
 */
function bw_endpunkt_probe()
{
    $p = bw_paths();
    $cfg = bw_config();
    $token = (string) $cfg['aktionstoken'];
    if ($token === '') {
        return array(0, 'KEIN_TOKEN', '');
    }
    $url = 'http://127.0.0.1/plugins/' . rawurlencode($p['plugin'])
         . '/index.php?selftest=1&token=' . rawurlencode($token);
    $ctx = stream_context_create(array('http' => array(
        'method' => 'GET', 'timeout' => 5,
        'ignore_errors' => true,
        // Keine Weiterleitung: file_get_contents folgt von sich aus bis zu
        // zwanzigmal und schickt den Kopf erneut mit.
        'follow_location' => 0, 'max_redirects' => 1,
    )));
    /* Der eigene Fehler-Aufnehmer statt des @-Zeichens.
     *
     * Kein Webserver zu erreichen ist hier der NORMALFALL - bei jedem
     * Seitenaufbau, solange der Prueflauf von aussen kommt. Das @-Zeichen
     * setzt nur error_reporting herunter; ein eingehaengter Fehlerbehandler
     * wird trotzdem gerufen, und in der Prüfkette landete daraufhin bei
     * jedem Rendern eine Warnung. Gemessen am 18.08.2026 mit rendern.py
     * unter beiden PHP-Fassungen.
     *
     * Der Aufnehmer wird unmittelbar danach wieder abgehaengt - er darf
     * nichts anderes verschlucken als genau diesen einen Aufruf. */
    set_error_handler(function () { return true; });
    $rumpf = file_get_contents($url, false, $ctx);
    restore_error_handler();
    if ($rumpf === false) {
        return array(-1, 'KEINE_ANTWORT', $url);
    }
    $code = 0;
    if (isset($http_response_header) && is_array($http_response_header)) {
        foreach ($http_response_header as $z) {
            if (preg_match('#^HTTP/\S+\s+([0-9]{3})#', $z, $m)) { $code = (int) $m[1]; }
        }
    }
    if ($code === 200 && strpos($rumpf, 'SELFTEST;OK=1') !== false) {
        return array(1, (string) $code, $url);
    }
    return array(0, $code . ' / ' . substr(trim((string) $rumpf), 0, 120), $url);
}

/** Die Vorgabeschluessel aus dem Python-Dienst lesen - fuer den Abgleich. */
function bw_vorgaben_python()
{
    $f = bw_paths()['bindir'] . '/bewaesserung_dienst.py';
    if (!is_file($f)) { return array(); }
    $t = (string) @file_get_contents($f);
    $i = strpos($t, 'VORGABEN = {');
    if ($i === false) { return array(); }
    $j = strpos($t, "\n}", $i);
    if ($j === false) { return array(); }
    $block = substr($t, $i, $j - $i);
    // Nur Zeilen, die WIRKLICH einen Schluessel setzen - ein Kommentar, der
    // einen Schluessel erwaehnt, darf nicht mitzaehlen.
    $aus = array();
    foreach (explode("\n", $block) as $z) {
        $z = ltrim($z);
        if ($z === '' || $z[0] === '#') { continue; }
        if (preg_match_all('/"([a-z0-9_]+)"\s*:/', $z, $m)) {
            foreach ($m[1] as $k) { $aus[$k] = 1; }
        }
    }
    return array_keys($aus);
}

function bw_pruefungen()
{
    $zeilen = array();
    $cfg = bw_config();
    $a = bw_abbild();

    /* Die erste Zeile ist der echte Aufruf - sie steht VOR allem anderen,
     * weil sie die Frage beantwortet, von der alle uebrigen abhaengen. */
    list($bw_ep, $bw_epinfo, $bw_epurl) = bw_endpunkt_probe();
    if ($bw_ep === 1) {
        $zeilen[] = bw_pruefzeile(1, bw_t('TEST.F_ENDPUNKT'), bw_t('TEST.A_ENDPUNKT_OK'));
    } elseif ($bw_ep === -1) {
        $zeilen[] = bw_pruefzeile(-1, bw_t('TEST.F_ENDPUNKT'), bw_t('TEST.A_ENDPUNKT_STUMM'));
    } elseif ($bw_epinfo === 'KEIN_TOKEN') {
        $zeilen[] = bw_pruefzeile(0, bw_t('TEST.F_ENDPUNKT'), bw_t('TEST.A_ENDPUNKT_KEIN_TOKEN'));
    } else {
        $zeilen[] = bw_pruefzeile(0, bw_t('TEST.F_ENDPUNKT'),
            sprintf(bw_t('TEST.A_ENDPUNKT_FEHL'), bw_e($bw_epinfo)));
    }

    $pid = bw_dienst_pid();
    if ($pid > 0) {
        $zeilen[] = bw_pruefzeile(1, bw_t('TEST.F_DIENST'),
            bw_e(bw_t('TEST.A_DIENST_LAEUFT')) . ' ' . (int) $pid);
    } elseif (bw_dienst_soll()) {
        $zeilen[] = bw_pruefzeile(0, bw_t('TEST.F_DIENST'), bw_t('TEST.A_DIENST_SOLL_TOT'));
    } else {
        $zeilen[] = bw_pruefzeile(0, bw_t('TEST.F_DIENST'), bw_t('TEST.A_DIENST_GESTOPPT'));
    }

    $hat_ort = abs((float) $cfg['breite']) > 0.001 || abs((float) $cfg['laenge']) > 0.001;
    $zeilen[] = bw_pruefzeile($hat_ort ? 1 : 0, bw_t('TEST.F_STANDORT'),
        $hat_ort ? sprintf('%.4f, %.4f &mdash; %d m', (float) $cfg['breite'],
                           (float) $cfg['laenge'], (int) $cfg['hoehe'])
                 : bw_t('TEST.A_KEIN_STANDORT'));

    $zl = bw_zonen();
    if (!$zl) {
        $zeilen[] = bw_pruefzeile(0, bw_t('TEST.F_ZONEN'), bw_t('TEST.A_KEINE_ZONEN'));
    } else {
        $imz = 0;
        foreach ($zl as $z) { if (!empty($z['im_zyklus'])) { $imz++; } }
        $zeilen[] = bw_pruefzeile(1, bw_t('TEST.F_ZONEN'),
            sprintf(bw_t('TEST.A_ZONEN'), count($zl), $imz));
    }

    // Die Becherprobe ist der Unterschied zwischen einer Zahl und einer
    // Behauptung. Deshalb steht sie hier als eigene Zeile.
    // "Ja, bei allen Zonen im Zyklus" bei NULL Zonen ist wahr und wertlos.
    //
    // Am Gerät gemeldet: die Zeile stand auf gruen, waehrend die Zeile
    // darueber "Keine Zonen" meldete. Eine Prüfung, die eine leere Menge
    // bestaetigt, beruhigt genau dort, wo jemand hinsieht, weil etwas fehlt -
    // REGELN_1, Abschnitt 12.
    $imz = 0;
    foreach (bw_zonen() as $z) { if (!empty($z['im_zyklus'])) { $imz++; } }
    $ung = bw_ungemessen();
    if ($imz === 0) {
        $zeilen[] = bw_pruefzeile(-1, bw_t('TEST.F_BECHER'), bw_t('TEST.A_BECHER_KEINE_ZONEN'));
    } else {
        $zeilen[] = bw_pruefzeile($ung === 0 ? 1 : -1, bw_t('TEST.F_BECHER'),
            $ung === 0 ? sprintf(bw_t('TEST.A_BECHER_OK'), $imz)
                       : sprintf(bw_t('TEST.A_BECHER_FEHLT'), $ung));
    }

    // Woher kamen die Messwerte?
    $h = isset($a['herkunft']) && is_array($a['herkunft']) ? $a['herkunft'] : array();
    $station = 0; $online = 0; $keine = 0;
    foreach ($h as $w) {
        if ($w === 'station') { $station++; }
        elseif ($w === 'open-meteo') { $online++; }
        else { $keine++; }
    }
    if (!$h) {
        $zeilen[] = bw_pruefzeile(0, bw_t('TEST.F_MESSWERTE'), bw_t('TEST.A_KEINE_MESSWERTE'));
    } else {
        // Wer eine Station eingerichtet hat und NULL Werte von ihr bekommt,
        // hat ein Problem - auch wenn Open-Meteo einspringt. Bis 0.9.7 war
        // das ein Haken, weil irgendeine Quelle geliefert hatte.
        $bw_qf = bw_quellen();
        $eingerichtet = 0;
        foreach ((isset($bw_qf['felder']) && is_array($bw_qf['felder']) ? $bw_qf['felder'] : array()) as $bw_ff) {
            if (!empty($bw_ff['weg'])) { $eingerichtet++; }
        }
        if ($eingerichtet > 0 && $station === 0) {
            $zeilen[] = bw_pruefzeile(0, bw_t('TEST.F_MESSWERTE'),
                sprintf(bw_t('TEST.A_MESSWERTE_STUMM'), $eingerichtet, $online));
        } else {
            $zeilen[] = bw_pruefzeile($station + $online > 0 ? 1 : 0, bw_t('TEST.F_MESSWERTE'),
                sprintf(bw_t('TEST.A_MESSWERTE'), $station, $online, $keine));
        }
    }

    if (isset($a['et0']) && $a['et0'] !== null) {
        $g = (string) (isset($a['et0_guete']) ? $a['et0_guete'] : '');
        $gt = bw_t('GUETE.' . strtoupper($g));
        // Eine Verdunstung aus einem einzigen Messpunkt ist keine
        // Tagesverdunstung. Am 18.08.2026 um 21:20 kamen so 0,39 mm heraus,
        // gekennzeichnet als "gemessen", an einem Tag mit rund 3,8 mm.
        if (!empty($a['et0_verworfen'])) {
            $zeilen[] = bw_pruefzeile(-1, bw_t('TEST.F_ET0'),
                sprintf(bw_t('TEST.A_ET0_VERWORFEN'), (float) $a['et0'],
                        bw_e((string) $a['et0_verworfen'])));
        } elseif ($g === 'momentaufnahme') {
            $zeilen[] = bw_pruefzeile(0, bw_t('TEST.F_ET0'),
                sprintf(bw_t('TEST.A_ET0_MOMENT'), (float) $a['et0'],
                        (float) (isset($a['et0_abdeckung_h']) ? $a['et0_abdeckung_h'] : 0)));
        } else {
        $zeilen[] = bw_pruefzeile($g === 'gemessen' ? 1 : -1, bw_t('TEST.F_ET0'),
            sprintf(bw_t('TEST.A_ET0'), (float) $a['et0'], $gt));
        }
    } else {
        $zeilen[] = bw_pruefzeile(0, bw_t('TEST.F_ET0'),
            bw_e((string) (isset($a['et0_fehler']) ? $a['et0_fehler'] : '')) ?: bw_t('TEST.A_KEIN_ET0'));
    }

    $alter = bw_alter();
    if ($alter < 0) {
        $zeilen[] = bw_pruefzeile(0, bw_t('TEST.F_ALTER'), bw_t('TEST.A_NIE_GERECHNET'));
    } else {
        // Einmal am Tag reicht; nach 36 Stunden stimmt die Bilanz nicht mehr.
        $zeilen[] = bw_pruefzeile($alter < 129600 ? 1 : 0, bw_t('TEST.F_ALTER'),
            sprintf(bw_t('TEST.A_ALTER'), (int) round($alter / 3600)));
    }

    $v = bw_verlauf();
    $tage = isset($v['tage']) && is_array($v['tage']) ? count($v['tage']) : 0;
    $zeilen[] = bw_pruefzeile($tage >= 3 ? 1 : -1, bw_t('TEST.F_VERLAUF'),
        sprintf(bw_t('TEST.A_VERLAUF'), $tage));

    $plan = isset($a['plan']) && is_array($a['plan']) ? $a['plan'] : array();
    if ($plan && (int) (isset($plan['zonen_im_zyklus']) ? $plan['zonen_im_zyklus'] : 0) === 0) {
        // "0 Durchlaeufe - der Boden ist feucht genug" ohne eine einzige Zone
        // ist die freundlichste Art, nichts zu sagen.
        $zeilen[] = bw_pruefzeile(-1, bw_t('TEST.F_PLAN'), bw_t('TEST.A_PLAN_KEINE_ZONEN'));
    } elseif ($plan) {
        $grund = (string) (isset($plan['grund']) ? $plan['grund'] : '');
        $stand = ($grund === 'anlage_am_limit' || $grund === 'fenster_zu_kurz') ? 0 : 1;
        $zeilen[] = bw_pruefzeile($stand, bw_t('TEST.F_PLAN'),
            sprintf(bw_t('TEST.A_PLAN'), (int) $plan['durchlaeufe'],
                    (int) $plan['noetige_durchlaeufe'], (int) $plan['moegliche_durchlaeufe'])
            . ($grund !== '' ? ' &mdash; ' . bw_t('GRUND.' . strtoupper($grund)) : ''));
    }

    /* ---- neu in 0.9.7 ---- */

    // Sperren: der Zustand gehoert sichtbar auf die Seite, sonst sucht
    // jemand nach einem Defekt, waehrend das Plugin absichtlich nicht giesst.
    $sp = isset($a['sperre']) && is_array($a['sperre']) ? $a['sperre'] : array();
    $an = array();
    foreach (array('frost_ein' => 'GRUND.SPERRE_FROST', 'wind_ein' => 'GRUND.SPERRE_WIND',
                   'regen_ein' => 'GRUND.SPERRE_REGEN') as $sk => $st) {
        if (!empty($cfg[$sk])) { $an[] = bw_t($st); }
    }
    if (!$an) {
        $zeilen[] = bw_pruefzeile(-1, bw_t('TEST.F_SPERREN'), bw_t('TEST.A_SPERREN_AUS'));
    } elseif (!empty($sp['aktiv'])) {
        $zeilen[] = bw_pruefzeile(-1, bw_t('TEST.F_SPERREN'),
            sprintf(bw_t('TEST.A_SPERRE_AKTIV'), bw_t('GRUND.' . strtoupper((string) $sp['grund']))));
    } else {
        $zeilen[] = bw_pruefzeile(1, bw_t('TEST.F_SPERREN'),
            sprintf(bw_t('TEST.A_SPERREN_AN'), bw_e(implode(', ', $an))));
    }

    // Rueckmeldung der ausgebrachten Menge - die Voraussetzung dafuer, dass
    // die Bilanz ueberhaupt stimmen kann.
    $mit = 0; $ohne = array();
    foreach (bw_zonen() as $z) {
        if (empty($z['im_zyklus'])) { continue; }
        if (!empty($z['giess_thema'])) { $mit++; } else { $ohne[] = (string) $z['name']; }
    }
    if ($mit === 0) {
        $zeilen[] = bw_pruefzeile(0, bw_t('TEST.F_RUECKKANAL'), bw_t('TEST.A_RUECKKANAL_KEINER'));
    } elseif ($ohne) {
        $zeilen[] = bw_pruefzeile(-1, bw_t('TEST.F_RUECKKANAL'),
            sprintf(bw_t('TEST.A_RUECKKANAL_TEILS'), $mit, bw_e(implode(', ', $ohne))));
    } else {
        $zeilen[] = bw_pruefzeile(1, bw_t('TEST.F_RUECKKANAL'),
            sprintf(bw_t('TEST.A_RUECKKANAL_OK'), $mit));
    }

    // Luecken im Verlauf.
    $lk = bw_verlauf_luecken();
    $zeilen[] = bw_pruefzeile($lk === 0 ? 1 : ($cfg['luecken_fuellen'] ? -1 : 0),
        bw_t('TEST.F_LUECKEN'),
        $lk === 0 ? bw_t('TEST.A_LUECKEN_KEINE')
                  : sprintf(bw_t('TEST.A_LUECKEN'), (int) $lk));

    // Abdeckung der Tagesreihe: aus vier Stunden Strahlung wird kein
    // Tagesmittel, und aus einem Momentanwert kein Tmin.
    $ab = isset($a['abdeckung']) && is_array($a['abdeckung']) ? $a['abdeckung'] : array();
    if (!$ab) {
        $zeilen[] = bw_pruefzeile(-1, bw_t('TEST.F_ABDECKUNG'), bw_t('TEST.A_ABDECKUNG_KEINE'));
    } else {
        $st = max(0, (float) (isset($ab['tmin']) ? $ab['tmin'] : 0));
        $zeilen[] = bw_pruefzeile($st >= 18 ? 1 : -1, bw_t('TEST.F_ABDECKUNG'),
            sprintf(bw_t('TEST.A_ABDECKUNG'), $st));
    }

    // Der Nachtplan.
    $fest = isset($a['nachtplan']) && is_array($a['nachtplan']) ? $a['nachtplan'] : array();
    if (empty($cfg['plan_festhalten'])) {
        $zeilen[] = bw_pruefzeile(-1, bw_t('TEST.F_NACHTPLAN'), bw_t('TEST.A_NACHTPLAN_AUS'));
    } elseif ($fest) {
        $zeilen[] = bw_pruefzeile(1, bw_t('TEST.F_NACHTPLAN'),
            sprintf(bw_t('TEST.A_NACHTPLAN'), bw_e((string) $fest['tag']),
                    (int) $fest['durchlaeufe'], bw_e((string) $fest['zeit'])));
    } else {
        $zeilen[] = bw_pruefzeile(-1, bw_t('TEST.F_NACHTPLAN'),
            sprintf(bw_t('TEST.A_NACHTPLAN_OFFEN'), bw_e((string) $cfg['rechenzeit'])));
    }

    // Koennen Meldungen ueberhaupt abgelegt werden? Geprueft wird die
    // AUFRUFFORM, nicht der Name - ein Kommentar ist kein Beleg.
    if (empty($cfg['melden_ein'])) {
        $zeilen[] = bw_pruefzeile(-1, bw_t('TEST.F_MELDEN'), bw_t('TEST.A_MELDEN_AUS'));
    } else {
        $sdk = bw_paths()['home'] . '/libs/phplib/loxberry_log.php';
        $da = is_file($sdk);
        $bruecke = is_file(bw_paths()['bindir'] . '/bw_notify.php');
        $zeilen[] = bw_pruefzeile($da && $bruecke ? 1 : 0, bw_t('TEST.F_MELDEN'),
            $da && $bruecke ? bw_t('TEST.A_MELDEN_OK')
                            : sprintf(bw_t('TEST.A_MELDEN_FEHLT'), bw_e($sdk)));
    }

    // Zwei Vorgabelisten, die auseinanderlaufen koennen: PHP und Python.
    $vp = bw_vorgaben_python();
    if (!$vp) {
        $zeilen[] = bw_pruefzeile(-1, bw_t('TEST.F_VORGABEN'), bw_t('TEST.A_VORGABEN_UNLESBAR'));
    } else {
        $php = array_keys(bw_vorgaben());
        $nur_py = array_values(array_diff($vp, $php));
        $nur_php = array_values(array_diff($php, $vp));
        $zeilen[] = bw_pruefzeile(!$nur_py && !$nur_php ? 1 : 0, bw_t('TEST.F_VORGABEN'),
            !$nur_py && !$nur_php
                ? sprintf(bw_t('TEST.A_VORGABEN_OK'), count($php))
                : sprintf(bw_t('TEST.A_VORGABEN_FEHL'),
                          bw_e(implode(', ', $nur_py)), bw_e(implode(', ', $nur_php))));
    }

    // Jeder Grund, den der Plan erzeugen kann, braucht seinen Satz. Bis
    // 0.9.6 fehlten drei von sechs in BEIDEN Sprachdateien - im Reiter Test
    // stand dann buchstaeblich "GRUND.RATE_FEHLT".
    $gruende = array('kein_bedarf', 'fenster_ungueltig', 'fenster_zu_kurz',
                     'anlage_am_limit', 'rate_fehlt', 'rate_fehlt_teilweise',
                     'sperre_frost', 'sperre_wind', 'sperre_regen');
    $fehlend = array();
    foreach ($gruende as $gk) {
        $s = 'GRUND.' . strtoupper($gk);
        if (bw_t($s) === $s) { $fehlend[] = $gk; }
    }
    $zeilen[] = bw_pruefzeile($fehlend ? 0 : 1, bw_t('TEST.F_GRUENDE'),
        $fehlend ? sprintf(bw_t('TEST.A_GRUENDE_FEHLEN'), bw_e(implode(', ', $fehlend)))
                 : sprintf(bw_t('TEST.A_GRUENDE_OK'), count($gruende)));

    // Reiter, Bereiche und Positivliste gegeneinander - das prueft
    // hausstandard_pruefen.py nicht mehr, seit die Klassen zusammengesetzt
    // sind. Wer eine Pruefung blind macht, ersetzt sie.
    $oberflaeche = (string) @file_get_contents(__DIR__ . '/index.php');
    preg_match_all('/data-ziel="(tab-[a-z0-9]+)"/', $oberflaeche, $m1);
    preg_match_all('/class="sm-seite[^"]*"[^>]*id="(tab-[a-z0-9]+)"/', $oberflaeche, $m2);
    $liste = array();
    if (preg_match('/\^tab-\(([a-z0-9|]+)\)/', $oberflaeche, $m3)) {
        foreach (explode('|', $m3[1]) as $x) { $liste[] = 'tab-' . $x; }
    }
    $r1 = array_unique($m1[1]); $r2 = array_unique($m2[1]);
    sort($r1); sort($r2); sort($liste);
    $zeilen[] = bw_pruefzeile($r1 && $r1 === $r2 && $r1 === $liste ? 1 : 0,
        bw_t('TEST.F_REITER'),
        sprintf(bw_t('TEST.A_REITER'), count($r1), count($r2), count($liste)));

    $g = bw_mqtt_zustand();
    if (empty($g['gefunden'])) {
        $zeilen[] = bw_pruefzeile(0, bw_t('TEST.F_MQTT'), bw_t('TEST.A_MQTT_NICHT_GEFUNDEN'));
    } elseif (empty($g['autostart'])) {
        $zeilen[] = bw_pruefzeile(0, bw_t('TEST.F_MQTT'), bw_t('TEST.A_MQTT_AUS'));
    } else {
        $zeilen[] = bw_pruefzeile(1, bw_t('TEST.F_MQTT'),
            sprintf(bw_t('TEST.A_MQTT_OK'), (int) $g['udpport']));
    }
    return $zeilen;
}

function bw_pruefungen_html()
{
    return '<table class="sm-tabelle"><tr><th>&nbsp;</th><th>' . bw_e(bw_t('TEST.T_FRAGE'))
         . '</th><th>' . bw_e(bw_t('TEST.T_BEFUND')) . '</th></tr>'
         . implode('', bw_pruefungen()) . '</table>';
}

/** Die Knoepfe des Reiters Test. Rueckgabe: array(stand, Text). */
function bw_test_aktion($was)
{
    if ($was === 'status') { return array(1, bw_statuszeile()); }
    if ($was === 'roh') {
        $a = bw_abbild();
        if (!$a) { return array(0, bw_t('TEST.M_KEIN_ABBILD')); }
        return array(1, json_encode($a, JSON_PRETTY_PRINT | JSON_UNESCAPED_UNICODE
                                       | JSON_UNESCAPED_SLASHES));
    }
    if ($was === 'rechnen') {
        list($ok, $aus) = bw_jetzt_rechnen();
        return array($ok, $aus !== '' ? $aus : bw_t('TEST.M_OHNE_AUSGABE'));
    }
    return array(0, bw_t('TEST.M_UNBEKANNT'));
}
