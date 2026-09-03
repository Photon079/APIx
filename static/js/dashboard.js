/**
 * Vayu Dashboard — Light Apple Glassmorphism Frontend
 * Liquid glass animations with spring physics
 */

// ─── Light-Themed Chart.js Defaults (STRICT 5-COLOR PALETTE) ───────────
Chart.defaults.color = '#8c9aae';  // var(--palette-dark)
Chart.defaults.borderColor = 'rgba(197, 208, 217, 0.3)';
Chart.defaults.font.family = "-apple-system, BlinkMacSystemFont, 'Inter', sans-serif";
Chart.defaults.font.size = 11;
Chart.defaults.plugins.legend.labels.usePointStyle = true;
Chart.defaults.plugins.legend.labels.pointStyleWidth = 8;
Chart.defaults.plugins.legend.labels.padding = 16;
Chart.defaults.animation.duration = 500;
Chart.defaults.animation.easing = 'easeOutQuart';

let trendChart = null;
let validationChart = null;
const sparkCharts = {};
let ws = null;
let currentActiveRouteIndex = 0;

// ─── Initialize on DOM Ready ────────────────────────────────────────────
document.addEventListener('DOMContentLoaded', async () => {
    initRouteSegmentedControl();
    await Promise.all([
        loadTrendChart(),
        loadValidationChart(),
        loadRouteBreakdown(),
        loadPipelineStats(),
        loadScrapeLog(),
    ]);
    initWebSocket();
});

// ─── Apple Liquid Glass Segmented Control ───────────────────────────────
function initRouteSegmentedControl() {
    const segmentedControl = document.querySelector('.segmented-control');
    if (!segmentedControl) return;

    const buttons = segmentedControl.querySelectorAll('.segment-btn');
    const indicator = segmentedControl.querySelector('.segment-indicator');
    const panels = document.querySelectorAll('.route-content-panel');

    if (!buttons.length || !indicator) return;

    function setIndicatorPosition(index) {
        currentActiveRouteIndex = index;
        const widthPct = 100 / buttons.length;
        indicator.style.width = `calc(${widthPct}% - ${(buttons.length > 1 ? (buttons.length + 1) * 2 : 4)}px)`;
        // Liquid morphing with spring physics
        indicator.style.transform = `translateX(calc(${index * 100}% + ${index * 4}px))`;
    }

    buttons.forEach((btn, index) => {
        btn.addEventListener('click', () => {
            if (btn.classList.contains('active')) return;

            // Update button active state
            buttons.forEach(b => {
                b.classList.remove('active');
                b.setAttribute('aria-selected', 'false');
            });
            btn.classList.add('active');
            btn.setAttribute('aria-selected', 'true');

            // Liquid morph indicator
            setIndicatorPosition(index);

            // Liquid crossfade content panels
            const targetRoute = btn.dataset.route;
            panels.forEach(panel => {
                if (panel.id === `route-${targetRoute}`) {
                    panel.style.display = 'flex';
                    void panel.offsetWidth; // Trigger reflow
                    panel.classList.add('active');
                } else {
                    panel.classList.remove('active');
                    setTimeout(() => {
                        if (!panel.classList.contains('active')) {
                            panel.style.display = 'none';
                        }
                    }, 300);
                }
            });
        });
    });

    // Set initial position
    setIndicatorPosition(0);
}

// ─── 30-Day Main Trend Chart (Light Theme) ──────────────────────────────
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
        projectedValues.push(values[values.length - 1]);

        projectionData.forEach(p => {
            fullLabels.push(fmtDate(p.date) + ' (Proj)');
            historicalValues.push(null);
            projectedValues.push(p.projected_vayu);
        });

        const ctx = document.getElementById('trendChart');
        if (!ctx) return;

        const chartCtx = ctx.getContext('2d');
        const gradient = chartCtx.createLinearGradient(0, 0, 0, 300);
        // Using palette-darkest (#526382) for gradient
        gradient.addColorStop(0, 'rgba(82, 99, 130, 0.25)');
        gradient.addColorStop(0.7, 'rgba(82, 99, 130, 0.05)');
        gradient.addColorStop(1, 'rgba(82, 99, 130, 0)');

        if (trendChart) trendChart.destroy();

        trendChart = new Chart(ctx, {
            type: 'line',
            data: {
                labels: fullLabels,
                datasets: [
                    {
                        label: 'Vayu (Historical)',
                        data: historicalValues,
                        borderColor: '#526382',  // palette-darkest
                        backgroundColor: gradient,
                        borderWidth: 2.5,
                        fill: true,
                        tension: 0.38,
                        pointRadius: 0,
                        pointHoverRadius: 6,
                        pointHoverBackgroundColor: '#ffffff',
                        pointHoverBorderColor: '#526382',
                        pointHoverBorderWidth: 3,

                        
                    },

                    {
                        label: '3-Day ML Projection',
                        data: projectedValues,
                        borderColor: '#8c9aae',  // palette-dark
                        backgroundColor: 'transparent',
                        borderWidth: 2.5,
                        borderDash: [6, 4],
                        fill: false,
                        tension: 0.38,
                        pointRadius: 4,
                        pointBackgroundColor: '#8c9aae',
                        pointHoverRadius: 7,
                    }
                ],
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                interaction: { mode: 'index', intersect: false },
                plugins: {
                    legend: { display: false },
                    tooltip: {
                        backgroundColor: 'rgba(255, 255, 255, 0.95)',
                        borderColor: 'rgba(197, 208, 217, 0.6)',
                        borderWidth: 1.5,
                        cornerRadius: 12,
                        padding: 12,
                        titleColor: '#526382',
                        titleFont: { weight: '700', size: 12 },
                        bodyColor: '#526382',
                        bodyFont: { family: "'JetBrains Mono', monospace", size: 13 },
                        displayColors: true,
                        boxPadding: 4,
                    },
                },
                scales: {
                    x: {
                        grid: { display: false },
                        ticks: {
                            maxTicksLimit: 8,
                            color: 'rgb(7, 7, 7)',
                            font: { size: 10 }
                        },
                        border: { display: false }
                    },
                    y: {
                        grid: { color: 'rgba(197, 208, 217, 0.25)' },
                        ticks: {
                            color: 'rgb(8, 8, 8)',
                            font: { family: "'JetBrains Mono', monospace", size: 10 },
                            callback: v => v.toFixed(1),
                        },
                        border: { display: false }
                    },
                },
            },
        });
    } catch (err) {
        console.error('Trend chart error:', err);
    }
}

// ─── Dual-Axis Validation Chart (Light Theme) ───────────────────────────
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
                        borderColor: '#526382',  // palette-darkest
                        backgroundColor: 'transparent',
                        borderWidth: 2.5,
                        tension: 0.38,
                        pointRadius: 0,
                        pointHoverRadius: 5,
                        yAxisID: 'y',
                    },
                    {
                        label: 'DGCA Avg Fare (₹)',
                        data: series.dgca_fare,
                        borderColor: '#8c9aae',  // palette-dark
                        backgroundColor: 'transparent',
                        borderWidth: 2,
                        borderDash: [5, 4],
                        tension: 0.38,
                        pointRadius: 0,
                        pointHoverRadius: 5,
                        yAxisID: 'y1',
                    },
                ],
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                interaction: { mode: 'index', intersect: false },
                plugins: {
                    legend: {
                        position: 'top',
                        align: 'end',
                        labels: { color: '#526382' }
                    },
                    tooltip: {
                        backgroundColor: 'rgba(255, 255, 255, 0.95)',
                        borderColor: 'rgba(197, 208, 217, 0.6)',
                        borderWidth: 1.5,
                        cornerRadius: 10,
                        padding: 10,
                        titleColor: '#526382',
                        bodyColor: '#526382',
                        bodyFont: { family: "'JetBrains Mono', monospace", size: 12 },
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
                        ticks: { maxTicksLimit: 8, color: '#8c9aae', font: { size: 10 } },
                        border: { display: false }
                    },
                    y: {
                        position: 'left',
                        title: { display: true, text: 'Vayu Index', font: { size: 11, weight: '600' }, color: '#526382' },
                        grid: { color: 'rgba(197, 208, 217, 0.25)' },
                        ticks: { font: { family: "'JetBrains Mono'", size: 10 }, color: '#526382' },
                        border: { display: false }
                    },
                    y1: {
                        position: 'right',
                        title: { display: true, text: 'DGCA Fare (₹)', font: { size: 11, weight: '600' }, color: '#8c9aae' },
                        grid: { drawOnChartArea: false },
                        ticks: {
                            font: { family: "'JetBrains Mono'", size: 10 },
                            color: '#8c9aae',
                            callback: v => '₹' + v.toLocaleString('en-IN'),
                        },
                        border: { display: false }
                    },
                },
            },
        });
    } catch (err) {
        console.error('Validation chart error:', err);
    }
}

// ─── Route Breakdown & Sparklines ───────────────────────────────────────
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

        // Rule 135 compliance
        const badgeEl = document.getElementById(`badge-${route}`);
        if (badgeEl) {
            if (info.rule_135_compliant) {
                badgeEl.className = 'glass-pill green';
                badgeEl.textContent = '✓ COMPLIANT';
            } else {
                badgeEl.className = 'glass-pill red';
                badgeEl.textContent = `✕ BREACH (${info.rule_135_breaches || 1})`;
            }
        }

        // HHI status
        const hhiStatusEl = document.getElementById(`hhi-status-${route}`);
        if (hhiStatusEl) {
            let pillColor = 'green';
            if (info.hhi_score > 2500 || !info.rule_135_compliant) pillColor = 'red';
            else if (info.hhi_score >= 1500) pillColor = 'orange';

            hhiStatusEl.className = `glass-pill ${pillColor}`;
            hhiStatusEl.textContent = `HHI: ${info.hhi_score}`;
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
            if (sparkCharts[route]) {
                sparkCharts[route].destroy();
            }

            const isUp = info.sparkline[info.sparkline.length - 1] >= info.sparkline[0];
            const sparkCtx = sparkEl.getContext('2d');
            const sparkGradient = sparkCtx.createLinearGradient(0, 0, 0, 50);
            sparkGradient.addColorStop(0, isUp ? 'rgba(52, 199, 89, 0.25)' : 'rgba(255, 59, 48, 0.25)');
            sparkGradient.addColorStop(1, 'transparent');

            sparkCharts[route] = new Chart(sparkEl, {
                type: 'line',
                data: {
                    labels: info.sparkline.map((_, i) => i),
                    datasets: [{
                        data: info.sparkline,
                        borderColor: '#8c9aae',  // palette-dark for all sparklines
                        backgroundColor: sparkGradient,
                        borderWidth: 2,
                        fill: true,
                        tension: 0.4,
                        pointRadius: 0,
                    }],
                },
                options: {
                    responsive: true,
                    maintainAspectRatio: false,
                    plugins: { legend: { display: false }, tooltip: { enabled: false } },
                    scales: {
                        x: { display: false },
                        y: { display: false }
                    },
                    animation: false,
                },
            });
        }
    });
}

// ─── Pipeline Stats ─────────────────────────────────────────────────────
async function loadPipelineStats() {
    try {
        const res = await fetch('/api/pipeline/stats');
        const json = await res.json();
        if (json.status !== 'ok') return;
        const d = json.data;

        setText('stat-fares-processed', d.cleaner?.cleaned || d.cleaner?.total_db_fares || 0);
        setText('stat-outliers', d.cleaner?.dropped_outlier || 0);
        setText('stat-persisted', `${d.scraper?.persisted_files || 0} files`);

        // Telemetry page
        setText('telemetry-cleaned', d.cleaner?.cleaned || d.cleaner?.total_db_fares || 0);
        setText('telemetry-dupes', d.cleaner?.dropped_duplicate || 0);
        setText('telemetry-outliers', d.cleaner?.dropped_outlier || 0);
        setText('telemetry-invalid', d.cleaner?.dropped_invalid || 0);
    } catch (err) {}
}

// ─── Scrape Log ─────────────────────────────────────────────────────────
async function loadScrapeLog() {
    try {
        const res = await fetch('/api/scrape/log');
        const json = await res.json();
        if (json.status !== 'ok') return;

        const list = document.getElementById('scrape-log');
        if (!list) return;

        if (json.data.length === 0) {
            list.innerHTML = '<li style="color:#8c9aae;font-size:12px;padding:12px 0;text-align:center;">No scrape activity yet. Click "Run Live Scrape" to start.</li>';
            return;
        }

        list.innerHTML = json.data.map(entry => `
            <li class="glass-log-row">
                <span style="font-family:var(--font-mono);color:#8c9aae;">${entry.time}</span>
                <span style="font-family:var(--font-mono);color:#526382;font-weight:600;">${entry.route}</span>
                <span style="color:#526382;">${entry.mode} — ${entry.detail}</span>
                <span style="font-family:var(--font-mono);color:#526382;text-align:right;font-weight:600;">${entry.fares} fares</span>
            </li>
        `).join('');
    } catch (err) {}
}

// ─── Scrape Trigger ─────────────────────────────────────────────────────
async function triggerScrape() {
    const btn = document.getElementById('btn-scrape');
    if (!btn || btn.classList.contains('loading')) return;

    btn.classList.add('loading');
    showToast('Connecting to Playwright scrape engine...', 'info');

    try {
        const res = await fetch('/api/scrape');
        const json = await res.json();

        if (json.status === 'ok') {
            showToast(`${json.message} (Mode: ${json.scraper_mode})`, 'success');

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

// ─── WebSocket ──────────────────────────────────────────────────────────
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
    const msg = `SURGE: ${data.route} fares exceed 7-day SMA by +${data.variance_pct}%`;
    showToast(msg, 'warning');

    if (feed) {
        const empty = feed.querySelector('[style*="dashed"]');
        if (empty) empty.remove();

        const item = document.createElement('div');
        item.className = 'surge-card-item';
        item.innerHTML = `
            <div>
                <strong style="color:#526382;">SURGE DETECTED (${data.route}):</strong>
                <span style="color:#526382;margin-left:4px;">
                    Avg fare INR ${data.current_avg.toLocaleString('en-IN')} exceeds 7-day SMA (INR ${data.sma.toLocaleString('en-IN')}) by
                    <strong style="color:#526382;">+${data.variance_pct}%</strong>
                </span>
            </div>
            <span style="font-family:var(--font-mono);font-size:11px;color:#8c9aae;">${data.timestamp}</span>
        `;
        feed.prepend(item);

        const countEl = document.getElementById('stat-surge-count');
        if (countEl) {
            const currentCount = parseInt(countEl.textContent) || 0;
            countEl.textContent = `${currentCount + 1} ALERTS`;
        }
    }
}

// ─── Update Hero ────────────────────────────────────────────────────────
function updateHero(value, changePct) {
    const valEl = document.getElementById('index-value');
    if (valEl) valEl.textContent = value.toFixed(2);

    const globalVal = document.getElementById('global-apix-val');
    if (globalVal) globalVal.textContent = value.toFixed(2);

    const changeEl = document.getElementById('index-change');
    if (changeEl && changePct !== undefined) {
        const sign = changePct >= 0 ? '+' : '';
        const cls = changePct > 0 ? 'up' : changePct < 0 ? 'down' : 'flat';
        changeEl.className = `chart-hero-badge ${cls}`;
        changeEl.textContent = `${sign}${changePct.toFixed(3)}%`;
    }
}

// ─── Light Glass Toast ──────────────────────────────────────────────────
function showToast(msg, type = 'info') {
    const container = document.getElementById('toast-container');
    if (!container) return;
    const el = document.createElement('div');
    el.className = `toast ${type}`;
    el.textContent = msg;
    container.appendChild(el);
    setTimeout(() => {
        el.style.opacity = '0';
        el.style.transform = 'translateY(10px) scale(0.95)';
        setTimeout(() => el.remove(), 300);
    }, 4000);
}

// ─── Helpers ────────────────────────────────────────────────────────────
function fmtDate(s) {
    const d = new Date(s);
    return d.toLocaleDateString('en-IN', { day: '2-digit', month: 'short' });
}

function setText(id, val) {
    const el = document.getElementById(id);
    if (el) el.textContent = val;
}
