/* Auto Report - Gestor Dashboard JavaScript */

let gestorEvtSource = null;

// ─────────────────────────────────────────────
// Load gestores dropdown
// ─────────────────────────────────────────────
async function loadGestores() {
    try {
        const resp = await fetch('/api/gestores');
        const gestores = await resp.json();
        const select = document.getElementById('gestor-select');
        if (!select) return;

        select.innerHTML = '<option value="">Selecione um gestor...</option>';
        gestores.forEach(g => {
            const opt = document.createElement('option');
            opt.value = g;
            opt.textContent = g;
            select.appendChild(opt);
        });

        initGestorSSE();
    } catch (err) {
        showToast('Erro ao carregar gestores: ' + err.message, 'error');
    }
}

// ─────────────────────────────────────────────
// Load gestor dashboard data
// ─────────────────────────────────────────────
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

    // Toggle manage clients button visibility
    const btnManage = document.getElementById('btn-manage-clients');
    if (btnManage) {
        if (nome) btnManage.classList.remove('hidden');
        else btnManage.classList.add('hidden');
    }

    if (!nome) {
        if (empty) empty.classList.remove('hidden');
        return;
    }

    if (loading) loading.classList.remove('hidden');

    try {
        const resp = await fetch(`/api/gestor/${encodeURIComponent(nome)}/dashboard`);
        const data = await resp.json();

        if (loading) loading.classList.add('hidden');

        // Summary cards
        if (summary) {
            summary.classList.remove('hidden');
            document.getElementById('sum-clientes').textContent = data.summary.total_clientes;
            document.getElementById('sum-faturamento').textContent = formatBRL(data.summary.total_faturamento);
            document.getElementById('sum-investimento').textContent = formatBRL(data.summary.total_investimento);
            document.getElementById('sum-roas').textContent = data.summary.roas_medio != null
                ? data.summary.roas_medio.toFixed(2) + 'x'
                : '-';
        }

        // Platform breakdown
        if (platforms) {
            platforms.classList.remove('hidden');
            document.getElementById('sum-vendas').textContent = data.summary.total_vendas || '-';
            document.getElementById('sum-inv-google').textContent = formatBRL(data.summary.total_inv_google);
            document.getElementById('sum-inv-meta').textContent = formatBRL(data.summary.total_inv_meta);
        }

        // Client metrics table
        if (clients && data.clients.length > 0) {
            clients.classList.remove('hidden');

            // Update count badge
            const countBadge = document.getElementById('client-metrics-count');
            if (countBadge) countBadge.textContent = `${data.clients.length} clientes com metricas`;

            const tbody = document.getElementById('gestor-clients-tbody');
            tbody.innerHTML = data.clients.map(c => {
                const isLead = (c.categoria || '').toLowerCase().startsWith('lead');
                const convLabel = isLead ? 'leads' : 'vendas';
                return `
                <tr>
                    <td class="px-4 py-3">
                        <a href="/client/${encodeURIComponent(c.cliente_nome)}" class="text-sm font-medium text-primary-600 hover:text-primary-500">
                            ${escapeHtml(c.cliente_nome)}
                        </a>
                    </td>
                    <td class="px-4 py-3 text-sm text-surface-400">${escapeHtml(c.categoria || '-')}</td>
                    <td class="px-4 py-3 text-sm text-right font-medium text-emerald-500">${isLead ? '-' : formatBRL(c.faturamento)}</td>
                    <td class="px-4 py-3 text-sm text-right text-surface-500 dark:text-surface-400">${formatBRL(c.investimento)}</td>
                    <td class="px-4 py-3 text-sm text-right font-medium text-primary-500">${c.roas != null ? Number(c.roas).toFixed(2) + 'x' : '-'}</td>
                    <td class="px-4 py-3 text-sm text-right text-surface-500 dark:text-surface-400">${c.vendas != null ? c.vendas : '-'}</td>
                    <td class="px-4 py-3 text-sm text-right text-surface-500 dark:text-surface-400">${c.cpa != null ? formatBRL(c.cpa) : '-'}</td>
                    <td class="px-4 py-3 text-xs text-surface-400">${formatPeriodo(c.periodo_inicio, c.periodo_fim)}</td>
                </tr>`;
            }).join('');
        }

        // Clients without metrics
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
// Full Sync (Sync clients + Collect all metrics)
// ─────────────────────────────────────────────
async function fullSync() {
    const freq = document.getElementById('freq-select-gestor')?.value || 'SEMANAL';
    const gestor = document.getElementById('gestor-select')?.value || '';
    const btn = document.getElementById('btn-full-sync');

    // Disable button and show spinning state
    if (btn) {
        btn.disabled = true;
        btn.innerHTML = `
            <svg class="w-4 h-4 animate-spin" fill="none" viewBox="0 0 24 24">
                <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle>
                <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"></path>
            </svg>
            Sincronizando...`;
    }

    // Show stepper
    const stepper = document.getElementById('sync-stepper');
    if (stepper) stepper.classList.remove('hidden');
    resetStepper();
    updateStepperPhase(1);

    try {
        const resp = await fetch('/api/full-sync', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ freq, gestor }),
        });
        const data = await resp.json();
        if (!resp.ok) throw new Error(data.error || 'Erro ao iniciar sincronizacao');
    } catch (err) {
        showToast('Erro: ' + err.message, 'error');
        resetSyncButton();
        if (stepper) stepper.classList.add('hidden');
    }
}

// ─────────────────────────────────────────────
// Stepper UI management
// ─────────────────────────────────────────────
function resetStepper() {
    const step1 = document.getElementById('step1');
    const step2 = document.getElementById('step2');
    const connector = document.getElementById('step-connector');

    if (step1) { step1.className = 'flex items-center gap-2'; }
    if (step2) { step2.className = 'flex items-center gap-2'; }
    if (connector) { connector.className = 'step-connector'; }

    updateSyncProgress(0, '');
}

function updateStepperPhase(phase) {
    const step1 = document.getElementById('step1');
    const step2 = document.getElementById('step2');
    const connector = document.getElementById('step-connector');

    if (phase === 1) {
        if (step1) step1.className = 'flex items-center gap-2 step-active';
        if (step2) step2.className = 'flex items-center gap-2';
        if (connector) connector.className = 'step-connector';
    } else if (phase === 2) {
        if (step1) step1.className = 'flex items-center gap-2 step-complete';
        if (step2) step2.className = 'flex items-center gap-2 step-active';
        if (connector) connector.className = 'step-connector active';
    }
}

function completeAllSteps() {
    const step1 = document.getElementById('step1');
    const step2 = document.getElementById('step2');
    const connector = document.getElementById('step-connector');

    if (step1) step1.className = 'flex items-center gap-2 step-complete';
    if (step2) step2.className = 'flex items-center gap-2 step-complete';
    if (connector) connector.className = 'step-connector complete';
}

function updateSyncProgress(pct, text, detail) {
    const bar = document.getElementById('sync-progress-bar');
    const textEl = document.getElementById('sync-progress-text');
    const detailEl = document.getElementById('sync-progress-detail');

    if (bar) bar.style.width = pct + '%';
    if (textEl) textEl.textContent = text || '';
    if (detailEl) detailEl.textContent = detail || '';
}

function resetSyncButton() {
    const btn = document.getElementById('btn-full-sync');
    if (btn) {
        btn.disabled = false;
        btn.innerHTML = `
            <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15"/></svg>
            Sincronizar Tudo`;
    }
}

// ─────────────────────────────────────────────
// SSE for real-time progress
// ─────────────────────────────────────────────
function initGestorSSE() {
    if (gestorEvtSource) gestorEvtSource.close();
    gestorEvtSource = new EventSource('/api/status/stream');

    // Full sync progress (phases 1 and 2)
    gestorEvtSource.addEventListener('full_sync_progress', (e) => {
        const data = JSON.parse(e.data);

        updateStepperPhase(data.phase);

        if (data.phase === 1) {
            // Phase 1: syncing clients (indeterminate -> complete)
            updateSyncProgress(
                data.total > 0 ? 100 : 50,
                data.phase_label,
                data.detail
            );
        } else if (data.phase === 2) {
            // Phase 2: collecting metrics (progress per client)
            const pct = data.total > 0 ? Math.round((data.done / data.total) * 100) : 0;
            updateSyncProgress(
                pct,
                `${data.done} de ${data.total}`,
                data.detail
            );
        }
    });

    // Full sync complete
    gestorEvtSource.addEventListener('full_sync_complete', (e) => {
        const data = JSON.parse(e.data);

        completeAllSteps();
        updateSyncProgress(100, 'Concluido!', '');

        const hasErrors = data.collected_errors > 0;
        showToast(
            `Sincronizacao completa: ${data.synced} clientes, ${data.collected_ok} metricas ok` +
            (hasErrors ? `, ${data.collected_errors} erro(s)` : ''),
            hasErrors ? 'error' : 'success'
        );

        resetSyncButton();

        // Reload gestores list and dashboard
        loadGestores().then(() => {
            loadGestorDashboard();
        });

        // Hide stepper after a moment
        setTimeout(() => {
            const stepper = document.getElementById('sync-stepper');
            if (stepper) stepper.classList.add('hidden');
        }, 4000);
    });

    // Legacy: single gestor collect progress (if still used)
    gestorEvtSource.addEventListener('collect_progress', (e) => {
        const data = JSON.parse(e.data);
        const status = data.status === 'ok' ? '\u2713' : '\u2717';
        const pct = data.total > 0 ? Math.round((data.done / data.total) * 100) : 0;
        updateSyncProgress(pct, `${data.done} de ${data.total}`, `${data.client}: ${status}`);
    });

    gestorEvtSource.addEventListener('collect_complete', (e) => {
        const data = JSON.parse(e.data);
        const hasErrors = data.errors > 0;
        showToast(
            `Coleta concluida: ${data.ok} ok, ${data.errors} erro(s) de ${data.total} clientes`,
            hasErrors ? 'error' : 'success'
        );
        resetSyncButton();
        loadGestorDashboard();
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
// Utilities
// ─────────────────────────────────────────────
function formatBRL(value) {
    if (value == null) return '-';
    if (value === 0) return 'R$ 0,00';
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

// ─────────────────────────────────────────────
// Manage Clients (assign to gestor)
// ─────────────────────────────────────────────
let _selectedClients = new Set();
let _searchTimer = null;

function openManageClients() {
    const gestor = document.getElementById('gestor-select')?.value || '';
    if (!gestor) return;

    const modal = document.getElementById('manage-clients-modal');
    const label = document.getElementById('manage-gestor-label');
    if (label) label.textContent = `Gestor: ${gestor}`;

    _selectedClients.clear();
    updateSelectedBar();

    const input = document.getElementById('client-search-input');
    if (input) input.value = '';
    document.getElementById('client-search-results')?.classList.add('hidden');
    document.getElementById('client-search-empty')?.classList.remove('hidden');

    if (modal) modal.classList.remove('hidden');
}

function closeManageClients() {
    const modal = document.getElementById('manage-clients-modal');
    if (modal) modal.classList.add('hidden');
}

function debounceSearchClients() {
    if (_searchTimer) clearTimeout(_searchTimer);
    _searchTimer = setTimeout(searchClients, 300);
}

async function searchClients() {
    const q = document.getElementById('client-search-input')?.value?.trim() || '';
    const gestor = document.getElementById('gestor-select')?.value || '';

    const resultsEl = document.getElementById('client-search-results');
    const emptyEl = document.getElementById('client-search-empty');
    const loadingEl = document.getElementById('client-search-loading');

    if (q.length < 2) {
        if (resultsEl) resultsEl.classList.add('hidden');
        if (emptyEl) { emptyEl.classList.remove('hidden'); emptyEl.textContent = 'Digite ao menos 2 caracteres'; }
        return;
    }

    if (emptyEl) emptyEl.classList.add('hidden');
    if (loadingEl) loadingEl.classList.remove('hidden');
    if (resultsEl) resultsEl.classList.add('hidden');

    try {
        const resp = await fetch(`/api/clientes/search?q=${encodeURIComponent(q)}&exclude_gestor=${encodeURIComponent(gestor)}`);
        const clients = await resp.json();

        if (loadingEl) loadingEl.classList.add('hidden');

        if (clients.length === 0) {
            if (emptyEl) { emptyEl.classList.remove('hidden'); emptyEl.textContent = 'Nenhum cliente encontrado'; }
            return;
        }

        if (resultsEl) {
            resultsEl.classList.remove('hidden');
            resultsEl.innerHTML = clients.map(c => {
                const checked = _selectedClients.has(c.nome) ? 'checked' : '';
                const gestorTag = c.gestor ? `<span class="text-xs text-surface-400 ml-2">(${escapeHtml(c.gestor)})</span>` : '';
                return `
                    <label class="flex items-center gap-3 p-2.5 rounded-lg hover:bg-surface-50 dark:hover:bg-surface-800 cursor-pointer transition">
                        <input type="checkbox" class="client-check rounded border-surface-300 dark:border-surface-600
                               text-primary-600 focus:ring-primary-500"
                               value="${escapeHtml(c.nome)}" ${checked}
                               onchange="toggleClientSelection(this)">
                        <div class="flex-1 min-w-0">
                            <span class="text-sm font-medium text-surface-700 dark:text-surface-200 truncate block">${escapeHtml(c.nome)}</span>
                            <span class="text-xs text-surface-400">${escapeHtml(c.categoria || '-')}</span>${gestorTag}
                        </div>
                    </label>`;
            }).join('');
        }
    } catch (err) {
        if (loadingEl) loadingEl.classList.add('hidden');
        if (emptyEl) { emptyEl.classList.remove('hidden'); emptyEl.textContent = 'Erro ao buscar: ' + err.message; }
    }
}

function toggleClientSelection(checkbox) {
    if (checkbox.checked) {
        _selectedClients.add(checkbox.value);
    } else {
        _selectedClients.delete(checkbox.value);
    }
    updateSelectedBar();
}

function updateSelectedBar() {
    const bar = document.getElementById('manage-selected-bar');
    const count = document.getElementById('manage-selected-count');

    if (_selectedClients.size > 0) {
        if (bar) bar.classList.remove('hidden');
        if (count) count.textContent = `${_selectedClients.size} cliente(s) selecionado(s)`;
    } else {
        if (bar) bar.classList.add('hidden');
    }
}

async function assignSelectedClients() {
    const gestor = document.getElementById('gestor-select')?.value || '';
    if (!gestor || _selectedClients.size === 0) return;

    try {
        const resp = await fetch('/api/gestor/assign', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ gestor, clients: Array.from(_selectedClients) }),
        });
        const data = await resp.json();

        if (!resp.ok) throw new Error(data.error || 'Erro ao vincular');

        showToast(`${data.updated.length} cliente(s) vinculados a ${gestor}`, 'success');
        closeManageClients();
        loadGestorDashboard();
    } catch (err) {
        showToast('Erro: ' + err.message, 'error');
    }
}
