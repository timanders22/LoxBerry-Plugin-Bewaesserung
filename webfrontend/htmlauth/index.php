<?php
/**
 * Bewaesserung vorausschauend - Bedienoberflaeche
 *
 * Reiter: Einstellungen | Quellen | Zonen | MQTT |
 *         Einbindung in Loxone | Test | Logdateien
 *
 * Zwei Reiter kommen zu den fuenf des Hausstandards hinzu, weil sie eigene
 * Vorgaenge sind: 'Quellen' ordnet die Wetterstation zu (herstellerneutral),
 * 'Zonen' pflegt Flaechen, Bepflanzung, Boden und die Becherprobe. In den
 * Einstellungen wuerden beide untergehen.
 */

error_reporting(E_ALL & ~E_DEPRECATED & ~E_NOTICE);

$bw_gefunden = false;
foreach (array(
    dirname(dirname(__DIR__)) . '/html/plugins/' . basename(__DIR__) . '/bw_lib.php',
    dirname(dirname(dirname(__DIR__))) . '/html/plugins/' . basename(__DIR__) . '/bw_lib.php',
    dirname(__DIR__) . '/html/bw_lib.php',
) as $bw_kandidat) {
    if (is_file($bw_kandidat)) { require_once $bw_kandidat; $bw_gefunden = true; break; }
}
if (!$bw_gefunden) {
    echo '<p><b>Fehler:</b> bw_lib.php wurde nicht gefunden. Bitte das Plugin neu installieren.</p>';
    exit;
}
require_once __DIR__ . '/bw_test.php';

$bw_p = bw_paths();
if ($bw_p['home'] !== '' && is_file($bw_p['home'] . '/libs/phplib/loxberry_system.php')) {
    require_once $bw_p['home'] . '/libs/phplib/loxberry_system.php';
    require_once $bw_p['home'] . '/libs/phplib/loxberry_web.php';
}

/* Positivliste: jeder Reiter MUSS hier stehen, sonst springt die Seite nach
 * jedem Absenden zurueck auf Einstellungen. */
$bw_muster = '/^tab-(settings|sources|zones|mqtt|loxone|test|log)$/';
$bw_tab = 'tab-settings';
if (isset($_POST['activetab']) && preg_match($bw_muster, (string) $_POST['activetab'])) {
    $bw_tab = (string) $_POST['activetab'];
} elseif (isset($_GET['form']) && preg_match($bw_muster, 'tab-' . (string) $_GET['form'])) {
    $bw_tab = 'tab-' . (string) $_GET['form'];
}

$bw_meldungen = array();
$bw_fehler = array();
$bw_ausgabe = '';
$bw_post = (isset($_SERVER['REQUEST_METHOD']) ? $_SERVER['REQUEST_METHOD'] : '') === 'POST';

$bw_sauber = function ($feld) {
    return trim(preg_replace('/[\x00-\x1F\x7F"\']/', '',
        (string) (isset($_POST[$feld]) ? $_POST[$feld] : '')));
};
$bw_kommazahl = function ($s) {
    // Deutsche Eingabe mit Komma zulassen - alles andere waere schikanoes.
    return str_replace(',', '.', trim((string) $s));
};

/* ---------------- Loxone-Vorlage ---------------- */
if ($bw_post && isset($_POST['vorlage_laden'])) {
    list($bw_name, $bw_xml) = bw_vorlage();
    header('Content-Type: application/xml; charset=utf-8');
    header('Content-Disposition: attachment; filename="' . $bw_name . '"');
    echo $bw_xml;
    exit;
}

/* ---------------- Einstellungen ---------------- */
if ($bw_post && isset($_POST['speichern'])) {
    $bw_cfg = bw_config();
    foreach (array('breite' => array(-90, 90), 'laenge' => array(-180, 180),
                   'hoehe' => array(-500, 5000), 'wind_hoehe' => array(0.5, 50)) as $f => $g) {
        $w = $bw_kommazahl($bw_sauber($f));
        if (!preg_match('/^-?[0-9]+(\.[0-9]+)?$/', $w)) {
            $bw_fehler[] = sprintf(bw_t('EINST.FEHLER_ZAHL'), bw_t('EINST.L_' . strtoupper($f)));
        } elseif ((float) $w < $g[0] || (float) $w > $g[1]) {
            $bw_fehler[] = sprintf(bw_t('EINST.FEHLER_BEREICH'),
                                   bw_t('EINST.L_' . strtoupper($f)), $g[0], $g[1]);
        } else {
            $bw_cfg[$f] = (float) $w;
        }
    }
    foreach (array('vorschautage' => array(1, 7), 'zonendauer_s' => array(30, 3600),
                   'pause_min' => array(0, 240), 'max_durchlaeufe' => array(1, 24),
                   'takt' => array(60, 3600)) as $f => $g) {
        $w = $bw_sauber($f);
        if (!preg_match('/^[0-9]+$/', $w)) {
            $bw_fehler[] = sprintf(bw_t('EINST.FEHLER_ZAHL'), bw_t('EINST.L_' . strtoupper($f)));
        } elseif ((int) $w < $g[0] || (int) $w > $g[1]) {
            $bw_fehler[] = sprintf(bw_t('EINST.FEHLER_BEREICH'),
                                   bw_t('EINST.L_' . strtoupper($f)), $g[0], $g[1]);
        } else {
            $bw_cfg[$f] = (int) $w;
        }
    }
    foreach (array('regen_anteil', 'wirkungsgrad') as $f) {
        $w = $bw_kommazahl($bw_sauber($f));
        if (!preg_match('/^[0-9]+(\.[0-9]+)?$/', $w) || (float) $w < 0.1 || (float) $w > 1.0) {
            $bw_fehler[] = sprintf(bw_t('EINST.FEHLER_ANTEIL'), bw_t('EINST.L_' . strtoupper($f)));
        } else {
            $bw_cfg[$f] = (float) $w;
        }
    }
    foreach (array('fenster_von', 'fenster_bis') as $f) {
        $w = $bw_sauber($f);
        if (!preg_match('/^([01][0-9]|2[0-3]):[0-5][0-9]$/', $w)) {
            $bw_fehler[] = sprintf(bw_t('EINST.FEHLER_ZEIT'), bw_t('EINST.L_' . strtoupper($f)));
        } else {
            $bw_cfg[$f] = $w;
        }
    }
    $bw_topic = $bw_sauber('mqtt_topic');
    if ($bw_topic === '' || !preg_match('#^[A-Za-z0-9_/\-]{1,64}$#', $bw_topic)) {
        $bw_fehler[] = bw_t('EINST.FEHLER_TOPIC');
    } else {
        $bw_cfg['mqtt_topic'] = trim($bw_topic, '/');
    }
    $bw_cfg['mqtt_ein'] = isset($_POST['mqtt_ein']) ? 1 : 0;
    $bw_cfg['kuestennah'] = isset($_POST['kuestennah']) ? 1 : 0;

    if (!$bw_fehler) {
        if (bw_config_speichern($bw_cfg)) { $bw_meldungen[] = bw_t('EINST.GESPEICHERT'); }
        else { $bw_fehler[] = sprintf(bw_t('EINST.FEHLER_SPEICHERN'), $bw_p['config']); }
    }
    $bw_tab = 'tab-settings';
}

/* ---------------- Dienst ---------------- */
if ($bw_post && isset($_POST['dienst'])) {
    $bw_was = (string) $_POST['dienst'];
    if (!in_array($bw_was, array('start', 'stop', 'restart'), true)) {
        $bw_fehler[] = bw_t('EINST.FEHLER_DIENST');
    } else {
        list($bw_ok, $bw_aus) = bw_dienst($bw_was);
        if ($bw_ok) { $bw_meldungen[] = sprintf(bw_t('EINST.DIENST_OK'), bw_e($bw_aus)); }
        else { $bw_fehler[] = sprintf(bw_t('EINST.DIENST_FEHL'), bw_e($bw_aus)); }
    }
    $bw_tab = 'tab-settings';
}

/* ---------------- Quellen ---------------- */
if ($bw_post && isset($_POST['vorlage_waehlen'])) {
    $bw_v = $bw_sauber('vorlage');
    $bw_alle = bw_vorlagen();
    if (!isset($bw_alle['vorlagen'][$bw_v])) {
        $bw_fehler[] = bw_t('QUELL.FEHLER_VORLAGE');
    } else {
        $bw_q = bw_quellen();
        $bw_q['vorlage'] = $bw_v;
        $bw_q['felder'] = isset($bw_alle['vorlagen'][$bw_v]['felder'])
            ? $bw_alle['vorlagen'][$bw_v]['felder'] : array();
        if (isset($bw_alle['vorlagen'][$bw_v]['http_url'])) {
            $bw_q['http_url'] = $bw_alle['vorlagen'][$bw_v]['http_url'];
        }
        if (bw_quellen_speichern($bw_q)) { $bw_meldungen[] = bw_t('QUELL.VORLAGE_UEBERNOMMEN'); }
        else { $bw_fehler[] = sprintf(bw_t('EINST.FEHLER_SPEICHERN'), $bw_p['quellen']); }
    }
    $bw_tab = 'tab-sources';
}

if ($bw_post && isset($_POST['quellen_speichern'])) {
    $bw_q = bw_quellen();
    $bw_url = trim((string) (isset($_POST['http_url']) ? $_POST['http_url'] : ''));
    if ($bw_url !== '' && !preg_match('#^https?://\S{3,200}$#', $bw_url)) {
        $bw_fehler[] = bw_t('QUELL.FEHLER_URL');
    } else {
        $bw_q['http_url'] = $bw_url;
    }
    $bw_felder = array();
    $bw_alle = bw_vorlagen();
    foreach (array_keys($bw_alle['groessen']) as $bw_g) {
        $bw_weg = isset($_POST['weg'][$bw_g]) ? (string) $_POST['weg'][$bw_g] : '';
        if (!in_array($bw_weg, array('', 'mqtt', 'http'), true)) {
            $bw_fehler[] = sprintf(bw_t('QUELL.FEHLER_WEG'), bw_e($bw_g));
            continue;
        }
        if ($bw_weg === '') { continue; }
        $bw_thema = trim(preg_replace('/[\x00-\x1F\x7F"\']/', '',
            (string) (isset($_POST['thema'][$bw_g]) ? $_POST['thema'][$bw_g] : '')));
        $bw_pfad = trim(preg_replace('/[\x00-\x1F\x7F"\']/', '',
            (string) (isset($_POST['pfad'][$bw_g]) ? $_POST['pfad'][$bw_g] : '')));
        $bw_eh = trim(preg_replace('/[^A-Za-z0-9\/2]/', '',
            (string) (isset($_POST['einheit'][$bw_g]) ? $_POST['einheit'][$bw_g] : '')));
        if ($bw_weg === 'mqtt' && $bw_thema === '') {
            $bw_fehler[] = sprintf(bw_t('QUELL.FEHLER_THEMA'), bw_e($bw_g));
            continue;
        }
        if ($bw_weg === 'http' && $bw_pfad === '') {
            $bw_fehler[] = sprintf(bw_t('QUELL.FEHLER_PFAD'), bw_e($bw_g));
            continue;
        }
        $bw_eintrag = array('weg' => $bw_weg);
        if ($bw_thema !== '') { $bw_eintrag['thema'] = $bw_thema; }
        if ($bw_pfad !== '')  { $bw_eintrag['pfad'] = $bw_pfad; }
        if ($bw_eh !== '')    { $bw_eintrag['einheit_quelle'] = $bw_eh; }
        $bw_felder[$bw_g] = $bw_eintrag;
    }
    if (!$bw_fehler) {
        $bw_q['felder'] = $bw_felder;
        if (bw_quellen_speichern($bw_q)) { $bw_meldungen[] = bw_t('QUELL.GESPEICHERT'); }
        else { $bw_fehler[] = sprintf(bw_t('EINST.FEHLER_SPEICHERN'), $bw_p['quellen']); }
    }
    $bw_tab = 'tab-sources';
}

/* ---------------- Zonen ---------------- */
if ($bw_post && isset($_POST['zonen_speichern'])) {
    $bw_pf = bw_pflanzen();
    $bw_neu = array();
    $bw_schluessel = array();
    $bw_n = isset($_POST['z_name']) ? (array) $_POST['z_name'] : array();
    foreach ($bw_n as $bw_i => $bw_name) {
        $bw_name = trim(preg_replace('/[\x00-\x1F\x7F"]/', '', (string) $bw_name));
        if ($bw_name === '') { continue; }
        $bw_s = trim(preg_replace('/[^a-z0-9_-]/', '',
            strtolower((string) (isset($_POST['z_schluessel'][$bw_i]) ? $_POST['z_schluessel'][$bw_i] : ''))));
        if ($bw_s === '') {
            $bw_fehler[] = sprintf(bw_t('ZONE.FEHLER_SCHLUESSEL'), bw_e($bw_name));
            continue;
        }
        if (isset($bw_schluessel[$bw_s])) {
            $bw_fehler[] = sprintf(bw_t('ZONE.FEHLER_DOPPELT'), bw_e($bw_s));
            continue;
        }
        $bw_schluessel[$bw_s] = 1;
        $bw_hol = function ($feld) use ($bw_i, $bw_kommazahl) {
            $a = isset($_POST[$feld]) ? (array) $_POST[$feld] : array();
            return $bw_kommazahl(trim(preg_replace('/[\x00-\x1F\x7F"\']/', '',
                (string) (isset($a[$bw_i]) ? $a[$bw_i] : ''))));
        };
        $bw_fl = $bw_hol('z_flaeche');
        if ($bw_fl !== '' && (!is_numeric($bw_fl) || (float) $bw_fl < 0 || (float) $bw_fl > 100000)) {
            $bw_fehler[] = sprintf(bw_t('ZONE.FEHLER_FLAECHE'), bw_e($bw_name));
            continue;
        }
        $bw_bep = preg_replace('/[^a-z_]/', '', strtolower($bw_hol('z_bepflanzung')));
        $bw_bod = preg_replace('/[^a-z_]/', '', strtolower($bw_hol('z_boden')));
        $bw_bepd = isset($bw_pf['bepflanzung'][$bw_bep]) ? $bw_pf['bepflanzung'][$bw_bep] : null;
        $bw_bodd = isset($bw_pf['boden'][$bw_bod]) ? $bw_pf['boden'][$bw_bod] : null;
        if ($bw_bepd === null || $bw_bodd === null) {
            $bw_fehler[] = sprintf(bw_t('ZONE.FEHLER_AUSWAHL'), bw_e($bw_name));
            continue;
        }
        $bw_rate = $bw_hol('z_rate');
        if ($bw_rate !== '' && (!is_numeric($bw_rate) || (float) $bw_rate < 0 || (float) $bw_rate > 200)) {
            $bw_fehler[] = sprintf(bw_t('ZONE.FEHLER_RATE'), bw_e($bw_name));
            continue;
        }
        $bw_alt = bw_zone($bw_s);
        $bw_neu[] = array(
            'schluessel'   => $bw_s,
            'name'         => $bw_name,
            'flaeche'      => $bw_fl !== '' ? (float) $bw_fl : 0.0,
            'bepflanzung'  => $bw_bep,
            'boden'        => $bw_bod,
            'kc'           => (float) $bw_bepd['kc'],
            'zr'           => (float) $bw_bepd['zr'],
            'p'            => (float) $bw_bepd['p'],
            'theta_fc'     => (float) $bw_bodd['theta_fc'],
            'theta_wp'     => (float) $bw_bodd['theta_wp'],
            'rate_mmh'     => $bw_rate !== '' ? (float) $bw_rate : 0.0,
            'rate_gemessen' => (int) (isset($bw_alt['rate_gemessen']) ? $bw_alt['rate_gemessen'] : 0),
            'im_zyklus'    => !empty($_POST['z_zyklus'][$bw_i]) ? 1 : 0,
            'feuchte_thema' => trim(preg_replace('/[\x00-\x1F\x7F"\']/', '',
                (string) (isset($_POST['z_feuchte'][$bw_i]) ? $_POST['z_feuchte'][$bw_i] : ''))),
            'sensor_gewicht' => (float) (isset($bw_alt['sensor_gewicht']) ? $bw_alt['sensor_gewicht'] : 0.5),
            'dr'           => (float) (isset($bw_alt['dr']) ? $bw_alt['dr'] : 0.0),
        );
    }
    if (!$bw_fehler) {
        if (bw_zonen_speichern($bw_neu)) { $bw_meldungen[] = bw_t('ZONE.GESPEICHERT'); }
        else { $bw_fehler[] = sprintf(bw_t('EINST.FEHLER_SPEICHERN'), $bw_p['zonen']); }
    }
    $bw_tab = 'tab-zones';
}

/* ---------------- Becherprobe ---------------- */
if ($bw_post && isset($_POST['becher'])) {
    $bw_s = preg_replace('/[^a-z0-9_-]/', '', strtolower((string) $_POST['becher']));
    $bw_mm = $bw_kommazahl($bw_sauber('becher_mm'));
    $bw_min = $bw_kommazahl($bw_sauber('becher_min'));
    $bw_zone = bw_zone($bw_s);
    if ($bw_zone === null) {
        $bw_fehler[] = bw_t('ZONE.FEHLER_UNBEKANNT');
    } elseif (!is_numeric($bw_mm) || !is_numeric($bw_min)
              || (float) $bw_mm <= 0 || (float) $bw_min <= 0) {
        $bw_fehler[] = bw_t('ZONE.FEHLER_BECHER');
    } else {
        $bw_rate = bw_becherprobe((float) $bw_mm, (float) $bw_min);
        $bw_liste = array();
        foreach (bw_zonen() as $bw_z) {
            if ($bw_z['schluessel'] === $bw_s) {
                $bw_z['rate_mmh'] = round($bw_rate, 2);
                $bw_z['rate_gemessen'] = 1;
                $bw_z['rate_gemessen_am'] = date('Y-m-d');
            }
            $bw_liste[] = $bw_z;
        }
        if (bw_zonen_speichern($bw_liste)) {
            $bw_meldungen[] = sprintf(bw_t('ZONE.BECHER_OK'), bw_e($bw_zone['name']), $bw_rate);
        } else {
            $bw_fehler[] = sprintf(bw_t('EINST.FEHLER_SPEICHERN'), $bw_p['zonen']);
        }
    }
    $bw_tab = 'tab-zones';
}

/* ---------------- Token, Test, Log ---------------- */
if ($bw_post && isset($_POST['token_neu'])) {
    $bw_cfg = bw_config();
    $bw_cfg['aktionstoken'] = bw_token_erzeugen();
    if (bw_config_speichern($bw_cfg)) { $bw_meldungen[] = bw_t('LOX.TOKEN_NEU'); }
    else { $bw_fehler[] = sprintf(bw_t('EINST.FEHLER_SPEICHERN'), $bw_p['config']); }
    $bw_tab = 'tab-loxone';
}
if ($bw_post && isset($_POST['log_leeren'])) {
    @mkdir(dirname($bw_p['log']), 0775, true);
    $bw_klar = trim(strip_tags(html_entity_decode(bw_t('LOG.GELEERT'), ENT_QUOTES, 'UTF-8')));
    @file_put_contents($bw_p['log'], '[' . date('Y-m-d H:i:s') . '] ' . $bw_klar . "\n");
    $bw_meldungen[] = bw_t('LOG.GELEERT');
    $bw_tab = 'tab-log';
}
if ($bw_post && isset($_POST['test'])) {
    list($bw_stand, $bw_text) = bw_test_aktion((string) $_POST['test']);
    if ($bw_stand === 1) { $bw_ausgabe = $bw_text; }
    else { $bw_fehler[] = bw_e($bw_text); }
    $bw_tab = 'tab-test';
}
if ($bw_post && isset($_POST['selbsttest'])) {
    $bw_ausgabe = bw_selbsttest_ausgabe();
    $bw_tab = 'tab-test';
}

/* ---------------- Laden ---------------- */
$bw_cfg = bw_config();
$bw_token = bw_token();
$bw_zonen = bw_zonen();
$bw_q = bw_quellen();
$bw_vorl = bw_vorlagen();
$bw_pf = bw_pflanzen();
$bw_a = bw_abbild();
$bw_pid = bw_dienst_pid();
$bw_alter = bw_alter();
$bw_plan = isset($bw_a['plan']) && is_array($bw_a['plan']) ? $bw_a['plan'] : array();

$bw_rahmen = class_exists('LBWeb', false) && method_exists('LBWeb', 'lbheader');
if ($bw_rahmen) {
    LBWeb::lbheader(bw_t('ALLG.TITEL'), 'https://www.fao.org/3/x0490e/x0490e00.htm', '');
}
?>
<style>
.sm-wrap { max-width: 980px; margin: 0 auto; font-family: -apple-system, 'Segoe UI', Roboto, sans-serif; color: #333; }
.sm-wrap, .sm-wrap *, .sm-tabs, .sm-tabs * { text-shadow: none !important; }
.sm-wrap h2 { color: #6dac20; margin: 24px 0 10px; font-size: 1.15em; border-bottom: 2px solid #e0e0e0; padding-bottom: 6px; }
.sm-wrap h3 { color: #4f7d17; font-size: 1.0em; font-weight: 700; margin: 16px 0 2px; }
.sm-tabs { display: flex; gap: 4px; margin: 14px 0 0; border-bottom: 2px solid #6dac20; flex-wrap: wrap; }
.sm-tab { background: #eee; border: 1px solid #ccc; border-bottom: 0; border-radius: 8px 8px 0 0;
          padding: 9px 18px; font-size: 0.95em; color: #444 !important; text-decoration: none; display: inline-block; }
.sm-tab.sm-active { background: #6dac20; color: #fff !important; border-color: #6dac20; font-weight: 600; }
.sm-seite { display: none; }
.sm-seite.sm-active { display: block; }
.sm-feld { margin: 14px 0; }
.sm-feld > label { display: block; font-weight: 600; font-size: 0.9em; color: #555; margin: 0 0 4px; }
.sm-feld input[type=text], .sm-feld input[type=password], .sm-feld select, .sm-feld textarea {
    width: 100%; padding: 8px 10px; border: 1px solid #ccc; border-radius: 6px;
    box-sizing: border-box; font-size: 0.95em; background: #fff; color: #333; }
.sm-hilfe { font-size: 0.84em; color: #777; margin: 3px 0 0; line-height: 1.45; }
.sm-hinweis { border: 1px solid #a5d6a7; background: #e8f5e9; border-radius: 6px; padding: 10px 12px; margin: 12px 0; font-size: 0.9em; }
.sm-warnung { border: 1px solid #f0c9a0; background: #fdf4ec; border-radius: 6px; padding: 10px 12px; margin: 12px 0; font-size: 0.9em; }
.sm-fehler { border: 1px solid #ef9a9a; background: #ffebee; border-radius: 6px; padding: 10px 12px; margin: 12px 0; font-size: 0.9em; }
.sm-an  { color: #1a7f1a; font-weight: 700; }
.sm-aus { color: #b00000; font-weight: 700; }
.sm-mono { font-family: Consolas, 'Courier New', monospace; background: #f2f2f2; padding: 1px 5px; border-radius: 4px; font-size: 0.92em; word-break: break-all; }
.sm-log { background: #1e1e1e; color: #d4d4d4; font-family: Consolas, 'Courier New', monospace;
    font-size: 0.82em; padding: 12px; border-radius: 8px; max-height: 480px; overflow: auto; white-space: pre-wrap; }
.sm-tabelle { border-collapse: collapse; width: 100%; font-size: 0.88em; margin: 10px 0; }
.sm-tabelle th, .sm-tabelle td { border: 1px solid #ddd; padding: 6px 8px; text-align: left; vertical-align: top; }
.sm-tabelle th { background: #f5f5f5; font-weight: 600; }
.sm-b { border: 0; border-radius: 6px; padding: 9px 18px; font-size: 0.93em; cursor: pointer; color: #fff; margin: 4px 6px 4px 0; }
.sm-b-lesen { background: #4f7d17; } .sm-b-technik { background: #6b7280; } .sm-b-aktion { background: #d97706; }
.sm-legende { font-size: 0.83em; color: #666; margin: 6px 0 14px; line-height: 1.8; }
.sm-legende span { display: inline-block; width: 12px; height: 12px; border-radius: 3px; vertical-align: -2px; margin-right: 5px; }
.sm-step { border-left: 3px solid #6dac20; padding: 2px 0 2px 14px; margin: 18px 0; }
.sm-step h3 { margin-top: 0; }
.sm-balken { height: 10px; border-radius: 5px; background: #eee; overflow: hidden; min-width: 90px; }
.sm-balken i { display: block; height: 100%; background: #6dac20; }
.sm-schaetz { color: #d97706; font-weight: 600; }
</style>

<div class="sm-wrap">

<?php foreach ($bw_meldungen as $bw_m) { ?>
<div class="sm-hinweis"><?= $bw_m ?></div>
<?php } ?>
<?php if ($bw_fehler) { ?>
<div class="sm-fehler"><b><?= bw_e(bw_t('ALLG.BEANSTANDUNG')) ?></b>
<ul style="margin:6px 0 0;padding-left:20px">
<?php foreach ($bw_fehler as $bw_f) { ?><li><?= $bw_f ?></li><?php } ?>
</ul></div>
<?php } ?>

<table class="sm-tabelle" style="max-width:640px">
<tr><th><?= bw_e(bw_t('ALLG.EIGENSCHAFT')) ?></th><th><?= bw_e(bw_t('ALLG.WERT')) ?></th></tr>
<tr><td><?= bw_e(bw_t('ALLG.DIENST')) ?></td>
    <td class="<?= $bw_pid ? 'sm-an' : 'sm-aus' ?>"><?= $bw_pid
        ? bw_e(bw_t('ALLG.LAEUFT')) . ' (PID ' . (int) $bw_pid . ')' : bw_e(bw_t('ALLG.GESTOPPT')) ?></td></tr>
<tr><td><?= bw_e(bw_t('ALLG.ET0')) ?></td>
    <td><?= isset($bw_a['et0']) && $bw_a['et0'] !== null
        ? '<b>' . number_format((float) $bw_a['et0'], 2, ',', '.') . '</b> mm &mdash; '
          . bw_e(bw_t('GUETE.' . strtoupper((string) $bw_a['et0_guete'])))
        : '<span class="sm-aus">' . bw_e(bw_t('ALLG.KEIN_ET0')) . '</span>' ?></td></tr>
<tr><td><?= bw_e(bw_t('ALLG.PLAN')) ?></td>
    <td><?php if ($bw_plan) {
        echo '<b>' . (int) $bw_plan['durchlaeufe'] . '</b> ' . bw_e(bw_t('ALLG.DURCHLAEUFE'));
        if ((int) $bw_plan['noetige_durchlaeufe'] > (int) $bw_plan['durchlaeufe']) {
            echo ' <span class="sm-aus">(' . sprintf(bw_e(bw_t('ALLG.NOETIG_WAEREN')),
                 (int) $bw_plan['noetige_durchlaeufe']) . ')</span>';
        }
    } else { echo bw_e(bw_t('ALLG.KEIN_PLAN')); } ?></td></tr>
<tr><td><?= bw_e(bw_t('ALLG.ZONEN')) ?></td><td><?= count($bw_zonen) ?></td></tr>
<tr><td><?= bw_e(bw_t('ALLG.GERECHNET')) ?></td>
    <td class="<?= ($bw_alter >= 0 && $bw_alter < 129600) ? 'sm-an' : 'sm-aus' ?>"><?= $bw_alter < 0
        ? bw_e(bw_t('ALLG.NIE')) : sprintf(bw_e(bw_t('ALLG.VOR_STUNDEN')), (int) round($bw_alter / 3600)) ?></td></tr>
</table>

<div class="sm-tabs">
  <a href="#" class="sm-tab" data-ziel="tab-settings"><?= bw_e(bw_t('REITER.EINSTELLUNGEN')) ?></a>
  <a href="#" class="sm-tab" data-ziel="tab-sources"><?= bw_e(bw_t('REITER.QUELLEN')) ?></a>
  <a href="#" class="sm-tab" data-ziel="tab-zones"><?= bw_e(bw_t('REITER.ZONEN')) ?></a>
  <a href="#" class="sm-tab" data-ziel="tab-mqtt"><?= bw_e(bw_t('REITER.MQTT')) ?></a>
  <a href="#" class="sm-tab" data-ziel="tab-loxone"><?= bw_e(bw_t('REITER.LOXONE')) ?></a>
  <a href="#" class="sm-tab" data-ziel="tab-test"><?= bw_e(bw_t('REITER.TEST')) ?></a>
  <a href="#" class="sm-tab" data-ziel="tab-log"><?= bw_e(bw_t('REITER.LOG')) ?></a>
</div>

<!-- ============ Einstellungen ============ -->
<div class="sm-seite" id="tab-settings">
<div class="sm-hinweis"><?= bw_t('EINST.WAS_IST_DAS') ?></div>

<h2><?= bw_e(bw_t('EINST.H_DIENST')) ?></h2>
<div class="sm-legende">
  <span style="background:#4f7d17"></span><?= bw_t('LEGENDE.LESEN') ?><br>
  <span style="background:#6b7280"></span><?= bw_t('LEGENDE.TECHNIK') ?><br>
  <span style="background:#d97706"></span><?= bw_t('LEGENDE.AKTION') ?>
</div>
<form method="post">
  <input type="hidden" name="activetab" value="tab-settings">
  <button class="sm-b sm-b-aktion" name="dienst" value="start"><?= bw_e(bw_t('EINST.K_START')) ?></button>
  <button class="sm-b sm-b-aktion" name="dienst" value="restart"><?= bw_e(bw_t('EINST.K_NEUSTART')) ?></button>
  <button class="sm-b sm-b-aktion" name="dienst" value="stop"><?= bw_e(bw_t('EINST.K_STOP')) ?></button>
</form>

<form method="post">
<input type="hidden" name="activetab" value="tab-settings">
<h2><?= bw_e(bw_t('EINST.H_STANDORT')) ?></h2>
<p class="sm-hilfe"><?= bw_t('EINST.STANDORT_ERKLAERUNG') ?></p>
<?php foreach (array('breite', 'laenge', 'hoehe', 'wind_hoehe') as $bw_f) { ?>
<div class="sm-feld">
  <label for="<?= $bw_f ?>"><?= bw_t('EINST.L_' . strtoupper($bw_f)) ?></label>
  <input data-role="none" type="text" name="<?= $bw_f ?>" id="<?= $bw_f ?>" value="<?= bw_e($bw_cfg[$bw_f]) ?>">
  <?php if ($bw_f === 'wind_hoehe') { ?><p class="sm-hilfe"><?= bw_t('EINST.H_WIND_HOEHE') ?></p><?php } ?>
</div>
<?php } ?>
<label><input data-role="none" type="checkbox" name="kuestennah" value="1"<?= !empty($bw_cfg['kuestennah']) ? ' checked' : '' ?>>
  <?= bw_e(bw_t('EINST.L_KUESTENNAH')) ?></label>

<h2><?= bw_e(bw_t('EINST.H_RECHNUNG')) ?></h2>
<?php foreach (array('vorschautage', 'regen_anteil', 'wirkungsgrad', 'takt') as $bw_f) { ?>
<div class="sm-feld">
  <label for="<?= $bw_f ?>"><?= bw_t('EINST.L_' . strtoupper($bw_f)) ?></label>
  <input data-role="none" type="text" name="<?= $bw_f ?>" id="<?= $bw_f ?>" value="<?= bw_e($bw_cfg[$bw_f]) ?>">
  <p class="sm-hilfe"><?= bw_t('EINST.H_' . strtoupper($bw_f)) ?></p>
</div>
<?php } ?>

<h2><?= bw_e(bw_t('EINST.H_ANLAGE')) ?></h2>
<p class="sm-hilfe"><?= bw_t('EINST.ANLAGE_ERKLAERUNG') ?></p>
<?php foreach (array('zonendauer_s', 'pause_min', 'fenster_von', 'fenster_bis', 'max_durchlaeufe') as $bw_f) { ?>
<div class="sm-feld">
  <label for="<?= $bw_f ?>"><?= bw_t('EINST.L_' . strtoupper($bw_f)) ?></label>
  <input data-role="none" type="text" name="<?= $bw_f ?>" id="<?= $bw_f ?>" value="<?= bw_e($bw_cfg[$bw_f]) ?>">
</div>
<?php } ?>

<h2><?= bw_e(bw_t('EINST.H_MQTT')) ?></h2>
<label><input data-role="none" type="checkbox" name="mqtt_ein" value="1"<?= !empty($bw_cfg['mqtt_ein']) ? ' checked' : '' ?>>
  <?= bw_e(bw_t('EINST.L_MQTT_EIN')) ?></label>
<div class="sm-feld">
  <label for="mqtt_topic"><?= bw_e(bw_t('EINST.L_MQTT_TOPIC')) ?></label>
  <input data-role="none" type="text" name="mqtt_topic" id="mqtt_topic" value="<?= bw_e($bw_cfg['mqtt_topic']) ?>">
</div>
<button class="sm-b sm-b-aktion" name="speichern" value="1"><?= bw_e(bw_t('ALLG.SPEICHERN')) ?></button>
</form>
</div>

<!-- ============ Quellen ============ -->
<div class="sm-seite" id="tab-sources">
<h2><?= bw_e(bw_t('QUELL.H_TITEL')) ?></h2>
<div class="sm-hinweis"><?= bw_t('QUELL.ERKLAERUNG') ?></div>

<form method="post">
<input type="hidden" name="activetab" value="tab-sources">
<div class="sm-feld">
  <label for="vorlage"><?= bw_e(bw_t('QUELL.L_VORLAGE')) ?></label>
  <select data-role="none" name="vorlage" id="vorlage">
  <?php foreach (($bw_vorl['vorlagen'] ?: array()) as $bw_k => $bw_v) { ?>
    <option value="<?= bw_e($bw_k) ?>"<?= (isset($bw_q['vorlage']) && $bw_q['vorlage'] === $bw_k) ? ' selected' : '' ?>><?= bw_e($bw_v['text']) ?></option>
  <?php } ?>
  </select>
  <p class="sm-hilfe"><?= bw_t('QUELL.H_VORLAGE') ?></p>
</div>
<button class="sm-b sm-b-aktion" name="vorlage_waehlen" value="1"><?= bw_e(bw_t('QUELL.K_VORLAGE')) ?></button>
</form>
<?php if (isset($bw_q['vorlage']) && isset($bw_vorl['vorlagen'][$bw_q['vorlage']]['hinweis'])) { ?>
<div class="sm-warnung"><?= bw_e($bw_vorl['vorlagen'][$bw_q['vorlage']]['hinweis']) ?></div>
<?php } ?>

<form method="post">
<input type="hidden" name="activetab" value="tab-sources">
<div class="sm-feld">
  <label for="http_url"><?= bw_e(bw_t('QUELL.L_URL')) ?></label>
  <input data-role="none" type="text" name="http_url" id="http_url"
         value="<?= bw_e(isset($bw_q['http_url']) ? $bw_q['http_url'] : '') ?>"
         placeholder="http://192.0.2.10/get_livedata_info">
</div>
<table class="sm-tabelle">
<tr><th><?= bw_e(bw_t('QUELL.T_GROESSE')) ?></th><th><?= bw_e(bw_t('QUELL.T_WEG')) ?></th>
    <th><?= bw_e(bw_t('QUELL.T_THEMA')) ?></th><th><?= bw_e(bw_t('QUELL.T_PFAD')) ?></th>
    <th><?= bw_e(bw_t('QUELL.T_EINHEIT')) ?></th><th><?= bw_e(bw_t('QUELL.T_HERKUNFT')) ?></th></tr>
<?php
$bw_h = isset($bw_a['herkunft']) && is_array($bw_a['herkunft']) ? $bw_a['herkunft'] : array();
foreach (($bw_vorl['groessen'] ?: array()) as $bw_g => $bw_gd) {
    $bw_f = isset($bw_q['felder'][$bw_g]) ? $bw_q['felder'][$bw_g] : array(); ?>
<tr>
  <td><?= bw_e($bw_gd['text']) ?><?= !empty($bw_gd['pflicht']) ? ' <span class="sm-aus">*</span>' : '' ?>
      <div class="sm-hilfe sm-mono"><?= bw_e($bw_g) ?> [<?= bw_e($bw_gd['einheit']) ?>]</div></td>
  <td><select data-role="none" name="weg[<?= bw_e($bw_g) ?>]" style="min-width:88px">
      <?php foreach (array('' => bw_t('QUELL.WEG_KEINE'), 'mqtt' => 'MQTT', 'http' => 'HTTP') as $bw_wk => $bw_wt) { ?>
      <option value="<?= bw_e($bw_wk) ?>"<?= (isset($bw_f['weg']) ? $bw_f['weg'] : '') === $bw_wk ? ' selected' : '' ?>><?= bw_e($bw_wt) ?></option>
      <?php } ?></select></td>
  <td><input data-role="none" type="text" name="thema[<?= bw_e($bw_g) ?>]" size="20"
             value="<?= bw_e(isset($bw_f['thema']) ? $bw_f['thema'] : '') ?>"></td>
  <td><input data-role="none" type="text" name="pfad[<?= bw_e($bw_g) ?>]" size="16"
             value="<?= bw_e(isset($bw_f['pfad']) ? $bw_f['pfad'] : '') ?>"></td>
  <td><input data-role="none" type="text" name="einheit[<?= bw_e($bw_g) ?>]" size="5"
             value="<?= bw_e(isset($bw_f['einheit_quelle']) ? $bw_f['einheit_quelle'] : '') ?>"></td>
  <td><?php $bw_hw = isset($bw_h[$bw_g]) ? $bw_h[$bw_g] : '';
      echo $bw_hw === 'station' ? '<span class="sm-an">' . bw_e(bw_t('QUELL.HK_STATION')) . '</span>'
         : ($bw_hw === 'open-meteo' ? bw_e(bw_t('QUELL.HK_ONLINE'))
         : '<span class="sm-hilfe">' . bw_e($bw_hw !== '' ? $bw_hw : bw_t('QUELL.HK_KEINE')) . '</span>'); ?></td>
</tr>
<?php } ?>
</table>
<p class="sm-hilfe"><?= bw_t('QUELL.FUSSNOTE') ?></p>
<button class="sm-b sm-b-aktion" name="quellen_speichern" value="1"><?= bw_e(bw_t('ALLG.SPEICHERN')) ?></button>
</form>
</div>

<!-- ============ Zonen ============ -->
<div class="sm-seite" id="tab-zones">
<h2><?= bw_e(bw_t('ZONE.H_TITEL')) ?></h2>
<p class="sm-hilfe"><?= bw_t('ZONE.ERKLAERUNG') ?></p>
<form method="post">
<input type="hidden" name="activetab" value="tab-zones">
<table class="sm-tabelle">
<tr><th><?= bw_e(bw_t('ZONE.T_NAME')) ?></th><th><?= bw_e(bw_t('ZONE.T_SCHLUESSEL')) ?></th>
    <th><?= bw_e(bw_t('ZONE.T_FLAECHE')) ?></th><th><?= bw_e(bw_t('ZONE.T_BEPFLANZUNG')) ?></th>
    <th><?= bw_e(bw_t('ZONE.T_BODEN')) ?></th><th><?= bw_e(bw_t('ZONE.T_RATE')) ?></th>
    <th><?= bw_e(bw_t('ZONE.T_FEUCHTE')) ?></th><th><?= bw_e(bw_t('ZONE.T_ZYKLUS')) ?></th></tr>
<?php for ($bw_i = 0; $bw_i < 8; $bw_i++) {
    $bw_z = isset($bw_zonen[$bw_i]) ? $bw_zonen[$bw_i] : array(); ?>
<tr>
  <td><input data-role="none" type="text" name="z_name[<?= $bw_i ?>]" size="16"
             value="<?= bw_e(isset($bw_z['name']) ? $bw_z['name'] : '') ?>"></td>
  <td><input data-role="none" type="text" name="z_schluessel[<?= $bw_i ?>]" size="9"
             value="<?= bw_e(isset($bw_z['schluessel']) ? $bw_z['schluessel'] : '') ?>"></td>
  <td><input data-role="none" type="text" name="z_flaeche[<?= $bw_i ?>]" size="6"
             value="<?= bw_e(isset($bw_z['flaeche']) ? $bw_z['flaeche'] : '') ?>"></td>
  <td><select data-role="none" name="z_bepflanzung[<?= $bw_i ?>]">
      <?php foreach (($bw_pf['bepflanzung'] ?: array()) as $bw_k => $bw_v) { ?>
      <option value="<?= bw_e($bw_k) ?>"<?= (isset($bw_z['bepflanzung']) ? $bw_z['bepflanzung'] : 'rasen_kuehl') === $bw_k ? ' selected' : '' ?>><?= bw_e($bw_v['text']) ?><?= !empty($bw_v['geschaetzt']) ? ' *' : '' ?></option>
      <?php } ?></select></td>
  <td><select data-role="none" name="z_boden[<?= $bw_i ?>]">
      <?php foreach (($bw_pf['boden'] ?: array()) as $bw_k => $bw_v) {
          if ($bw_k === '_hinweis') { continue; } ?>
      <option value="<?= bw_e($bw_k) ?>"<?= (isset($bw_z['boden']) ? $bw_z['boden'] : 'lehm') === $bw_k ? ' selected' : '' ?>><?= bw_e($bw_v['text']) ?><?= !empty($bw_v['geschaetzt']) ? ' *' : '' ?></option>
      <?php } ?></select></td>
  <td><input data-role="none" type="text" name="z_rate[<?= $bw_i ?>]" size="5"
             value="<?= bw_e(isset($bw_z['rate_mmh']) ? $bw_z['rate_mmh'] : '') ?>">
      <?php if (!empty($bw_z['schluessel'])) { ?>
      <div class="sm-hilfe"><?= !empty($bw_z['rate_gemessen'])
          ? '<span class="sm-an">' . bw_e(bw_t('ZONE.GEMESSEN')) . '</span>'
          : '<span class="sm-schaetz">' . bw_e(bw_t('ZONE.GESCHAETZT')) . '</span>' ?></div>
      <?php } ?></td>
  <td><input data-role="none" type="text" name="z_feuchte[<?= $bw_i ?>]" size="16"
             value="<?= bw_e(isset($bw_z['feuchte_thema']) ? $bw_z['feuchte_thema'] : '') ?>"
             placeholder="<?= bw_e(bw_t('ZONE.P_FEUCHTE')) ?>"></td>
  <td style="text-align:center"><input data-role="none" type="checkbox" name="z_zyklus[<?= $bw_i ?>]" value="1"<?= !empty($bw_z['im_zyklus']) ? ' checked' : '' ?>></td>
</tr>
<?php } ?>
</table>
<p class="sm-hilfe"><?= bw_t('ZONE.FUSSNOTE') ?></p>
<button class="sm-b sm-b-aktion" name="zonen_speichern" value="1"><?= bw_e(bw_t('ALLG.SPEICHERN')) ?></button>
</form>

<h2><?= bw_e(bw_t('ZONE.H_BECHER')) ?></h2>
<div class="sm-warnung"><?= bw_t('ZONE.BECHER_ERKLAERUNG') ?></div>
<?php if ($bw_zonen) { ?>
<form method="post">
<input type="hidden" name="activetab" value="tab-zones">
<div class="sm-feld"><label for="becher"><?= bw_e(bw_t('ZONE.L_BECHER_ZONE')) ?></label>
<select data-role="none" name="becher" id="becher">
<?php foreach ($bw_zonen as $bw_z) { ?>
<option value="<?= bw_e($bw_z['schluessel']) ?>"><?= bw_e($bw_z['name']) ?></option>
<?php } ?>
</select></div>
<div class="sm-feld"><label for="becher_min"><?= bw_e(bw_t('ZONE.L_BECHER_MIN')) ?></label>
<input data-role="none" type="text" name="becher_min" id="becher_min" value="15"></div>
<div class="sm-feld"><label for="becher_mm"><?= bw_e(bw_t('ZONE.L_BECHER_MM')) ?></label>
<input data-role="none" type="text" name="becher_mm" id="becher_mm" value=""></div>
<button class="sm-b sm-b-aktion" name="becher_senden" value="1"><?= bw_e(bw_t('ZONE.K_BECHER')) ?></button>
</form>
<?php } ?>

<?php if ($bw_a && !empty($bw_a['zonen'])) { ?>
<h2><?= bw_e(bw_t('ZONE.H_STAND')) ?></h2>
<table class="sm-tabelle">
<tr><th><?= bw_e(bw_t('ZONE.T_NAME')) ?></th><th><?= bw_e(bw_t('ZONE.T_FUELLSTAND')) ?></th>
    <th><?= bw_e(bw_t('ZONE.T_DEFIZIT')) ?></th><th><?= bw_e(bw_t('ZONE.T_BEDARF')) ?></th>
    <th><?= bw_e(bw_t('ZONE.T_LITER')) ?></th><th><?= bw_e(bw_t('ZONE.T_MINUTEN')) ?></th></tr>
<?php foreach ($bw_zonen as $bw_z) {
    $bw_s = (string) $bw_z['schluessel'];
    $bw_e = isset($bw_a['zonen'][$bw_s]) ? $bw_a['zonen'][$bw_s] : null;
    if (!is_array($bw_e) || empty($bw_e['ok'])) { continue; }
    $bw_ges = empty($bw_z['rate_gemessen']); ?>
<tr><td><?= bw_e($bw_z['name']) ?></td>
    <td><div class="sm-balken"><i style="width:<?= (int) $bw_e['fuellstand'] ?>%"></i></div>
        <span class="sm-hilfe"><?= (int) $bw_e['fuellstand'] ?> %</span></td>
    <td><?= number_format((float) $bw_e['dr'], 1, ',', '.') ?> mm</td>
    <td><?= number_format((float) $bw_e['bedarf_mm'], 1, ',', '.') ?> mm</td>
    <td><?= number_format((float) (isset($bw_e['liter']) ? $bw_e['liter'] : 0), 0, ',', '.') ?><?= $bw_ges ? ' <span class="sm-schaetz">*</span>' : '' ?></td>
    <td><?= number_format((float) (isset($bw_e['minuten']) ? $bw_e['minuten'] : 0), 0, ',', '.') ?><?= $bw_ges ? ' <span class="sm-schaetz">*</span>' : '' ?></td></tr>
<?php } ?>
</table>
<p class="sm-hilfe"><?= bw_t('ZONE.STAND_FUSSNOTE') ?></p>
<?php } ?>
</div>

<!-- ============ MQTT ============ -->
<div class="sm-seite" id="tab-mqtt">
<h2><?= bw_e(bw_t('MQTT.H_TITEL')) ?></h2>
<?php $bw_g = bw_mqtt_zustand(); ?>
<table class="sm-tabelle" style="max-width:520px">
<tr><td><?= bw_e(bw_t('MQTT.T_GATEWAY')) ?></td>
    <td class="<?= !empty($bw_g['autostart']) ? 'sm-an' : 'sm-aus' ?>"><?= !empty($bw_g['autostart'])
        ? bw_e(bw_t('MQTT.AUTOSTART_EIN')) : bw_e(bw_t('MQTT.AUTOSTART_AUS')) ?></td></tr>
<tr><td><?= bw_e(bw_t('MQTT.T_UDP')) ?></td><td class="sm-mono"><?= (int) (isset($bw_g['udpport']) ? $bw_g['udpport'] : 0) ?></td></tr>
</table>
<div class="sm-warnung"><?= bw_t('MQTT.ABO_WARNUNG') ?></div>
<p class="sm-hilfe"><?= bw_t('MQTT.ABO_TEXT') ?></p>
<p><span class="sm-mono"><?= bw_e($bw_cfg['mqtt_topic']) ?>/#</span></p>

<h3><?= bw_e(bw_t('MQTT.H_THEMEN')) ?></h3>
<table class="sm-tabelle">
<tr><th><?= bw_e(bw_t('MQTT.T_THEMA')) ?></th><th><?= bw_e(bw_t('MQTT.T_BEDEUTUNG')) ?></th></tr>
<?php foreach (array('ok' => 'MQTT.B_OK', 'et0' => 'MQTT.B_ET0', 'giessen' => 'MQTT.B_GIESSEN',
                     'durchlaeufe' => 'MQTT.B_DURCHLAEUFE', 'noetige_durchlaeufe' => 'MQTT.B_NOETIG',
                     'reicht' => 'MQTT.B_REICHT') as $bw_k => $bw_v) { ?>
<tr><td class="sm-mono"><?= bw_e($bw_cfg['mqtt_topic'] . '/' . $bw_k) ?></td><td><?= bw_t($bw_v) ?></td></tr>
<?php } ?>
<?php foreach ($bw_zonen as $bw_z) { $bw_s = bw_e($bw_z['schluessel']); ?>
<tr><td class="sm-mono"><?= bw_e($bw_cfg['mqtt_topic']) ?>/<?= $bw_s ?>/defizit_mm</td><td><?= sprintf(bw_t('MQTT.B_ZONE_DEFIZIT'), bw_e($bw_z['name'])) ?></td></tr>
<tr><td class="sm-mono"><?= bw_e($bw_cfg['mqtt_topic']) ?>/<?= $bw_s ?>/liter</td><td><?= sprintf(bw_t('MQTT.B_ZONE_LITER'), bw_e($bw_z['name'])) ?></td></tr>
<?php } ?>
</table>
</div>

<!-- ============ Einbindung in Loxone ============ -->
<div class="sm-seite" id="tab-loxone">
<h2><?= bw_e(bw_t('LOX.H_TITEL')) ?></h2>
<p class="sm-hilfe"><?= bw_t('LOX.EINLEITUNG') ?></p>

<div class="sm-step">
<h3><?= bw_e(bw_t('LOX.S1_TITEL')) ?></h3>
<p class="sm-hilfe"><?= bw_t('LOX.S1_TEXT') ?></p>
<table class="sm-tabelle">
<tr><th><?= bw_e(bw_t('LOX.T_TITEL')) ?></th><th><?= bw_e(bw_t('LOX.T_BEFEHL')) ?></th><th><?= bw_e(bw_t('LOX.T_BEDEUTUNG')) ?></th></tr>
<?php foreach (bw_status_felder() as $bw_feld => $bw_info) { ?>
<tr><td class="sm-mono">BEW_<?= bw_e($bw_feld) ?></td><td class="sm-mono">\i<?= bw_e($bw_feld) ?>=\i\v</td>
    <td><?= bw_t($bw_info[1]) ?><?= $bw_info[0] !== '' ? ' [' . bw_e($bw_info[0]) . ']' : '' ?></td></tr>
<?php } ?>
</table>
<p class="sm-hilfe sm-mono">http://<?= bw_e(isset($_SERVER['HTTP_HOST']) ? $_SERVER['HTTP_HOST'] : 'loxberry') ?>/plugins/<?= bw_e($bw_p['plugin']) ?>/index.php?token=<?= bw_e($bw_token) ?>&amp;aktion=status</p>
<form method="post" style="display:inline">
  <input type="hidden" name="activetab" value="tab-loxone">
  <button class="sm-b sm-b-lesen" name="vorlage_laden" value="1"><?= bw_e(bw_t('LOX.K_VORLAGE')) ?></button>
</form>
</div>

<div class="sm-step">
<h3><?= bw_e(bw_t('LOX.S2_TITEL')) ?></h3>
<p class="sm-hilfe"><?= bw_t('LOX.S2_TEXT') ?></p>
<div class="sm-hinweis"><?= bw_t('LOX.S2_HINWEIS') ?></div>
</div>

<div class="sm-step">
<h3><?= bw_e(bw_t('LOX.S3_TITEL')) ?></h3>
<p class="sm-hilfe"><?= bw_t('LOX.S3_TEXT') ?></p>
<table class="sm-tabelle">
<tr><th>#</th><th><?= bw_e(bw_t('LOX.T_BAUSTEIN')) ?></th><th><?= bw_e(bw_t('LOX.T_NAMENSVORSCHLAG')) ?></th>
    <th><?= bw_e(bw_t('LOX.T_PARAMETER')) ?></th><th><?= bw_e(bw_t('LOX.T_EINGAENGE')) ?></th></tr>
<?php
$bw_liste = array(
    array(1,  'BAUSTEIN.T_VE',      'BAUSTEIN.N01', 'BAUSTEIN.P01', '&mdash;'),
    array(2,  'BAUSTEIN.T_VE',      'BAUSTEIN.N02', 'BAUSTEIN.P02', '&mdash;'),
    array(3,  'BAUSTEIN.T_VE',      'BAUSTEIN.N03', 'BAUSTEIN.P03', '&mdash;'),
    array(4,  'BAUSTEIN.T_VE',      'BAUSTEIN.N04', 'BAUSTEIN.P04', '&mdash;'),
    array(5,  'BAUSTEIN.T_SWS',     'BAUSTEIN.N05', 'BAUSTEIN.P05', 'I &larr; #1'),
    array(6,  'BAUSTEIN.T_NICHT',   'BAUSTEIN.N06', '',             'I &larr; #5'),
    array(7,  'BAUSTEIN.T_ZAEHLER', 'BAUSTEIN.N07', 'BAUSTEIN.P07', 'I &larr; ' . bw_t('BAUSTEIN.E_DURCHLAUF')),
    array(8,  'BAUSTEIN.T_VERGL',   'BAUSTEIN.N08', 'BAUSTEIN.P08', 'AI1 &larr; #7, AI2 &larr; #2'),
    array(9,  'BAUSTEIN.T_ODER',    'BAUSTEIN.N09', '',             'I1 &larr; #6, I2 &larr; #8'),
    array(10, 'BAUSTEIN.T_BEW',     'BAUSTEIN.N10', 'BAUSTEIN.P10', 'Off &larr; #9'),
    array(11, 'BAUSTEIN.T_SWS',     'BAUSTEIN.N11', 'BAUSTEIN.P11', 'I &larr; #4'),
    array(12, 'BAUSTEIN.T_BENACHR', 'BAUSTEIN.N12', 'BAUSTEIN.P12', 'I &larr; #11'),
);
foreach ($bw_liste as $bw_z2) { ?>
<tr><td><?= (int) $bw_z2[0] ?></td><td><?= bw_t($bw_z2[1]) ?></td>
    <td class="sm-mono"><?= bw_t($bw_z2[2]) ?></td>
    <td><?= $bw_z2[3] !== '' ? bw_t($bw_z2[3]) : '&mdash;' ?></td>
    <td class="sm-mono"><?= $bw_z2[4] ?></td></tr>
<?php } ?>
</table>
<div class="sm-hinweis"><?= bw_t('LOX.S3_ERLAEUTERUNG') ?></div>
</div>

<div class="sm-step">
<h3><?= bw_e(bw_t('LOX.S4_TITEL')) ?></h3>
<p class="sm-hilfe"><?= bw_t('LOX.S4_TEXT') ?></p>
<table class="sm-tabelle"><tr><th><?= bw_e(bw_t('LOX.T_TOKEN')) ?></th><td class="sm-mono"><?= bw_e($bw_token) ?></td></tr></table>
<form method="post" style="display:inline">
  <input type="hidden" name="activetab" value="tab-loxone">
  <button class="sm-b sm-b-aktion" name="token_neu" value="1"
    onclick="return confirm(<?= json_encode(strip_tags(html_entity_decode(bw_t('LOX.TOKEN_FRAGE'), ENT_QUOTES, 'UTF-8'))) ?>)"><?= bw_e(bw_t('LOX.K_TOKEN_NEU')) ?></button>
</form>
</div>
</div>

<!-- ============ Test ============ -->
<div class="sm-seite" id="tab-test">
<h2><?= bw_e(bw_t('TEST.H_SELBSTPRUEFUNG')) ?></h2>
<p class="sm-hilfe"><?= bw_t('TEST.EINLEITUNG') ?></p>
<?= bw_pruefungen_html() ?>

<h2><?= bw_e(bw_t('TEST.H_LESEN')) ?></h2>
<div class="sm-legende">
  <span style="background:#4f7d17"></span><?= bw_t('LEGENDE.LESEN') ?><br>
  <span style="background:#6b7280"></span><?= bw_t('LEGENDE.TECHNIK') ?><br>
  <span style="background:#d97706"></span><?= bw_t('LEGENDE.AKTION') ?>
</div>
<form method="post">
  <input type="hidden" name="activetab" value="tab-test">
  <button class="sm-b sm-b-lesen" name="test" value="status"><?= bw_e(bw_t('TEST.K_STATUS')) ?></button>
  <button class="sm-b sm-b-technik" name="test" value="roh"><?= bw_e(bw_t('TEST.K_ROH')) ?></button>
  <button class="sm-b sm-b-technik" name="selbsttest" value="1"><?= bw_e(bw_t('TEST.K_SELBSTTEST')) ?></button>
  <button class="sm-b sm-b-aktion" name="test" value="rechnen"><?= bw_e(bw_t('TEST.K_RECHNEN')) ?></button>
</form>
<?php if ($bw_ausgabe !== '') { ?>
<div class="sm-log"><?= bw_e($bw_ausgabe) ?></div>
<?php } ?>

<h2><?= bw_e(bw_t('TEST.H_UNGEPRUEFT')) ?></h2>
<div class="sm-warnung"><?= bw_t('TEST.UNGEPRUEFT') ?></div>
</div>

<!-- ============ Logdateien ============ -->
<div class="sm-seite" id="tab-log">
<h2><?= bw_e(bw_t('LOG.H_TITEL')) ?></h2>
<p class="sm-hilfe"><?= bw_t('LOG.ERKLAERUNG') ?></p>
<p class="sm-hilfe sm-mono"><?= bw_e($bw_p['log']) ?></p>
<?php
$bw_zeilen = array();
if (is_file($bw_p['log'])) {
    $bw_alle2 = @file($bw_p['log'], FILE_IGNORE_NEW_LINES);
    if (is_array($bw_alle2)) { $bw_zeilen = array_slice($bw_alle2, -400); }
}
if (!$bw_zeilen) { ?>
<div class="sm-hinweis"><?= bw_t('LOG.LEER') ?></div>
<?php } else { ?>
<div class="sm-log"><?= bw_e(implode("\n", $bw_zeilen)) ?></div>
<?php } ?>
<div class="sm-legende"><span style="background:#d97706"></span><?= bw_t('LEGENDE.AKTION_LOG') ?></div>
<form method="post">
  <input type="hidden" name="activetab" value="tab-log">
  <button class="sm-b sm-b-aktion" name="log_leeren" value="1"><?= bw_e(bw_t('LOG.K_LEEREN')) ?></button>
</form>
</div>

</div><!-- /sm-wrap -->

<script>
(function () {
	var reiter = document.querySelectorAll('.sm-tab');
	function zeige(id) {
		reiter.forEach(function (r) { r.classList.toggle('sm-active', r.dataset.ziel === id); });
		document.querySelectorAll('.sm-seite').forEach(function (s) { s.classList.toggle('sm-active', s.id === id); });
		document.querySelectorAll('input[name="activetab"]').forEach(function (f) { f.value = id; });
		if (history.replaceState) { history.replaceState(null, '', 'index.php?form=' + id.replace('tab-', '')); }
	}
	reiter.forEach(function (r) {
		r.addEventListener('click', function (e) { e.preventDefault(); zeige(r.dataset.ziel); });
	});
	zeige(<?= json_encode($bw_tab) ?>);
})();
</script>

<?php
if ($bw_rahmen) {
    LBWeb::lbfooter();
}
