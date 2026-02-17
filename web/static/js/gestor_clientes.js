/* Auto Report - Gestor Clientes Page JavaScript */

let _allClientes = [];

// ─────────────────────────────────────────────
// Role detection (same pattern as gestor.js)
// ─────────────────────────────────────────────
function _getRole() {
    const el = document.getElementById('clientes-app');
    return el ? el.dataset.role : 'admin';
}
function _getGestorName() {
    const el = document.getElementById('clientes-app');
    return el ? el.dataset.gestorName : '';
}
function _isGestor() { return _getRole() === 'gestor'; }

// ─────────────────────────────────────────────
// Load clients
// ─────────────────────────────────────────────
async function loadGestorClientes() {
    const loading = document.getElementById('clientes-loading');
    const empty = document.getElementById('clientes-empty');
    const table = document.getElementById('clientes-table-container');

    [loading, empty, table].forEach(el => { if (el) el.classList.add('hidden'); });
    if (loading) loading.classList.remove('hidden');

    // Hide gestor field in add modal for gestor role
    if (_isGestor()) {
        const gestorGroup = document.getElementById('add-gestor-group');
        if (gestorGroup) gestorGroup.classList.add('hidden');
    }

    try {
        const resp = await fetch('/api/clients');
        const data = await resp.json();

        if (loading) loading.classList.add('hidden');

        // Filter by gestor if gestor role
        if (_isGestor()) {
            const gn = _getGestorName().toLowerCase();
            _allClientes = data.filter(c => (c.gestor || '').toLowerCase() === gn);
        } else {
            _allClientes = data;
        }

        renderClientesTable();
    } catch (err) {
        if (loading) loading.classList.add('hidden');
        showToast('Erro ao carregar clientes: ' + err.message, 'error');
    }
}

// ─────────────────────────────────────────────
// Render table
// ─────────────────────────────────────────────
function renderClientesTable() {
    const empty = document.getElementById('clientes-empty');
    const table = document.getElementById('clientes-table-container');
    const tbody = document.getElementById('clientes-tbody');
    const countEl = document.getElementById('clientes-count');

    // Apply filters
    const search = (document.getElementById('clientes-search')?.value || '').toLowerCase().trim();
    const cat = document.getElementById('clientes-cat-filter')?.value || '';

    let filtered = _allClientes;
    if (search) {
        filtered = filtered.filter(c => (c.nome || '').toLowerCase().includes(search));
    }
    if (cat) {
        filtered = filtered.filter(c => (c.categoria || '') === cat);
    }

    if (countEl) countEl.textContent = `${filtered.length} cliente(s)`;

    if (filtered.length === 0) {
        if (table) table.classList.add('hidden');
        if (empty) empty.classList.remove('hidden');
        return;
    }

    if (empty) empty.classList.add('hidden');
    if (table) table.classList.remove('hidden');

    tbody.innerHTML = filtered.map(c => {
        const painelIcon = c.painel_url
            ? `<a href="${escapeHtml(c.painel_url)}" target="_blank" class="text-primary-500 hover:text-primary-400 transition" title="Abrir painel">
                   <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M10 6H6a2 2 0 00-2 2v10a2 2 0 002 2h10a2 2 0 002-2v-4M14 4h6m0 0v6m0-6L10 14"/></svg>
               </a>`
            : '<span class="text-surface-300 dark:text-surface-600">-</span>';

        const pastaIcon = c.pasta_url
            ? `<a href="${escapeHtml(c.pasta_url)}" target="_blank" class="text-amber-500 hover:text-amber-400 transition" title="Abrir pasta">
                   <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M3 7v10a2 2 0 002 2h14a2 2 0 002-2V9a2 2 0 00-2-2h-6l-2-2H5a2 2 0 00-2 2z"/></svg>
               </a>`
            : '<span class="text-surface-300 dark:text-surface-600">-</span>';

        return `
        <tr class="clientes-row">
            <td class="px-4 py-3">
                <a href="/client/${encodeURIComponent(c.nome)}" class="text-sm font-medium text-primary-600 hover:text-primary-500">${escapeHtml(c.nome)}</a>
            </td>
            <td class="px-4 py-3">
                <span class="text-xs px-2 py-0.5 rounded-full ${_catClass(c.categoria)}">${escapeHtml(c.categoria || '-')}</span>
            </td>
            <td class="px-4 py-3 text-center">${painelIcon}</td>
            <td class="px-4 py-3 text-center">${pastaIcon}</td>
            <td class="px-4 py-3 text-xs font-mono text-surface-500 dark:text-surface-400">${escapeHtml(c.id_google_ads || '-')}</td>
            <td class="px-4 py-3 text-xs font-mono text-surface-500 dark:text-surface-400">${escapeHtml(c.id_meta_ads || '-')}</td>
            <td class="px-4 py-3 text-xs font-mono text-surface-500 dark:text-surface-400">${escapeHtml(c.id_ga4 || '-')}</td>
            <td class="px-4 py-3 text-center">
                <button onclick="openEditModal('${escapeHtml(c.nome)}')"
                        class="p-1.5 rounded-lg hover:bg-surface-100 dark:hover:bg-surface-800 text-surface-400 hover:text-primary-500 transition"
                        title="Editar">
                    <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M11 5H6a2 2 0 00-2 2v11a2 2 0 002 2h11a2 2 0 002-2v-5m-1.414-9.414a2 2 0 112.828 2.828L11.828 15H9v-2.828l8.586-8.586z"/></svg>
                </button>
            </td>
        </tr>`;
    }).join('');
}

function _catClass(cat) {
    if (!cat) return 'bg-surface-100 dark:bg-surface-800 text-surface-400';
    const c = cat.toLowerCase();
    if (c === 'e-commerce') return 'bg-emerald-100 dark:bg-emerald-900/30 text-emerald-600 dark:text-emerald-400';
    if (c.startsWith('lead')) return 'bg-blue-100 dark:bg-blue-900/30 text-blue-600 dark:text-blue-400';
    return 'bg-surface-100 dark:bg-surface-800 text-surface-500';
}

function filterClientes() {
    renderClientesTable();
}

// ─────────────────────────────────────────────
// Add Client Modal
// ─────────────────────────────────────────────
function openAddModal() {
    document.getElementById('add-nome').value = '';
    document.getElementById('add-categoria').value = '';
    document.getElementById('add-gestor').value = _isGestor() ? _getGestorName() : '';
    document.getElementById('add-painel-url').value = '';
    document.getElementById('add-pasta-url').value = '';
    document.getElementById('add-id-google').value = '';
    document.getElementById('add-id-meta').value = '';
    document.getElementById('add-id-ga4').value = '';

    document.getElementById('add-client-modal').classList.remove('hidden');
}

function closeAddModal() {
    document.getElementById('add-client-modal').classList.add('hidden');
}

async function saveNewClient(event) {
    event.preventDefault();

    const body = {
        nome: document.getElementById('add-nome').value.trim(),
        categoria: document.getElementById('add-categoria').value,
        gestor: document.getElementById('add-gestor').value.trim(),
        painel_url: document.getElementById('add-painel-url').value.trim(),
        pasta_url: document.getElementById('add-pasta-url').value.trim(),
        id_google_ads: document.getElementById('add-id-google').value.trim(),
        id_meta_ads: document.getElementById('add-id-meta').value.trim(),
        id_ga4: document.getElementById('add-id-ga4').value.trim(),
    };

    if (!body.nome) {
        showToast('Nome do cliente e obrigatorio', 'error');
        return;
    }

    try {
        const resp = await fetch('/api/clients', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(body),
        });
        const data = await resp.json();
        if (!resp.ok) throw new Error(data.error || 'Erro ao cadastrar');

        showToast(`Cliente "${data.nome}" cadastrado!`, 'success');
        closeAddModal();
        loadGestorClientes();
    } catch (err) {
        showToast('Erro: ' + err.message, 'error');
    }
}

// ─────────────────────────────────────────────
// Edit Client Modal
// ─────────────────────────────────────────────
function openEditModal(clientName) {
    const c = _allClientes.find(x => x.nome === clientName);
    if (!c) return;

    document.getElementById('edit-original-nome').value = c.nome;
    document.getElementById('edit-nome').value = c.nome;
    document.getElementById('edit-categoria').value = c.categoria || '';
    document.getElementById('edit-painel-url').value = c.painel_url || '';
    document.getElementById('edit-pasta-url').value = c.pasta_url || '';
    document.getElementById('edit-id-google').value = c.id_google_ads || '';
    document.getElementById('edit-id-meta').value = c.id_meta_ads || '';
    document.getElementById('edit-id-ga4').value = c.id_ga4 || '';

    document.getElementById('edit-client-modal').classList.remove('hidden');
}

function closeEditModal() {
    document.getElementById('edit-client-modal').classList.add('hidden');
}

async function saveEditClient(event) {
    event.preventDefault();

    const nome = document.getElementById('edit-original-nome').value;
    const body = {
        categoria: document.getElementById('edit-categoria').value,
        painel_url: document.getElementById('edit-painel-url').value.trim(),
        pasta_url: document.getElementById('edit-pasta-url').value.trim(),
        id_google_ads: document.getElementById('edit-id-google').value.trim(),
        id_meta_ads: document.getElementById('edit-id-meta').value.trim(),
        id_ga4: document.getElementById('edit-id-ga4').value.trim(),
    };

    try {
        const resp = await fetch(`/api/client/${encodeURIComponent(nome)}/pg`, {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(body),
        });
        const data = await resp.json();
        if (!resp.ok) throw new Error(data.error || 'Erro ao salvar');

        showToast(`"${data.updated}" atualizado!`, 'success');
        closeEditModal();
        loadGestorClientes();
    } catch (err) {
        showToast('Erro: ' + err.message, 'error');
    }
}
