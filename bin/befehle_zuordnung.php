<?php
/**
 * bin/befehle_zuordnung.php - Zuordnungstabelle der Befehlsbruecke, Linie Bewaesserung (linieneigen).
 *
 * Gruppe 2 / MQTT (0.9.44; Entwurf bw Abschnitt 3, E8-E12; ENTSCHEIDUNGEN_GRUPPE2_MQTT.md Punkt 1: "Bewaesserung
 * wechselt auf die gemeinsame Befehlsbruecke"). Muster: vb_g1_bruecke_bau/beispiel/bin/befehle_zuordnung.php und die
 * Tabelle der Linie Ferien und Feiertage. Die Bruecke selbst (bin/befehlsbruecke.php, .sh) ist die gemeinsame
 * Stammfassung und wird hier nicht veraendert.
 *
 * Ein Befehl je Zone: rueckmeldung/{zone} - die fertigen Durchlaeufe (bzw. Laufminuten oder mm, je nach "Rueckmeldung
 * als" im Reiter Zonen) seit Mitternacht, eine Zahl 0 bis 1440. Nicht eingreifend: er schaltet nichts, er meldet nur,
 * was Loxone gegossen hat. Einen zweiten Haken hat die Linie deshalb nicht (E12). {zone} ist der Zonenschluessel mit
 * "_" statt "-" (die Bruecke erlaubt je Ebene nur a-z, 0-9, _; Zonenschluessel duerfen "-" tragen, E10);
 * bw_rueckmeldung_annehmen() bildet ihn zurueck und lehnt einen mehrdeutigen ab.
 *
 * 'tun' ruft bw_rueckmeldung_annehmen() - dieselbe Pruefung (Zone, Wert, Becherprobe) fuer jeden Weg, kein zweiter
 * Rechenweg: die Funktion schreibt nur data/plugins/<ordner>/rueckmeldung.json, verbucht wird wie bisher im Dienst
 * (giesswerte_einsammeln(), Tageshoechstwert). Die Quittung heisst deshalb "uebergeben", nicht "ausgefuehrt".
 * Der alte Rueckmeldeweg (Thema giess_thema je Zone, vom Dienst abonniert) wird weiter angenommen (E8).
 * Das Praefix kommt aus bw_mqtt_praefix() - derselben Rechnung wie die Themen des Dienstes.
 *
 * Die Datei setzt keine Konfiguration und schreibt nichts.
 */
if (!function_exists('bw_config')) {
    $bw_kand = array();
    if (basename(dirname(__DIR__)) === 'plugins') {
        $bw_kand[] = dirname(dirname(dirname(__DIR__))) . '/webfrontend/html/plugins/' . basename(__DIR__) . '/bw_lib.php';
    }
    $bw_kand[] = dirname(__DIR__) . '/webfrontend/html/bw_lib.php';
    foreach ($bw_kand as $bw_k) {
        if (is_file($bw_k)) { require_once $bw_k; break; }
    }
}
return array(
    'fassung' => 1,
    'linie'   => 'bewaesserung',
    'plugin'  => "Bew\u{e4}sserung",
    'geladen' => function_exists('bw_config') && function_exists('bw_rueckmeldung_annehmen')
                 && function_exists('bw_mqtt_praefix'),
    'einstellungen' => function () {
        $c = bw_config(false);
        return array('praefix'     => bw_mqtt_praefix($c),
                     'annehmen'    => !empty($c['befehle_mqtt_ein']) && !empty($c['mqtt_ein']),
                     'eingreifend' => false,
                     'mqtt_ein'    => !empty($c['mqtt_ein']));
    },
    'protokoll' => function ($stufe, $text) { bw_log(($stufe === 'INFO' ? '' : $stufe . ': ') . $text); },
    'teile' => array('zone' => '[a-z0-9_]{1,40}'),
    'befehle' => array(
        'rueckmeldung/{zone}' => array(
            'art' => 'zahl', 'min' => 0, 'max' => 1440, 'eingreifend' => false,
            'titel' => "Bew\u{e4}sserung <Zone> R\u{fc}ckmeldung (MQTT)",
            'kachel' => 'BEFEHL.K_RUECKMELDUNG', 'quittung' => 'uebergeben',
            'tun' => function ($w, $t) {
                return bw_rueckmeldung_annehmen(isset($t['zone']) ? (string) $t['zone'] : '', $w, 'mqtt');
            }),
    ),
);
