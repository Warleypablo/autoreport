/* Auto Report - Gestor Dashboard JavaScript */

let gestorEvtSource = null;

async function loadGestores() {
    try {
        const resp = await fetch('/api/gestores');
        const gestores = await resp.json();
        const select = document.getElementById('gestor-select');
        if (!select) return;

        // Keep the placeholder option
        select.innerHTML = '<option value="">Selecione um gestor...</option>';
        gestores.forEach(g => {
            const opt = document.createElement('option');
            opt.value = g;
            opt.textContent = g;
            select.appendChild(opt);
        });

        // Init SSE for collect progress
        initGestorSSE();
    } catch (err) {
        showToast('Erro ao carregar gestores: ' + err.message, 'error');
    }
}

async function loadGestorDashboard() {
    const select = document.getElementById('gestor-select');
    const nome = select ? select.value : '';

    const loading = document.getElementById('gestor-loading');
    const empty = document.getElementById('gestor-empty');
    const summary = document.getElementById('gestor-summary');
    const platforms = document.getElementById('gestor-platforms');
    const clients = document.getElementById('gestor-clients');
    const noMetrics = document.getElementById('gestor-no-metrics');

    // Hide all sections
    [loading, empty, summary, platforms, clients, noMetrics].forEach(el => {
        if (el) el.classList.add('hidden');
    });

    if (!nome) {
        if (empty) empty.classList.remove('hidden');
        return;
    }

    if (loading) loading.classList.remove('hidden');

    try {
        const resp = await fetch(`/api/gestor/${encodeURIComponent(nome)}/dashboard`);
        const data = await resp.json();

        if (loading) loading.classList.add('hidden');

        // Render summary cards
        if (summary) {
            summary.classList.remove('hidden');
            document.getElementById('sum-clientes').textContent = data.summary.total_clientes;
            document.getElementById('sum-faturamento').textContent = formatBRL(data.summary.total_faturamento);
            document.getElementById('sum-investimento').textContent = formatBRL(data.summary.total_investimento);
            document.getElementById('sum-roas').textContent = data.summary.roas_medio != null
                ? data.summary.roas_medio.toFixed(2) + 'x'
                : '-';
        }

        // Render platform breakdown
        if (platforms) {
            platforms.classList.remove('hidden');
            document.getElementById('sum-vendas').textContent = data.summary.total_vendas || 0;
            document.getElementById('sum-inv-google').textContent = formatBRL(data.summary.total_inv_google);
            document.getElementById('sum-inv-meta').textContent = formatBRL(data.summary.total_inv_meta);
        }

        // Render clients table
        if (clients && data.clients.length > 0) {
            clients.classList.remove('hidden');
            const tbody = document.getElementById('gestor-clients-tbody');
            tbody.innerHTML = data.clients.map(c => `
                <tr>
                    <td class="px-4 py-3">
                        <a href="/client/${encodeURIComponent(c.cliente_nome)}" class="text-sm font-medium text-primary-600 hover:text-primary-500">
                            ${escapeHtml(c.cliente_nome)}
                        </a>
                    </td>
                    <td class="px-4 py-3 text-sm text-surface-400">${escapeHtml(c.categoria || '-')}</td>
                    <td class="px-4 py-3 text-sm text-right font-medium text-emerald-500">${formatBRL(c.faturamento)}</td>
                    <td class="px-4 py-3 text-sm text-right text-surface-500 dark:text-surface-400">${formatBRL(c.investimento)}</td>
                    <td class="px-4 py-3 text-sm text-right font-medium text-primary-500">${c.roas != null ? Number(c.roas).toFixed(2) + 'x' : '-'}</td>
                    <td class="px-4 py-3 text-sm text-right text-surface-500 dark:text-surface-400">${c.vendas != null ? c.vendas : '-'}</td>
                    <td class="px-4 py-3 text-sm text-right text-surface-500 dark:text-surface-400">${c.cpa != null ? formatBRL(c.cpa) : '-'}</td>
                    <td class="px-4 py-3 text-xs text-surface-400">${formatPeriodo(c.periodo_inicio, c.periodo_fim)}</td>
                </tr>
            `).join('');
        }

        // Render clients without metrics
        if (noMetrics && data.clients_no_metrics && data.clients_no_metrics.length > 0) {
            noMetrics.classList.remove('hidden');
            const list = document.getElementById('gestor-no-metrics-list');
            list.innerHTML = data.clients_no_metrics.map(c => `
                <a href="/client/${encodeURIComponent(c.cliente_nome)}"
                   class="inline-flex items-center px-3 py-1.5 rounded-lg text-xs font-medium
                          bg-surface-100 dark:bg-surface-800 text-surface-500 dark:text-surface-400
                          hover:bg-surface-200 dark:hover:bg-surface-700 transition">
                    ${escapeHtml(c.cliente_nome)}
                </a>
            `).join('');
        }

    } catch (err) {
        if (loading) loading.classList.add('hidden');
        showToast('Erro ao carregar dashboard: ' + err.message, 'error');
    }
}

// ─────────────────────────────────────────────
// Metrics collection
// ─────────────────────────────────────────────
async function collectMetrics() {
    const select = document.getElementById('gestor-select');
    const gestor = select ? select.value : '';
    if (!gestor) {
        showToast('Selecione um gestor primeiro', 'error');
        return;
    }

    const freq = document.getElementById('freq-select-gestor')?.value || 'SEMANAL';
    const btn = document.getElementById('btn-collect-metrics');
    if (btn) {
        btn.disabled = true;
        btn.textContent = 'Coletando...';
    }

    // Show progress bar
    const progress = document.getElementById('collect-progress');
    if (progress) progress.classList.remove('hidden');
    updateCollectProgress(0, 0, '');

    try {
        const resp = await fetch('/api/collect-metrics', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ gestor, freq }),
        });
        const data = await resp.json();
        if (!resp.ok) throw new Error(data.error || 'Erro ao iniciar coleta');
        showToast('Coleta de metricas iniciada...', 'info');
    } catch (err) {
        showToast('Erro: ' + err.message, 'error');
        if (btn) {
            btn.disabled = false;
            btn.textContent = 'Coletar Metricas';
        }
        if (progress) progress.classList.add('hidden');
    }
}

function updateCollectProgress(done, total, detail) {
    const pct = total > 0 ? Math.round((done / total) * 100) : 0;
    const bar = document.getElementById('collect-progress-bar');
    const text = document.getElementById('collect-progress-text');
    const detailEl = document.getElementById('collect-progress-detail');

    if (bar) bar.style.width = pct + '%';
    if (text) text.textContent = `${done} de ${total}`;
    if (detailEl) detailEl.textContent = detail;
}

function onCollectComplete(data) {
    const hasErrors = data.errors > 0;
    showToast(
        `Coleta concluida: ${data.ok} ok, ${data.errors} erro(s) de ${data.total} clientes`,
        hasErrors ? 'error' : 'success'
    );

    const btn = document.getElementById('btn-collect-metrics');
    if (btn) {
        btn.disabled = false;
        btn.textContent = 'Coletar Metricas';
    }

    // Hide progress bar after a moment
    setTimeout(() => {
        const progress = document.getElementById('collect-progress');
        if (progress) progress.classList.add('hidden');
    }, 2000);

    // Reload dashboard to show new metrics
    loadGestorDashboard();
}

// ─────────────────────────────────────────────
// SSE for collection progress
// ─────────────────────────────────────────────
function initGestorSSE() {
    if (gestorEvtSource) gestorEvtSource.close();
    gestorEvtSource = new EventSource('/api/status/stream');

    gestorEvtSource.addEventListener('collect_progress', (e) => {
        const data = JSON.parse(e.data);
        const status = data.status === 'ok' ? '✓' : '✗';
        updateCollectProgress(data.done, data.total, `${data.client}: ${status}`);
    });

    gestorEvtSource.addEventListener('collect_complete', (e) => {
        const data = JSON.parse(e.data);
        onCollectComplete(data);
    });

    gestorEvtSource.onerror = () => {
        setTimeout(() => {
            if (gestorEvtSource && gestorEvtSource.readyState === EventSource.CLOSED) {
                initGestorSSE();
            }
        }, 5000);
    };
}

// ─────────────────────────────────────────────
// Sync and utilities
// ─────────────────────────────────────────────
async function syncClientsFromGestor() {
    try {
        showToast('Sincronizando clientes...', 'info');
        const resp = await fetch('/api/sync-clients', { method: 'POST' });
        const data = await resp.json();
        if (data.error) throw new Error(data.error);
        showToast(`${data.synced} clientes sincronizados`, 'success');
        // Reload gestores list and current dashboard
        await loadGestores();
        loadGestorDashboard();
    } catch (err) {
        showToast('Erro ao sincronizar: ' + err.message, 'error');
    }
}

function formatBRL(value) {
    if (value == null || value === 0) return 'R$ 0,00';
    return 'R$ ' + Number(value).toLocaleString('pt-BR', {
        minimumFractionDigits: 2,
        maximumFractionDigits: 2,
    });
}

function formatPeriodo(inicio, fim) {
    if (!inicio || !fim) return '-';
    try {
        const di = new Date(inicio);
        const df = new Date(fim);
        return di.toLocaleDateString('pt-BR') + ' - ' + df.toLocaleDateString('pt-BR');
    } catch {
        return `${inicio} - ${fim}`;
    }
}
