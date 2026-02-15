/* Auto Report - Main JavaScript */

let allClients = [];
let currentJobId = null;
let evtSource = null;

// ─────────────────────────────────────────────
// SSE (Server-Sent Events)
// ─────────────────────────────────────────────
function initSSE() {
    if (evtSource) evtSource.close();
    evtSource = new EventSource('/api/status/stream');

    evtSource.addEventListener('client_status', (e) => {
        const data = JSON.parse(e.data);
        updateClientRow(data.client, data.status, data.presentation_url);
        updateJobProgress(data.completed, data.total, data.errors);
    });

    evtSource.addEventListener('status_change', (e) => {
        const data = JSON.parse(e.data);
        updateClientRow(data.client, data.status);
    });

    evtSource.addEventListener('job_status', (e) => {
        const data = JSON.parse(e.data);
        if (data.status === 'EM EXECUCAO') {
            currentJobId = data.job_id;
            showJobPanel(data.job_id);
        }
    });

    evtSource.addEventListener('job_update', (e) => {
        const data = JSON.parse(e.data);
        updateJobProgress(0, data.total, 0);
    });

    evtSource.addEventListener('job_complete', (e) => {
        const data = JSON.parse(e.data);
        onJobComplete(data);
    });

    evtSource.onerror = () => {
        setTimeout(() => {
            if (evtSource.readyState === EventSource.CLOSED) initSSE();
        }, 3000);
    };
}

// ─────────────────────────────────────────────
// Client listing
// ─────────────────────────────────────────────
async function loadClients() {
    const loading = document.getElementById('loading-state');
    const error = document.getElementById('error-state');
    const table = document.getElementById('clients-table-container');

    if (loading) loading.classList.remove('hidden');
    if (error) error.classList.add('hidden');
    if (table) table.classList.add('hidden');

    try {
        const resp = await fetch('/api/clients');
        if (!resp.ok) throw new Error((await resp.json()).error || resp.statusText);
        allClients = await resp.json();

        populateCategories();
        renderClients();

        if (loading) loading.classList.add('hidden');
        if (table) table.classList.remove('hidden');
    } catch (err) {
        if (loading) loading.classList.add('hidden');
        if (error) {
            error.classList.remove('hidden');
            document.getElementById('error-message').textContent = err.message;
        }
    }
}

function populateCategories() {
    const select = document.getElementById('category-filter');
    if (!select) return;
    const cats = [...new Set(allClients.map(c => c.categoria))].sort();
    // Keep the "Todas" option, clear the rest
    select.innerHTML = '<option value="">Todas</option>';
    cats.forEach(cat => {
        const opt = document.createElement('option');
        opt.value = cat;
        opt.textContent = cat;
        select.appendChild(opt);
    });
}

function getFilteredClients() {
    const catFilter = document.getElementById('category-filter')?.value || '';
    const searchFilter = (document.getElementById('search-input')?.value || '').toLowerCase();

    return allClients.filter(c => {
        if (catFilter && c.categoria !== catFilter) return false;
        if (searchFilter && !c.nome.toLowerCase().includes(searchFilter)) return false;
        return true;
    });
}

function renderClients() {
    const tbody = document.getElementById('clients-tbody');
    if (!tbody) return;

    const filtered = getFilteredClients();
    document.getElementById('client-count').textContent = filtered.length;

    tbody.innerHTML = filtered.map(c => `
        <tr data-client="${escapeHtml(c.nome)}" class="border-b border-gray-100">
            <td class="px-4 py-3">
                <input type="checkbox" class="client-checkbox rounded" value="${escapeHtml(c.nome)}" onchange="updateSelectedCount()">
            </td>
            <td class="px-4 py-3">
                <a href="/client/${encodeURIComponent(c.nome)}" class="text-sm font-medium text-primary-700 hover:text-primary-900">
                    ${escapeHtml(c.nome)}
                </a>
            </td>
            <td class="px-4 py-3">
                <span class="text-sm text-gray-600">${escapeHtml(c.categoria)}</span>
            </td>
            <td class="px-4 py-3">
                <span class="status-badge ${getStatusClass(c.status)}">${escapeHtml(c.status || '-')}</span>
            </td>
            <td class="px-4 py-3 text-sm text-gray-600">${escapeHtml(c.ultima_geracao || '-')}</td>
            <td class="px-4 py-3 actions-cell">
                <button onclick="generateSingle('${escapeHtml(c.nome)}')" class="text-xs text-primary-600 hover:text-primary-800 font-medium">
                    Gerar
                </button>
                <button onclick="openEditModal('${escapeHtml(c.nome)}')" class="text-xs text-gray-500 hover:text-gray-700 font-medium ml-2" title="Configuracoes">
                    &#9881;
                </button>
            </td>
        </tr>
    `).join('');

    updateSelectedCount();
}

// Attach filter listeners
document.addEventListener('DOMContentLoaded', () => {
    const catFilter = document.getElementById('category-filter');
    const searchInput = document.getElementById('search-input');
    if (catFilter) catFilter.addEventListener('change', renderClients);
    if (searchInput) searchInput.addEventListener('input', renderClients);
});

// ─────────────────────────────────────────────
// Selection
// ─────────────────────────────────────────────
function toggleSelectAll() {
    const checked = document.getElementById('select-all')?.checked || false;
    document.querySelectorAll('.client-checkbox').forEach(cb => { cb.checked = checked; });
    updateSelectedCount();
}

function updateSelectedCount() {
    const selected = document.querySelectorAll('.client-checkbox:checked').length;
    const countEl = document.getElementById('selected-count');
    const btn = document.getElementById('btn-generate-selected');
    if (countEl) countEl.textContent = selected;
    if (btn) btn.disabled = selected === 0;
}

function getSelectedClients() {
    return [...document.querySelectorAll('.client-checkbox:checked')].map(cb => cb.value);
}

// ─────────────────────────────────────────────
// Generation
// ─────────────────────────────────────────────
async function generateSelected() {
    const clients = getSelectedClients();
    if (!clients.length) return;
    await startGeneration(clients);
}

async function generateAll() {
    if (!confirm('Gerar relatorios para todos os clientes elegiveis?')) return;
    await startGenerationAll();
}

async function generateSingle(clientName) {
    await startGeneration([clientName]);
}

async function startGeneration(clients) {
    const freq = document.getElementById('freq-select')?.value
        || document.getElementById('freq-select-detail')?.value
        || 'SEMANAL';

    disableGenerateButtons();
    try {
        const resp = await fetch('/api/generate', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ clients, freq }),
        });
        const data = await resp.json();
        if (!resp.ok) throw new Error(data.error);
        currentJobId = data.job_id;
        showToast('Geracao iniciada', 'info');
    } catch (err) {
        showToast('Erro: ' + err.message, 'error');
        enableGenerateButtons();
    }
}

async function startGenerationAll() {
    const freq = document.getElementById('freq-select')?.value || 'SEMANAL';

    disableGenerateButtons();
    try {
        const resp = await fetch('/api/generate-all', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ freq }),
        });
        const data = await resp.json();
        if (!resp.ok) throw new Error(data.error);
        currentJobId = data.job_id;
        showToast('Geracao de todos iniciada', 'info');
    } catch (err) {
        showToast('Erro: ' + err.message, 'error');
        enableGenerateButtons();
    }
}

async function cancelJob() {
    if (!currentJobId) return;
    try {
        await fetch(`/api/job/${currentJobId}/cancel`, { method: 'POST' });
        showToast('Job cancelado', 'info');
    } catch (err) {
        showToast('Erro ao cancelar: ' + err.message, 'error');
    }
}

// ─────────────────────────────────────────────
// Job panel
// ─────────────────────────────────────────────
function showJobPanel(jobId) {
    const panel = document.getElementById('job-panel');
    if (panel) {
        panel.classList.remove('hidden');
        document.getElementById('job-panel-id').textContent = `#${jobId}`;
    }
}

function hideJobPanel() {
    const panel = document.getElementById('job-panel');
    if (panel) panel.classList.add('hidden');
}

function updateJobProgress(completed, total, errors) {
    const pct = total > 0 ? Math.round((completed / total) * 100) : 0;
    const bar = document.getElementById('job-progress-bar');
    const text = document.getElementById('job-progress-text');
    const errText = document.getElementById('job-error-text');

    if (bar) bar.style.width = pct + '%';
    if (text) text.textContent = `${completed} de ${total} concluidos`;
    if (errText) errText.textContent = errors > 0 ? `${errors} erro(s)` : '';
}

function onJobComplete(data) {
    const hasErrors = data.errors > 0;
    showToast(
        `Geracao concluida: ${data.completed} clientes, ${data.errors} erro(s)`,
        hasErrors ? 'error' : 'success'
    );
    enableGenerateButtons();
    setTimeout(() => {
        hideJobPanel();
        loadClients(); // Refresh to show updated statuses
    }, 2000);
}

function disableGenerateButtons() {
    ['btn-generate-selected', 'btn-generate-all', 'btn-generate-single'].forEach(id => {
        const btn = document.getElementById(id);
        if (btn) btn.disabled = true;
    });
}

function enableGenerateButtons() {
    ['btn-generate-selected', 'btn-generate-all', 'btn-generate-single'].forEach(id => {
        const btn = document.getElementById(id);
        if (btn) btn.disabled = false;
    });
    updateSelectedCount(); // Re-check selected count for the selected button
}

// ─────────────────────────────────────────────
// Client row update
// ─────────────────────────────────────────────
function updateClientRow(clientName, status, presentationUrl) {
    const row = document.querySelector(`tr[data-client="${CSS.escape(clientName)}"]`);
    if (!row) return;
    const badge = row.querySelector('.status-badge');
    if (badge) {
        badge.textContent = status;
        badge.className = `status-badge ${getStatusClass(status)}`;
    }
    // Show presentation link if available
    if (presentationUrl) {
        const actionsCell = row.querySelector('.actions-cell');
        if (actionsCell) {
            const existingLink = actionsCell.querySelector('.report-link');
            if (!existingLink) {
                actionsCell.insertAdjacentHTML('beforeend',
                    ` <a href="${escapeHtml(presentationUrl)}" target="_blank" class="report-link text-xs text-green-700 hover:text-green-900 font-medium ml-2">Abrir Relatorio</a>`
                );
            }
        }
    }
    row.classList.add('status-update-flash');
    setTimeout(() => row.classList.remove('status-update-flash'), 600);
}

// ─────────────────────────────────────────────
// History
// ─────────────────────────────────────────────
async function loadHistory() {
    const loading = document.getElementById('history-loading');
    const empty = document.getElementById('history-empty');
    const container = document.getElementById('history-container');

    if (!container) return;

    if (loading) loading.classList.remove('hidden');
    if (empty) empty.classList.add('hidden');
    container.classList.add('hidden');

    try {
        const resp = await fetch('/api/history');
        const jobs = await resp.json();

        if (loading) loading.classList.add('hidden');

        if (!jobs.length) {
            if (empty) empty.classList.remove('hidden');
            return;
        }

        container.classList.remove('hidden');
        container.innerHTML = jobs.map(job => `
            <div class="bg-white rounded-xl shadow-sm overflow-hidden">
                <div class="p-4 cursor-pointer hover:bg-gray-50 transition" onclick="toggleHistoryDetail('${job.id}')">
                    <div class="flex items-center justify-between">
                        <div class="flex items-center gap-4">
                            <span class="status-badge ${getStatusClass(job.status)}">${escapeHtml(job.status)}</span>
                            <span class="text-sm font-medium text-gray-800">${escapeHtml(job.freq)}</span>
                            <span class="text-sm text-gray-500">${formatDate(job.created_at)}</span>
                        </div>
                        <div class="flex items-center gap-4 text-sm text-gray-600">
                            <span>${job.completed}/${job.total} clientes</span>
                            ${job.errors > 0 ? `<span class="text-red-600">${job.errors} erro(s)</span>` : ''}
                            <span class="text-gray-400">por ${escapeHtml(job.started_by || '-')}</span>
                            <span class="text-gray-400">&#9660;</span>
                        </div>
                    </div>
                </div>
                <div id="history-detail-${job.id}" class="history-details border-t border-gray-100">
                    <div class="p-4">
                        <table class="w-full text-sm">
                            <thead>
                                <tr class="text-left text-xs text-gray-500">
                                    <th class="pb-2">Cliente</th>
                                    <th class="pb-2">Categoria</th>
                                    <th class="pb-2">Status</th>
                                    <th class="pb-2">Relatorio</th>
                                    <th class="pb-2">Erro</th>
                                </tr>
                            </thead>
                            <tbody>
                                ${(job.results || []).map(r => `
                                    <tr class="border-t border-gray-50">
                                        <td class="py-2 font-medium text-gray-700">${escapeHtml(r.client_name)}</td>
                                        <td class="py-2 text-gray-500">${escapeHtml(r.category || '-')}</td>
                                        <td class="py-2"><span class="status-badge ${getStatusClass(r.status)}">${escapeHtml(r.status)}</span></td>
                                        <td class="py-2">${r.presentation_url ? `<a href="${escapeHtml(r.presentation_url)}" target="_blank" class="text-xs text-green-700 hover:text-green-900 font-medium">Abrir</a>` : '-'}</td>
                                        <td class="py-2 text-red-600 text-xs">${escapeHtml(r.error_detail || '')}</td>
                                    </tr>
                                `).join('')}
                            </tbody>
                        </table>
                    </div>
                </div>
            </div>
        `).join('');
    } catch (err) {
        if (loading) loading.classList.add('hidden');
        showToast('Erro ao carregar historico: ' + err.message, 'error');
    }
}

function toggleHistoryDetail(jobId) {
    const el = document.getElementById(`history-detail-${jobId}`);
    if (el) el.classList.toggle('open');
}

// ─────────────────────────────────────────────
// Logs
// ─────────────────────────────────────────────
async function loadLogs() {
    const client = document.getElementById('log-client-filter')?.value || '';
    const level = document.getElementById('log-level-filter')?.value || '';
    const lines = document.getElementById('log-lines')?.value || '200';
    const output = document.getElementById('log-output');

    if (!output) return;

    try {
        const params = new URLSearchParams({ client, level, lines });
        const resp = await fetch(`/api/logs?${params}`);
        const logLines = await resp.json();
        output.textContent = logLines.length ? logLines.join('\n') : 'Nenhum log encontrado.';
    } catch (err) {
        output.textContent = 'Erro ao carregar logs: ' + err.message;
    }
}

async function loadClientLogs(clientName) {
    const output = document.getElementById('client-logs');
    if (!output) return;
    try {
        const params = new URLSearchParams({ client: clientName, lines: '100' });
        const resp = await fetch(`/api/logs?${params}`);
        const logLines = await resp.json();
        output.textContent = logLines.length ? logLines.join('\n') : 'Nenhum log encontrado para este cliente.';
    } catch (err) {
        output.textContent = 'Erro ao carregar logs: ' + err.message;
    }
}

// ─────────────────────────────────────────────
// Client detail
// ─────────────────────────────────────────────
async function loadClientDetail(clientName) {
    const infoEl = document.getElementById('client-info');
    const histEl = document.getElementById('client-history');

    // Load client info from API
    try {
        const resp = await fetch('/api/clients');
        const clients = await resp.json();
        const client = clients.find(c => c.nome === clientName);

        if (client && infoEl) {
            infoEl.innerHTML = `
                <div class="flex justify-between"><span class="text-gray-500">Categoria</span><span class="font-medium">${escapeHtml(client.categoria)}</span></div>
                <div class="flex justify-between"><span class="text-gray-500">Status</span><span class="status-badge ${getStatusClass(client.status)}">${escapeHtml(client.status || '-')}</span></div>
                <div class="flex justify-between"><span class="text-gray-500">Ultima Geracao</span><span class="font-medium">${escapeHtml(client.ultima_geracao || '-')}</span></div>
                ${client.painel_url ? `<div><span class="text-gray-500">Painel</span><br><a href="${escapeHtml(client.painel_url)}" target="_blank" class="text-xs text-primary-600 hover:text-primary-800 break-all">Abrir painel</a></div>` : ''}
                ${client.pasta_url ? `<div><span class="text-gray-500">Pasta</span><br><a href="${escapeHtml(client.pasta_url)}" target="_blank" class="text-xs text-primary-600 hover:text-primary-800 break-all">Abrir pasta</a></div>` : ''}
                <div class="flex justify-between"><span class="text-gray-500">Google Ads</span><span class="text-xs font-mono">${escapeHtml(client.id_google_ads || '-')}</span></div>
                <div class="flex justify-between"><span class="text-gray-500">Meta Ads</span><span class="text-xs font-mono">${escapeHtml(client.id_meta_ads || '-')}</span></div>
                <div class="flex justify-between"><span class="text-gray-500">GA4</span><span class="text-xs font-mono">${escapeHtml(client.id_ga4 || '-')}</span></div>
            `;
        }
    } catch (err) {
        if (infoEl) infoEl.innerHTML = `<p class="text-red-500 text-sm">Erro ao carregar: ${escapeHtml(err.message)}</p>`;
    }

    // Load client history
    try {
        const resp = await fetch(`/api/history`);
        const jobs = await resp.json();
        const clientResults = [];
        for (const job of jobs) {
            for (const r of (job.results || [])) {
                if (r.client_name === clientName) {
                    clientResults.push({ ...r, freq: job.freq, job_date: job.created_at });
                }
            }
        }

        if (histEl) {
            if (!clientResults.length) {
                histEl.innerHTML = '<p class="text-gray-500 text-sm">Nenhuma geracao registrada.</p>';
            } else {
                histEl.innerHTML = `
                    <table class="w-full text-sm">
                        <thead><tr class="text-left text-xs text-gray-500">
                            <th class="pb-2">Data</th><th class="pb-2">Freq</th><th class="pb-2">Status</th><th class="pb-2">Erro</th>
                        </tr></thead>
                        <tbody>
                            ${clientResults.map(r => `
                                <tr class="border-t border-gray-100">
                                    <td class="py-2 text-gray-600">${formatDate(r.job_date)}</td>
                                    <td class="py-2 text-gray-600">${escapeHtml(r.freq)}</td>
                                    <td class="py-2"><span class="status-badge ${getStatusClass(r.status)}">${escapeHtml(r.status)}</span></td>
                                    <td class="py-2 text-red-600 text-xs">${escapeHtml(r.error_detail || '')}</td>
                                </tr>
                            `).join('')}
                        </tbody>
                    </table>
                `;
            }
        }
    } catch (err) {
        if (histEl) histEl.innerHTML = `<p class="text-red-500 text-sm">Erro: ${escapeHtml(err.message)}</p>`;
    }
}

// ─────────────────────────────────────────────
// Edit client modal
// ─────────────────────────────────────────────
function openEditModal(clientName) {
    const client = allClients.find(c => c.nome === clientName);
    if (!client) return;

    const modal = document.getElementById('edit-modal');
    if (!modal) return;

    // Fill standard fields
    document.getElementById('edit-original-nome').value = client.nome;
    document.getElementById('edit-nome').value = client.nome;
    document.getElementById('edit-categoria').value = client.categoria;
    document.getElementById('edit-painel_url').value = client.painel_url || '';
    document.getElementById('edit-pasta_url').value = client.pasta_url || '';
    document.getElementById('edit-id_google_ads').value = client.id_google_ads || '';
    document.getElementById('edit-id_meta_ads').value = client.id_meta_ads || '';
    document.getElementById('edit-id_ga4').value = client.id_ga4 || '';

    // Render extra fields dynamically
    const extrasContainer = document.getElementById('edit-extras-container');
    extrasContainer.innerHTML = '';
    if (client.extras && Object.keys(client.extras).length > 0) {
        extrasContainer.innerHTML = '<div class="border-t border-gray-200 pt-3 mt-2"><p class="text-xs font-semibold text-gray-500 uppercase mb-3">Campos adicionais</p></div>';
        for (const [key, value] of Object.entries(client.extras)) {
            const fieldId = `edit-extra-${key.replace(/[^a-zA-Z0-9]/g, '_')}`;
            extrasContainer.innerHTML += `
                <div class="mb-3">
                    <label class="block text-sm font-medium text-gray-700 mb-1">${escapeHtml(key)}</label>
                    <input type="text" id="${fieldId}" data-extra-key="${escapeHtml(key)}" value="${escapeHtml(value || '')}"
                           class="w-full px-3 py-2 border border-gray-300 rounded-lg text-sm focus:ring-2 focus:ring-primary-500 outline-none">
                </div>
            `;
        }
    }

    modal.classList.remove('hidden');
    modal.classList.add('flex');
}

function closeEditModal() {
    const modal = document.getElementById('edit-modal');
    if (modal) {
        modal.classList.add('hidden');
        modal.classList.remove('flex');
    }
}

async function saveClient(event) {
    event.preventDefault();
    const originalNome = document.getElementById('edit-original-nome').value;
    const btn = document.getElementById('btn-save-client');
    btn.disabled = true;
    btn.textContent = 'Salvando...';

    // Collect standard fields
    const data = {
        nome: document.getElementById('edit-nome').value.trim(),
        categoria: document.getElementById('edit-categoria').value,
        painel_url: document.getElementById('edit-painel_url').value.trim(),
        pasta_url: document.getElementById('edit-pasta_url').value.trim(),
        id_google_ads: document.getElementById('edit-id_google_ads').value.trim(),
        id_meta_ads: document.getElementById('edit-id_meta_ads').value.trim(),
        id_ga4: document.getElementById('edit-id_ga4').value.trim(),
    };

    // Collect extra fields
    document.querySelectorAll('[data-extra-key]').forEach(input => {
        const key = input.getAttribute('data-extra-key');
        data[key] = input.value.trim();
    });

    try {
        const resp = await fetch(`/api/client/${encodeURIComponent(originalNome)}`, {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(data),
        });
        const result = await resp.json();
        if (!resp.ok) throw new Error(result.error);

        showToast(`Cliente "${originalNome}" atualizado com sucesso`, 'success');
        closeEditModal();
        loadClients(); // Refresh the table
    } catch (err) {
        showToast('Erro ao salvar: ' + err.message, 'error');
    } finally {
        btn.disabled = false;
        btn.textContent = 'Salvar';
    }
}

// Close modal on Escape key or backdrop click
document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape') closeEditModal();
});
document.addEventListener('click', (e) => {
    const modal = document.getElementById('edit-modal');
    if (e.target === modal) closeEditModal();
});

// ─────────────────────────────────────────────
// Utilities
// ─────────────────────────────────────────────
function getStatusClass(status) {
    if (!status) return 'status-pendente';
    const s = status.toUpperCase();
    if (s.includes('GERADO') || s === 'SUCESSO' || s === 'CONCLUIDO') return 'status-gerado';
    if (s.includes('PROCESSANDO') || s === 'EM EXECUCAO' || s === 'AGUARDANDO') return 'status-processando';
    if (s.includes('ERRO') || s.includes('EXCEPTION') || s === 'FAILED') return 'status-erro';
    if (s === 'IGNORADO' || s === 'CANCELADO') return 'status-ignorado';
    return 'status-pendente';
}

function escapeHtml(str) {
    if (!str) return '';
    const div = document.createElement('div');
    div.textContent = str;
    return div.innerHTML;
}

function formatDate(isoStr) {
    if (!isoStr) return '-';
    try {
        const d = new Date(isoStr);
        return d.toLocaleDateString('pt-BR') + ' ' + d.toLocaleTimeString('pt-BR', { hour: '2-digit', minute: '2-digit' });
    } catch {
        return isoStr;
    }
}

function showToast(message, type = 'info') {
    const container = document.getElementById('toast-container');
    if (!container) return;
    const toast = document.createElement('div');
    toast.className = `toast toast-${type}`;
    toast.textContent = message;
    container.appendChild(toast);
    setTimeout(() => {
        toast.style.opacity = '0';
        toast.style.transition = 'opacity 0.3s';
        setTimeout(() => toast.remove(), 300);
    }, 5000);
}
