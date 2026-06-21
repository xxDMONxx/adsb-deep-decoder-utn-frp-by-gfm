// Coordenadas Iniciales (Aprox centro de Argentina/Santa Fe)
const MAP_CENTER = [-31.6333, -60.7000]; // Latitud/Longitud de UTN-FRP o Santa Fe
const MAP_ZOOM = 6;

// Inicializar Mapa
const map = L.map('map', {
    zoomControl: false
}).setView(MAP_CENTER, MAP_ZOOM);

L.control.zoom({ position: 'bottomright' }).addTo(map);

// Capa Base: CartoDB Dark Matter (Estilo oscuro y limpio)
L.tileLayer('https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png', {
    attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OSM</a> &copy; <a href="https://carto.com/attributions">CARTO</a>',
    subdomains: 'abcd',
    maxZoom: 20
}).addTo(map);

// Marcador de la antena (Radar)
const radarIcon = L.divIcon({
    className: 'radar-center-icon',
    html: '<div style="width:12px; height:12px; background:#10b981; border-radius:50%; border:2px solid #fff; box-shadow:0 0 10px #10b981;"></div>',
    iconSize: [12, 12],
    iconAnchor: [6, 6]
});
L.marker(MAP_CENTER, { icon: radarIcon }).addTo(map).bindPopup("<b>Estación Terrena Litoral 26</b><br>UTN-FRP");

// Variables globales
let aircraftMarkers = {};
let aircraftDataCache = [];

// Ícono de avión SVG dinámico
function createPlaneIcon(heading, isLost) {
    const color = isLost ? '#f59e0b' : '#3b82f6';
    const svg = `
        <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" width="28" height="28" style="transform: rotate(${heading || 0}deg);">
            <path d="M21,16V14L13,9V3.5A1.5,1.5 0 0,0 11.5,2A1.5,1.5 0 0,0 10,3.5V9L2,14V16L10,13.5V19L8,20.5V22L11.5,21L15,22V20.5L13,19V13.5L21,16Z" fill="${color}" stroke="#fff" stroke-width="1"/>
        </svg>
    `;
    return L.divIcon({
        className: 'plane-icon',
        html: svg,
        iconSize: [28, 28],
        iconAnchor: [14, 14],
        popupAnchor: [0, -14]
    });
}

// Función principal de actualización (Polling)
async function updateRadarData() {
    try {
        // Agregamos un query param aleatorio para evitar caché del navegador
        const response = await fetch(`data.json?t=${new Date().getTime()}`);
        if (!response.ok) throw new Error("No data");
        
        const data = await response.json();
        processData(data);
        
        document.getElementById('conn-status').textContent = '● LIVE';
        document.getElementById('conn-status').className = 'status-indicator online';
    } catch (err) {
        console.error("Error obteniendo datos del radar:", err);
        document.getElementById('conn-status').textContent = '● OFFLINE';
        document.getElementById('conn-status').className = 'status-indicator offline';
    }
}

function processData(data) {
    aircraftDataCache = data.aircraft || [];
    
    // Estadísticas
    const activeCount = aircraftDataCache.filter(ac => ac.age < 60).length;
    document.getElementById('stat-active').textContent = activeCount;
    document.getElementById('stat-msg').textContent = data.stats.total_received;

    // Actualizar Tabla
    const tbody = document.getElementById('aircraft-list');
    tbody.innerHTML = '';
    
    // Lista de ICAOs en este frame para eliminar marcadores obsoletos
    const currentIcaos = new Set();

    aircraftDataCache.forEach(ac => {
        currentIcaos.add(ac.icao);
        
        // --- 1. Tabla ---
        let statusClass = "ac-dead";
        let statusText = "DEAD";
        if (ac.age < 30) { statusClass = "ac-live"; statusText = "LIVE"; }
        else if (ac.age < 120) { statusClass = "ac-lost"; statusText = "LOST"; }

        const tr = document.createElement('tr');
        tr.innerHTML = `
            <td><b>${ac.callsign || '---'}</b></td>
            <td>${ac.icao}</td>
            <td>${ac.altitude !== null ? Math.round(ac.altitude * 0.3048) : '---'}</td>
            <td>${ac.speed !== null ? Math.round(ac.speed * 1.852) : '---'}</td>
            <td class="${statusClass}">${statusText}</td>
        `;
        
        // Al hacer click en la tabla, centrar el mapa
        tr.addEventListener('click', () => {
            if (ac.latitude && ac.longitude) {
                map.setView([ac.latitude, ac.longitude], 10);
                if (aircraftMarkers[ac.icao]) {
                    aircraftMarkers[ac.icao].openPopup();
                }
            }
        });
        tbody.appendChild(tr);

        // --- 2. Mapa ---
        if (ac.latitude && ac.longitude) {
            const isLost = ac.age > 30;
            const icon = createPlaneIcon(ac.heading, isLost);
            
            const popupContent = `
                <div class="popup-custom">
                    <h3>✈️ ${ac.callsign || 'Desconocido'}</h3>
                    <p><b>ICAO:</b> ${ac.icao}</p>
                    <p><b>Altitud:</b> ${Math.round(ac.altitude * 0.3048)} m</p>
                    <p><b>Velocidad:</b> ${Math.round(ac.speed * 1.852)} km/h</p>
                    <p><b>Rumbo:</b> ${ac.heading ? Math.round(ac.heading) + '°' : '---'}</p>
                </div>
            `;

            if (aircraftMarkers[ac.icao]) {
                // Actualizar marcador existente (suavidad)
                aircraftMarkers[ac.icao].setLatLng([ac.latitude, ac.longitude]);
                aircraftMarkers[ac.icao].setIcon(icon);
                aircraftMarkers[ac.icao].getPopup().setContent(popupContent);
            } else {
                // Crear nuevo marcador
                const marker = L.marker([ac.latitude, ac.longitude], { icon: icon })
                    .bindPopup(popupContent)
                    .addTo(map);
                aircraftMarkers[ac.icao] = marker;
            }
        }
    });

    // Limpiar marcadores viejos del mapa
    Object.keys(aircraftMarkers).forEach(icao => {
        if (!currentIcaos.has(icao)) {
            map.removeLayer(aircraftMarkers[icao]);
            delete aircraftMarkers[icao];
        }
    });
}

// Lógica de Exportación CSV
document.getElementById('btn-export').addEventListener('click', () => {
    if (aircraftDataCache.length === 0) {
        alert("No hay datos para exportar.");
        return;
    }

    let csvContent = "data:text/csv;charset=utf-8,";
    csvContent += "ICAO,Vuelo,Altitud(m),Velocidad(km/h),Rumbo(deg),Latitud,Longitud,UltimaVez(s)\n";

    aircraftDataCache.forEach(ac => {
        const alt = ac.altitude !== null ? Math.round(ac.altitude * 0.3048) : '';
        const spd = ac.speed !== null ? Math.round(ac.speed * 1.852) : '';
        const hdg = ac.heading !== null ? Math.round(ac.heading) : '';
        const lat = ac.latitude !== null ? ac.latitude : '';
        const lon = ac.longitude !== null ? ac.longitude : '';
        const row = `${ac.icao},${ac.callsign || ''},${alt},${spd},${hdg},${lat},${lon},${Math.round(ac.age)}`;
        csvContent += row + "\n";
    });

    const encodedUri = encodeURI(csvContent);
    const link = document.createElement("a");
    link.setAttribute("href", encodedUri);
    link.setAttribute("download", `litoral_radar_export_${new Date().getTime()}.csv`);
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
});

// Lógica de Mi Ubicación (Geolocalización)
let userLocationMarker = null;

document.getElementById('btn-geolocate').addEventListener('click', () => {
    if (!navigator.geolocation) {
        alert("Tu navegador no soporta geolocalización.");
        return;
    }
    
    document.getElementById('btn-geolocate').textContent = "📍 Ubicando...";
    
    navigator.geolocation.getCurrentPosition(
        (position) => {
            const lat = position.coords.latitude;
            const lon = position.coords.longitude;
            
            map.flyTo([lat, lon], 10);
            
            if (userLocationMarker) {
                userLocationMarker.setLatLng([lat, lon]);
            } else {
                userLocationMarker = L.circleMarker([lat, lon], {
                    radius: 6,
                    fillColor: "#3b82f6",
                    color: "#ffffff",
                    weight: 2,
                    opacity: 1,
                    fillOpacity: 1
                }).addTo(map).bindPopup("<b>Mi Ubicación</b>");
            }
            document.getElementById('btn-geolocate').textContent = "📍 Mi Ubicación";
        },
        (error) => {
            console.error("Error obteniendo ubicación:", error);
            alert("No se pudo obtener la ubicación. Revisá los permisos del navegador.");
            document.getElementById('btn-geolocate').textContent = "📍 Mi Ubicación";
        },
        { enableHighAccuracy: true, timeout: 5000 }
    );
});

// Iniciar Polling a 1 FPS
setInterval(updateRadarData, 1000);
updateRadarData();
