// Зчитуємо користувача з Telegram WebApp, URL-параметра або meta-тега
const tg = window.Telegram && window.Telegram.WebApp ? window.Telegram.WebApp : null;
if (tg) {
    try { tg.ready(); tg.expand(); } catch(e) {}
}

const tgUser = tg && tg.initDataUnsafe && tg.initDataUnsafe.user ? tg.initDataUnsafe.user : null;
const urlParams = new URLSearchParams(window.location.search);
const metaUserId = document.querySelector('meta[name="user-id"]')?.content;

let userId = tgUser ? tgUser.id : (urlParams.get('user_id') || (metaUserId && metaUserId !== 'None' ? metaUserId : null));

function goToMainPage() {
    if (userId) {
        window.location.href = `/?user_id=${userId}`;
    } else {
        window.location.href = '/';
    }
}

// Авторизований виклик API
async function fetchWithAuth(url, options = {}) {
    if (!options.headers) options.headers = {};
    
    if (userId) {
        if (options.headers instanceof Headers) {
            options.headers.set('x-telegram-user-id', userId);
        } else {
            options.headers['x-telegram-user-id'] = userId;
        }
    }

    try {
        const res = await fetch(url, options);
        if (res.status === 401 || res.status === 403) {
            window.location.href = '/login';
            return null;
        }
        return res;
    } catch (err) {
        console.error('Помилка запиту:', err);
        return null;
    }
}

function switchTab(tabId) {
    document.querySelectorAll('.tab-content').forEach(el => el.classList.remove('active'));
    document.querySelectorAll('.tab-btn').forEach(el => el.classList.remove('active'));
    
    document.getElementById(tabId).classList.add('active');
    event.currentTarget.classList.add('active');
    
    if (tabId === 'users') loadUsers();
    if (tabId === 'centers') loadCenters();
    if (tabId === 'categories') loadCategories();
    if (tabId === 'matrix') loadMatrix();
    if (tabId === 'cash') loadCash();
    if (tabId === 'ai') loadAiModels();
}

let allCenters = [];

async function loadCenters() {
    const res = await fetchWithAuth('/api/admin/centers');
    if (!res || !res.ok) return false;

    const data = await res.json();
    if (data.status === 'ok') {
        allCenters = data.data;
        const tbody = document.querySelector('#centers-table tbody');
        if (tbody) {
            tbody.innerHTML = '';
            data.data.forEach(c => {
                const tr = document.createElement('tr');
                tr.innerHTML = `
                    <td>${c.id}</td>
                    <td>${c.name}</td>
                    <td>${c.city || ''}</td>
                    <td>${c.is_active ? 'Активний' : 'Неактивний'}</td>
                    <td>
                        <button onclick="editCenter(${c.id}, '${c.name.replace(/'/g, "\\'")}', '${(c.city || '').replace(/'/g, "\\'")}', ${c.is_active})">Редагувати</button>
                    </td>
                `;
                tbody.appendChild(tr);
            });
        }
        
        // Заповнюємо випадаючий список для модального вікна
        const select = document.getElementById('u-center-select');
        if (select) {
            select.innerHTML = '<option value="">-- Не призначено --</option>';
            data.data.filter(c => c.is_active).forEach(c => {
                select.innerHTML += `<option value="${c.id}">${c.name}</option>`;
            });
        }
        return true;
    }
    return false;
}

async function loadUsers() {
    const res = await fetchWithAuth('/api/admin/users');
    if (!res || !res.ok) return false;

    const data = await res.json();
    if (data.status === 'ok') {
        const tbody = document.querySelector('#users-table tbody');
        if (tbody) {
            tbody.innerHTML = '';
            data.data.forEach(u => {
                const tr = document.createElement('tr');
                tr.innerHTML = `
                    <td>${u.name}</td>
                    <td>${u.city || ''}</td>
                    <td>${u.telegram_id}</td>
                    <td>${u.role}</td>
                    <td>${u.status}</td>
                    <td>${u.center_name || '—'}</td>
                    <td>
                        <button onclick="openUserModal(${u.telegram_id}, '${u.name.replace(/'/g, "\\'")}', ${u.center_id || "''"})">Призначити ЦН</button>
                    </td>
                `;
                tbody.appendChild(tr);
            });
        }
        return true;
    }
    return false;
}

// Модальне вікно центрів
function openCenterModal() {
    document.getElementById('c-id').value = '';
    document.getElementById('c-name').value = '';
    document.getElementById('c-city').value = '';
    document.getElementById('c-status').value = '1';
    document.getElementById('center-modal-title').innerText = 'Додати ЦН';
    document.getElementById('center-modal').style.display = 'block';
}

function editCenter(id, name, city, isActive) {
    document.getElementById('c-id').value = id;
    document.getElementById('c-name').value = name;
    document.getElementById('c-city').value = city;
    document.getElementById('c-status').value = isActive ? '1' : '0';
    document.getElementById('center-modal-title').innerText = 'Редагувати ЦН';
    document.getElementById('center-modal').style.display = 'block';
}

function closeCenterModal() {
    document.getElementById('center-modal').style.display = 'none';
}

async function saveCenter() {
    const id = document.getElementById('c-id').value;
    const name = document.getElementById('c-name').value;
    const city = document.getElementById('c-city').value;
    const isActive = parseInt(document.getElementById('c-status').value);
    
    if (!name) return alert('Назва обов\'язкова');
    
    const url = id ? `/api/admin/centers/${id}` : '/api/admin/centers';
    const method = id ? 'PUT' : 'POST';
    
    const res = await fetchWithAuth(url, {
        method: method,
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({name, city, is_active: isActive})
    });
    
    if (res && res.ok) {
        closeCenterModal();
        loadCenters();
    } else if (res) {
        alert('Помилка збереження');
    }
}

// Модальне вікно користувачів
function openUserModal(userId, userName, centerId) {
    document.getElementById('u-id').value = userId;
    document.getElementById('u-name-display').innerText = userName;
    document.getElementById('u-center-select').value = centerId || '';
    document.getElementById('user-modal').style.display = 'block';
}

function closeUserModal() {
    document.getElementById('user-modal').style.display = 'none';
}

async function saveUserCenter() {
    const userId = document.getElementById('u-id').value;
    const centerVal = document.getElementById('u-center-select').value;
    const centerId = centerVal ? parseInt(centerVal) : null;
    
    const res = await fetchWithAuth(`/api/admin/users/${userId}/center`, {
        method: 'PUT',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({center_id: centerId})
    });
    
    if (res && res.ok) {
        closeUserModal();
        loadUsers();
    } else if (res) {
        alert('Помилка оновлення');
    }
}

// Категорії
async function loadCategories() {
    const res = await fetchWithAuth('/api/admin/categories');
    if (!res || !res.ok) return;

    const data = await res.json();
    if (data.status === 'ok') {
        const tbody = document.querySelector('#categories-table tbody');
        if (tbody) {
            tbody.innerHTML = '';
            data.data.forEach(c => {
                const tr = document.createElement('tr');
                tr.innerHTML = `
                    <td>${c.id}</td>
                    <td>${c.name}</td>
                    <td>${c.sort_order}</td>
                    <td>${c.is_active ? 'Активна' : 'Неактивна'}</td>
                    <td>
                        <button onclick="editCategory('${c.id}', '${c.name.replace(/'/g, "\\'")}', ${c.sort_order}, ${c.is_active})">Редагувати</button>
                    </td>
                `;
                tbody.appendChild(tr);
            });
        }
    }
}

let isEditingCategory = false;

function openCategoryModal() {
    isEditingCategory = false;
    document.getElementById('cat-id').value = 'cat_';
    document.getElementById('cat-id').disabled = false;
    document.getElementById('cat-name').value = '';
    document.getElementById('cat-sort').value = '999';
    document.getElementById('cat-status').value = '1';
    document.getElementById('category-modal-title').innerText = 'Додати Категорію';
    document.getElementById('category-modal').style.display = 'block';
}

function editCategory(id, name, sortOrder, isActive) {
    isEditingCategory = true;
    document.getElementById('cat-id').value = id;
    document.getElementById('cat-id').disabled = true;
    document.getElementById('cat-name').value = name;
    document.getElementById('cat-sort').value = sortOrder;
    document.getElementById('cat-status').value = isActive ? '1' : '0';
    document.getElementById('category-modal-title').innerText = 'Редагувати Категорію';
    document.getElementById('category-modal').style.display = 'block';
}

function closeCategoryModal() {
    document.getElementById('category-modal').style.display = 'none';
}

async function saveCategory() {
    const id = document.getElementById('cat-id').value.trim();
    const name = document.getElementById('cat-name').value.trim();
    const sortOrder = parseInt(document.getElementById('cat-sort').value) || 999;
    const isActive = parseInt(document.getElementById('cat-status').value);
    
    if (!id || !name) return alert('ID та Назва обов\'язкові');
    if (!id.startsWith('cat_') && !isEditingCategory) return alert('ID має починатися з cat_');
    
    const url = isEditingCategory ? `/api/admin/categories/${id}` : '/api/admin/categories';
    const method = isEditingCategory ? 'PUT' : 'POST';
    
    const res = await fetchWithAuth(url, {
        method: method,
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({id, name, sort_order: sortOrder, is_active: isActive})
    });
    
    if (res && res.ok) {
        closeCategoryModal();
        loadCategories();
    } else if (res) {
        alert('Помилка збереження. Можливо, такий ID вже існує.');
    }
}

// Матриця
async function loadMatrix() {
    const res = await fetchWithAuth('/api/admin/matrix');
    if (!res || !res.ok) return;

    const data = await res.json();
    if (data.status === 'ok') {
        const centers = data.data.centers;
        const categories = data.data.categories;
        const links = data.data.links;
        
        const headerRow = document.getElementById('matrix-header');
        if (headerRow) {
            headerRow.innerHTML = '<th>Центр Надії \\ Категорії</th>';
            categories.forEach(cat => {
                headerRow.innerHTML += `<th>${cat.name}</th>`;
            });
        }
        
        const tbody = document.getElementById('matrix-body');
        if (tbody) {
            tbody.innerHTML = '';
            centers.forEach(center => {
                const tr = document.createElement('tr');
                tr.innerHTML = `<td><strong>${center.name}</strong></td>`;
                
                categories.forEach(cat => {
                    const isChecked = links.some(l => l.center_id === center.id && l.category_id === cat.id);
                    tr.innerHTML += `
                        <td style="text-align: center;">
                            <input type="checkbox" style="transform: scale(1.5); cursor: pointer;" 
                                ${isChecked ? 'checked' : ''} 
                                onchange="toggleMatrix(${center.id}, '${cat.id}', this.checked)">
                        </td>
                    `;
                });
                
                tbody.appendChild(tr);
            });
        }
    }
}

async function toggleMatrix(centerId, categoryId, isEnabled) {
    const res = await fetchWithAuth('/api/admin/matrix/toggle', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({
            center_id: centerId,
            category_id: categoryId,
            is_enabled: isEnabled
        })
    });
    
    if (!res || !res.ok) {
        alert('Помилка оновлення матриці');
        loadMatrix();
    }
}

// ==========================================
// ШІ-МОДЕЛІ (OPENROUTER)
// ==========================================
let allAiModels = [];

async function loadAiModels() {
    const res = await fetchWithAuth('/api/admin/ai');
    if (!res || !res.ok) return false;

    const data = await res.json();
    if (data.status !== 'ok') return false;

    allAiModels = data.data || [];
    const tbody = document.querySelector('#ai-table tbody');
    if (tbody) {
        tbody.innerHTML = '';
        if (!allAiModels.length) {
            tbody.innerHTML = '<tr><td colspan="8" style="text-align:center;">Ще не додано жодної моделі</td></tr>';
        }
        allAiModels.forEach(m => {
            const tr = document.createElement('tr');
            const activeLabel = m.is_active ? '<strong style="color:#4CAF50;">Так</strong>' : 'Ні';
            const keyLabel = m.has_key ? 'є' : '<span style="color:#f44336;">немає</span>';
            tr.innerHTML = `
                <td>${m.name}</td>
                <td>${m.model_id}</td>
                <td style="text-align:center;">${keyLabel}</td>
                <td style="text-align:center;">${activeLabel}</td>
                <td style="text-align:right;">${m.receipts}</td>
                <td style="text-align:right;">${m.total_tokens}</td>
                <td style="text-align:right;">${m.tokens_per_receipt}</td>
                <td>
                    <button onclick="editAiModel(${m.id})">Редагувати</button>
                    ${m.is_active ? '' : `<button onclick="activateAiModel(${m.id})" style="background:#4CAF50;color:#fff;">Активувати</button>`}
                    <button onclick="deleteAiModel(${m.id})" style="background:#f44336;color:#fff;">Видалити</button>
                </td>
            `;
            tbody.appendChild(tr);
        });
    }
    return true;
}

function openAiModal() {
    document.getElementById('ai-id').value = '';
    document.getElementById('ai-name').value = '';
    document.getElementById('ai-model-id').value = '';
    document.getElementById('ai-api-key').value = '';
    document.getElementById('ai-modal-title').innerText = 'Додати модель';
    document.getElementById('ai-modal').style.display = 'block';
}

function editAiModel(id) {
    const m = allAiModels.find(x => x.id === id);
    if (!m) return;
    document.getElementById('ai-id').value = m.id;
    document.getElementById('ai-name').value = m.name;
    document.getElementById('ai-model-id').value = m.model_id;
    document.getElementById('ai-api-key').value = '';
    document.getElementById('ai-modal-title').innerText = 'Редагувати модель';
    document.getElementById('ai-modal').style.display = 'block';
}

function closeAiModal() {
    document.getElementById('ai-modal').style.display = 'none';
}

async function saveAiModel() {
    const id = document.getElementById('ai-id').value;
    const name = document.getElementById('ai-name').value.trim();
    const modelId = document.getElementById('ai-model-id').value.trim();
    const apiKey = document.getElementById('ai-api-key').value.trim();

    if (!name || !modelId) return alert('Назва та ID моделі обов\'язкові');

    const url = id ? `/api/admin/ai/${id}` : '/api/admin/ai';
    const method = id ? 'PUT' : 'POST';
    const res = await fetchWithAuth(url, {
        method: method,
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({name: name, model_id: modelId, api_key: apiKey})
    });

    if (res && res.ok) {
        closeAiModal();
        loadAiModels();
    } else if (res) {
        alert('Помилка збереження моделі');
    }
}

async function activateAiModel(id) {
    const res = await fetchWithAuth(`/api/admin/ai/${id}/activate`, {method: 'POST'});
    if (res && res.ok) {
        loadAiModels();
    } else if (res) {
        alert('Помилка активації');
    }
}

async function deleteAiModel(id) {
    if (!confirm('Видалити цю модель?')) return;
    const res = await fetchWithAuth(`/api/admin/ai/${id}`, {method: 'DELETE'});
    if (res && res.ok) {
        loadAiModels();
    } else if (res) {
        alert('Помилка видалення');
    }
}

// ==========================================
// J. КОШТИ ЦН (КАСА) — етап 3: налаштування, видача, повернення, журнал
// ==========================================
let cashData = null;
let cashOpState = { centerId: null, kind: 'funding' };

const CASH_KIND_TITLES = {
    funding: 'Видати кошти',
    return: 'Повернути кошти',
    adjustment: 'Коригування залишку'
};

const CASH_KIND_HINTS = {
    funding: 'Збільшує залишок ЦН: адміністратор видав гроші центру.',
    return: 'Зменшує залишок: ЦН повернув невитрачені кошти.',
    adjustment: 'Може бути зі знаком мінус: −500 зменшить залишок, 500 — збільшить.'
};

function cashMoney(v) {
    if (v === null || v === undefined || v === '') return '—';
    return Number(v).toLocaleString('uk-UA', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

function cashEsc(text) {
    return String(text === null || text === undefined ? '' : text)
        .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;').replace(/'/g, '&#39;');
}

function cashPad(n) { return String(n).padStart(2, '0'); }

function cashMonth() {
    const el = document.getElementById('cash-month');
    if (el && !el.value) {
        const now = new Date();
        el.value = `${now.getFullYear()}-${cashPad(now.getMonth() + 1)}`;
    }
    return el ? el.value : '';
}

function cashToday() {
    const now = new Date();
    return `${now.getFullYear()}-${cashPad(now.getMonth() + 1)}-${cashPad(now.getDate())}`;
}

function cashRow(centerId) {
    if (!cashData || !cashData.rows) return null;
    return cashData.rows.find(r => r.center_id === centerId) || null;
}

async function cashApiError(res, fallback) {
    try {
        const body = await res.json();
        return body.detail || fallback;
    } catch (e) {
        return fallback;
    }
}

async function loadCash() {
    const month = cashMonth();
    const res = await fetchWithAuth(`/api/admin/cash/overview?month=${encodeURIComponent(month)}`);
    if (!res || !res.ok) return false;
    const body = await res.json();
    if (body.status !== 'ok') return false;
    cashData = body.data;
    renderCash();
    return true;
}

function renderCash() {
    const tbody = document.querySelector('#cash-table tbody');
    if (!tbody || !cashData) return;
    const d = cashData;
    tbody.innerHTML = '';

    if (!d.rows.length) {
        tbody.innerHTML = '<tr><td colspan="8" style="text-align:center; color:#888;">Центрів ще немає</td></tr>';
    }

    d.rows.forEach(r => {
        const started = !!(r.configured && r.start_month && r.start_month <= d.month);
        const closing = r.closing_balance;
        const negative = closing !== null && closing !== undefined && closing < 0;

        let state = '<span style="color:#f44336;">не налаштовано</span>';
        if (started) {
            state = r.status === 'closed'
                ? '<span style="color:#607D8B;">закритий</span>'
                : '<span style="color:#2e7d32;">відкритий</span>';
        }
        if (r.matches === false) {
            state += ' <span title="Розрахунок не збігається зі збереженим знімком">⚠️</span>';
        }

        const actions = started
            ? `<button type="button" class="btn-mini" onclick="openCashOpModal(${r.center_id}, 'funding')">Видати</button>
               <button type="button" class="btn-mini" onclick="openCashOpModal(${r.center_id}, 'return')">Повернути</button>
               <button type="button" class="btn-mini" onclick="openCashOpModal(${r.center_id}, 'adjustment')">±</button>
               <button type="button" class="btn-mini" onclick="openCashLedgerModal(${r.center_id})">Журнал</button>
               <button type="button" class="btn-mini" onclick="openCashSettingsModal(${r.center_id})">Налаштувати</button>`
            : `<button type="button" class="btn-mini" onclick="openCashSettingsModal(${r.center_id})">Налаштувати</button>`;

        const tr = document.createElement('tr');
        tr.innerHTML = `
            <td>${cashEsc(r.name)}${r.city ? `<div style="font-size:11px; color:#888;">${cashEsc(r.city)}</div>` : ''}</td>
            <td>${r.configured ? cashEsc(r.start_month) : '—'}</td>
            <td style="text-align:right;">${cashMoney(r.month_opening)}</td>
            <td style="text-align:right; color:#2e7d32;">${cashMoney(r.received)}</td>
            <td style="text-align:right; color:#c62828;">${cashMoney(r.spent)}</td>
            <td style="text-align:right; font-weight:bold; ${negative ? 'color:#f44336;' : ''}">${cashMoney(closing)}</td>
            <td>${state}</td>
            <td style="white-space:nowrap;">${actions}</td>
        `;
        tbody.appendChild(tr);
    });

    const totals = d.totals || {};
    const line = document.getElementById('cash-summary-line');
    if (line) {
        line.innerHTML = `Надійшло: ${cashMoney(totals.received)} · Витрачено: ${cashMoney(totals.spent)} · Залишок: ${cashMoney(totals.closing_balance)} грн`;
    }

    const warnings = document.getElementById('cash-warnings');
    if (warnings) {
        let html = '';
        if (d.negative && d.negative.length) {
            const names = d.negative
                .map(n => `${cashEsc(n.name)} (${cashMoney(n.closing_balance)} грн)`)
                .join(', ');
            html += `<div style="padding:8px 12px; border-left:4px solid #f44336; background:#ffebee; margin-bottom:8px;">⚠️ Мінусовий залишок: ${names}</div>`;
        }
        if (d.unconfigured && d.unconfigured.length) {
            html += `<div style="font-size:12px; color:#888;">Облік коштів не налаштовано: ${d.unconfigured.map(cashEsc).join(', ')}</div>`;
        }
        warnings.innerHTML = html;
    }
}

// ---------- Налаштування обліку ----------
function openCashSettingsModal(centerId) {
    const r = cashRow(centerId);
    if (!r) return;
    document.getElementById('cs-center-id').value = centerId;
    document.getElementById('cash-settings-center').innerText = r.name;
    document.getElementById('cs-start-month').value = r.start_month || cashMonth();
    document.getElementById('cs-opening').value =
        (r.opening_balance !== null && r.opening_balance !== undefined) ? r.opening_balance : 0;
    document.getElementById('cs-note').value = '';
    document.getElementById('cash-settings-modal').style.display = 'block';
}

function closeCashSettingsModal() {
    document.getElementById('cash-settings-modal').style.display = 'none';
}

async function saveCashSettings() {
    const centerId = parseInt(document.getElementById('cs-center-id').value, 10);
    const startMonth = document.getElementById('cs-start-month').value;
    const opening = parseFloat(document.getElementById('cs-opening').value) || 0;
    const note = document.getElementById('cs-note').value.trim();

    if (!startMonth) { alert('Вкажіть місяць початку обліку'); return; }
    if (!confirm(`Початок обліку: ${startMonth}, залишок ${opening} грн. Залишки наступних місяців буде перераховано. Продовжити?`)) return;

    const res = await fetchWithAuth('/api/admin/cash/settings', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
            center_id: centerId,
            start_month: startMonth,
            opening_balance: opening,
            note: note
        })
    });
    if (res && res.ok) {
        closeCashSettingsModal();
        loadCash();
    } else if (res) {
        alert(await cashApiError(res, 'Помилка збереження налаштувань'));
    }
}

// ---------- Рух коштів ----------
function openCashOpModal(centerId, kind) {
    const r = cashRow(centerId);
    if (!r) return;
    cashOpState = { centerId: centerId, kind: kind };

    document.getElementById('cash-op-title').innerText = CASH_KIND_TITLES[kind] || 'Рух коштів';
    document.getElementById('cash-op-center').innerText =
        `${r.name} · залишок ${cashMoney(r.closing_balance)} грн`;
    document.getElementById('cash-op-hint').innerText = CASH_KIND_HINTS[kind] || '';
    document.getElementById('op-date').value = cashToday();

    const amountEl = document.getElementById('op-amount');
    amountEl.value = '';
    amountEl.min = kind === 'adjustment' ? '' : '0.01';

    document.getElementById('op-method').value = 'cash';
    document.getElementById('op-counterparty').value = '';
    document.getElementById('op-comment').value = '';
    document.getElementById('cash-op-modal').style.display = 'block';
}

function closeCashOpModal() {
    document.getElementById('cash-op-modal').style.display = 'none';
}

async function saveCashOp() {
    const { centerId, kind } = cashOpState;
    const opDate = document.getElementById('op-date').value;
    const amount = parseFloat(document.getElementById('op-amount').value);
    const method = document.getElementById('op-method').value;
    const counterparty = document.getElementById('op-counterparty').value.trim();
    const comment = document.getElementById('op-comment').value.trim();

    if (!opDate) { alert('Вкажіть дату'); return; }
    if (!amount) { alert('Вкажіть суму'); return; }
    if (kind !== 'adjustment' && amount <= 0) { alert('Сума має бути більше нуля'); return; }

    const res = await fetchWithAuth('/api/admin/cash/operation', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
            center_id: centerId,
            op_date: opDate,
            kind: kind,
            amount: amount,
            method: method,
            counterparty: counterparty,
            comment: comment
        })
    });
    if (res && res.ok) {
        closeCashOpModal();
        loadCash();
    } else if (res) {
        alert(await cashApiError(res, 'Помилка операції'));
    }
}

// ---------- Масова видача ----------
function openCashBatchModal() {
    if (!cashData) return;
    const d = cashData;
    const started = d.rows.filter(r => r.configured && r.start_month && r.start_month <= d.month);
    if (!started.length) {
        alert('Немає ЦН з налаштованим обліком коштів на цей місяць');
        return;
    }

    const tbody = document.querySelector('#cash-batch-table tbody');
    tbody.innerHTML = '';
    started.forEach(r => {
        const tr = document.createElement('tr');
        tr.innerHTML = `
            <td>${cashEsc(r.name)}</td>
            <td style="text-align:right;">${cashMoney(r.closing_balance)}</td>
            <td><input type="number" step="0.01" min="0" data-center-id="${r.center_id}" style="width:100%; padding:6px;" oninput="cashBatchTotal()"></td>
        `;
        tbody.appendChild(tr);
    });

    document.getElementById('cb-date').value = cashToday();
    document.getElementById('cb-method').value = 'cash';
    document.getElementById('cb-counterparty').value = '';
    document.getElementById('cb-comment').value = `Видача на ${d.month}`;
    cashBatchTotal();
    document.getElementById('cash-batch-modal').style.display = 'block';
}

function closeCashBatchModal() {
    document.getElementById('cash-batch-modal').style.display = 'none';
}

function cashBatchTotal() {
    let total = 0;
    document.querySelectorAll('#cash-batch-table input[data-center-id]').forEach(inp => {
        total += parseFloat(inp.value) || 0;
    });
    document.getElementById('cash-batch-total').innerText = `Разом: ${cashMoney(total)} грн`;
    return total;
}

async function saveCashBatch() {
    const items = [];
    document.querySelectorAll('#cash-batch-table input[data-center-id]').forEach(inp => {
        const amount = parseFloat(inp.value) || 0;
        if (amount > 0) {
            items.push({ center_id: parseInt(inp.dataset.centerId, 10), amount: amount });
        }
    });
    if (!items.length) { alert('Вкажіть хоча б одну суму'); return; }

    const opDate = document.getElementById('cb-date').value;
    if (!opDate) { alert('Вкажіть дату'); return; }

    const res = await fetchWithAuth('/api/admin/cash/funding-batch', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
            op_date: opDate,
            method: document.getElementById('cb-method').value,
            counterparty: document.getElementById('cb-counterparty').value.trim(),
            comment: document.getElementById('cb-comment').value.trim(),
            amounts: items
        })
    });
    if (!res) return;
    if (!res.ok) {
        alert(await cashApiError(res, 'Помилка масової видачі'));
        return;
    }

    const body = await res.json();
    const errors = (body.data && body.data.errors) || [];
    if (errors.length) {
        alert('Частина ЦН не отримала кошти:\n' +
            errors.map(e => `ЦН #${e.center_id}: ${e.error}`).join('\n'));
    }
    closeCashBatchModal();
    loadCash();
}

// ---------- Журнал ----------
async function openCashLedgerModal(centerId) {
    const month = cashMonth();
    const r = cashRow(centerId);
    const title = document.getElementById('cash-ledger-title');
    const summaryBox = document.getElementById('cash-ledger-summary');
    const tbody = document.querySelector('#cash-ledger-table tbody');

    title.innerText = `Журнал коштів: ${r ? r.name : 'ЦН'} · ${month}`;
    summaryBox.innerHTML = '';
    tbody.innerHTML = '<tr><td colspan="5" style="text-align:center; color:#888;">Завантаження…</td></tr>';
    document.getElementById('cash-ledger-modal').style.display = 'block';

    const res = await fetchWithAuth(`/api/admin/cash/ledger?center_id=${centerId}&month=${encodeURIComponent(month)}`);
    if (!res || !res.ok) {
        tbody.innerHTML = '<tr><td colspan="5" style="text-align:center; color:#f44336;">Не вдалося завантажити журнал</td></tr>';
        return;
    }
    const body = await res.json();
    if (body.status !== 'ok') {
        tbody.innerHTML = '<tr><td colspan="5" style="text-align:center; color:#f44336;">Не вдалося завантажити журнал</td></tr>';
        return;
    }

    const d = body.data;
    if (!d.configured) {
        summaryBox.innerHTML = '<span style="color:#f44336;">Облік коштів для цього ЦН не налаштовано.</span>';
        tbody.innerHTML = '';
        return;
    }

    const s = d.summary || {};
    summaryBox.innerHTML = `
        <div style="display:flex; gap:14px; flex-wrap:wrap; font-size:13px;">
            <span>На початок: <b>${cashMoney(s.opening_balance)}</b></span>
            <span style="color:#2e7d32;">Надійшло: <b>${cashMoney(s.received)}</b></span>
            <span style="color:#c62828;">Витрачено: <b>${cashMoney(s.spent)}</b></span>
            <span>Залишок: <b>${cashMoney(s.closing_balance)}</b> грн</span>
        </div>
        <div style="font-size:12px; color:#888; margin-top:4px;">
            Облік з ${cashEsc(s.start_month || '—')} · стан: ${s.status === 'closed' ? 'закритий' : 'відкритий'}
            ${s.matches === false ? ' · ⚠️ не збігається зі знімком' : ''}
        </div>`;

    tbody.innerHTML = '';
    const rows = d.rows || [];
    if (!rows.length) {
        tbody.innerHTML = '<tr><td colspan="5" style="text-align:center; color:#888;">Руху коштів за місяць немає</td></tr>';
    }
    rows.forEach(row => {
        const amount = Number(row.amount) || 0;
        const color = amount < 0 ? '#c62828' : '#2e7d32';
        const extra = [];
        if (row.category_name) extra.push(cashEsc(row.category_name));
        if (row.comment) extra.push(cashEsc(row.comment));
        const tr = document.createElement('tr');
        tr.innerHTML = `
            <td style="white-space:nowrap;">${cashEsc(row.date)}</td>
            <td>${cashEsc(row.title)}</td>
            <td style="text-align:right; color:${color};">${cashMoney(amount)}</td>
            <td style="text-align:right;">${cashMoney(row.balance)}</td>
            <td style="font-size:12px; color:#666;">${extra.join(' · ')}</td>
        `;
        tbody.appendChild(tr);
    });

    if (d.truncated) {
        const tr = document.createElement('tr');
        tr.innerHTML = '<td colspan="5" style="text-align:center; color:#888;">Показано останні 300 операцій</td>';
        tbody.appendChild(tr);
    }
}

function closeCashLedgerModal() {
    document.getElementById('cash-ledger-modal').style.display = 'none';
}

// ==========================================
// F2. ЗАКРИТТЯ МОДАЛОК ПО ESC ТА КЛІКУ ПО BACKDROP
// ==========================================
const ADMIN_MODAL_CLOSERS = [
    { id: 'center-modal', close: () => closeCenterModal() },
    { id: 'category-modal', close: () => closeCategoryModal() },
    { id: 'user-modal', close: () => closeUserModal() },
        { id: 'ai-modal', close: () => closeAiModal() },
    { id: 'cash-settings-modal', close: () => closeCashSettingsModal() },
    { id: 'cash-op-modal', close: () => closeCashOpModal() },
    { id: 'cash-batch-modal', close: () => closeCashBatchModal() },
    { id: 'cash-ledger-modal', close: () => closeCashLedgerModal() }
];

function isAdminModalVisible(el) {
    return !!el && getComputedStyle(el).display !== 'none';
}

function initAdminModalDismiss() {
    ADMIN_MODAL_CLOSERS.forEach(({ id, close }) => {
        const el = document.getElementById(id);
        if (!el) return;
        let pressedOnBackdrop = false;
        el.addEventListener('mousedown', (e) => { pressedOnBackdrop = (e.target === el); });
        el.addEventListener('touchstart', (e) => { pressedOnBackdrop = (e.target === el); }, { passive: true });
        el.addEventListener('click', (e) => {
            if (e.target === el && pressedOnBackdrop) close();
            pressedOnBackdrop = false;
        });
    });

    document.addEventListener('keydown', (e) => {
        if (e.key !== 'Escape' && e.key !== 'Esc') return;
        const top = ADMIN_MODAL_CLOSERS.find(m => isAdminModalVisible(document.getElementById(m.id)));
        if (top) {
            e.preventDefault();
            top.close();
        }
    });
}

document.addEventListener('DOMContentLoaded', initAdminModalDismiss);

// Старт сторінки
window.onload = async () => {
    // Відразу перевіряємо авторизацію через завантаження центрів
    const success = await loadCenters();
    if (success) {
        loadUsers();
    }
};