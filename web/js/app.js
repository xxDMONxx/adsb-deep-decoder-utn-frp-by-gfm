/**
 * LITORAL-RADAR-FRP — Frontend Application Logic
 * ================================================
 * Polling de data.json cada 1s, renderizado de tabla y mapa Leaflet.
 * Integra datos de estación terrena (GND/SDR) y CubeSat (SAT).
 *
 * Flujo: data.json (generado por tui.py) → fetch → processData → render
 */

// ─── Configuración Inicial ─────────────────────────────────────────────────
const MAP_CENTER = [-31.6333, -60.7000];
const MAP_ZOOM = 6;

const map = L.map('map', { zoomControl: false }).setView(MAP_CENTER, MAP_ZOOM);
L.control.zoom({ position: 'bottomright' }).addTo(map);

// Capa oscura CartoDB — coherente con el diseño del dashboard
L.tileLayer('https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png', {
    attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OSM</a> &copy; <a href="https://carto.com/attributions">CARTO</a>',
    subdomains: 'abcd',
    maxZoom: 20
}).addTo(map);

// ─── Marcador de la Base Terrena ────────────────────────────────────────────
const baseIcon = L.divIcon({
    className: 'base-marker',
    html: '<div style="width:14px;height:14px;background:#22d3ee;border-radius:50%;border:2px solid #fff;box-shadow:0 0 12px #22d3ee;"></div>',
    iconSize: [14, 14],
    iconAnchor: [7, 7]
});
let baseMarker = L.marker(MAP_CENTER, { icon: baseIcon })
    .addTo(map)
    .bindPopup("<div class='popup-custom'><h3>BASE TERRENA</h3><p>UTN-FRP · Santa Fe</p></div>");

// ─── Estado Global ──────────────────────────────────────────────────────────
let aircraftMarkers = {};
let aircraftDataCache = [];

// ─── Icono SVG Wireframe para Aeronaves ─────────────────────────────────────
function createPlaneIcon(heading, isLost, source) {
    let color = isLost ? '#fbbf24' : '#22d3ee';
    if (source === 'cubesat') color = '#34d399';

    const svg = `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" width="28" height="28"
        style="transform:rotate(${heading || 0}deg)">
        <polygon points="12,2 14,14 22,16 22,18 13,17 12,22 11,17 2,18 2,16 10,14"
            fill="rgba(0,0,0,0.4)" stroke="${color}" stroke-width="1.5" stroke-linejoin="round"/>
        <circle cx="12" cy="12" r="1.5" fill="${color}"/>
    </svg>`;

    return L.divIcon({
        className: 'plane-icon',
        html: svg,
        iconSize: [28, 28],
        iconAnchor: [14, 14],
        popupAnchor: [0, -14]
    });
}

// ─── Polling Principal ──────────────────────────────────────────────────────
async function updateRadarData() {
    try {
        const res = await fetch(`data.json?t=${Date.now()}`);
        if (!res.ok) throw new Error('No data');
        processData(await res.json());

        document.getElementById('conn-status').textContent = 'SYS.ONLINE';
        document.getElementById('conn-status').className = 'status-indicator online';
    } catch (e) {
        console.error('Radar fetch error:', e);
        document.getElementById('conn-status').textContent = 'SYS.OFFLINE';
        document.getElementById('conn-status').className = 'status-indicator offline';
    }
}

// ─── Procesamiento de Datos ─────────────────────────────────────────────────
function processData(data) {
    aircraftDataCache = data.aircraft || [];

    // Estadísticas
    const active = aircraftDataCache.filter(a => a.age < 60).length;
    document.getElementById('stat-active').textContent = active.toString().padStart(3, '0');
    document.getElementById('stat-msg').textContent = data.stats.total_received.toString().padStart(5, '0');
    document.getElementById('table-count').textContent = `${aircraftDataCache.length} targets`;

    const tbody = document.getElementById('aircraft-list');
    tbody.innerHTML = '';
    const currentIcaos = new Set();

    // ── Renderizado de cada aeronave ──
    aircraftDataCache.forEach(ac => {
        currentIcaos.add(ac.icao);

        // Estado
        let statusClass = 'ac-dead', statusText = 'DEAD';
        if (ac.age < 30)       { statusClass = 'ac-live'; statusText = 'LIVE'; }
        else if (ac.age < 120) { statusClass = 'ac-lost'; statusText = 'LOST'; }

        // ¿Viene también del CubeSat?
        let isSat = false;
        if (data.cubesat_aircraft) {
            isSat = data.cubesat_aircraft.some(c => c.icao === ac.icao);
        }

        // Fila de tabla
        const tr = document.createElement('tr');
        const cs = ac.callsign || '---';
        const alt = ac.altitude !== null ? Math.round(ac.altitude * 0.3048) : '---';
        const spd = ac.speed !== null ? Math.round(ac.speed * 1.852) : '---';
        const hdg = ac.heading !== null ? Math.round(ac.heading) + '°' : '---';
        const lat = ac.latitude !== null ? ac.latitude.toFixed(4) : '---';
        const lon = ac.longitude !== null ? ac.longitude.toFixed(4) : '---';
        const srcClass = isSat ? 'src-sat' : 'src-gnd';
        const srcText = isSat ? 'SAT' : 'GND';

        tr.innerHTML = `
            <td>${cs}</td>
            <td>${ac.icao}</td>
            <td>${alt}</td>
            <td>${spd}</td>
            <td>${hdg}</td>
            <td>${lat}, ${lon}</td>
            <td><span class="${srcClass}">${srcText}</span></td>
            <td class="${statusClass}">${statusText}</td>
        `;

        tr.addEventListener('click', () => {
            if (ac.latitude && ac.longitude) {
                map.setView([ac.latitude, ac.longitude], 10);
                if (aircraftMarkers[ac.icao]) aircraftMarkers[ac.icao].openPopup();
            }
        });
        tbody.appendChild(tr);

        // Marcador en mapa
        if (ac.latitude && ac.longitude) {
            const icon = createPlaneIcon(ac.heading, ac.age > 30, 'ground');
            const popup = `<div class="popup-custom">
                <h3>${cs}</h3>
                <p><b>ICAO:</b> ${ac.icao}</p>
                <p><b>ALT:</b> ${alt} m · <b>SPD:</b> ${spd} km/h</p>
                <p><b>HDG:</b> ${hdg} · <b>SRC:</b> GROUND_SDR</p>
            </div>`;

            if (aircraftMarkers[ac.icao]) {
                aircraftMarkers[ac.icao].setLatLng([ac.latitude, ac.longitude]);
                aircraftMarkers[ac.icao].setIcon(icon);
                aircraftMarkers[ac.icao].getPopup().setContent(popup);
            } else {
                aircraftMarkers[ac.icao] = L.marker([ac.latitude, ac.longitude], { icon })
                    .bindPopup(popup).addTo(map);
            }
        }
    });

    // ── CubeSat-only aircraft ──
    if (data.cubesat_aircraft) {
        data.cubesat_aircraft.forEach(ac => {
            if (!currentIcaos.has(ac.icao) && ac.latitude && ac.longitude) {
                currentIcaos.add(ac.icao);
                const icon = createPlaneIcon(ac.heading, false, 'cubesat');
                const popup = `<div class="popup-custom">
                    <h3>${ac.callsign || '---'}</h3>
                    <p><b>ICAO:</b> ${ac.icao}</p>
                    <p><b>ALT:</b> ${Math.round((ac.altitude||0)*0.3048)} m · <b>SRC:</b> CUBESAT_TM</p>
                </div>`;

                if (aircraftMarkers[ac.icao]) {
                    aircraftMarkers[ac.icao].setLatLng([ac.latitude, ac.longitude]);
                    aircraftMarkers[ac.icao].setIcon(icon);
                    aircraftMarkers[ac.icao].getPopup().setContent(popup);
                } else {
                    aircraftMarkers[ac.icao] = L.marker([ac.latitude, ac.longitude], { icon })
                        .bindPopup(popup).addTo(map);
                }
            }
        });
    }

    // ── CubeSat Health Panel ──
    const h = data.cubesat_health;
    if (h && Object.keys(h).length > 0 && h.status !== 'OFFLINE') {
        document.getElementById('cs-status').className = 'cs-badge online';
        document.getElementById('cs-status').textContent = 'ONLINE';
        document.getElementById('cs-vbat').textContent = h.vbat !== undefined ? h.vbat.toFixed(2) : '--.--';
        document.getElementById('cs-temp').textContent = h.temp !== undefined ? h.temp.toFixed(1) : '--.-';
        document.getElementById('cs-pitch').textContent = h.pitch !== undefined ? h.pitch.toFixed(1) : '--.-';
        document.getElementById('cs-roll').textContent = h.roll !== undefined ? h.roll.toFixed(1) : '--.-';
    } else {
        document.getElementById('cs-status').className = 'cs-badge offline';
        document.getElementById('cs-status').textContent = 'OFFLINE';
        document.getElementById('cs-vbat').textContent = '--.--';
        document.getElementById('cs-temp').textContent = '--.-';
        document.getElementById('cs-pitch').textContent = '--.-';
        document.getElementById('cs-roll').textContent = '--.-';
    }

    // Limpiar marcadores expirados
    Object.keys(aircraftMarkers).forEach(icao => {
        if (!currentIcaos.has(icao)) {
            map.removeLayer(aircraftMarkers[icao]);
            delete aircraftMarkers[icao];
        }
    });
}

// ─── Exportación CSV ────────────────────────────────────────────────────────
document.getElementById('btn-export').addEventListener('click', () => {
    if (!aircraftDataCache.length) { alert('No hay datos para exportar.'); return; }

    let csv = 'data:text/csv;charset=utf-8,';
    csv += 'ICAO,Callsign,Alt(m),Spd(km/h),Hdg(deg),Lat,Lon,Age(s)\n';

    aircraftDataCache.forEach(ac => {
        const alt = ac.altitude !== null ? Math.round(ac.altitude * 0.3048) : '';
        const spd = ac.speed !== null ? Math.round(ac.speed * 1.852) : '';
        const hdg = ac.heading !== null ? Math.round(ac.heading) : '';
        const lat = ac.latitude ?? '';
        const lon = ac.longitude ?? '';
        csv += `${ac.icao},${ac.callsign||''},${alt},${spd},${hdg},${lat},${lon},${Math.round(ac.age)}\n`;
    });

    const a = document.createElement('a');
    a.href = encodeURI(csv);
    a.download = `litoral_radar_${Date.now()}.csv`;
    document.body.appendChild(a); a.click(); document.body.removeChild(a);
});

// ─── Geolocalización ────────────────────────────────────────────────────────
document.getElementById('btn-geolocate').addEventListener('click', () => {
    if (!navigator.geolocation) { alert('Geolocalización no soportada.'); return; }

    const label = document.querySelector('#btn-geolocate .btn-label');
    label.textContent = '...';

    navigator.geolocation.getCurrentPosition(
        pos => {
            const { latitude: lat, longitude: lon } = pos.coords;
            map.flyTo([lat, lon], 10);
            baseMarker.setLatLng([lat, lon]);
            baseMarker.getPopup().setContent(
                "<div class='popup-custom'><h3>BASE TERRENA</h3><p>Ubicación detectada</p></div>"
            );
            label.textContent = 'LOCATE';
        },
        err => {
            console.error('Geolocation error:', err);
            label.textContent = 'LOCATE';
            // No mostramos alert() — simplemente logueamos y reseteamos el botón.
            // El usuario puede reintentar inmediatamente.
        },
        { enableHighAccuracy: false, timeout: 20000, maximumAge: 60000 }
    );
});

// ─── Iniciar ────────────────────────────────────────────────────────────────
setInterval(updateRadarData, 1000);
updateRadarData();
