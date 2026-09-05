<?php
/**
 * Bewaesserung vorausschauend - Bedienoberflaeche
 *
 * Reiter: Einstellungen | Quellen | Zonen | Verlauf | MQTT |
 *         Einbindung in Loxone | Test | Logdateien
 *
 * Acht Reiter: drei kommen zu den fuenf des Hausstandards hinzu, weil sie
 * eigene Vorgaenge sind - 'Quellen' ordnet die Wetterstation zu
 * (herstellerneutral), 'Zonen' pflegt Flaechen, Bepflanzung, Boden und die
 * Becherprobe, 'Verlauf' zeigt die Tagesreihe, aus der die Bilanz entsteht.
 * In den Einstellungen wuerden alle drei untergehen.
 *
 * Kein verstecktes 'formular=<name>': jeder Handler haengt an einem eigenen,
 * eindeutigen Schluessel (dem Knopfnamen bzw. 'save_mqtt'), und der
 * Wachposten leert $_POST, bevor irgendein Zweig anlaeuft. Ein zweites
 * Kennzeichen waere eine zweite Stelle, die niemand pflegt. Wer hier einen
 * Handler ergaenzt, prueft einen Schluessel, den KEIN anderes Formular
 * mitschickt - sonst laufen zwei Zweige auf einen Druck.
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
$bw_muster = '/^tab-(settings|sources|zones|history|mqtt|loxone|test|log)$/';
$bw_tab = 'tab-settings';
if (isset($_POST['activetab']) && preg_match($bw_muster, (string) $_POST['activetab'])) {
    $bw_tab = (string) $_POST['activetab'];
} elseif (isset($_GET['form']) && preg_match($bw_muster, 'tab-' . (string) $_GET['form'])) {
    $bw_tab = 'tab-' . (string) $_GET['form'];
}

$bw_meldungen = array();
$bw_fehler = array();

/* ---------------------------------------------------------------- *
 * Der Wachposten - EIN Posten, vor allen Handlern.
 * Abgewiesen heisst gemeldet, und es wird NICHTS ausgefuehrt: $_POST
 * wird geleert, nur der aktive Reiter bleibt stehen, damit der Bediener
 * nach der Abweisung dort steht, wo er war.
 * ---------------------------------------------------------------- */
$bw_wache = bw_wachposten();
if ($bw_wache !== '') {
    $bw_reiter_merk = isset($_POST['activetab']) && is_string($_POST['activetab'])
        ? (string) $_POST['activetab'] : null;
    $_POST = array();
    if ($bw_reiter_merk !== null) {
        $_POST['activetab'] = $bw_reiter_merk;
    }
    $bw_fehler[] = $bw_wache;
}

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

/* ==================================================================
 * DIE HANDLER STEHEN VOR lbheader() - DAS IST BAUVORSCHRIFT
 * ==================================================================
 *
 * Stand der Kopf davor, war er beim Aufruf von header() schon
 * geschrieben - "Cannot modify header information", und der Knopf
 * "Einstellungen sichern" lieferte eine Seite mit angehaengtem JSON
 * statt einer Datei.
 *
 * Am PHP-CLI ist das unsichtbar: header() ist dort wirkungslos und
 * headers_sent() immer falsch. Und wer OHNE gueltiges Formularmerkmal
 * misst, wird vom Wachposten abgewiesen, bevor der Handler anlaeuft.
 * Beides hat den Fehler lange verdeckt.
 *
 * Reihenfolge: Bibliothek, Konfiguration, Wachposten, Reiterwahl,
 * ALLE Handler samt Downloads, dann erst lbheader(), dann HTML.
 * ================================================================== */
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
    // Gleiche Anfangs- und Endzeit wird abgewiesen.
    //
    // '08:00 bis 08:00' ist der Tippfehler, der entsteht, wenn jemand die
    // zweite Zeit vergisst zu aendern. Bis 0.9.0 fiel das in den
    // Mitternachtszweig der Fensterrechnung und kam als volle 24 Stunden
    // heraus - der Plan haette dann die ganze Nacht zum Giessen gehabt.
    // Wer wirklich rund um die Uhr giessen will, traegt 00:00 bis 23:59 ein;
    // das sagt dasselbe und meint es auch.
    if (isset($bw_cfg['fenster_von'], $bw_cfg['fenster_bis'])
        && $bw_cfg['fenster_von'] === $bw_cfg['fenster_bis']) {
        $bw_fehler[] = bw_t('EINST.FEHLER_FENSTER_GLEICH');
    }
    /* mqtt_ein und mqtt_topic werden hier NICHT mehr angefasst: sie
     * wohnen im Reiter MQTT und haben dort ein eigenes Formular. Die
     * Konfiguration kommt aus bw_config(), die Werte ueberleben also
     * unveraendert. */
    $bw_cfg['kuestennah'] = isset($_POST['kuestennah']) ? 1 : 0;

    /* ---- neu in 0.9.7 ---- */

    // Rechenzeit: dieselbe Pruefung wie beim Giessfenster.
    $bw_rz = $bw_sauber('rechenzeit');
    if (!preg_match('/^([01][0-9]|2[0-3]):[0-5][0-9]$/', $bw_rz)) {
        $bw_fehler[] = sprintf(bw_t('EINST.FEHLER_ZEIT'), bw_t('EINST.L_RECHENZEIT'));
    } else {
        $bw_cfg['rechenzeit'] = $bw_rz;
    }

    foreach (array('zonendauer_max_s' => array(60, 7200),
                   'hoechstalter' => array(300, 86400),
                   'melden_limit_tage' => array(1, 30),
                   'melden_station_tage' => array(1, 30)) as $bw_f => $bw_g) {
        $bw_w = $bw_sauber($bw_f);
        if (!preg_match('/^[0-9]+$/', $bw_w)) {
            $bw_fehler[] = sprintf(bw_t('EINST.FEHLER_ZAHL'), bw_t('EINST.L_' . strtoupper($bw_f)));
        } elseif ((int) $bw_w < $bw_g[0] || (int) $bw_w > $bw_g[1]) {
            $bw_fehler[] = sprintf(bw_t('EINST.FEHLER_BEREICH'),
                                   bw_t('EINST.L_' . strtoupper($bw_f)), $bw_g[0], $bw_g[1]);
        } else {
            $bw_cfg[$bw_f] = (int) $bw_w;
        }
    }

    // Die drei Sperrgrenzen. Sie duerfen negativ sein - Frost bei -3 Grad
    // ist der Regelfall, nicht die Ausnahme.
    foreach (array('frost_c' => array(-20, 15),
                   'wind_kmh_max' => array(5, 150),
                   'regen_mmh_max' => array(0.1, 50)) as $bw_f => $bw_g) {
        $bw_w = $bw_kommazahl($bw_sauber($bw_f));
        if (!preg_match('/^-?[0-9]+(\.[0-9]+)?$/', $bw_w)) {
            $bw_fehler[] = sprintf(bw_t('EINST.FEHLER_ZAHL'), bw_t('EINST.L_' . strtoupper($bw_f)));
        } elseif ((float) $bw_w < $bw_g[0] || (float) $bw_w > $bw_g[1]) {
            $bw_fehler[] = sprintf(bw_t('EINST.FEHLER_BEREICH'),
                                   bw_t('EINST.L_' . strtoupper($bw_f)), $bw_g[0], $bw_g[1]);
        } else {
            $bw_cfg[$bw_f] = (float) $bw_w;
        }
    }

    // Die Haken. Sie stehen alle im SELBEN Formular wie der Speichern-Knopf -
    // sonst setzte isset() sie beim Absenden eines anderen Formulars auf 0,
    // und der Benutzer verloere Werte, die er nie gesehen hat.
    foreach (array('luecken_fuellen', 'plan_festhalten', 'frost_ein',
                   'wind_ein', 'regen_ein', 'melden_ein') as $bw_f) {
        $bw_cfg[$bw_f] = isset($_POST[$bw_f]) ? 1 : 0;
    }

    if (!$bw_fehler) {
        if (bw_config_speichern($bw_cfg)) { $bw_meldungen[] = bw_t('EINST.GESPEICHERT'); }
        else { $bw_fehler[] = sprintf(bw_t('EINST.FEHLER_SPEICHERN'), bw_e($bw_p['config'])); }
    }
    $bw_tab = 'tab-settings';
}

/* ---------------- MQTT (eigener Reiter, eigenes Formular) ----------------
 *
 * Eigenes Formular UND eigener Handler gehoeren zusammen. Loesten beide
 * Formulare denselben Handler aus, setzte dieser die Haken des jeweils
 * nicht abgeschickten Formulars per isset() auf 0 - der Benutzer verloere
 * Werte, die er nie gesehen hat. */
if ($bw_post && isset($_POST['save_mqtt'])) {
    $bw_mcfg = bw_config();
    $bw_mcfg['mqtt_ein'] = isset($_POST['mqtt_ein']) ? 1 : 0;
    $bw_mtopic = trim(preg_replace('/[\x00-\x1F\x7F"\']/', '',
        (string) (isset($_POST['mqtt_topic']) ? $_POST['mqtt_topic'] : '')));
    if ($bw_mtopic === '' || !preg_match('#^[A-Za-z0-9_/\-]{1,64}$#', $bw_mtopic)) {
        $bw_fehler[] = bw_t('EINST.FEHLER_TOPIC');
    } else {
        $bw_mcfg['mqtt_topic'] = trim($bw_mtopic, '/');
    }
    if (!$bw_fehler) {
        if (bw_config_speichern($bw_mcfg)) {
            $bw_meldungen[] = bw_t('EINST.GESPEICHERT');
        } else {
            $bw_fehler[] = sprintf(bw_t('EINST.FEHLER_SPEICHERN'),
                                   bw_e($bw_p['config']));
        }
    }
    $bw_tab = 'tab-mqtt';
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
        /* Eine Vorlage ERGAENZT, sie loescht nicht.
         *
         * Bis 0.9.10 stand hier '$bw_q['felder'] = <Vorlage>' - das hat beim
         * Wechsel der Vorlage JEDE bestehende Zuordnung weggeworfen, auch die
         * eines anderen Weges. Und die Adresse wurde durch den Platzhalter
         * der Vorlage ersetzt: aus einer funktionierenden 192.0.2.16
         * wurde 'http://GATEWAY-ADRESSE/get_livedata_info', und der naechste
         * Abruf endete mit 'Name or service not known'.
         *
         * Am Geraet gemeldet am 18.08.2026. Es ist derselbe Satz wie in
         * REGELN_2 unter 'Speichern-Handler: uebernehmen, was das Formular
         * nicht mitschickt' - hier nur mit einer Vorlage als Taeter.
         *
         * Ab jetzt: nur Groessen fuellen, die noch keinen Weg haben. Was
         * dasteht, bleibt stehen, und die Meldung sagt beide Zahlen.
         */
        $bw_q = bw_quellen();
        $bw_q['vorlage'] = $bw_v;
        $bw_vorl_f = isset($bw_alle['vorlagen'][$bw_v]['felder'])
            ? (array) $bw_alle['vorlagen'][$bw_v]['felder'] : array();
        $bw_hat = isset($bw_q['felder']) && is_array($bw_q['felder'])
            ? $bw_q['felder'] : array();
        $bw_neu_n = 0; $bw_behalten = 0;
        foreach ($bw_vorl_f as $bw_g => $bw_f) {
            if (!empty($bw_hat[$bw_g]['weg'])) { $bw_behalten++; continue; }
            $bw_hat[$bw_g] = $bw_f;
            $bw_neu_n++;
        }
        $bw_q['felder'] = $bw_hat;

        /* Die Adresse: ein Platzhalter wird NIE gespeichert, und eine
         * vorhandene Adresse wird nie ueberschrieben. Der Platzhalter steht
         * ohnehin schon im Eingabefeld. */
        $bw_url_neu = (string) (isset($bw_alle['vorlagen'][$bw_v]['http_url'])
            ? $bw_alle['vorlagen'][$bw_v]['http_url'] : '');
        $bw_url_alt = trim((string) (isset($bw_q['http_url']) ? $bw_q['http_url'] : ''));
        $bw_ist_platzhalter = ($bw_url_neu !== ''
            && preg_match('/GATEWAY-ADRESSE|GERAET|BEISPIEL/i', $bw_url_neu));
        if ($bw_url_neu !== '' && !$bw_ist_platzhalter && $bw_url_alt === '') {
            $bw_q['http_url'] = $bw_url_neu;
        }

        if (bw_quellen_speichern($bw_q)) {
            $bw_meldungen[] = sprintf(bw_t('QUELL.VORLAGE_ERGAENZT'),
                                      $bw_neu_n, $bw_behalten);
            if ($bw_url_alt !== '') {
                $bw_meldungen[] = sprintf(bw_t('QUELL.VORLAGE_ADRESSE_BEHALTEN'),
                                          bw_e($bw_url_alt));
            }
        } else {
            $bw_fehler[] = sprintf(bw_t('EINST.FEHLER_SPEICHERN'), bw_e($bw_p['quellen']));
        }
    }
    $bw_tab = 'tab-sources';
}

/* ---------------- Antwort abholen und zuordnen ----------------
 *
 * Die Antwort auf "ich weiss nicht, was in die Felder gehoert". Geholt wird
 * die eingetragene Adresse, aufgelistet wird JEDES Blatt der Antwort mit
 * seinem Pfad, und vorgeschlagen wird nur, was die gemessene
 * Kennungstabelle hergibt. Uebernommen wird nichts ohne den zweiten Klick.
 */
$bw_erk = null;
$bw_erk_fehler = '';
if ($bw_post && (isset($_POST['quellen_erkennen']) || isset($_POST['quellen_uebernehmen']))) {
    $bw_q = bw_quellen();
    $bw_url = trim((string) (isset($bw_q['http_url']) ? $bw_q['http_url'] : ''));
    if ($bw_url === '') {
        $bw_erk_fehler = bw_t('QUELL.ERK_KEINE_ADRESSE');
    } else {
        // Eigener Fehler-Aufnehmer statt @: ein eingehaengter Behandler wird
        // vom @-Zeichen nicht aufgehalten (gemessen mit rendern.py).
        $bw_ctx = stream_context_create(array('http' => array(
            'method' => 'GET', 'timeout' => 10, 'ignore_errors' => true,
            'follow_location' => 0, 'max_redirects' => 1)));
        set_error_handler(function () { return true; });
        $bw_roh_neu = file_get_contents($bw_url, false, $bw_ctx);
        restore_error_handler();
        if ($bw_roh_neu === false) {
            $bw_erk_fehler = sprintf(bw_t('QUELL.ERK_NICHT_ERREICHBAR'), bw_e($bw_url));
        } else {
            $bw_dek = json_decode($bw_roh_neu, true);
            if (!is_array($bw_dek)) {
                $bw_erk_fehler = sprintf(bw_t('QUELL.ERK_KEIN_JSON'),
                    bw_e(substr(trim($bw_roh_neu), 0, 200)));
            } else {
                $bw_erk = bw_antwort_erkennen($bw_dek);
            }
        }
    }
    if ($bw_erk_fehler !== '') { $bw_fehler[] = $bw_erk_fehler; }
    if ($bw_erk && isset($_POST['quellen_uebernehmen'])) {
        // Uebernommen wird NUR, was die Erkennung gerade gefunden hat, und
        // nur in die betroffenen Groessen. Alles andere bleibt stehen.
        $bw_qf = isset($bw_q['felder']) && is_array($bw_q['felder']) ? $bw_q['felder'] : array();
        $bw_n = 0;
        foreach ($bw_erk['felder'] as $bw_g => $bw_f) {
            $bw_qf[$bw_g] = array('weg' => 'http', 'pfad' => $bw_f['pfad']);
            if ($bw_f['einheit'] !== '') { $bw_qf[$bw_g]['einheit_quelle'] = $bw_f['einheit']; }
            $bw_n++;
        }
        $bw_q['felder'] = $bw_qf;
        if (bw_quellen_speichern($bw_q)) {
            $bw_meldungen[] = sprintf(bw_t('QUELL.ERK_UEBERNOMMEN'), $bw_n);
        } else {
            $bw_fehler[] = sprintf(bw_t('EINST.FEHLER_SPEICHERN'), bw_e($bw_p['quellen']));
        }
    }
    $bw_tab = 'tab-sources';
}

/* ---------------- Woher kommen die Werte? ---------------- */
if ($bw_post && isset($_POST['weg_speichern'])) {
    $bw_q = bw_quellen();
    $bw_u = trim((string) (isset($_POST['http_url']) ? $_POST['http_url'] : ''));
    if ($bw_u !== '' && !preg_match('#^https?://\S{3,200}$#', $bw_u)) {
        $bw_fehler[] = bw_t('QUELL.FEHLER_URL');
    } else {
        $bw_q['http_url'] = $bw_u;
    }
    $bw_th = trim(preg_replace('/[\x00-\x1F\x7F"\']/', '',
        (string) (isset($_POST['mqtt_thema']) ? $_POST['mqtt_thema'] : '')));
    if ($bw_th !== '' && !preg_match('#^[A-Za-z0-9_/\#+.\-]{1,128}$#', $bw_th)) {
        $bw_fehler[] = bw_t('QUELL.FEHLER_HORCHTHEMA');
    } else {
        $bw_q['mqtt_thema'] = $bw_th;
    }
    if (!$bw_fehler) {
        if (bw_quellen_speichern($bw_q)) {
            $bw_meldungen[] = bw_t('QUELL.WEG_GESPEICHERT');
        } else {
            $bw_fehler[] = sprintf(bw_t('EINST.FEHLER_SPEICHERN'),
                                   bw_e($bw_p['quellen']));
        }
    }
    $bw_tab = 'tab-sources';
}

/* ---------------- Aus dem Broker vorschlagen ---------------- */
$bw_bro = null;
if ($bw_post && (isset($_POST['broker_erkennen']) || isset($_POST['broker_uebernehmen']))) {
    $bw_bro = bw_broker_erkennen();
    if ($bw_bro['themen'] === 0) {
        $bw_fehler[] = bw_t('QUELL.BRO_NICHTS');
    } elseif (isset($_POST['broker_uebernehmen'])) {
        // Wie bei der Vorlage: ERGAENZEN, nicht loeschen.
        $bw_q = bw_quellen();
        $bw_hat = isset($bw_q['felder']) && is_array($bw_q['felder'])
            ? $bw_q['felder'] : array();
        $bw_n = 0;
        foreach ($bw_bro['felder'] as $bw_g => $bw_f) {
            $bw_hat[$bw_g] = array('weg' => 'mqtt', 'thema' => $bw_f['thema'],
                                   'pfad' => $bw_f['pfad']);
            if ($bw_f['einheit'] !== '') {
                $bw_hat[$bw_g]['einheit_quelle'] = $bw_f['einheit'];
            }
            $bw_n++;
        }
        $bw_q['felder'] = $bw_hat;
        if (bw_quellen_speichern($bw_q)) {
            $bw_meldungen[] = sprintf(bw_t('QUELL.BRO_UEBERNOMMEN'), $bw_n);
        } else {
            $bw_fehler[] = sprintf(bw_t('EINST.FEHLER_SPEICHERN'), bw_e($bw_p['quellen']));
        }
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
    foreach (array_keys(bw_tabelle($bw_alle['groessen'])) as $bw_g) {
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
        /* Eine Zuordnung zu einer Groesse, die templates/quellen.json
         * nicht (mehr) fuehrt, wird UEBERNOMMEN statt weggeworfen.
         * Die Tabelle zeigt nur die bekannten Groessen; bis 0.9.18 war
         * jedes Speichern im Reiter Quellen damit ein stiller Loescher
         * fuer alles andere - dieselbe Klasse, gegen die der
         * Vorlagen-Handler weiter oben ausdruecklich abgesichert ist. */
        $bw_alt_f = isset($bw_q['felder']) && is_array($bw_q['felder'])
                  ? $bw_q['felder'] : array();
        $bw_behalten_n = 0;
        foreach ($bw_alt_f as $bw_ag => $bw_af) {
            if (!array_key_exists($bw_ag, bw_tabelle($bw_alle['groessen']))
                && !isset($bw_felder[$bw_ag])) {
                $bw_felder[$bw_ag] = $bw_af;
                $bw_behalten_n++;
            }
        }
        if ($bw_behalten_n > 0) {
            $bw_meldungen[] = sprintf(bw_t('QUELL.FREMD_BEHALTEN'),
                                      $bw_behalten_n);
        }
        $bw_q['felder'] = $bw_felder;
        if (bw_quellen_speichern($bw_q)) { $bw_meldungen[] = bw_t('QUELL.GESPEICHERT'); }
        else { $bw_fehler[] = sprintf(bw_t('EINST.FEHLER_SPEICHERN'), bw_e($bw_p['quellen'])); }
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
        // Mikroklima-Faktor. Leer heisst 1,0 - und das ist der Regelfall.
        $bw_mk = $bw_hol('z_mikroklima');
        if ($bw_mk !== '' && (!is_numeric($bw_mk) || (float) $bw_mk < 0.3 || (float) $bw_mk > 1.5)) {
            $bw_fehler[] = sprintf(bw_t('ZONE.FEHLER_MIKRO'), bw_e($bw_name));
            continue;
        }
        $bw_alt = bw_zone($bw_s);

        /* ---- neu in 0.9.7 ----
         *
         * Diese Felder werden ZURECHTGERUECKT und nicht abgewiesen: eine
         * unlesbare Pflanzenhoehe darf nicht dazu fuehren, dass die ganze
         * Zonentabelle ungespeichert bleibt. Was nicht als Zahl lesbar ist,
         * gilt als 'nichts eingetragen' - und das heisst bei jedem dieser
         * Felder 'verhaelt sich wie bis 0.9.6'.
         */
        $bw_zahl_oder_leer = function ($roh, $min, $max) {
            if ($roh === '' || !is_numeric($roh)) { return null; }
            $w = (float) $roh;
            if ($w < $min || $w > $max) { return null; }
            return $w;
        };
        $bw_dauer = $bw_zahl_oder_leer($bw_hol('z_dauer'), 30, 3600);
        $bw_hpf   = $bw_zahl_oder_leer($bw_hol('z_hoehe_pflanze'), 0.05, 10);
        $bw_abf   = $bw_zahl_oder_leer($bw_hol('z_abfluss'), 0, 1);
        $bw_sgw   = $bw_zahl_oder_leer($bw_hol('z_sensor_gewicht'), 0, 1);
        // Eigene Bodenwerte aus einer Bodenprobe. pflanzen.json sagt seit
        // jeher zu: "wer es genau will, laesst eine Bodenprobe untersuchen
        // und traegt die Werte von Hand ein - das Feld dafuer gibt es". Es
        // gab es nicht. Jetzt gibt es zwei, und sie schlagen die Bodenart.
        $bw_tfc = $bw_zahl_oder_leer($bw_hol('z_theta_fc'), 0.05, 0.60);
        $bw_twp = $bw_zahl_oder_leer($bw_hol('z_theta_wp'), 0.01, 0.45);
        if ($bw_tfc !== null && $bw_twp !== null && $bw_twp >= $bw_tfc) {
            $bw_fehler[] = sprintf(bw_t('ZONE.FEHLER_THETA'), bw_e($bw_name));
            $bw_tfc = null; $bw_twp = null;
        }
        $bw_gart  = (string) (isset($_POST['z_giess_art'][$bw_i])
            ? $_POST['z_giess_art'][$bw_i] : 'minuten');
        if (!in_array($bw_gart, array('minuten', 'durchlaeufe', 'mm'), true)) {
            $bw_gart = 'minuten';
        }
        $bw_gth = trim(preg_replace('/[\x00-\x1F\x7F"\']/', '',
            (string) (isset($_POST['z_giess_thema'][$bw_i]) ? $_POST['z_giess_thema'][$bw_i] : '')));
        // Ein Rueckmeldethema ohne Becherprobe kann nicht wirken - die Hoehe
        // entsteht aus Laufzeit MAL gemessener Rate. Gemeldet, nicht
        // blockiert: der Anwender traegt die Becherprobe gleich danach ein.
        if ($bw_gth !== '' && $bw_gart !== 'mm' && empty($bw_alt['rate_gemessen'])) {
            // HINWEIS, nicht Beanstandung.
            //
            // Bis 0.9.8 landete dieser Satz in $bw_fehler - und weil der
            // Handler nur speichert, wenn diese Liste leer ist, verhinderte
            // ein blosser Hinweis das Speichern der GANZEN Zonentabelle. Der
            // Anwender haette das Rueckmeldethema nie eintragen koennen, ohne
            // vorher die Becherprobe zu machen, obwohl beides in beliebiger
            // Reihenfolge geht. REGELN_2: melden, nicht blockieren.
            $bw_meldungen[] = sprintf(bw_t('ZONE.HINWEIS_GIESS_OHNE_RATE'), bw_e($bw_name));
        }
        $bw_regner = preg_replace('/[^a-z_]/', '', strtolower($bw_hol('z_regner')));
        // Regnertyp: nur ein STARTWERT, und nur wenn noch keine Rate dasteht.
        // Er ueberschreibt niemals eine Becherprobe - der Katalogwert weicht
        // je nach Duesen und Druck regelmaessig um die Haelfte ab.
        if ($bw_rate === '' && $bw_regner !== ''
            && isset($bw_pf['regner'][$bw_regner]['mmh'])) {
            $bw_rate = (string) (float) $bw_pf['regner'][$bw_regner]['mmh'];
        }

        $bw_neu[] = array(
            'schluessel'   => $bw_s,
            'name'         => $bw_name,
            'flaeche'      => $bw_fl !== '' ? (float) $bw_fl : 0.0,
            'bepflanzung'  => $bw_bep,
            'boden'        => $bw_bod,
            'kc'           => (float) $bw_bepd['kc'],
            'zr'           => (float) $bw_bepd['zr'],
            'p'            => (float) $bw_bepd['p'],
            'theta_fc'     => $bw_tfc !== null ? $bw_tfc : (float) $bw_bodd['theta_fc'],
            'theta_wp'     => $bw_twp !== null ? $bw_twp : (float) $bw_bodd['theta_wp'],
            'theta_fc_eigen' => $bw_tfc !== null ? $bw_tfc : 0.0,
            'theta_wp_eigen' => $bw_twp !== null ? $bw_twp : 0.0,
            'rate_mmh'     => $bw_rate !== '' ? (float) $bw_rate : 0.0,
            'mikroklima'   => $bw_mk !== '' ? (float) $bw_mk : 1.0,
            /* Wer die Rate leert, nimmt die Becherprobe zurueck. Das
             * Merkmal aus $bw_alt zu uebernehmen ist richtig (es steht
             * in keinem Formularfeld) - aber nicht fuer eine Rate von
             * null: die Zone zeigte sonst 'aus eigenen Messwerten' mit
             * dem alten Datum bei einer Rate, die es nicht mehr gibt. */
            'rate_gemessen' => $bw_rate === '' ? 0
                : (int) (isset($bw_alt['rate_gemessen']) ? $bw_alt['rate_gemessen'] : 0),
            'im_zyklus'    => !empty($_POST['z_zyklus'][$bw_i]) ? 1 : 0,
            'feuchte_thema' => trim(preg_replace('/[\x00-\x1F\x7F"\']/', '',
                (string) (isset($_POST['z_feuchte'][$bw_i]) ? $_POST['z_feuchte'][$bw_i] : ''))),
            'sensor_gewicht' => $bw_sgw !== null ? $bw_sgw
                : (float) (isset($bw_alt['sensor_gewicht']) ? $bw_alt['sensor_gewicht'] : 0.5),
            'dr'           => (float) (isset($bw_alt['dr']) ? $bw_alt['dr'] : 0.0),
            // ---- neu in 0.9.7 ----
            'regner'        => $bw_regner,
            'dauer_s'       => $bw_dauer !== null ? (int) $bw_dauer : 0,
            'hoehe_pflanze' => $bw_hpf !== null ? $bw_hpf : 0.0,
            'abfluss'       => $bw_abf !== null ? $bw_abf : 0.0,
            'giess_thema'   => $bw_gth,
            'giess_art'     => $bw_gart,
            // Das Datum der Becherprobe stand bis 0.9.6 zwar in der Datei,
            // fehlte hier aber - und dieser Handler baut die Zone von Grund
            // auf neu. Jedes Speichern der Zonentabelle hat es also still
            // geloescht. Genau die Fehlerklasse, die in REGELN_2 unter
            // "Speichern-Handler: uebernehmen, was das Formular nicht
            // mitschickt" steht.
            'rate_gemessen_am' => $bw_rate === '' ? ''
                : (string) (isset($bw_alt['rate_gemessen_am'])
                    ? $bw_alt['rate_gemessen_am'] : ''),
        );
    }
    if (!$bw_fehler) {
        if (bw_zonen_speichern($bw_neu)) { $bw_meldungen[] = bw_t('ZONE.GESPEICHERT'); }
        else { $bw_fehler[] = sprintf(bw_t('EINST.FEHLER_SPEICHERN'), bw_e($bw_p['zonen'])); }
    }
    $bw_tab = 'tab-zones';
}

/* ---------------- Becherprobe ----------------
 *
 * Ausgeloest wird am KNOPF, nicht am Auswahlfeld: 'becher' geht bei
 * jedem Absenden dieses Formulars mit, ein zweiter Knopf darin haette
 * die Becherprobe also mitgefeuert. Alle uebrigen Handler haengen
 * ebenfalls am Knopfnamen. */
if ($bw_post && isset($_POST['becher_senden'])) {
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
            $bw_fehler[] = sprintf(bw_t('EINST.FEHLER_SPEICHERN'), bw_e($bw_p['zonen']));
        }
    }
    $bw_tab = 'tab-zones';
}

/* ---------------- Token, Test, Log ---------------- */
if ($bw_post && isset($_POST['token_neu'])) {
    $bw_cfg = bw_config();
    $bw_cfg['aktionstoken'] = bw_token_erzeugen();
    if (bw_config_speichern($bw_cfg)) { $bw_meldungen[] = bw_t('LOX.TOKEN_NEU'); }
    else { $bw_fehler[] = sprintf(bw_t('EINST.FEHLER_SPEICHERN'), bw_e($bw_p['config'])); }
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

/* ---------------- Einstellungen sichern ----------------
 *
 * Ausgegeben wird die VOLLE Konfiguration - samt Aktionstoken. Ohne ihn
 * stuenden nach dem Zurueckspielen alle Felder richtig, und das Plugin
 * kaeme trotzdem nicht an die Anlage; die Datei waere wertlos. Damit
 * traegt sie ein Geheimnis, und der Hinweis am Knopf sagt das. */
if ($bw_post && isset($_POST['bw_sichern'])) {
    $bw_js = json_encode(bw_config(),
        JSON_PRETTY_PRINT | JSON_UNESCAPED_UNICODE | JSON_UNESCAPED_SLASHES);
    if ($bw_js !== false) {
        header('Content-Type: application/json; charset=utf-8');
        header('Content-Disposition: attachment; filename="bewaesserung_einstellungen_'
               . date('Ymd_His') . '.json"');
        echo $bw_js;
        exit;
    }
    $bw_fehler[] = bw_t('EINST.SICH_SCHREIBFEHLER');
}

/* ---------------- Einstellungen zurueckspielen ----------------
 *
 * is_uploaded_file() ZUERST: ohne diese Pruefung liesse sich jede Datei des
 * Servers unterschieben. Dann die Groessengrenze - eine Sicherung dieses
 * Plugins ist wenige Kilobyte gross; alles darueber wird gar nicht gelesen.
 *
 * Dieser Zweig stand bis 0.9.18 als einziger schreibender Handler HINTER dem
 * Ladeblock. Er schrieb die Datei, aber $bw_cfg und $bw_token im Speicher
 * blieben die alten: die Seite meldete 'uebernommen' und zeigte daneben an
 * sechzehn Stellen die Werte von vorher, samt altem Token in der
 * Loxone-Adresse. Deshalb steht er jetzt bei den uebrigen Handlern. */
if ($bw_post && isset($_POST['bw_zurueck'])) {
    if (!isset($_FILES['bw_sicherung']) || !is_array($_FILES['bw_sicherung'])
        || !isset($_FILES['bw_sicherung']['tmp_name'])
        || !@is_uploaded_file($_FILES['bw_sicherung']['tmp_name'])) {
        $bw_fehler[] = bw_t('EINST.SICH_KEINE_DATEI');
    } elseif ((int) $_FILES['bw_sicherung']['size'] > 262144) {
        $bw_fehler[] = bw_t('EINST.SICH_ZU_GROSS');
    } else {
        list($bw_neu, $bw_mangel, $bw_n) = bw_sicherung_lesen(
            (string) @file_get_contents($_FILES['bw_sicherung']['tmp_name']));
        if ($bw_neu === null) {
            /* ALLE Beanstandungen, nicht nur die erste - und geaendert wird
             * nichts. */
            $bw_fehler[] = bw_t('EINST.SICH_ABGELEHNT') . ' '
                            . implode(' ', $bw_mangel);
        } else {
            /* Traegt die Datei KEIN Aktionstoken, wird das laufende behalten.
             * bw_sicherung_lesen() baut auf den Vorgaben auf, und dort ist es
             * leer: eine von Hand gekuerzte Sicherung hat es bis 0.9.18 beim
             * Zurueckspielen stillschweigend geloescht. Jede im Miniserver
             * eingetragene Adresse antwortete danach mit 403, und weil ein
             * virtueller Eingang die Antwort nicht auswertet, blieb der
             * Ausfall stumm. */
            $bw_altcfg = bw_config();
            if (trim((string) $bw_neu['aktionstoken']) === ''
                && trim((string) $bw_altcfg['aktionstoken']) !== '') {
                $bw_neu['aktionstoken'] = $bw_altcfg['aktionstoken'];
                $bw_meldungen[] = bw_t('EINST.SICH_TOKEN_BEHALTEN');
            }
            if (bw_config_speichern($bw_neu)) {
                $bw_meldungen[] = sprintf(bw_t('EINST.SICH_UEBERNOMMEN'), $bw_n);
            } else {
                $bw_fehler[] = bw_t('EINST.SICH_SCHREIBFEHLER');
            }
        }
    }
    $bw_tab = 'tab-settings';
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
    LBWeb::lbheader(bw_t('ALLG.TITEL'), 'https://www.fao.org/3/x0490e/x0490e00.htm', 'help.html');
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
/* Ein Auswahlfeld muss man als Auswahlfeld erkennen.
 *
 * Am Gerät gemeldet: die Vorlagenliste im Reiter Quellen sah aus wie ein
 * Textfeld - der eingebaute Pfeil sitzt am rechten Rand eines Feldes, das
 * ueber die ganze Breite geht, und faellt dort nicht auf. Wer nicht
 * hineinklickt, erfaehrt nie, dass es acht Vorlagen gibt.
 *
 * Der Pfeil wird deshalb selbst gezeichnet und sitzt sichtbar am Feldende.
 * Die Raute im SVG ist als %23 kodiert - eine rohe Raute beendet in einer
 * CSS-Adresse den Wert. */
.sm-wrap select {
    appearance: none; -webkit-appearance: none; -moz-appearance: none;
    background-image: url("data:image/svg+xml;charset=UTF-8,%3Csvg xmlns='http://www.w3.org/2000/svg' width='14' height='9' viewBox='0 0 14 9'%3E%3Cpath d='M1 1l6 6 6-6' fill='none' stroke='%234f7d17' stroke-width='2'/%3E%3C/svg%3E");
    background-repeat: no-repeat; background-position: right 10px center;
    padding-right: 32px; cursor: pointer; }
.sm-tabelle select { padding-right: 28px; background-position: right 7px center; }
.sm-hinweis { border: 1px solid #a5d6a7; background: #e8f5e9; border-radius: 6px; padding: 10px 12px; margin: 12px 0; font-size: 0.9em; }
.sm-warnung { border: 1px solid #f0c9a0; background: #fdf4ec; border-radius: 6px; padding: 10px 12px; margin: 12px 0; font-size: 0.9em; }
.sm-fehler { border: 1px solid #ef9a9a; background: #ffebee; border-radius: 6px; padding: 10px 12px; margin: 12px 0; font-size: 0.9em; }
.sm-an  { color: #1a7f1a; font-weight: 700; }
.sm-aus { color: #b00000; font-weight: 700; }
.sm-mono { font-family: Consolas, 'Courier New', monospace; background: #f2f2f2; padding: 1px 5px; border-radius: 4px; font-size: 0.92em; word-break: break-all; }
.sm-log { background: #1e1e1e; color: #d4d4d4; font-family: Consolas, 'Courier New', monospace;
    font-size: 0.82em; padding: 12px; border-radius: 8px; max-height: 480px; overflow: auto; white-space: pre-wrap; }
.sm-tabelle { border-collapse: collapse; width: 100%; font-size: 0.88em; margin: 10px 0; }
/* Eine Tabelle, die breiter ist als das Fenster, braucht eine eigene
 * Bildlaufleiste. Am Geraet gemeldet: die Spalte "im Zyklus" stand rechts
 * ausserhalb, und es gab keinen Weg, dorthin zu scrollen - der Haken, ohne
 * den keine Zone mitlaeuft, war schlicht unerreichbar. */
.sm-breit { overflow-x: auto; -webkit-overflow-scrolling: touch; margin: 10px 0; }
.sm-breit .sm-tabelle { margin: 0; min-width: 760px; }
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
  <a href="index.php?form=settings" class="sm-tab<?= $bw_tab === 'tab-settings' ? ' sm-active' : '' ?>" data-ziel="tab-settings"><?= bw_e(bw_t('REITER.EINSTELLUNGEN')) ?></a>
  <a href="index.php?form=sources" class="sm-tab<?= $bw_tab === 'tab-sources' ? ' sm-active' : '' ?>" data-ziel="tab-sources"><?= bw_e(bw_t('REITER.QUELLEN')) ?></a>
  <a href="index.php?form=zones" class="sm-tab<?= $bw_tab === 'tab-zones' ? ' sm-active' : '' ?>" data-ziel="tab-zones"><?= bw_e(bw_t('REITER.ZONEN')) ?></a>
  <a href="index.php?form=history" class="sm-tab<?= $bw_tab === 'tab-history' ? ' sm-active' : '' ?>" data-ziel="tab-history"><?= bw_e(bw_t('REITER.VERLAUF')) ?></a>
  <a href="index.php?form=mqtt" class="sm-tab<?= $bw_tab === 'tab-mqtt' ? ' sm-active' : '' ?>" data-ziel="tab-mqtt"><?= bw_e(bw_t('REITER.MQTT')) ?></a>
  <a href="index.php?form=loxone" class="sm-tab<?= $bw_tab === 'tab-loxone' ? ' sm-active' : '' ?>" data-ziel="tab-loxone"><?= bw_e(bw_t('REITER.LOXONE')) ?></a>
  <a href="index.php?form=test" class="sm-tab<?= $bw_tab === 'tab-test' ? ' sm-active' : '' ?>" data-ziel="tab-test"><?= bw_e(bw_t('REITER.TEST')) ?></a>
  <a href="index.php?form=log" class="sm-tab<?= $bw_tab === 'tab-log' ? ' sm-active' : '' ?>" data-ziel="tab-log"><?= bw_e(bw_t('REITER.LOG')) ?></a>
</div>

<!-- ============ Einstellungen ============ -->
<div class="sm-seite<?= $bw_tab === 'tab-settings' ? ' sm-active' : '' ?>" id="tab-settings">
<div class="sm-hinweis"><?= bw_t('EINST.WAS_IST_DAS') ?></div>

<h2><?= bw_e(bw_t('EINST.H_DIENST')) ?></h2>
<div class="sm-legende">
  <span class="sm-b-lesen" style="background:#4f7d17"></span><?= bw_t('LEGENDE.LESEN') ?><br>
  <span class="sm-b-aktion" style="background:#d97706"></span><?= bw_t('LEGENDE.AKTION') ?>
</div>
<form action="index.php" method="post">
  <?php echo bw_fmt(); ?>
  <input data-role="none" type="hidden" name="activetab" value="tab-settings">
  <button data-role="none" class="sm-b sm-b-aktion" name="dienst" value="start"><?= bw_e(bw_t('EINST.K_START')) ?></button>
  <button data-role="none" class="sm-b sm-b-aktion" name="dienst" value="restart"><?= bw_e(bw_t('EINST.K_NEUSTART')) ?></button>
  <button data-role="none" class="sm-b sm-b-aktion" name="dienst" value="stop"><?= bw_e(bw_t('EINST.K_STOP')) ?></button>
</form>

<form action="index.php" method="post">
  <?php echo bw_fmt(); ?>
<input data-role="none" type="hidden" name="activetab" value="tab-settings">
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

<div class="sm-feld">
  <label for="zonendauer_max_s"><?= bw_t('EINST.L_ZONENDAUER_MAX_S') ?></label>
  <input data-role="none" type="text" name="zonendauer_max_s" id="zonendauer_max_s" value="<?= bw_e($bw_cfg['zonendauer_max_s']) ?>">
  <p class="sm-hilfe"><?= bw_t('EINST.H_ZONENDAUER_MAX_S') ?></p>
</div>

<h2><?= bw_e(bw_t('EINST.H_NACHTPLAN')) ?></h2>
<p class="sm-hilfe"><?= bw_t('EINST.NACHTPLAN_ERKLAERUNG') ?></p>
<label><input data-role="none" type="checkbox" name="plan_festhalten" value="1"<?= !empty($bw_cfg['plan_festhalten']) ? ' checked' : '' ?>>
  <?= bw_e(bw_t('EINST.L_PLAN_FESTHALTEN')) ?></label>
<div class="sm-feld">
  <label for="rechenzeit"><?= bw_t('EINST.L_RECHENZEIT') ?></label>
  <input data-role="none" type="text" name="rechenzeit" id="rechenzeit" value="<?= bw_e($bw_cfg['rechenzeit']) ?>">
  <p class="sm-hilfe"><?= bw_t('EINST.H_RECHENZEIT') ?></p>
</div>

<h2><?= bw_e(bw_t('EINST.H_SPERREN')) ?></h2>
<div class="sm-warnung"><?= bw_t('EINST.SPERREN_ERKLAERUNG') ?></div>
<label><input data-role="none" type="checkbox" name="frost_ein" value="1"<?= !empty($bw_cfg['frost_ein']) ? ' checked' : '' ?>>
  <?= bw_e(bw_t('EINST.L_FROST_EIN')) ?></label>
<div class="sm-feld">
  <label for="frost_c"><?= bw_t('EINST.L_FROST_C') ?></label>
  <input data-role="none" type="text" name="frost_c" id="frost_c" value="<?= bw_e($bw_cfg['frost_c']) ?>">
  <p class="sm-hilfe"><?= bw_t('EINST.H_FROST_C') ?></p>
</div>
<label><input data-role="none" type="checkbox" name="wind_ein" value="1"<?= !empty($bw_cfg['wind_ein']) ? ' checked' : '' ?>>
  <?= bw_e(bw_t('EINST.L_WIND_EIN')) ?></label>
<div class="sm-feld">
  <label for="wind_kmh_max"><?= bw_t('EINST.L_WIND_KMH_MAX') ?></label>
  <input data-role="none" type="text" name="wind_kmh_max" id="wind_kmh_max" value="<?= bw_e($bw_cfg['wind_kmh_max']) ?>">
  <p class="sm-hilfe"><?= bw_t('EINST.H_WIND_KMH_MAX') ?></p>
</div>
<label><input data-role="none" type="checkbox" name="regen_ein" value="1"<?= !empty($bw_cfg['regen_ein']) ? ' checked' : '' ?>>
  <?= bw_e(bw_t('EINST.L_REGEN_EIN')) ?></label>
<div class="sm-feld">
  <label for="regen_mmh_max"><?= bw_t('EINST.L_REGEN_MMH_MAX') ?></label>
  <input data-role="none" type="text" name="regen_mmh_max" id="regen_mmh_max" value="<?= bw_e($bw_cfg['regen_mmh_max']) ?>">
  <p class="sm-hilfe"><?= bw_t('EINST.H_REGEN_MMH_MAX') ?></p>
</div>

<h2><?= bw_e(bw_t('EINST.H_WEITERES')) ?></h2>
<label><input data-role="none" type="checkbox" name="luecken_fuellen" value="1"<?= !empty($bw_cfg['luecken_fuellen']) ? ' checked' : '' ?>>
  <?= bw_e(bw_t('EINST.L_LUECKEN_FUELLEN')) ?></label>
<p class="sm-hilfe"><?= bw_t('EINST.H_LUECKEN_FUELLEN') ?></p>
<div class="sm-feld">
  <label for="hoechstalter"><?= bw_t('EINST.L_HOECHSTALTER') ?></label>
  <input data-role="none" type="text" name="hoechstalter" id="hoechstalter" value="<?= bw_e($bw_cfg['hoechstalter']) ?>">
  <p class="sm-hilfe"><?= bw_t('EINST.H_HOECHSTALTER') ?></p>
</div>
<label><input data-role="none" type="checkbox" name="melden_ein" value="1"<?= !empty($bw_cfg['melden_ein']) ? ' checked' : '' ?>>
  <?= bw_e(bw_t('EINST.L_MELDEN_EIN')) ?></label>
<p class="sm-hilfe"><?= bw_t('EINST.H_MELDEN_EIN') ?></p>
<div class="sm-feld">
  <label for="melden_limit_tage"><?= bw_t('EINST.L_MELDEN_LIMIT_TAGE') ?></label>
  <input data-role="none" type="text" name="melden_limit_tage" id="melden_limit_tage" value="<?= bw_e($bw_cfg['melden_limit_tage']) ?>">
</div>
<div class="sm-feld">
  <label for="melden_station_tage"><?= bw_t('EINST.L_MELDEN_STATION_TAGE') ?></label>
  <input data-role="none" type="text" name="melden_station_tage" id="melden_station_tage" value="<?= bw_e($bw_cfg['melden_station_tage']) ?>">
</div>

<?php /* MQTT stand hier bis zu dieser Fassung. Es wohnt jetzt
         vollstaendig im Reiter MQTT - eine Sache, eine Stelle. */ ?>
<button data-role="none" class="sm-b sm-b-aktion" name="speichern" value="1"><?= bw_e(bw_t('ALLG.SPEICHERN')) ?></button>
</form>

<h2><?= bw_e(bw_t('EINST.H_SICHERUNG')) ?></h2>
<div class="sm-hinweis"><?= bw_t('EINST.SICH_ERKLAERUNG') ?></div>
<div class="sm-warnung"><?= bw_t('EINST.SICH_WARNUNG') ?></div>
<!-- ZWEI GETRENNTE Formulare. Das Sichern schickt einen Download und ruft
     exit auf; das Zurueckspielen braucht enctype="multipart/form-data".
     Wer beides in ein Formular legt, bekommt entweder keinen Upload oder
     einen Download, der das Speichern verschluckt. -->
  <form action="index.php" method="post">
    <?php echo bw_fmt(); ?>
    <input data-role="none" type="hidden" name="activetab" value="tab-settings">
    <button data-role="none" class="sm-b sm-b-lesen" type="submit" name="bw_sichern" value="1"><?= bw_e(bw_t('EINST.K_SICHERN')) ?></button>
  </form>
  <form action="index.php" method="post" enctype="multipart/form-data">
    <?php echo bw_fmt(); ?>
    <input data-role="none" type="hidden" name="activetab" value="tab-settings">
    <input data-role="none" type="file" name="bw_sicherung" accept=".json">
    <button data-role="none" class="sm-b sm-b-aktion" type="submit" name="bw_zurueck" value="1"><?= bw_e(bw_t('EINST.K_ZURUECK')) ?></button>
  </form>
</div>

<!-- ============ Quellen ============ -->
<div class="sm-seite<?= $bw_tab === 'tab-sources' ? ' sm-active' : '' ?>" id="tab-sources">
<h2><?= bw_e(bw_t('QUELL.H_TITEL')) ?></h2>
<div class="sm-legende">
  <span class="sm-b-lesen" style="background:#4f7d17"></span><?= bw_t('LEGENDE.LESEN') ?><br>
  <span class="sm-b-aktion" style="background:#d97706"></span><?= bw_t('LEGENDE.AKTION') ?>
</div>
<div class="sm-hinweis"><?= bw_t('QUELL.ERKLAERUNG') ?></div>
<div class="sm-warnung"><?= bw_t('QUELL.WEG_ERKLAERUNG') ?></div>

<form action="index.php" method="post">
  <?php echo bw_fmt(); ?>
<input data-role="none" type="hidden" name="activetab" value="tab-sources">
<div class="sm-feld">
  <label for="vorlage"><?= bw_e(bw_t('QUELL.L_VORLAGE')) ?></label>
  <select data-role="none" name="vorlage" id="vorlage">
  <?php foreach (bw_tabelle($bw_vorl['vorlagen']) as $bw_k => $bw_v) { ?>
    <option value="<?= bw_e($bw_k) ?>"<?= (isset($bw_q['vorlage']) && $bw_q['vorlage'] === $bw_k) ? ' selected' : '' ?>><?= bw_e($bw_v['text']) ?></option>
  <?php } ?>
  </select>
  <p class="sm-hilfe"><?= bw_t('QUELL.H_VORLAGE') ?></p>
</div>
<button data-role="none" class="sm-b sm-b-aktion" name="vorlage_waehlen" value="1"><?= bw_e(bw_t('QUELL.K_VORLAGE')) ?></button>
</form>
<?php if (isset($bw_q['vorlage']) && isset($bw_vorl['vorlagen'][$bw_q['vorlage']]['hinweis'])) { ?>
<div class="sm-warnung"><?= bw_e($bw_vorl['vorlagen'][$bw_q['vorlage']]['hinweis']) ?></div>
<?php } ?>

<form action="index.php" method="post">
  <?php echo bw_fmt(); ?>
<input data-role="none" type="hidden" name="activetab" value="tab-sources">
<?php /* Die Adresse steht in Schritt 1. Zwei Eingabefelder fuer denselben
         Wert auf einer Seite sind eine Fehlerquelle: welches gilt? Das
         Formular hier schickt sie als verstecktes Feld mit, damit der
         Speichern-Handler sie nicht als leer liest und loescht. */ ?>
<input data-role="none" type="hidden" name="http_url"
       value="<?= bw_e(isset($bw_q['http_url']) ? $bw_q['http_url'] : '') ?>">
<h2><?= bw_e(bw_t('QUELL.S3_TITEL')) ?></h2>
<p class="sm-hilfe"><?= bw_t('QUELL.S3_TEXT') ?></p>
<div class="sm-breit">
<table class="sm-tabelle">
<tr><th><?= bw_e(bw_t('QUELL.T_GROESSE')) ?></th><th><?= bw_e(bw_t('QUELL.T_WEG')) ?></th>
    <th><?= bw_e(bw_t('QUELL.T_THEMA')) ?></th><th><?= bw_e(bw_t('QUELL.T_PFAD')) ?></th>
    <th><?= bw_e(bw_t('QUELL.T_EINHEIT')) ?></th><th><?= bw_e(bw_t('QUELL.T_HERKUNFT')) ?></th></tr>
<?php
$bw_h = isset($bw_a['herkunft']) && is_array($bw_a['herkunft']) ? $bw_a['herkunft'] : array();
foreach (bw_tabelle($bw_vorl['groessen']) as $bw_g => $bw_gd) {
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
</div>
<p class="sm-hilfe"><?= bw_t('QUELL.FUSSNOTE') ?></p>
<p class="sm-hilfe"><?= bw_t('QUELL.FUSSNOTE_THEMA') ?></p>
<p class="sm-hilfe"><?= bw_t('QUELL.FUSSNOTE_TMINMAX') ?></p>
<button data-role="none" class="sm-b sm-b-aktion" name="quellen_speichern" value="1"><?= bw_e(bw_t('ALLG.SPEICHERN')) ?></button>
</form>

<h2><?= bw_e(bw_t('QUELL.H_ERKENNEN')) ?></h2>
<div class="sm-step">
<h3><?= bw_e(bw_t('QUELL.S1_TITEL')) ?></h3>
<p class="sm-hilfe"><?= bw_t('QUELL.S1_TEXT') ?></p>
<form action="index.php" method="post">
  <?php echo bw_fmt(); ?>
<input data-role="none" type="hidden" name="activetab" value="tab-sources">
<div class="sm-feld">
  <label for="http_url2"><?= bw_e(bw_t('QUELL.S1_L_HTTP')) ?></label>
  <?php $bw_u2 = (string) (isset($bw_q['http_url']) ? $bw_q['http_url'] : '');
        if (preg_match('/GATEWAY-ADRESSE|GERAET|BEISPIEL/i', $bw_u2)) { $bw_u2 = ''; } ?>
  <input data-role="none" type="text" name="http_url" id="http_url2"
         value="<?= bw_e($bw_u2) ?>" placeholder="http://192.0.2.10/get_livedata_info">
</div>
<div class="sm-feld">
  <label for="mqtt_thema"><?= bw_e(bw_t('QUELL.S1_L_MQTT')) ?></label>
  <input data-role="none" type="text" name="mqtt_thema" id="mqtt_thema"
         value="<?= bw_e(isset($bw_q['mqtt_thema']) ? $bw_q['mqtt_thema'] : '') ?>"
         placeholder="ecowitt/FCE8C0F0BCD3">
  <p class="sm-hilfe"><?= bw_t('QUELL.S1_H_MQTT') ?></p>
</div>
<button data-role="none" class="sm-b sm-b-aktion" name="weg_speichern" value="1"><?= bw_e(bw_t('ALLG.SPEICHERN')) ?></button>
</form>
</div>

<div class="sm-step">
<h3><?= bw_e(bw_t('QUELL.S2_TITEL')) ?></h3>
<p class="sm-hilfe"><?= bw_t('QUELL.S2_TEXT') ?></p>
<table class="sm-tabelle" style="max-width:700px">
<tr><th><?= bw_e(bw_t('QUELL.S2_T_WEG')) ?></th><th><?= bw_e(bw_t('QUELL.S2_T_KNOPF')) ?></th>
    <th><?= bw_e(bw_t('QUELL.S2_T_VORAUS')) ?></th></tr>
<tr><td><b>HTTP</b></td>
    <td><form action="index.php" method="post" style="margin:0">
      <?php echo bw_fmt(); ?>
      <input data-role="none" type="hidden" name="activetab" value="tab-sources">
      <button data-role="none" class="sm-b sm-b-lesen" name="quellen_erkennen" value="1"><?= bw_e(bw_t('QUELL.K_ERKENNEN')) ?></button>
    </form></td>
    <td class="sm-hilfe"><?= bw_t('QUELL.S2_V_HTTP') ?></td></tr>
<tr><td><b>MQTT</b></td>
    <td><form action="index.php" method="post" style="margin:0">
      <?php echo bw_fmt(); ?>
      <input data-role="none" type="hidden" name="activetab" value="tab-sources">
      <button data-role="none" class="sm-b sm-b-lesen" name="broker_erkennen" value="1"><?= bw_e(bw_t('QUELL.K_BROKER')) ?></button>
    </form></td>
    <td class="sm-hilfe"><?= bw_t('QUELL.S2_V_MQTT') ?></td></tr>
</table>
<div class="sm-hinweis"><?= bw_t('QUELL.S2_RECHNEN') ?></div>
<?php if ($bw_bro !== null && $bw_bro['themen'] > 0) { ?>
<h3><?= sprintf(bw_e(bw_t('QUELL.BRO_VORSCHLAG')), (int) $bw_bro['themen']) ?></h3>
<?php if (!$bw_bro['felder']) { ?>
<div class="sm-warnung"><?= bw_t('QUELL.BRO_NICHTS_ERKANNT') ?></div>
<?php } else { ?>
<div class="sm-breit">
<table class="sm-tabelle">
<tr><th><?= bw_e(bw_t('QUELL.T_GROESSE')) ?></th><th><?= bw_e(bw_t('MQTT.T_THEMA')) ?></th>
    <th><?= bw_e(bw_t('QUELL.T_PFAD')) ?></th><th><?= bw_e(bw_t('QUELL.ERK_T_WERT')) ?></th>
    <th><?= bw_e(bw_t('QUELL.T_EINHEIT')) ?></th></tr>
<?php foreach ($bw_bro['felder'] as $bw_g => $bw_f) { ?>
<tr><td><?= bw_e($bw_g) ?></td><td class="sm-mono"><?= bw_e($bw_f['thema']) ?></td>
    <td class="sm-mono"><?= bw_e($bw_f['pfad']) ?></td>
    <td class="sm-mono"><?= bw_e($bw_f['wert']) ?></td>
    <td class="sm-mono"><?= bw_e($bw_f['einheit'] !== '' ? $bw_f['einheit'] : '—') ?></td></tr>
<?php } ?>
</table>
</div>
<form action="index.php" method="post">
  <?php echo bw_fmt(); ?>
  <input data-role="none" type="hidden" name="activetab" value="tab-sources">
  <button data-role="none" class="sm-b sm-b-aktion" name="broker_uebernehmen" value="1"><?= bw_e(bw_t('QUELL.K_UEBERNEHMEN')) ?></button>
</form>
<p class="sm-hilfe"><?= bw_t('QUELL.BRO_FUSSNOTE') ?></p>
<?php } ?>
<h4><?= bw_e(bw_t('QUELL.BRO_ALLE')) ?></h4>
<div class="sm-breit">
<table class="sm-tabelle">
<tr><th><?= bw_e(bw_t('MQTT.T_THEMA')) ?></th><th><?= bw_e(bw_t('QUELL.T_PFAD')) ?></th>
    <th><?= bw_e(bw_t('QUELL.ERK_T_WERT')) ?></th></tr>
<?php foreach ($bw_bro['blaetter'] as $bw_bl) { ?>
<tr><td class="sm-mono"><?= bw_e($bw_bl['thema']) ?></td>
    <td class="sm-mono"><?= bw_e($bw_bl['pfad']) ?></td>
    <td class="sm-mono"><?= bw_e($bw_bl['wert']) ?></td></tr>
<?php } ?>
</table>
</div>
<?php } ?>

<?php if ($bw_erk !== null) { ?>
<h3><?= bw_e(bw_t('QUELL.ERK_VORSCHLAG')) ?></h3>
<?php if (!$bw_erk['felder']) { ?>
<div class="sm-warnung"><?= bw_t('QUELL.ERK_NICHTS_ERKANNT') ?></div>
<?php } else { ?>
<div class="sm-breit">
<table class="sm-tabelle">
<tr><th><?= bw_e(bw_t('QUELL.T_GROESSE')) ?></th><th><?= bw_e(bw_t('QUELL.T_PFAD')) ?></th>
    <th><?= bw_e(bw_t('QUELL.ERK_T_WERT')) ?></th><th><?= bw_e(bw_t('QUELL.ERK_T_KENNUNG')) ?></th></tr>
<?php foreach ($bw_erk['felder'] as $bw_g => $bw_f) { ?>
<tr><td><?= bw_e($bw_g) ?></td><td class="sm-mono"><?= bw_e($bw_f['pfad']) ?></td>
    <td class="sm-mono"><?= bw_e($bw_f['wert']) ?></td>
    <td class="sm-mono"><?= bw_e($bw_f['kennung']) ?></td></tr>
<?php } ?>
</table>
</div>
<form action="index.php" method="post">
  <?php echo bw_fmt(); ?>
  <input data-role="none" type="hidden" name="activetab" value="tab-sources">
  <button data-role="none" class="sm-b sm-b-aktion" name="quellen_uebernehmen" value="1"><?= bw_e(bw_t('QUELL.K_UEBERNEHMEN')) ?></button>
</form>
<p class="sm-hilfe"><?= bw_t('QUELL.ERK_FUSSNOTE') ?></p>
<?php } ?>
<h3><?= bw_e(bw_t('QUELL.ERK_ALLE')) ?></h3>
<p class="sm-hilfe"><?= bw_t('QUELL.ERK_ALLE_TEXT') ?></p>
<div class="sm-breit">
<table class="sm-tabelle">
<tr><th><?= bw_e(bw_t('QUELL.T_PFAD')) ?></th><th><?= bw_e(bw_t('QUELL.ERK_T_WERT')) ?></th>
    <th><?= bw_e(bw_t('QUELL.T_EINHEIT')) ?></th></tr>
<?php foreach ($bw_erk['blaetter'] as $bw_bl) { ?>
<tr><td class="sm-mono"><?= bw_e($bw_bl['pfad']) ?></td>
    <td class="sm-mono"><?= bw_e($bw_bl['wert']) ?></td>
    <td class="sm-mono"><?= bw_e($bw_bl['einheit']) ?></td></tr>
<?php } ?>
</table>
</div>
<?php } ?>

</div>

<?php
/* Was zuletzt wirklich angekommen ist.
 *
 * Zwei Vorlagen sagen das seit jeher zu ("Der Reiter Quellen zeigt die
 * Rohantwort - daran laesst sich jeder Pfad in einer Minute richtigstellen"),
 * und bis 0.9.6 zeigte er es nicht. Ohne diese Anzeige muss man Pfade raten. */
$bw_roh = bw_json_lesen(bw_paths()['datadir'] . '/roh.json');
?>
<h2><?= bw_e(bw_t('QUELL.H_ROH')) ?></h2>
<p class="sm-hilfe"><?= bw_t('QUELL.ROH_ERKLAERUNG') ?></p>
<?php if (!$bw_roh) { ?>
<div class="sm-hinweis"><?= bw_t('QUELL.ROH_LEER') ?></div>
<?php } else { ?>
<p class="sm-hilfe"><?= sprintf(bw_t('QUELL.ROH_STAND'),
    date('d.m.Y H:i', (int) (isset($bw_roh['ts']) ? $bw_roh['ts'] : 0))) ?></p>
<?php
/* Eine leere Anzeige ohne Begruendung ist keine Anzeige.
 *
 * Am Gerät gemeldet: unter der Ueberschrift stand nur das Datum und sonst
 * nichts. Der Grund war harmlos - die Adresse war nach dem letzten
 * Rechengang eingetragen worden -, aber ablesbar war er nirgends. Jetzt
 * sagt der Abschnitt in jedem Fall, WAS er hat und was fehlt. */
$bw_roh_url = (string) (isset($bw_roh['http_url']) ? $bw_roh['http_url'] : '');
$bw_roh_hat = !empty($bw_roh['http']) || !empty($bw_roh['mqtt']);
$bw_url_jetzt = (string) (isset($bw_q['http_url']) ? $bw_q['http_url'] : '');
if (!$bw_roh_hat) { ?>
<div class="sm-warnung"><?php
    if ($bw_url_jetzt !== '' && $bw_roh_url === '') {
        echo bw_t('QUELL.ROH_NOCH_NICHT');
    } elseif ($bw_url_jetzt !== '' && $bw_roh_url !== $bw_url_jetzt) {
        echo bw_t('QUELL.ROH_ANDERE_ADRESSE');
    } elseif ($bw_url_jetzt === '') {
        echo bw_t('QUELL.ROH_KEINE_ADRESSE');
    } else {
        echo bw_t('QUELL.ROH_NICHTS');
    }
?></div>
<?php }
if (!empty($bw_roh['http_fehler'])) { ?>
<div class="sm-fehler"><?= sprintf(bw_t('QUELL.ROH_FEHLER'), bw_e($bw_roh['http_fehler'])) ?></div>
<?php }
if (!empty($bw_roh['http'])) { ?>
<h3><?= bw_e(bw_t('QUELL.ROH_HTTP')) ?> <span class="sm-mono"><?= bw_e($bw_roh['http_url']) ?></span></h3>
<div class="sm-log"><?= bw_e($bw_roh['http']) ?></div>
<?php }
if (!empty($bw_roh['mqtt']) && is_array($bw_roh['mqtt'])) { ?>
<h3><?= bw_e(bw_t('QUELL.ROH_MQTT')) ?></h3>
<table class="sm-tabelle">
<tr><th><?= bw_e(bw_t('MQTT.T_THEMA')) ?></th><th><?= bw_e(bw_t('QUELL.T_NUTZLAST')) ?></th>
    <th><?= bw_e(bw_t('QUELL.T_ALTER')) ?></th></tr>
<?php foreach ($bw_roh['mqtt'] as $bw_th => $bw_mw) { ?>
<tr><td class="sm-mono"><?= bw_e($bw_th) ?></td>
    <td class="sm-mono"><?= bw_e((string) (isset($bw_mw['nutzlast']) ? $bw_mw['nutzlast'] : '')) ?></td>
    <td><?= (int) (isset($bw_mw['alter_s']) ? $bw_mw['alter_s'] : 0) ?> s</td></tr>
<?php } ?>
</table>
<?php } } ?>
</div>

<!-- ============ Zonen ============ -->
<div class="sm-seite<?= $bw_tab === 'tab-zones' ? ' sm-active' : '' ?>" id="tab-zones">
<h2><?= bw_e(bw_t('ZONE.H_TITEL')) ?></h2>
<div class="sm-legende">
  <span class="sm-b-aktion" style="background:#d97706"></span><?= bw_t('LEGENDE.AKTION') ?>
</div>
<p class="sm-hilfe"><?= bw_t('ZONE.ERKLAERUNG') ?></p>
<form action="index.php" method="post">
  <?php echo bw_fmt(); ?>
<input data-role="none" type="hidden" name="activetab" value="tab-zones">
<div class="sm-breit">
<table class="sm-tabelle">
<tr><th><?= bw_e(bw_t('ZONE.T_NAME')) ?></th><th><?= bw_e(bw_t('ZONE.T_SCHLUESSEL')) ?></th>
    <th><?= bw_e(bw_t('ZONE.T_FLAECHE')) ?></th><th><?= bw_e(bw_t('ZONE.T_BEPFLANZUNG')) ?></th>
    <th><?= bw_e(bw_t('ZONE.T_BODEN')) ?></th><th><?= bw_e(bw_t('ZONE.T_RATE')) ?></th>
    <th><?= bw_e(bw_t('ZONE.T_MIKRO')) ?></th>
    <th><?= bw_e(bw_t('ZONE.T_FEUCHTE')) ?></th><th><?= bw_e(bw_t('ZONE.T_ZYKLUS')) ?></th></tr>
<?php /* Acht Zeilen sind die Vorgabe, aber NIE weniger, als es Zonen
         gibt: der Speichern-Handler baut die Liste aus dem Formular
         neu auf. Stuenden in zonen.json neun Zonen und die Tabelle
         zeigte acht, wuerde die neunte bei jedem Speichern still
         weggeworfen - sichtbar blieb sie in Auswahlfeld, Standtabelle
         und Themenliste, die alle ungekappt zaehlen. */
   $bw_zeilen_n = max(8, count($bw_zonen)); ?>
<?php for ($bw_i = 0; $bw_i < $bw_zeilen_n; $bw_i++) {
    $bw_z = isset($bw_zonen[$bw_i]) ? $bw_zonen[$bw_i] : array(); ?>
<tr>
  <td><input data-role="none" type="text" name="z_name[<?= $bw_i ?>]" size="16"
             value="<?= bw_e(isset($bw_z['name']) ? $bw_z['name'] : '') ?>"></td>
  <td><input data-role="none" type="text" name="z_schluessel[<?= $bw_i ?>]" size="9"
             value="<?= bw_e(isset($bw_z['schluessel']) ? $bw_z['schluessel'] : '') ?>"></td>
  <td><input data-role="none" type="text" name="z_flaeche[<?= $bw_i ?>]" size="6"
             value="<?= bw_e(isset($bw_z['flaeche']) ? $bw_z['flaeche'] : '') ?>"></td>
  <td><select data-role="none" name="z_bepflanzung[<?= $bw_i ?>]">
      <?php foreach (bw_tabelle($bw_pf['bepflanzung']) as $bw_k => $bw_v) { ?>
      <option value="<?= bw_e($bw_k) ?>"<?= (isset($bw_z['bepflanzung']) ? $bw_z['bepflanzung'] : 'rasen_kuehl') === $bw_k ? ' selected' : '' ?>><?= bw_e($bw_v['text']) ?><?= !empty($bw_v['geschaetzt']) ? ' *' : '' ?></option>
      <?php } ?></select></td>
  <td><select data-role="none" name="z_boden[<?= $bw_i ?>]">
      <?php foreach (bw_tabelle($bw_pf['boden']) as $bw_k => $bw_v) { ?>
      <option value="<?= bw_e($bw_k) ?>"<?= (isset($bw_z['boden']) ? $bw_z['boden'] : 'lehm') === $bw_k ? ' selected' : '' ?>><?= bw_e($bw_v['text']) ?><?= !empty($bw_v['geschaetzt']) ? ' *' : '' ?></option>
      <?php } ?></select></td>
  <td><input data-role="none" type="text" name="z_rate[<?= $bw_i ?>]" size="5"
             value="<?= bw_e(isset($bw_z['rate_mmh']) ? $bw_z['rate_mmh'] : '') ?>">
      <select data-role="none" name="z_regner[<?= $bw_i ?>]" style="margin-top:3px">
      <option value=""><?= bw_e(bw_t('ZONE.REGNER_KEINER')) ?></option>
      <?php foreach (bw_tabelle($bw_pf['regner']) as $bw_rk => $bw_rv) { ?>inue; } ?>
      <option value="<?= bw_e($bw_rk) ?>"<?= (isset($bw_z['regner']) ? $bw_z['regner'] : '') === $bw_rk ? ' selected' : '' ?>><?= bw_e($bw_rv['text']) ?> (<?= bw_e($bw_rv['mmh']) ?>)</option>
      <?php } ?></select>
      <?php if (!empty($bw_z['schluessel'])) { ?>
      <div class="sm-hilfe"><?= !empty($bw_z['rate_gemessen'])
          ? '<span class="sm-an">' . bw_e(bw_t('ZONE.GEMESSEN'))
            . (!empty($bw_z['rate_gemessen_am'])
               ? ' ' . bw_e($bw_z['rate_gemessen_am']) : '') . '</span>'
          : '<span class="sm-schaetz">' . bw_e(bw_t('ZONE.GESCHAETZT')) . '</span>' ?></div>
      <?php } ?></td>
  <td><input data-role="none" type="text" name="z_mikroklima[<?= $bw_i ?>]" size="4"
             value="<?= bw_e(isset($bw_z['mikroklima']) && (float) $bw_z['mikroklima'] != 1.0
                             ? $bw_z['mikroklima'] : '') ?>" placeholder="1,0"></td>
  <td><input data-role="none" type="text" name="z_feuchte[<?= $bw_i ?>]" size="16"
             value="<?= bw_e(isset($bw_z['feuchte_thema']) ? $bw_z['feuchte_thema'] : '') ?>"
             placeholder="<?= bw_e(bw_t('ZONE.P_FEUCHTE')) ?>"></td>
  <td style="text-align:center"><input data-role="none" type="checkbox" name="z_zyklus[<?= $bw_i ?>]" value="1"<?= !empty($bw_z['im_zyklus']) ? ' checked' : '' ?>></td>
</tr>
<?php } ?>
</table>
</div>
<p class="sm-hilfe"><?= bw_t('ZONE.FUSSNOTE') ?></p>
<p class="sm-hilfe"><?= bw_t('ZONE.HILFE_MIKRO') ?></p>

<h3><?= bw_e(bw_t('ZONE.H_FEIN')) ?></h3>
<p class="sm-hilfe"><?= bw_t('ZONE.FEIN_ERKLAERUNG') ?></p>
<div class="sm-breit">
<table class="sm-tabelle">
<tr><th><?= bw_e(bw_t('ZONE.T_NAME')) ?></th><th><?= bw_e(bw_t('ZONE.T_DAUER')) ?></th>
    <th><?= bw_e(bw_t('ZONE.T_HOEHE_PFLANZE')) ?></th><th><?= bw_e(bw_t('ZONE.T_ABFLUSS')) ?></th>
    <th><?= bw_e(bw_t('ZONE.T_SENSOR_GEWICHT')) ?></th>
    <th><?= bw_e(bw_t('ZONE.T_THETA_FC')) ?></th><th><?= bw_e(bw_t('ZONE.T_THETA_WP')) ?></th>
    <th><?= bw_e(bw_t('ZONE.T_GIESS_THEMA')) ?></th><th><?= bw_e(bw_t('ZONE.T_GIESS_ART')) ?></th></tr>
<?php for ($bw_j = 0; $bw_j < $bw_zeilen_n; $bw_j++) {
    $bw_z = isset($bw_zonen[$bw_j]) ? $bw_zonen[$bw_j] : array(); ?>
<tr>
  <?php /* NICHT bw_e('&mdash;') - die Maskierfunktion macht daraus
             '&amp;mdash;', und auf dem Bildschirm steht dann der Quelltext.
             Genau der Befund mit 40 Fundstellen in 13 Plugins, hier von mir
             selbst neu eingeschleppt und am Geraet gesehen. Der Name geht
             durch bw_e(), das Zeichen daneben nicht. */ ?>
  <td class="sm-hilfe"><?= !empty($bw_z['name']) ? bw_e($bw_z['name']) : '&mdash;' ?></td>
  <td><input data-role="none" type="text" name="z_dauer[<?= $bw_j ?>]" size="5"
             value="<?= bw_e(!empty($bw_z['dauer_s']) ? $bw_z['dauer_s'] : '') ?>"
             placeholder="<?= bw_e($bw_cfg['zonendauer_s']) ?>"></td>
  <td><input data-role="none" type="text" name="z_hoehe_pflanze[<?= $bw_j ?>]" size="5"
             value="<?= bw_e(!empty($bw_z['hoehe_pflanze']) ? $bw_z['hoehe_pflanze'] : '') ?>"></td>
  <td><input data-role="none" type="text" name="z_abfluss[<?= $bw_j ?>]" size="5"
             value="<?= bw_e(!empty($bw_z['abfluss']) ? $bw_z['abfluss'] : '') ?>" placeholder="0"></td>
  <td><input data-role="none" type="text" name="z_sensor_gewicht[<?= $bw_j ?>]" size="5"
             value="<?= bw_e(isset($bw_z['sensor_gewicht'])
                 ? str_replace('.', ',', (string) $bw_z['sensor_gewicht']) : '') ?>" placeholder="0,5"></td>
  <td><input data-role="none" type="text" name="z_theta_fc[<?= $bw_j ?>]" size="5"
             value="<?= bw_e(!empty($bw_z['theta_fc_eigen'])
                 ? str_replace('.', ',', (string) $bw_z['theta_fc_eigen']) : '') ?>"
             placeholder="<?= bw_e(isset($bw_z['theta_fc'])
                 ? str_replace('.', ',', (string) $bw_z['theta_fc']) : '') ?>"></td>
  <td><input data-role="none" type="text" name="z_theta_wp[<?= $bw_j ?>]" size="5"
             value="<?= bw_e(!empty($bw_z['theta_wp_eigen'])
                 ? str_replace('.', ',', (string) $bw_z['theta_wp_eigen']) : '') ?>"
             placeholder="<?= bw_e(isset($bw_z['theta_wp'])
                 ? str_replace('.', ',', (string) $bw_z['theta_wp']) : '') ?>"></td>
  <td><input data-role="none" type="text" name="z_giess_thema[<?= $bw_j ?>]" size="18"
             value="<?= bw_e(isset($bw_z['giess_thema']) ? $bw_z['giess_thema'] : '') ?>"
             placeholder="<?= bw_e(bw_t('ZONE.P_GIESS')) ?>"></td>
  <td><select data-role="none" name="z_giess_art[<?= $bw_j ?>]">
      <?php foreach (array('minuten' => bw_t('ZONE.GIESS_MINUTEN'),
                           'durchlaeufe' => bw_t('ZONE.GIESS_DURCHLAEUFE'),
                           'mm' => bw_t('ZONE.GIESS_MM')) as $bw_gk => $bw_gv) { ?>
      <option value="<?= bw_e($bw_gk) ?>"<?= (isset($bw_z['giess_art']) ? $bw_z['giess_art'] : 'minuten') === $bw_gk ? ' selected' : '' ?>><?= bw_e($bw_gv) ?></option>
      <?php } ?></select></td>
</tr>
<?php } ?>
</table>
</div>
<p class="sm-hilfe"><?= bw_t('ZONE.FEIN_FUSSNOTE') ?></p>
<button data-role="none" class="sm-b sm-b-aktion" name="zonen_speichern" value="1"><?= bw_e(bw_t('ALLG.SPEICHERN')) ?></button>
</form>

<h2><?= bw_e(bw_t('ZONE.H_BECHER')) ?></h2>
<div class="sm-warnung"><?= bw_t('ZONE.BECHER_ERKLAERUNG') ?></div>
<?php if ($bw_zonen) { ?>
<form action="index.php" method="post">
  <?php echo bw_fmt(); ?>
<input data-role="none" type="hidden" name="activetab" value="tab-zones">
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
<button data-role="none" class="sm-b sm-b-aktion" name="becher_senden" value="1"><?= bw_e(bw_t('ZONE.K_BECHER')) ?></button>
</form>
<?php } ?>

<?php if ($bw_a && !empty($bw_a['zonen'])) { ?>
<h2><?= bw_e(bw_t('ZONE.H_STAND')) ?></h2>
<table class="sm-tabelle">
<tr><th><?= bw_e(bw_t('ZONE.T_NAME')) ?></th><th><?= bw_e(bw_t('ZONE.T_FUELLSTAND')) ?></th>
    <th><?= bw_e(bw_t('ZONE.T_DEFIZIT')) ?></th><th><?= bw_e(bw_t('ZONE.T_BEDARF')) ?></th>
    <th><?= bw_e(bw_t('ZONE.T_LITER')) ?></th><th><?= bw_e(bw_t('ZONE.T_MINUTEN')) ?></th>
    <th><?= bw_e(bw_t('ZONE.T_VENTILZEIT')) ?></th><th><?= bw_e(bw_t('ZONE.T_GEGOSSEN')) ?></th></tr>
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
    <td><?= number_format((float) (isset($bw_e['minuten']) ? $bw_e['minuten'] : 0), 0, ',', '.') ?><?= $bw_ges ? ' <span class="sm-schaetz">*</span>' : '' ?></td>
<?php   $bw_jz = isset($bw_plan['je_zone'][$bw_s]) && is_array($bw_plan['je_zone'][$bw_s])
            ? $bw_plan['je_zone'][$bw_s] : array();
        $bw_ged = in_array((string) $bw_z['name'],
            isset($bw_plan['ventilzeit_gedeckelt']) && is_array($bw_plan['ventilzeit_gedeckelt'])
                ? $bw_plan['ventilzeit_gedeckelt'] : array(), true); ?>
    <td><?= (int) (isset($bw_jz['sekunden_soll']) ? $bw_jz['sekunden_soll'] : 0) ?> s<?php
        if ($bw_ged) { echo ' <span class="sm-aus">' . bw_e(bw_t('ZONE.GEDECKELT')) . '</span>'; } ?></td>
    <td><?= isset($bw_e['gegossen_mm']) && $bw_e['gegossen_mm'] !== null
        ? number_format((float) $bw_e['gegossen_mm'], 1, ',', '.') . ' mm'
        : '<span class="sm-hilfe">&mdash;</span>' ?></td></tr>
<?php } ?>
</table>
<p class="sm-hilfe"><?= bw_t('ZONE.STAND_FUSSNOTE') ?></p>
<?php
/* Die Zonen ohne Niederschlagsrate BENENNEN.
 *
 * README und Quelltext sagen seit 0.9.1 zu: "der Grund lautet rate_fehlt,
 * und die Oberflaeche zeigt, welche Zone es betrifft". Der Plan liefert die
 * Namensliste in 'ohne_rate' - angezeigt wurde sie nirgends. Ausgerechnet
 * der Fall, den der Quelltext als den gefaehrlichsten des Moduls bezeichnet,
 * war damit unsichtbar. */
$bw_or = isset($bw_plan['ohne_rate']) && is_array($bw_plan['ohne_rate'])
    ? $bw_plan['ohne_rate'] : array();
if ($bw_or) { ?>
<div class="sm-fehler"><?= sprintf(bw_t('ZONE.OHNE_RATE'), bw_e(implode(', ', $bw_or))) ?></div>
<?php }
$bw_gd = isset($bw_plan['ventilzeit_gedeckelt']) && is_array($bw_plan['ventilzeit_gedeckelt'])
    ? $bw_plan['ventilzeit_gedeckelt'] : array();
if ($bw_gd) { ?>
<div class="sm-warnung"><?= sprintf(bw_t('ZONE.GEDECKELT_TEXT'), bw_e(implode(', ', $bw_gd))) ?></div>
<?php }
/* Und der Sensorhinweis, der bis 0.9.6 sorgfaeltig formuliert und niemandem
 * gezeigt wurde. */
foreach ($bw_zonen as $bw_z) {
    $bw_s = (string) $bw_z['schluessel'];
    $bw_e2 = isset($bw_a['zonen'][$bw_s]) ? $bw_a['zonen'][$bw_s] : null;
    if (is_array($bw_e2) && !empty($bw_e2['sensor_hinweis'])) { ?>
<div class="sm-warnung"><b><?= bw_e($bw_z['name']) ?>:</b> <?= bw_e($bw_e2['sensor_hinweis']) ?></div>
<?php }
} ?>
<?php } ?>
</div>

<!-- ============ Verlauf ============ -->
<div class="sm-seite<?= $bw_tab === 'tab-history' ? ' sm-active' : '' ?>" id="tab-history">
<h2><?= bw_e(bw_t('VERL.H_TITEL')) ?></h2>
<div class="sm-hinweis"><?= bw_t('VERL.ERKLAERUNG') ?></div>
<?php
$bw_vt = bw_verlauf_tage(60);
$bw_luecken = bw_verlauf_luecken();
if ($bw_luecken > 0) { ?>
<div class="sm-warnung"><?= sprintf(bw_t('VERL.LUECKEN'), (int) $bw_luecken) ?></div>
<?php }
if (!$bw_vt) { ?>
<div class="sm-hinweis"><?= bw_t('VERL.LEER') ?></div>
<?php } else {
    // Summen ueber den gezeigten Zeitraum - die Zahl, nach der man wirklich
    // sucht: wie viel ist verdunstet, wie viel ist gefallen, wie viel wurde
    // ausgebracht.
    $bw_s_et0 = 0.0; $bw_s_reg = 0.0; $bw_s_bew = 0.0;
    foreach ($bw_vt as $bw_t2) {
        $bw_s_et0 += (float) $bw_t2['et0'];
        $bw_s_reg += (float) $bw_t2['regen'];
        $bw_s_bew += (float) $bw_t2['bew_summe'];
    }
    $bw_max = 1.0;
    foreach ($bw_vt as $bw_t2) {
        $bw_max = max($bw_max, (float) $bw_t2['et0'], (float) $bw_t2['regen']);
    }
?>
<table class="sm-tabelle" style="max-width:560px">
<tr><th><?= bw_e(bw_t('VERL.T_ZEITRAUM')) ?></th><td><?= count($bw_vt) ?> <?= bw_e(bw_t('VERL.TAGE')) ?></td></tr>
<tr><th><?= bw_e(bw_t('VERL.T_S_ET0')) ?></th><td><?= number_format($bw_s_et0, 1, ',', '.') ?> mm</td></tr>
<tr><th><?= bw_e(bw_t('VERL.T_S_REGEN')) ?></th><td><?= number_format($bw_s_reg, 1, ',', '.') ?> mm</td></tr>
<tr><th><?= bw_e(bw_t('VERL.T_S_BEW')) ?></th><td><?= number_format($bw_s_bew, 1, ',', '.') ?> mm</td></tr>
</table>
<table class="sm-tabelle">
<tr><th><?= bw_e(bw_t('VERL.T_DATUM')) ?></th><th><?= bw_e(bw_t('VERL.T_ET0')) ?></th>
    <th><?= bw_e(bw_t('VERL.T_REGEN')) ?></th><th><?= bw_e(bw_t('VERL.T_BEW')) ?></th>
    <th><?= bw_e(bw_t('VERL.T_QUELLE')) ?></th></tr>
<?php foreach ($bw_vt as $bw_t2) { ?>
<tr>
  <td class="sm-mono"><?= bw_e($bw_t2['datum']) ?></td>
  <td><?= $bw_t2['et0'] === null ? '&mdash;' : number_format((float) $bw_t2['et0'], 2, ',', '.') ?>
      <div class="sm-balken" style="max-width:70px"><i style="width:<?= (int) (100 * (float) $bw_t2['et0'] / $bw_max) ?>%"></i></div></td>
  <td><?= $bw_t2['regen'] === null ? '&mdash;' : number_format((float) $bw_t2['regen'], 1, ',', '.') ?></td>
  <td><?php if ($bw_t2['bew_summe'] > 0) {
          echo number_format((float) $bw_t2['bew_summe'], 1, ',', '.');
          echo ' <span class="sm-hilfe">(';
          $bw_teile = array();
          foreach ($bw_t2['bewaesserung'] as $bw_zk => $bw_zw) {
              $bw_teile[] = bw_e($bw_zk) . ' ' . number_format((float) $bw_zw, 1, ',', '.');
          }
          echo implode(', ', $bw_teile) . ')</span>';
      } else { echo '<span class="sm-hilfe">&mdash;</span>'; } ?></td>
  <td class="sm-hilfe"><?= bw_e($bw_t2['quelle']) ?><?= $bw_t2['nachgetragen']
      ? ' <span class="sm-schaetz">' . bw_e(bw_t('VERL.NACHGETRAGEN')) . '</span>' : '' ?></td>
</tr>
<?php } ?>
</table>
<p class="sm-hilfe"><?= bw_t('VERL.FUSSNOTE') ?></p>
<?php } ?>
</div>

<!-- ============ MQTT ============ --><!-- ============ MQTT ============ -->
<div class="sm-seite<?= $bw_tab === 'tab-mqtt' ? ' sm-active' : '' ?>" id="tab-mqtt">

<h2>MQTT</h2>
<form action="index.php" method="post">
  <?php echo bw_fmt(); ?>
<input data-role="none" type="hidden" name="save_mqtt" value="1">
<input data-role="none" type="hidden" name="activetab" value="tab-mqtt">
<h2><?= bw_e(bw_t('EINST.H_MQTT')) ?></h2>
<label><input data-role="none" type="checkbox" name="mqtt_ein" value="1"<?= !empty($bw_cfg['mqtt_ein']) ? ' checked' : '' ?>>
  <?= bw_e(bw_t('EINST.L_MQTT_EIN')) ?></label>
<div class="sm-feld">
  <label for="mqtt_topic"><?= bw_e(bw_t('EINST.L_MQTT_TOPIC')) ?></label>
  <input data-role="none" type="text" name="mqtt_topic" id="mqtt_topic" value="<?= bw_e($bw_cfg['mqtt_topic']) ?>">
</div>
<?php /* Schreibweise wie im uebrigen Plugin: die Knopf-Grundklasse dieser
         Linie ist die kurze Form, und die Legendenpunkte bekommen ihre
         Groesse aus '.sm-legende span' und ihre Farbe unmittelbar aus dem
         style-Attribut. Eine eigene Punktklasse und eine Klasse fuer die
         Knopfreihe gibt es in dieser Linie nicht - bis 0.9.18 standen beide
         als Namen im HTML, ohne dass der Stilblock sie kannte. */ ?>
<div class="sm-legende">
  <span class="sm-b-aktion" style="background:#d97706"></span><?= bw_t('LEGENDE.AKTION') ?>
</div>
<button data-role="none" class="sm-b sm-b-aktion" type="submit"><?= bw_e(bw_t('ALLG.SPEICHERN')) ?></button>
</form>
<h2><?= bw_e(bw_t('MQTT.H_TITEL')) ?></h2>
<?php $bw_g = bw_mqtt_zustand(); ?>
<table class="sm-tabelle" style="max-width:520px">
<tr><td><?= bw_e(bw_t('MQTT.T_GATEWAY')) ?></td>
    <td class="<?= !empty($bw_g['autostart']) ? 'sm-an' : 'sm-aus' ?>"><?= !empty($bw_g['autostart'])
        ? bw_e(bw_t('MQTT.AUTOSTART_EIN')) : bw_e(bw_t('MQTT.AUTOSTART_AUS')) ?></td></tr>
<tr><td><?= bw_e(bw_t('MQTT.T_UDP')) ?></td><td class="sm-mono"><?= (int) (isset($bw_g['udpport']) ? $bw_g['udpport'] : 0) ?></td></tr>
</table>
<div class="sm-warnung"><?= bw_abo_text() ?></div>
<div class="sm-hinweis"><?= bw_t('MQTT.RUECKKANAL') ?></div>
<p class="sm-hilfe"><?= bw_t('MQTT.ABO_TEXT') ?></p>
<p><span class="sm-mono"><?= bw_e($bw_cfg['mqtt_topic']) ?>/#</span></p>

<h3><?= bw_e(bw_t('MQTT.H_THEMEN')) ?></h3>
<table class="sm-tabelle">
<tr><th><?= bw_e(bw_t('MQTT.T_THEMA')) ?></th><th><?= bw_e(bw_t('MQTT.T_BEDEUTUNG')) ?></th></tr>
<?php foreach (array('ok' => 'MQTT.B_OK', 'et0' => 'MQTT.B_ET0', 'giessen' => 'MQTT.B_GIESSEN',
                     'durchlaeufe' => 'MQTT.B_DURCHLAEUFE', 'noetige_durchlaeufe' => 'MQTT.B_NOETIG',
                     'reicht' => 'MQTT.B_REICHT', 'alter' => 'MQTT.B_ALTER',
                     'gesperrt' => 'MQTT.B_GESPERRT', 'sperrgrund' => 'MQTT.B_SPERRGRUND',
                     'plan_fest' => 'MQTT.B_PLANFEST') as $bw_k => $bw_v) { ?>
<tr><td class="sm-mono"><?= bw_e($bw_cfg['mqtt_topic'] . '/' . $bw_k) ?></td><td><?= bw_t($bw_v) ?></td></tr>
<?php } ?>
<?php foreach ($bw_zonen as $bw_z) { $bw_s = bw_e($bw_z['schluessel']);
    foreach (array('defizit_mm' => 'MQTT.B_ZONE_DEFIZIT', 'bedarf_mm' => 'MQTT.B_ZONE_BEDARF',
                   'dr_mm' => 'MQTT.B_ZONE_DR', 'fuellstand' => 'MQTT.B_ZONE_FUELLSTAND',
                   'liter' => 'MQTT.B_ZONE_LITER', 'minuten' => 'MQTT.B_ZONE_MINUTEN',
                   'sekunden' => 'MQTT.B_ZONE_SEKUNDEN',
                   'durchlaeufe' => 'MQTT.B_ZONE_DURCHLAEUFE',
                   'gegossen_mm' => 'MQTT.B_ZONE_GEGOSSEN') as $bw_zk => $bw_zv) { ?>
<tr><td class="sm-mono"><?= bw_e($bw_cfg['mqtt_topic']) ?>/<?= $bw_s ?>/<?= bw_e($bw_zk) ?></td><td><?= sprintf(bw_t($bw_zv), bw_e($bw_z['name'])) ?></td></tr>
<?php } } ?>
</table>
</div>

<!-- ============ Einbindung in Loxone ============ -->
<div class="sm-seite<?= $bw_tab === 'tab-loxone' ? ' sm-active' : '' ?>" id="tab-loxone">
<h2><?= bw_e(bw_t('LOX.H_TITEL')) ?></h2>
<div class="sm-legende">
  <span class="sm-b-lesen" style="background:#4f7d17"></span><?= bw_t('LEGENDE.LESEN') ?><br>
  <span class="sm-b-aktion" style="background:#d97706"></span><?= bw_t('LEGENDE.AKTION') ?>
</div>
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
<form action="index.php" method="post" style="display:inline">
  <?php echo bw_fmt(); ?>
  <input data-role="none" type="hidden" name="activetab" value="tab-loxone">
  <button data-role="none" class="sm-b sm-b-lesen" name="vorlage_laden" value="1"><?= bw_e(bw_t('LOX.K_VORLAGE')) ?></button>
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
    array(1,  'BAUSTEIN.T_VE',      'BAUSTEIN.N01', array('text' => sprintf(bw_t('BAUSTEIN.P01'),
              '<span class="sm-mono">' . bw_e(bw_check('GIESSEN')) . '</span>')), '&mdash;'),
    array(2,  'BAUSTEIN.T_VE',      'BAUSTEIN.N02', array('text' => sprintf(bw_t('BAUSTEIN.P02'),
              '<span class="sm-mono">' . bw_e(bw_check('DURCHLAEUFE')) . '</span>')), '&mdash;'),
    array(3,  'BAUSTEIN.T_VE',      'BAUSTEIN.N03', array('text' => sprintf(bw_t('BAUSTEIN.P03'),
              '<span class="sm-mono">' . bw_e(bw_check('ET0')) . '</span>')), '&mdash;'),
    array(4,  'BAUSTEIN.T_VE',      'BAUSTEIN.N04', array('text' => sprintf(bw_t('BAUSTEIN.P04'),
              '<span class="sm-mono">' . bw_e(bw_check('REICHT')) . '</span>')), '&mdash;'),
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
    <?php /* Ein Feld, das als array('text' => ...) kommt, ist FERTIG und
             geht nicht noch einmal durch bw_t() - sonst suchte die
             Uebersetzung nach einem Schluessel, der der halbe Satz ist. */ ?>
    <td><?= is_array($bw_z2[3]) ? $bw_z2[3]['text']
            : ($bw_z2[3] !== '' ? bw_t($bw_z2[3]) : '&mdash;') ?></td>
    <td class="sm-mono"><?= $bw_z2[4] ?></td></tr>
<?php } ?>
</table>
<div class="sm-hinweis"><?= bw_t('LOX.S3_ERLAEUTERUNG') ?></div>
</div>

<div class="sm-step">
<h3><?= bw_e(bw_t('LOX.S4_TITEL')) ?></h3>
<p class="sm-hilfe"><?= bw_t('LOX.S4_TEXT') ?></p>
<table class="sm-tabelle"><tr><th><?= bw_e(bw_t('LOX.T_TOKEN')) ?></th><td class="sm-mono"><?= bw_e($bw_token) ?></td></tr></table>
<form action="index.php" method="post" style="display:inline">
  <?php echo bw_fmt(); ?>
  <input data-role="none" type="hidden" name="activetab" value="tab-loxone">
  <button data-role="none" class="sm-b sm-b-aktion" name="token_neu" value="1"
    onclick="return confirm(<?= bw_e(json_encode(strip_tags(html_entity_decode(bw_t('LOX.TOKEN_FRAGE'), ENT_QUOTES, 'UTF-8')))) ?>)"><?= bw_e(bw_t('LOX.K_TOKEN_NEU')) ?></button>
</form>
</div>
</div>

<!-- ============ Test ============ -->
<div class="sm-seite<?= $bw_tab === 'tab-test' ? ' sm-active' : '' ?>" id="tab-test">
<h2><?= bw_e(bw_t('TEST.H_SELBSTPRUEFUNG')) ?></h2>
<p class="sm-hilfe"><?= bw_t('TEST.EINLEITUNG') ?></p>
<?php /* Nur im offenen Reiter rechnen. Der PHP-Ausdruck lief bis
         0.9.18 bei JEDEM Seitenaufbau - 'sm-active' steuert nur die
         Sichtbarkeit -, und darin steckt ein HTTP-Aufruf des eigenen
         Endpunkts mit fuenf Sekunden Zeitgrenze. Gemessen wurden 3,5 s
         je Aufruf des Reiters Einstellungen. */ ?>
<?php if ($bw_tab === 'tab-test') { ?>
<?= bw_pruefungen_html() ?>
<?php } else { ?>
<p class="sm-hilfe"><?= bw_e(bw_t('TEST.NUR_IM_REITER')) ?></p>
<?php } ?>

<h2><?= bw_e(bw_t('TEST.H_LESEN')) ?></h2>
<div class="sm-legende">
  <span class="sm-b-lesen" style="background:#4f7d17"></span><?= bw_t('LEGENDE.LESEN') ?><br>
  <span class="sm-b-technik" style="background:#6b7280"></span><?= bw_t('LEGENDE.TECHNIK') ?><br>
  <span class="sm-b-aktion" style="background:#d97706"></span><?= bw_t('LEGENDE.AKTION') ?>
</div>
<form action="index.php" method="post">
  <?php echo bw_fmt(); ?>
  <input data-role="none" type="hidden" name="activetab" value="tab-test">
  <button data-role="none" class="sm-b sm-b-lesen" name="test" value="status"><?= bw_e(bw_t('TEST.K_STATUS')) ?></button>
  <button data-role="none" class="sm-b sm-b-technik" name="test" value="roh"><?= bw_e(bw_t('TEST.K_ROH')) ?></button>
  <button data-role="none" class="sm-b sm-b-technik" name="selbsttest" value="1"><?= bw_e(bw_t('TEST.K_SELBSTTEST')) ?></button>
  <button data-role="none" class="sm-b sm-b-aktion" name="test" value="rechnen"><?= bw_e(bw_t('TEST.K_RECHNEN')) ?></button>
</form>
<?php if ($bw_ausgabe !== '') { ?>
<div class="sm-log"><?= bw_e($bw_ausgabe) ?></div>
<?php } ?>

<h2><?= bw_e(bw_t('TEST.H_UNGEPRUEFT')) ?></h2>
<div class="sm-warnung"><?= bw_t('TEST.UNGEPRUEFT') ?></div>
</div>

<!-- ============ Logdateien ============ -->
<div class="sm-seite<?= $bw_tab === 'tab-log' ? ' sm-active' : '' ?>" id="tab-log">
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
<div class="sm-legende"><span class="sm-b-aktion" style="background:#d97706"></span><?= bw_t('LEGENDE.AKTION_LOG') ?></div>
<form action="index.php" method="post">
  <?php echo bw_fmt(); ?>
  <input data-role="none" type="hidden" name="activetab" value="tab-log">
  <button data-role="none" class="sm-b sm-b-aktion" name="log_leeren" value="1"><?= bw_e(bw_t('LOG.K_LEEREN')) ?></button>
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
