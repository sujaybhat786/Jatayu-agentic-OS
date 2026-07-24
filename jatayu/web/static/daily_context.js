/**
 * JATAYU OS — Daily Context Bar Controller
 * Fetches and renders situational environment awareness (Weather)
 */

async function initDailyContextBar() {
    const containers = document.querySelectorAll('.daily-context-bar');
    if (!containers || containers.length === 0) return;

    try {
        const resp = await fetch('/api/daily-context');
        if (!resp.ok) {
            containers.forEach(el => el.classList.add('hidden'));
            return;
        }

        const data = await resp.json();
        if (!data || !data.has_content) {
            containers.forEach(el => el.classList.add('hidden'));
            return;
        }

        const html = renderDailyContextHTML(data);
        containers.forEach(el => {
            el.innerHTML = html;
            el.classList.remove('hidden');
        });

    } catch (err) {
        console.warn('DailyContextBar fetch failed:', err);
        containers.forEach(el => el.classList.add('hidden'));
    }
}

function renderDailyContextHTML(data) {
    const items = [];

    // Date
    if (data.date_formatted) {
        items.push(`
            <div class="dc-item">
                <span class="dc-icon">📅</span>
                <span class="dc-value">${escapeHTML(data.date_formatted)}</span>
            </div>
        `);
    }

    // Weather main
    const w = data.weather;
    if (w) {
        items.push(`
            <div class="dc-item">
                <span class="dc-icon">${w.icon || '🌤'}</span>
                <span class="dc-value">${escapeHTML(w.city)} ${w.temp_c}°C</span>
                <span class="dc-label">${escapeHTML(w.condition)}</span>
            </div>
        `);

        // High / Low
        items.push(`
            <div class="dc-item">
                <span class="dc-icon">🌡</span>
                <span class="dc-label">H:</span><span class="dc-value">${w.high_c}°C</span>
                <span class="dc-label">L:</span><span class="dc-value">${w.low_c}°C</span>
            </div>
        `);

        // Humidity
        if (w.humidity !== undefined) {
            items.push(`
                <div class="dc-item">
                    <span class="dc-icon">💧</span>
                    <span class="dc-label">Humidity</span>
                    <span class="dc-value">${w.humidity}%</span>
                </div>
            `);
        }

        // Wind Speed
        if (w.wind_kmh !== undefined) {
            items.push(`
                <div class="dc-item">
                    <span class="dc-icon">💨</span>
                    <span class="dc-label">Wind</span>
                    <span class="dc-value">${w.wind_kmh} km/h</span>
                </div>
            `);
        }

        // Sunrise & Sunset
        if (w.sunrise) {
            items.push(`
                <div class="dc-item">
                    <span class="dc-icon">☀</span>
                    <span class="dc-label">Sunrise</span>
                    <span class="dc-value">${escapeHTML(w.sunrise)}</span>
                </div>
            `);
        }

        if (w.sunset) {
            items.push(`
                <div class="dc-item">
                    <span class="dc-icon">🌇</span>
                    <span class="dc-label">Sunset</span>
                    <span class="dc-value">${escapeHTML(w.sunset)}</span>
                </div>
            `);
        }
    }

    return items.join('<div class="dc-sep"></div>');
}

function escapeHTML(str) {
    if (!str) return '';
    return String(str)
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;');
}

// Global initialization hook
window.initDailyContextBar = initDailyContextBar;
