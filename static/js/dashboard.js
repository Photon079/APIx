/**
 * Vayu Dashboard — Data-focused charts and live pipeline interaction
 */

Chart.defaults.color = '#7a8499';
Chart.defaults.borderColor = '#2a3142';
Chart.defaults.font.family = "'IBM Plex Sans', sans-serif";
Chart.defaults.font.size = 11;
Chart.defaults.plugins.legend.labels.usePointStyle = true;
Chart.defaults.plugins.legend.labels.pointStyleWidth = 8;
Chart.defaults.plugins.legend.labels.padding = 16;
Chart.defaults.animation.duration = 400;

let trendChart = null;
let validationChart = null;
let ws = null;

document.addEventListener('DOMContentLoaded', async () => {
    await Promise.all([
        loadTrendChart(),
        loadValidationChart(),
        loadRouteBreakdown(),
        loadPipelineStats(),
        loadScrapeLog(),
    ]);
    initWebSocket();
});

// ─── Trend Chart ───────────────────────────────────────────────────────
async function loadTrendChart() {
    try {
        const res = await fetch('/api/index/history');
        const json = await res.json();
        if (json.status !== 'ok' || !json.data.length) return;

        const data = json.data;
        const labels = data.map(d => fmtDate(d.date));
        const values = data.map(d => d.vayu_value);

        // Fetch 3-Day ML Projections
        let projectionData = [];
        try {
            const projRes = await fetch('/api/index/projection');
            const projJson = await projRes.json();
            if (projJson.status === 'ok') {
                projectionData = projJson.projections;
            }
        } catch (e) {}

        const fullLabels = [...labels];
        const historicalValues = [...values];
        const projectedValues = new Array(values.length - 1).fill(null);
        projectedValues.push(values[values.length - 1]); // Connect last historical point

        projectionData.forEach(p => {
            fullLabels.push(fmtDate(p.date) + ' (Proj)');
            historicalValues.push(null);
            projectedValues.push(p.projected_vayu);
        });

        const ctx = document.getElementById('trendChart');
        if (!ctx) return;

        if (trendChart) trendChart.destroy();

        trendChart = new Chart(ctx, {
            type: 'line',
            data: {
                labels: fullLabels,
                datasets: [
                    {
                        label: 'Vayu (Historical)',
                        data: historicalValues,
                        borderColor: '#4a9eff',
                        backgroundColor: 'rgba(74, 158, 255, 0.06)',
                        borderWidth: 2,
                        fill: true,
                        tension: 0.3,
                        pointRadius: 0,
                        pointHoverRadius: 4,
                    },
                    {
                        label: '3-Day ML Projection',
                        data: projectedValues,
                        borderColor: '#ffab40',
                        borderWidth: 2,
                        borderDash: [5, 4],
                        fill: false,
                        tension: 0.3,
                        pointRadius: 3,
                        pointBackgroundColor: '#ffab40',
                    }
                ],
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                interaction: { mode: 'index', intersect: false },
                plugins: {
                    legend: { display: true, position: 'top', align: 'end' },
                    tooltip: {
                        backgroundColor: '#1a1f2e',
                        borderColor: '#2a3142',
                        borderWidth: 1,
                        cornerRadius: 4,
                        padding: 10,
                        titleFont: { weight: '600', size: 12 },
                        bodyFont: { family: "'IBM Plex Mono'", size: 13 },
                        displayColors: false,
                    },
                },
                scales: {
                    x: {
                        grid: { display: false },
                        ticks: { maxTicksLimit: 10, font: { size: 10 } },
                    },
                    y: {
                        grid: { color: '#1e2433' },
                        ticks: {
                            font: { family: "'IBM Plex Mono'", size: 10 },
                            callback: v => v.toFixed(1),
                        },
                    },
                },
            },
        });
    } catch (err) {
        console.error('Trend chart error:', err);
    }
}

// ─── Validation Chart ──────────────────────────────────────────────────
async function loadValidationChart() {
    try {
        const res = await fetch('/api/validation');
        const json = await res.json();
        if (json.status !== 'ok') return;

        const { series, r_squared } = json.data;
        if (!series.dates.length) return;

        const labels = series.dates.map(d => fmtDate(d));

        const badge = document.getElementById('correlation-badge');
        if (badge) badge.textContent = `R² = ${r_squared.toFixed(4)}`;

        const ctx = document.getElementById('validationChart');
        if (!ctx) return;

        if (validationChart) validationChart.destroy();

        validationChart = new Chart(ctx, {
            type: 'line',
            data: {
                labels,
                datasets: [
                    {
                        label: 'Vayu (Computed)',
                        data: series.vayu,
                        borderColor: '#4a9eff',
                        backgroundColor: 'transparent',
                        borderWidth: 2,
                        tension: 0.3,
                        pointRadius: 0,
                        pointHoverRadius: 3,
                        yAxisID: 'y',
                    },
                    {
                        label: 'DGCA Avg Fare (₹)',
                        data: series.dgca_fare,
                        borderColor: '#ff5252',
                        backgroundColor: 'transparent',
                        borderWidth: 1.5,
                        borderDash: [4, 3],
                        tension: 0.3,
                        pointRadius: 0,
                        pointHoverRadius: 3,
                        yAxisID: 'y1',
                    },
                ],
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                interaction: { mode: 'index', intersect: false },
                plugins: {
                    legend: { position: 'top', align: 'end' },
                    tooltip: {
                        backgroundColor: '#1a1f2e',
                        borderColor: '#2a3142',
                        borderWidth: 1,
                        cornerRadius: 4,
                        padding: 10,
                        bodyFont: { family: "'IBM Plex Mono'", size: 12 },
                        callbacks: {
                            label: (item) => item.datasetIndex === 0
                                ? `Vayu: ${item.raw.toFixed(2)}`
                                : `DGCA: ₹${item.raw.toLocaleString('en-IN')}`,
                        },
                    },
                },
                scales: {
                    x: {
                        grid: { display: false },
                        ticks: { maxTicksLimit: 8, font: { size: 10 } },
                    },
                    y: {
                        position: 'left',
                        title: { display: true, text: 'Vayu', font: { size: 11, weight: '600' }, color: '#4a9eff' },
                        grid: { color: '#1e2433' },
                        ticks: { font: { family: "'IBM Plex Mono'", size: 10 }, color: '#4a9eff' },
                    },
                    y1: {
                        position: 'right',
                        title: { display: true, text: 'DGCA Fare (₹)', font: { size: 11, weight: '600' }, color: '#ff5252' },
                        grid: { drawOnChartArea: false },
                        ticks: {
                            font: { family: "'IBM Plex Mono'", size: 10 },
                            color: '#ff5252',
                            callback: v => '₹' + v.toLocaleString('en-IN'),
                        },
                    },
                },
            },
        });
    } catch (err) {
        console.error('Validation chart error:', err);
    }
}

// ─── Route Breakdown, Rule 135 & HHI ───────────────────────────────────
async function loadRouteBreakdown() {
    try {
        const res = await fetch('/api/routes/breakdown');
        const json = await res.json();
        if (json.status !== 'ok') return;
        renderRouteBreakdownDOM(json.data);
    } catch (err) {
        console.error('Route breakdown error:', err);
    }
}

function renderRouteBreakdownDOM(routes) {
    if (!routes) return;
    Object.entries(routes).forEach(([route, info]) => {
        // Fare display
        const fareEl = document.getElementById(`fare-${route}`);
        if (fareEl) fareEl.textContent = `INR ${Math.round(info.current_fare).toLocaleString('en-IN')}`;

        // Rule 135 compliance badge & heatmap styling
        const badgeEl = document.getElementById(`badge-${route}`);
        if (badgeEl) {
            if (info.rule_135_compliant) {
                badgeEl.className = 'badge-status compliant bg-green-900';
                badgeEl.textContent = 'COMPLIANT';
            } else {
                badgeEl.className = 'badge-status breach bg-red-900';
                badgeEl.textContent = `RULE 135 BREACH (${info.rule_135_breaches} flights)`;
            }
        }

        // HHI score and status meter & heatmap styling
        const hhiScoreEl = document.getElementById(`hhi-score-${route}`);
        if (hhiScoreEl) hhiScoreEl.textContent = info.hhi_score;

        const hhiStatusEl = document.getElementById(`hhi-status-${route}`);
        if (hhiStatusEl) {
            let heatClass = 'bg-green-900';
            if (info.hhi_score > 2500 || !info.rule_135_compliant) heatClass = 'bg-red-900';
            else if (info.hhi_score >= 1500) heatClass = 'bg-yellow-900';

            hhiStatusEl.className = `hhi-meter ${info.hhi_level} ${heatClass}`;
            hhiStatusEl.textContent = `HHI: ${info.hhi_score} (${info.hhi_status})`;
        }

        const hhiSharesEl = document.getElementById(`hhi-shares-${route}`);
        if (hhiSharesEl && info.hhi_shares) {
            const sharesStr = Object.entries(info.hhi_shares)
                .map(([k, v]) => `${k} ${v}%`)
                .join(', ');
            if (sharesStr) hhiSharesEl.textContent = sharesStr;
        }

        // Sparkline chart
        const sparkEl = document.getElementById(`spark-${route}`);
        if (sparkEl && info.sparkline && info.sparkline.length > 1) {
            const isUp = info.sparkline[info.sparkline.length - 1] >= info.sparkline[0];
            new Chart(sparkEl, {
                type: 'line',
                data: {
                    labels: info.sparkline.map((_, i) => i),
                    datasets: [{
                        data: info.sparkline,
                        borderColor: isUp ? '#00c853' : '#ff5252',
                        borderWidth: 1.5,
                        fill: false,
                        tension: 0.4,
                        pointRadius: 0,
                    }],
                },
                options: {
                    responsive: true,
                    maintainAspectRatio: false,
                    plugins: { legend: { display: false }, tooltip: { enabled: false } },
                    scales: { x: { display: false }, y: { display: false } },
                    animation: false,
                },
            });
        }
    });
}

// ─── Pipeline Stats ────────────────────────────────────────────────────
async function loadPipelineStats() {
    try {
        const res = await fetch('/api/pipeline/stats');
        const json = await res.json();
        if (json.status !== 'ok') return;
        const d = json.data;
        setText('stat-records', d.index_records || 0);
        setText('stat-cleaned', d.cleaner?.cleaned || d.cleaner?.total_db_fares || 0);
        setText('stat-outliers', d.cleaner?.dropped_outlier || 0);
        setText('stat-persisted', d.scraper?.persisted_files || 0);

        // Update Telemetry Page Pipeline Cards
        setText('telemetry-cleaned', d.cleaner?.cleaned || d.cleaner?.total_db_fares || 0);
        setText('telemetry-dupes', d.cleaner?.dropped_duplicate || 0);
        setText('telemetry-outliers', d.cleaner?.dropped_outlier || 0);
        setText('telemetry-invalid', d.cleaner?.dropped_invalid || 0);
    } catch (err) {}
}

// ─── Scrape Log ────────────────────────────────────────────────────────
async function loadScrapeLog() {
    try {
        const res = await fetch('/api/scrape/log');
        const json = await res.json();
        if (json.status !== 'ok') return;

        const list = document.getElementById('scrape-log');
        if (!list) return;

        if (json.data.length === 0) {
            list.innerHTML = '<li style="color:var(--text-3);font-size:12px;padding:8px 0;">No scrape activity yet. Click "Run Scrape" to start.</li>';
            return;
        }

        list.innerHTML = json.data.map(entry => `
            <li class="log-item">
                <span class="log-time">${entry.time}</span>
                <span class="log-route">${entry.route}</span>
                <span class="log-detail">${entry.mode} — ${entry.detail}</span>
                <span class="log-count">${entry.fares} fares</span>
            </li>
        `).join('');
    } catch (err) {}
}

// ─── Scrape Trigger ────────────────────────────────────────────────────
async function triggerScrape() {
    const btn = document.getElementById('btn-scrape');
    if (!btn || btn.classList.contains('loading')) return;

    btn.classList.add('loading');
    showToast('Scraping flight sources...', 'info');

    try {
        const res = await fetch('/api/scrape');
        const json = await res.json();

        if (json.status === 'ok') {
            showToast(`${json.message} | Mode: ${json.scraper_mode}`, 'success');

            if (json.index) {
                updateHero(json.index.vayu_value, json.index.daily_change_pct);
            }

            await Promise.all([
                loadTrendChart(),
                loadValidationChart(),
                loadRouteBreakdown(),
                loadPipelineStats(),
                loadScrapeLog(),
            ]);
        } else {
            showToast(`Scrape failed: ${json.message}`, 'error');
        }
    } catch (err) {
        showToast(`Error: ${err.message}`, 'error');
    } finally {
        btn.classList.remove('loading');
    }
}

// ─── WebSocket ─────────────────────────────────────────────────────────
function initWebSocket() {
    const protocol = location.protocol === 'https:' ? 'wss:' : 'ws:';
    try {
        ws = new WebSocket(`${protocol}//${location.host}/ws/live`);
        ws.onmessage = (e) => {
            const msg = JSON.parse(e.data);
            if (msg.type === 'index_update') {
                const d = msg.data;
                if (d.index) {
                    updateHero(d.index.vayu_value, d.index.daily_change_pct);
                } else if (d.vayu_value !== undefined) {
                    updateHero(d.vayu_value, d.daily_change_pct);
                }

                if (d.elasticity && d.elasticity.badge_text) {
                    const elBadge = document.getElementById('elasticity-badge');
                    if (elBadge) elBadge.textContent = d.elasticity.badge_text;
                }

                if (d.routes) {
                    renderRouteBreakdownDOM(d.routes);
                }

                loadTrendChart();
                loadValidationChart();
                loadPipelineStats();
                loadScrapeLog();
            } else if (msg.type === 'surge_alert') {
                handleSurgeAlert(msg.data);
            }
        };
        ws.onclose = () => setTimeout(initWebSocket, 5000);
        setInterval(() => { if (ws?.readyState === 1) ws.send('ping'); }, 30000);
    } catch (err) {}
}

function handleSurgeAlert(data) {
    const feed = document.getElementById('surge-alert-feed');
    const msg = `SURGE DETECTED: ${data.route} fares exceed 7-day moving average by +${data.variance_pct}%. Flagged for DGCA review.`;
    showToast(msg, 'warning');

    if (feed) {
        const empty = feed.querySelector('.surge-alert-empty');
        if (empty) empty.remove();

        const item = document.createElement('div');
        item.className = 'surge-alert-item';
        item.innerHTML = `
            <div>
                <strong>SURGE DETECTED (${data.route}):</strong> Average fare INR ${data.current_avg.toLocaleString('en-IN')} exceeds 7-day SMA (INR ${data.sma.toLocaleString('en-IN')}) by <strong>+${data.variance_pct}%</strong>. Flagged for DGCA TMU review.
            </div>
            <span style="font-family:var(--mono);font-size:11px;color:var(--text-3);">${data.timestamp}</span>
        `;
        feed.prepend(item);

        const countEl = document.getElementById('stat-surge-count');
        if (countEl) {
            const currentCount = parseInt(countEl.textContent) || 0;
            countEl.textContent = `${currentCount + 1} ALERTS`;
        }
    }
}

// ─── Update Hero ───────────────────────────────────────────────────────
function updateHero(value, changePct) {
    const valEl = document.getElementById('index-value');
    if (valEl) valEl.textContent = value.toFixed(2);

    const changeEl = document.getElementById('index-change');
    if (changeEl && changePct !== undefined) {
        const sign = changePct >= 0 ? '+' : '';
        const cls = changePct > 0 ? 'up' : changePct < 0 ? 'down' : 'flat';
        changeEl.className = `index-change ${cls}`;
        changeEl.textContent = `${sign}${changePct.toFixed(3)}%`;
    }
}

// ─── Toast ─────────────────────────────────────────────────────────────
function showToast(msg, type = 'info') {
    const container = document.getElementById('toast-container');
    if (!container) return;
    const el = document.createElement('div');
    el.className = `toast ${type}`;
    el.textContent = msg;
    container.appendChild(el);
    setTimeout(() => { el.style.opacity = '0'; setTimeout(() => el.remove(), 200); }, 4000);
}

// ─── Helpers ───────────────────────────────────────────────────────────
function fmtDate(s) {
    const d = new Date(s);
    return d.toLocaleDateString('en-IN', { day: '2-digit', month: 'short' });
}
function setText(id, val) {
    const el = document.getElementById(id);
    if (el) el.textContent = val;
}
