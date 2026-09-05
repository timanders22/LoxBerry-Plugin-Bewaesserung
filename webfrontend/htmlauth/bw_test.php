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
    // Mit WERT, nicht nur mit Namen: die Frage lautet 'fuehren Dienst und
    // Oberflaeche dieselben VORGABEWERTE', und genau der abweichende Wert
    // ist der Schaden, den der Kommentar an bw_vorgaben() beschreibt.
    $aus = array();
    foreach (explode("\n", $block) as $z) {
        $z = ltrim($z);
        if ($z === '' || $z[0] === '#') { continue; }
        if (preg_match_all('/"([a-z0-9_]+)"\s*:\s*([^,#]+)/', $z, $m,
                           PREG_SET_ORDER)) {
            foreach ($m as $t) {
                $w = trim($t[2]);
                $w = rtrim($w, ',');
                if (strlen($w) >= 2 && ($w[0] === '"' || $w[0] === "'")) {
                    $w = substr($w, 1, -1);
                }
                $aus[$t[1]] = $w;
            }
        }
    }
    return $aus;
}

/** Alle Dateien der Oberflaeche - nicht nur index.php. */
function bw_oberflaechendateien()
{
    $aus = array();
    foreach (glob(__DIR__ . '/*.php') ?: array() as $p) {
        $t = @file_get_contents($p);
        if (is_string($t) && $t !== '') { $aus[basename($p)] = $t; }
    }
    return $aus;
}

/** Die Reiterbereiche einer Oberflaechendatei mit ihrem Inhalt. */
function bw_reiterbereiche($text)
{
    $aus = array();
    if (!preg_match_all('/<div class="sm-seite[^"]*"[^>]*id="(tab-[a-z0-9]+)"/',
                        $text, $m, PREG_OFFSET_CAPTURE)) {
        return $aus;
    }
    foreach ($m[0] as $i => $tref) {
        $rest = substr($text, $tref[1]);
        $tiefe = 0; $len = 0;
        if (preg_match_all('#</?div#', $rest, $tok, PREG_OFFSET_CAPTURE)) {
            foreach ($tok[0] as $t) {
                $tiefe += ($t[0] === '<div') ? 1 : -1;
                if ($tiefe === 0) { $len = $t[1] + strlen($t[0]); break; }
            }
        }
        $aus[$m[1][$i][0]] = $len ? substr($rest, 0, $len) : $rest;
    }
    return $aus;
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

    /* Pflichtzeile des Hausstandards: in welchem Zustand war die
     * Konfiguration, als sie zum ersten Mal in diesem Aufruf gelesen
     * wurde? bw_config() haelt den ZUERST festgestellten Zustand fest -
     * ohne das faende diese Zeile immer eine heile Datei, weil die
     * Selbstheilung lange vorher gelaufen ist. */
    $kz = bw_config_zustand();
    if (strpos($kz, 'kaputt') !== false) {
        /* Beide Schluessel woertlich, nicht zusammengesetzt: der
         * Schluesselpruefer sieht nur literale bw_t('KEY')-Aufrufe, und ein
         * fehlender Schluessel stuende sonst als Name auf dem Schirm. */
        $zeilen[] = strpos($kz, 'zweitschrift') !== false
            ? bw_pruefzeile(0, bw_t('TEST.F_KONFIG'), bw_t('TEST.A_KONFIG_KAPUTT_GEHEILT'))
            : bw_pruefzeile(0, bw_t('TEST.F_KONFIG'), bw_t('TEST.A_KONFIG_KAPUTT'));
    } elseif (strpos($kz, 'zweitschrift') !== false) {
        $zeilen[] = bw_pruefzeile(-1, bw_t('TEST.F_KONFIG'),
                                  bw_t('TEST.A_KONFIG_ZWEITSCHRIFT'));
    } elseif ($kz === 'fehlt' || $kz === 'leer') {
        $zeilen[] = bw_pruefzeile(-1, bw_t('TEST.F_KONFIG'),
                                  bw_t('TEST.A_KONFIG_LEER'));
    } elseif ($kz === 'neu') {
        $zeilen[] = bw_pruefzeile(-1, bw_t('TEST.F_KONFIG'),
                                  bw_t('TEST.A_KONFIG_NEU'));
    } else {
        $zeilen[] = bw_pruefzeile(1, bw_t('TEST.F_KONFIG'),
                                  bw_t('TEST.A_KONFIG_OK'));
    }

    $pid = bw_dienst_pid();
    if ($pid > 0) {
        $zeilen[] = bw_pruefzeile(1, bw_t('TEST.F_DIENST'),
            bw_e(bw_t('TEST.A_DIENST_LAEUFT')) . ' ' . (int) $pid);
    } elseif (bw_dienst_soll()) {
        $zeilen[] = bw_pruefzeile(0, bw_t('TEST.F_DIENST'), bw_t('TEST.A_DIENST_SOLL_TOT'));
    } else {
        /* Punkt, kein Kreuz: der Dienst steht, WEIL ihn jemand angehalten
         * hat. Die Unterscheidung stand schon da, nur das Zeichen folgte
         * ihr nicht. */
        $zeilen[] = bw_pruefzeile(-1, bw_t('TEST.F_DIENST'), bw_t('TEST.A_DIENST_GESTOPPT'));
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
    } else {
        /* Ohne Abbild gab es bis 0.9.18 GAR KEINE Zeile - eine
         * verschwundene Zeile ist schlimmer als ein Punkt, weil sie nicht
         * einmal zum Nachfragen einlaedt. */
        $zeilen[] = bw_pruefzeile(-1, bw_t('TEST.F_PLAN'), bw_t('TEST.A_NIE_GERECHNET'));
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
    $mit = 0; $ohne = array(); $imz = 0;
    foreach (bw_zonen() as $z) {
        if (empty($z['im_zyklus'])) { continue; }
        $imz++;
        if (!empty($z['giess_thema'])) { $mit++; } else { $ohne[] = (string) $z['name']; }
    }
    if ($imz === 0) {
        /* Keine Zone im Zyklus heisst nicht 'der Rueckkanal fehlt',
         * sondern 'es gibt nichts zu melden'. Bis 0.9.18 stand hier ein
         * Kreuz samt Schadensbeschreibung auf einer Anlage, an der nichts
         * kaputt ist - dieselbe Falle, die die Becherproben-Zeile darueber
         * ausdruecklich vermeidet. */
        $zeilen[] = bw_pruefzeile(-1, bw_t('TEST.F_RUECKKANAL'),
                                  bw_t('TEST.A_RUECKKANAL_KEINE_ZONEN'));
    } elseif ($mit === 0) {
        $zeilen[] = bw_pruefzeile(0, bw_t('TEST.F_RUECKKANAL'), bw_t('TEST.A_RUECKKANAL_KEINER'));
    } elseif ($ohne) {
        $zeilen[] = bw_pruefzeile(-1, bw_t('TEST.F_RUECKKANAL'),
            sprintf(bw_t('TEST.A_RUECKKANAL_TEILS'), $mit, bw_e(implode(', ', $ohne))));
    } else {
        $zeilen[] = bw_pruefzeile(1, bw_t('TEST.F_RUECKKANAL'),
            sprintf(bw_t('TEST.A_RUECKKANAL_OK'), $mit));
    }

    // Luecken im Verlauf.
    /* Unter zwei Tagen kann bw_verlauf_luecken() nichts finden und gibt 0
     * zurueck - bis 0.9.18 wurde daraus der Haken 'Der Verlauf ist
     * lueckenlos'. 0 von 0 ist kein Haken. */
    if ($tage < 2) {
        $zeilen[] = bw_pruefzeile(-1, bw_t('TEST.F_LUECKEN'),
                                  bw_t('TEST.A_LUECKEN_ZU_KURZ'));
    } else {
        $lk = bw_verlauf_luecken();
        $zeilen[] = bw_pruefzeile($lk === 0 ? 1 : ($cfg['luecken_fuellen'] ? -1 : 0),
            bw_t('TEST.F_LUECKEN'),
            $lk === 0 ? bw_t('TEST.A_LUECKEN_KEINE')
                      : sprintf(bw_t('TEST.A_LUECKEN'), (int) $lk));
    }

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
        /* Geprueft wird die AUFRUFFORM, und jetzt auch wirklich: steht
         * notify_ext in der Bibliothek, ruft die Bruecke sie, und gibt es
         * ueberhaupt ein php-Programm? Der Dienst ruft die Bruecke ueber
         * subprocess.run([php, ...]) - ohne php-cli kommt nie eine Meldung
         * an, und die Zeile war trotzdem gruen. */
        $sdk_hat = $da && strpos((string) @file_get_contents($sdk),
                                 'function notify_ext') !== false;
        $br_ruft = $bruecke && strpos((string) @file_get_contents(
            bw_paths()['bindir'] . '/bw_notify.php'), 'notify_ext(') !== false;
        $php_da = false;
        foreach (array('/usr/bin/php', '/usr/local/bin/php') as $pk) {
            if (is_file($pk)) { $php_da = true; break; }
        }
        $zeilen[] = bw_pruefzeile($sdk_hat && $br_ruft && $php_da ? 1 : 0,
                                  bw_t('TEST.F_MELDEN'),
            $da && $bruecke ? bw_t('TEST.A_MELDEN_OK')
                            : sprintf(bw_t('TEST.A_MELDEN_FEHLT'), bw_e($sdk)));
    }

    // Zwei Vorgabelisten, die auseinanderlaufen koennen: PHP und Python.
    $vp_werte = bw_vorgaben_python();
    $vp = array_keys($vp_werte);
    if (!$vp) {
        $zeilen[] = bw_pruefzeile(-1, bw_t('TEST.F_VORGABEN'), bw_t('TEST.A_VORGABEN_UNLESBAR'));
    } else {
        $php = array_keys(bw_vorgaben());
        $nur_py = array_values(array_diff($vp, $php));
        $nur_php = array_values(array_diff($php, $vp));
        /* Bis 0.9.18 wurden nur die NAMEN verglichen, waehrend Frage und
         * Antwort von Vorgabewerten sprachen: 'zonendauer_s' = 240 hier
         * und 300 dort waere gruen durchgegangen - genau der Schaden, den
         * der Kommentar an bw_vorgaben() beschreibt. */
        $wert_ab = array();
        foreach (bw_vorgaben() as $vk => $vv) {
            if (!array_key_exists($vk, $vp_werte)) { continue; }
            $py = $vp_werte[$vk];
            $gleich = (is_int($vv) || is_float($vv))
                ? (is_numeric($py) && abs((float) $py - (float) $vv) < 1e-9)
                : ((string) $py === (string) $vv);
            if (!$gleich) {
                $wert_ab[] = $vk . ' (' . $vv . ' / ' . $py . ')';
            }
        }
        $zeilen[] = bw_pruefzeile(!$nur_py && !$nur_php && !$wert_ab ? 1 : 0, bw_t('TEST.F_VORGABEN'),
            $wert_ab
                ? sprintf(bw_t('TEST.A_VORGABEN_WERT'),
                          bw_e(implode('; ', $wert_ab)))
                : (!$nur_py && !$nur_php
                    ? sprintf(bw_t('TEST.A_VORGABEN_OK'), count($php))
                    : sprintf(bw_t('TEST.A_VORGABEN_FEHL'),
                              bw_e(implode(', ', $nur_py)),
                              bw_e(implode(', ', $nur_php)))));
    }

    // Jeder Grund, den der Plan erzeugen kann, braucht seinen Satz. Bis
    // 0.9.6 fehlten drei von sechs in BEIDEN Sprachdateien - im Reiter Test
    // stand dann buchstaeblich "GRUND.RATE_FEHLT".
    /* Die Gruende werden AUS giessplan.py gelesen, nicht hier abgeschrieben.
     * Eine Liste im Pruefcode beantwortet die Frage 'welche Gruende kann
     * der Plan erzeugen?' nicht - sie beantwortet 'welche kannte ich, als
     * ich sie tippte'. Bekommt giessplan.py einen zehnten Grund, meldete
     * die Zeile weiter gruen 'alle 9 haben ihren Satz', und im Reiter
     * stuende buchstaeblich der Schluesselname. */
    $gp = (string) @file_get_contents(bw_paths()['bindir'] . '/giessplan.py');
    $gruende = array();
    if ($gp !== '') {
        preg_match_all('/"grund":\s*"([a-z_]+)"/', $gp, $mg);
        preg_match_all('/grund\s*=\s*"([a-z_]+)"/', $gp, $mg2);
        preg_match_all('/"sperre_"\s*\+\s*([a-z_]+)/', $gp, $mg3);
        $gruende = array_unique(array_merge($mg[1], $mg2[1]));
        if ($mg3[0]) {
            $gruende = array_merge($gruende,
                array('sperre_frost', 'sperre_wind', 'sperre_regen'));
        }
        $gruende = array_values(array_unique($gruende));
    }
    if (!$gruende) {
        /* Nichts gelesen heisst nicht 'alles in Ordnung'. */
        $zeilen[] = bw_pruefzeile(-1, bw_t('TEST.F_GRUENDE'),
                                  bw_t('TEST.A_GRUENDE_UNLESBAR'));
    } else {
    /* Dazu die Guetestufen: dieselbe Fehlerklasse, nur eine Tabelle
     * weiter - ohne Satz stuende 'GUETE.' auf dem Schirm. */
    foreach (array('gemessen', 'sonnenschein', 'geschaetzt', 'modell',
                   'modellstrahlung', 'keine', 'momentaufnahme') as $gg) {
        $gruende[] = 'guete:' . $gg;
    }
    $fehlend = array();
    foreach ($gruende as $gk) {
        $s = (strpos($gk, 'guete:') === 0)
           ? 'GUETE.' . strtoupper(substr($gk, 6))
           : 'GRUND.' . strtoupper($gk);
        if (bw_t($s) === $s) { $fehlend[] = $s; }
    }
    $zeilen[] = bw_pruefzeile($fehlend ? 0 : 1, bw_t('TEST.F_GRUENDE'),
        $fehlend ? sprintf(bw_t('TEST.A_GRUENDE_FEHLEN'), bw_e(implode(', ', $fehlend)))
                 : sprintf(bw_t('TEST.A_GRUENDE_OK'), count($gruende)));
    }

    // Reiter, Bereiche und Positivliste gegeneinander - das prueft
    // hausstandard_pruefen.py nicht mehr, seit die Klassen zusammengesetzt
    // sind. Wer eine Pruefung blind macht, ersetzt sie.
    /* ALLE Dateien der Oberflaeche, nicht nur index.php: sobald ein Reiter
     * aus einer zweiten Datei kaeme, meldete die Zeile still eine zu
     * kleine Zahl - und die Zahl stimmte mit sich selbst ueberein. */
    $oberflaeche = implode("\n", bw_oberflaechendateien());
    preg_match_all('/data-ziel="(tab-[a-z0-9]+)"/', $oberflaeche, $m1);
    preg_match_all('/class="sm-seite[^"]*"[^>]*id="(tab-[a-z0-9]+)"/', $oberflaeche, $m2);
    $liste = array();
    if (preg_match('/\^tab-\(([a-z0-9|]+)\)/', $oberflaeche, $m3)) {
        foreach (explode('|', $m3[1]) as $x) { $liste[] = 'tab-' . $x; }
    }
    $r1 = array_unique($m1[1]); $r2 = array_unique($m2[1]);
    sort($r1); sort($r2); sort($liste);
    if (!$r1 && !$r2 && !$liste) {
        /* Nichts gelesen ist weder Haken noch Kreuz. */
        $zeilen[] = bw_pruefzeile(-1, bw_t('TEST.F_REITER'),
                                  bw_t('TEST.A_REITER_UNLESBAR'));
    } elseif ($r1 && $r1 === $r2 && $r1 === $liste) {
        $zeilen[] = bw_pruefzeile(1, bw_t('TEST.F_REITER'),
            sprintf(bw_t('TEST.A_REITER'), count($r1), count($r2), count($liste)));
    } else {
        /* Bei einem Fehlbefund standen bis 0.9.18 ein rotes Kreuz und der
         * Satz 'alle drei stimmen ueberein' nebeneinander - und gemeldet
         * wurden nur Zahlen. Laufen die NAMEN bei gleicher Anzahl
         * auseinander, las man '8, 8, 8' und ein Kreuz. */
        $fehlt = array_merge(array_diff($r1, $r2), array_diff($r1, $liste),
                             array_diff($r2, $r1), array_diff($liste, $r1));
        $zeilen[] = bw_pruefzeile(0, bw_t('TEST.F_REITER'),
            sprintf(bw_t('TEST.A_REITER_FEHL'), count($r1), count($r2),
                    count($liste), bw_e(implode(', ', array_unique($fehlt)))));
    }

    /* Tragen ALLE Formulare das Merkmal gegen fremde Absender? Der
     * Wachposten weist jeden POST ohne Merkmal ab - ein vergessenes
     * bw_fmt() macht einen Knopf dauerhaft funktionslos, und kein
     * Werkzeug der Hauskette findet es. */
    $alles = implode("\n", bw_oberflaechendateien());
    $formulare = substr_count($alles, '<form ');
    $merkmale = substr_count($alles, 'bw_fmt()');
    if ($formulare === 0) {
        $zeilen[] = bw_pruefzeile(-1, bw_t('TEST.F_FORMULARE'),
                                  bw_t('TEST.A_FORMULARE_KEINE'));
    } else {
        $zeilen[] = bw_pruefzeile($merkmale >= $formulare ? 1 : 0,
            bw_t('TEST.F_FORMULARE'),
            sprintf(bw_t('TEST.A_FORMULARE'), $formulare, $merkmale));
    }

    /* Nennt jede Legende genau die Knopffarben ihres Reiters? Das misst
     * hausstandard_pruefen.py an dieser Linie NICHT: es sucht die
     * Legendenpunkte an einer Klasse, die diese Linie nicht schreibt, und
     * die Knoepfe an einer zweiten. Wer eine Pruefung blind macht,
     * ersetzt sie - hier ist der Ersatz. */
    $leg_schief = array();
    $leg_n = 0;
    foreach (bw_oberflaechendateien() as $inhalt) {
        foreach (bw_reiterbereiche($inhalt) as $tab => $bereich) {
            $leg_n++;
            preg_match_all('/<button[^>]*class="[^"]*\bsm-b-([a-z]+)/',
                           $bereich, $mk);
            $knopf = array_unique($mk[1]);
            $leg = array();
            if (preg_match_all('/<div class="sm-legende".*?<\/div>/s',
                               $bereich, $ml)) {
                foreach ($ml[0] as $lb) {
                    preg_match_all('/<span[^>]*class="[^"]*\bsm-b-([a-z]+)/',
                                   $lb, $mm);
                    $leg = array_merge($leg, $mm[1]);
                }
            }
            $leg = array_unique($leg);
            sort($knopf); sort($leg);
            if ($knopf && $knopf !== $leg) { $leg_schief[] = $tab; }
        }
    }
    if ($leg_n === 0) {
        $zeilen[] = bw_pruefzeile(-1, bw_t('TEST.F_LEGENDEN'),
                                  bw_t('TEST.A_LEGENDEN_KEINE'));
    } else {
        $zeilen[] = bw_pruefzeile($leg_schief ? 0 : 1, bw_t('TEST.F_LEGENDEN'),
            $leg_schief
                ? sprintf(bw_t('TEST.A_LEGENDEN_FEHL'),
                          bw_e(implode(', ', $leg_schief)))
                : sprintf(bw_t('TEST.A_LEGENDEN_OK'), $leg_n));
    }

    /* Ist jedes Suchmuster eindeutig? Gemessen an der ERZEUGTEN
     * Antwortzeile, nicht am Quelltext: Loxone sucht woertlich und nimmt
     * den ersten Treffer, und seit die Muster aus bw_check() kommen,
     * steht keines mehr als Literal in einer Datei - das Hauswerkzeug
     * kann sie also nicht mehr zaehlen. Diese Zeile misst die Sache
     * statt der Schreibweise. */
    $zeile = bw_statuszeile();
    $felder = array_keys(bw_status_felder());
    if (!$felder || $zeile === '') {
        $zeilen[] = bw_pruefzeile(-1, bw_t('TEST.F_MUSTER'),
                                  bw_t('TEST.A_MUSTER_KEINE'));
    } else {
        $doppelt = array();
        foreach ($felder as $f) {
            if (substr_count($zeile, ';' . $f . '=') !== 1) { $doppelt[] = $f; }
        }
        $zeilen[] = bw_pruefzeile($doppelt ? 0 : 1, bw_t('TEST.F_MUSTER'),
            $doppelt
                ? sprintf(bw_t('TEST.A_MUSTER_FEHL'), bw_e(implode(', ', $doppelt)))
                : sprintf(bw_t('TEST.A_MUSTER_OK'), count($felder)));
    }

    /* Ist die erzeugbare Loxone-Vorlage wohlgeformt? Ein kaputter Import
     * faellt sonst erst in Loxone Config auf. */
    /* bw_vorlage() gibt array(Dateiname, XML) zurueck - nicht die
     * Zeichenkette. Beim ersten Anlauf dieser Zeile stand hier $xml =
     * bw_vorlage(), und die Zeile meldete zuverlaessig 'keine Vorlage'.
     * Beim ersten Lauf einer neuen Pruefzeile gilt die Vermutung gegen die
     * Pruefung, nicht gegen den Prueflieferanten. */
    list($xml_name, $xml) = bw_vorlage();
    if (!is_string($xml) || $xml === '') {
        $zeilen[] = bw_pruefzeile(-1, bw_t('TEST.F_VORLAGE'),
                                  bw_t('TEST.A_VORLAGE_KEINE'));
    } else {
        $vorher = libxml_use_internal_errors(true);
        $ok = simplexml_load_string($xml) !== false;
        libxml_clear_errors();
        libxml_use_internal_errors($vorher);
        $zeilen[] = bw_pruefzeile($ok ? 1 : 0, bw_t('TEST.F_VORLAGE'),
            $ok ? sprintf(bw_t('TEST.A_VORLAGE_OK'),
                          substr_count($xml, '<VirtualInHttpCmd'))
                : bw_t('TEST.A_VORLAGE_KAPUTT'));
    }

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
