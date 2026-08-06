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

function bw_pruefungen()
{
    $zeilen = array();
    $cfg = bw_config();
    $a = bw_abbild();

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
    $ung = bw_ungemessen();
    $zeilen[] = bw_pruefzeile($ung === 0 ? 1 : -1, bw_t('TEST.F_BECHER'),
        $ung === 0 ? bw_t('TEST.A_BECHER_OK') : sprintf(bw_t('TEST.A_BECHER_FEHLT'), $ung));

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
        $zeilen[] = bw_pruefzeile($station + $online > 0 ? 1 : 0, bw_t('TEST.F_MESSWERTE'),
            sprintf(bw_t('TEST.A_MESSWERTE'), $station, $online, $keine));
    }

    if (isset($a['et0']) && $a['et0'] !== null) {
        $g = (string) (isset($a['et0_guete']) ? $a['et0_guete'] : '');
        $gt = bw_t('GUETE.' . strtoupper($g));
        $zeilen[] = bw_pruefzeile($g === 'gemessen' ? 1 : -1, bw_t('TEST.F_ET0'),
            sprintf(bw_t('TEST.A_ET0'), (float) $a['et0'], $gt));
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
    if ($plan) {
        $grund = (string) (isset($plan['grund']) ? $plan['grund'] : '');
        $stand = ($grund === 'anlage_am_limit' || $grund === 'fenster_zu_kurz') ? 0 : 1;
        $zeilen[] = bw_pruefzeile($stand, bw_t('TEST.F_PLAN'),
            sprintf(bw_t('TEST.A_PLAN'), (int) $plan['durchlaeufe'],
                    (int) $plan['noetige_durchlaeufe'], (int) $plan['moegliche_durchlaeufe'])
            . ($grund !== '' ? ' &mdash; ' . bw_t('GRUND.' . strtoupper($grund)) : ''));
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
