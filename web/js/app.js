/**
 * LITORAL-RADAR-FRP — Frontend Application Logic
 * ================================================
 * Polling data.json cada 1s, renderiza tabla y mapa Leaflet.
 * Integra datos de estación terrena (GND/SDR) y CubeSat (SAT).
 */

// ─── Config ─────────────────────────────────────────────────────────────────
const MAP_CENTER = [-31.6333, -60.7000];
const MAP_ZOOM = 6;

const map = L.map('map', { zoomControl: false }).setView(MAP_CENTER, MAP_ZOOM);
L.control.zoom({ position: 'bottomright' }).addTo(map);

L.tileLayer('https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png', {
    attribution: '&copy; OSM &copy; CARTO',
    subdomains: 'abcd',
    maxZoom: 20
}).addTo(map);

// ─── Base Terrena ───────────────────────────────────────────────────────────
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

// ─── Icono SVG ──────────────────────────────────────────────────────────────
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

// ─── Polling ────────────────────────────────────────────────────────────────
async function updateRadarData() {
    try {
        const res = await fetch(`data.json?t=${Date.now()}`);
        if (!res.ok) throw new Error('No data');
        processData(await res.json());
        document.getElementById('conn-status').textContent = 'SYS.ONLINE';
        document.getElementById('conn-status').className = 'status-led online';
    } catch (e) {
        console.error('Radar fetch error:', e);
        document.getElementById('conn-status').textContent = 'SYS.OFFLINE';
        document.getElementById('conn-status').className = 'status-led offline';
    }
}

// ─── Process Data ───────────────────────────────────────────────────────────
function processData(data) {
    const mergedAircraft = new Map();

    // Add ground aircraft
    if (data.aircraft) {
        data.aircraft.forEach(ac => {
            mergedAircraft.set(ac.icao, {
                ...ac,
                source: 'GND'
            });
        });
    }

    // Add/merge cubesat aircraft
    if (data.cubesat_aircraft) {
        data.cubesat_aircraft.forEach(ac => {
            if (mergedAircraft.has(ac.icao)) {
                const existing = mergedAircraft.get(ac.icao);
                // Keep whichever has lower age (more recent/live)
                const newer = ac.age < existing.age ? ac : existing;
                mergedAircraft.set(ac.icao, {
                    ...existing,
                    ...newer,
                    source: 'BOTH'
                });
            } else {
                mergedAircraft.set(ac.icao, {
                    ...ac,
                    source: 'SAT'
                });
            }
        });
    }

    aircraftDataCache = Array.from(mergedAircraft.values());

    const active = aircraftDataCache.filter(a => a.age < 60).length;
    document.getElementById('stat-active').textContent = active.toString().padStart(3, '0');
    document.getElementById('stat-msg').textContent = data.stats.total_received.toString().padStart(5, '0');
    document.getElementById('table-count').textContent = `${aircraftDataCache.length} targets`;

    const tbody = document.getElementById('aircraft-list');
    tbody.innerHTML = '';
    const currentIcaos = new Set();

    aircraftDataCache.forEach(ac => {
        currentIcaos.add(ac.icao);

        let statusClass = 'ac-dead', statusText = 'DEAD';
        if (ac.age < 30)       { statusClass = 'ac-live'; statusText = 'LIVE'; }
        else if (ac.age < 120) { statusClass = 'ac-lost'; statusText = 'LOST'; }

        const tr = document.createElement('tr');
        const cs  = ac.callsign || '---';
        const alt = ac.altitude !== null ? Math.round(ac.altitude * 0.3048) : '---';
        const spd = ac.speed !== null ? Math.round(ac.speed * 1.852) : '---';
        const hdg = ac.heading !== null ? Math.round(ac.heading) + '°' : '---';
        const lat = ac.latitude !== null ? ac.latitude.toFixed(4) : '---';
        const lon = ac.longitude !== null ? ac.longitude.toFixed(4) : '---';

        let srcClass = 'src-gnd';
        if (ac.source === 'SAT') srcClass = 'src-sat';
        else if (ac.source === 'BOTH') srcClass = 'src-both';

        tr.innerHTML = `
            <td>${cs}</td>
            <td>${ac.icao}</td>
            <td>${alt}</td>
            <td>${spd}</td>
            <td>${hdg}</td>
            <td>${lat}, ${lon}</td>
            <td><span class="${srcClass}">${ac.source}</span></td>
            <td class="${statusClass}">${statusText}</td>
        `;

        tr.addEventListener('click', () => {
            if (ac.latitude && ac.longitude) {
                map.setView([ac.latitude, ac.longitude], 10);
                if (aircraftMarkers[ac.icao]) aircraftMarkers[ac.icao].openPopup();
            }
        });
        tbody.appendChild(tr);

        // Solo mostramos en el mapa aviones LIVE (age < 30s)
        if (ac.latitude && ac.longitude && ac.age < 30) {
            const iconType = ac.source === 'SAT' ? 'cubesat' : 'ground';
            const icon = createPlaneIcon(ac.heading, false, iconType);
            
            const srcText = ac.source === 'SAT' ? 'CUBESAT' : (ac.source === 'BOTH' ? 'GND + SAT' : 'GROUND_SDR');
            const popup = `<div class="popup-custom">
                <h3>${cs}</h3>
                <p><b>ICAO:</b> ${ac.icao}</p>
                <p><b>ALT:</b> ${alt} m · <b>SPD:</b> ${spd} km/h</p>
                <p><b>HDG:</b> ${hdg} · <b>SRC:</b> ${srcText}</p>
            </div>`;

            if (aircraftMarkers[ac.icao]) {
                aircraftMarkers[ac.icao].setLatLng([ac.latitude, ac.longitude]);
                aircraftMarkers[ac.icao].setIcon(icon);
                aircraftMarkers[ac.icao].getPopup().setContent(popup);
            } else {
                aircraftMarkers[ac.icao] = L.marker([ac.latitude, ac.longitude], { icon })
                    .bindPopup(popup).addTo(map);
            }
        } else if (aircraftMarkers[ac.icao]) {
            // Avión LOST/DEAD o sin posición válida → eliminamos del mapa
            map.removeLayer(aircraftMarkers[ac.icao]);
            delete aircraftMarkers[ac.icao];
        }
    });

    // CubeSat Health
    const h = data.cubesat_health;
    if (h && Object.keys(h).length > 0 && h.status !== 'OFFLINE') {
        document.getElementById('cs-status').className = 'cs-badge online';
        document.getElementById('cs-status').textContent = 'ONLINE';
        document.getElementById('cs-vbat').textContent  = h.vbat  !== undefined ? h.vbat.toFixed(2) : '--.--';
        document.getElementById('cs-temp').textContent   = h.temp  !== undefined ? h.temp.toFixed(1) : '--.-';
        document.getElementById('cs-pitch').textContent  = h.pitch !== undefined ? h.pitch.toFixed(1) : '--.-';
        document.getElementById('cs-roll').textContent   = h.roll  !== undefined ? h.roll.toFixed(1) : '--.-';
    } else {
        document.getElementById('cs-status').className = 'cs-badge offline';
        document.getElementById('cs-status').textContent = 'OFFLINE';
        document.getElementById('cs-vbat').textContent = '--.--';
        document.getElementById('cs-temp').textContent = '--.-';
        document.getElementById('cs-pitch').textContent = '--.-';
        document.getElementById('cs-roll').textContent = '--.-';
    }

    // Cleanup
    Object.keys(aircraftMarkers).forEach(icao => {
        if (!currentIcaos.has(icao)) {
            map.removeLayer(aircraftMarkers[icao]);
            delete aircraftMarkers[icao];
        }
    });
}

// ─── CSV Export ─────────────────────────────────────────────────────────────
document.getElementById('btn-export').addEventListener('click', () => {
    if (!aircraftDataCache.length) { alert('No hay datos para exportar.'); return; }
    let csv = 'data:text/csv;charset=utf-8,ICAO,Callsign,Alt(m),Spd(km/h),Hdg,Lat,Lon,Age(s)\n';
    aircraftDataCache.forEach(ac => {
        csv += `${ac.icao},${ac.callsign||''},${ac.altitude!==null?Math.round(ac.altitude*0.3048):''},${ac.speed!==null?Math.round(ac.speed*1.852):''},${ac.heading!==null?Math.round(ac.heading):''},${ac.latitude??''},${ac.longitude??''},${Math.round(ac.age)}\n`;
    });
    const a = document.createElement('a');
    a.href = encodeURI(csv);
    a.download = `litoral_radar_${Date.now()}.csv`;
    document.body.appendChild(a); a.click(); document.body.removeChild(a);
});

// ─── Geolocation ────────────────────────────────────────────────────────────
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
        },
        { enableHighAccuracy: false, timeout: 20000, maximumAge: 60000 }
    );
});

// ─── Start ──────────────────────────────────────────────────────────────────
setInterval(updateRadarData, 1000);
updateRadarData();
