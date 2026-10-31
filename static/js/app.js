// ==========================================
// TELEGRAM WEBAPP ТА БРАУЗЕРНА АВТОРИЗАЦІЯ
// ==========================================
const tg = window.Telegram && window.Telegram.WebApp ? window.Telegram.WebApp : null;
if (tg) {
    try { 
        tg.ready(); 
        tg.expand(); 
    } catch(e) {}
}

const tgUser = tg && tg.initDataUnsafe && tg.initDataUnsafe.user ? tg.initDataUnsafe.user : null;
const urlParams = new URLSearchParams(window.location.search);
const metaUserId = document.querySelector('meta[name="user-id"]')?.content;

let userId = tgUser ? tgUser.id : (urlParams.get('user_id') || (metaUserId && metaUserId !== 'None' && metaUserId !== '' ? metaUserId : null));

// РЕДІРЕКТ: Якщо немає авторизації ні з Telegram, ні з браузерної сесії
if (!userId) {
    window.location.href = '/login';
}

if (tg && tg.colorScheme === 'dark') {
    document.body.classList.add('dark');
}

// Перевизначаємо fetch для автоматичного додавання заголовка авторизації
const originalFetch = window.fetch;
window.fetch = function() {
    let [resource, config] = arguments;
    if (userId) {
        if (!config) config = {};
        if (!config.headers) config.headers = {};
        if (config.headers instanceof Headers) {
            config.headers.set('x-telegram-user-id', userId);
        } else {
            config.headers['x-telegram-user-id'] = userId;
        }
    }
    return originalFetch(resource, config);
};

function openAdminPage() {
    if (userId) {
        window.location.href = `/admin?user_id=${userId}`;
    } else {
        window.location.href = '/admin';
    }
}

function parseDate(rawDate) {
    if (!rawDate) return null;
    if (!isNaN(rawDate) && !String(rawDate).includes('-') && !String(rawDate).includes('.')) {
        const serial = Number(rawDate);
        const utcDays = serial - 25569;
        const dateObj = new Date(utcDays * 86400 * 1000);
        return {
            year: dateObj.getUTCFullYear(),
            month: String(dateObj.getUTCMonth() + 1).padStart(2, '0'),
            day: String(dateObj.getUTCDate()).padStart(2, '0')
        };
    }
    const dateStr = String(rawDate).trim().split(' ')[0];
    const parts = dateStr.split('-');
    if (parts.length === 3) {
        return { year: parts[0], month: parts[1].padStart(2, '0'), day: parts[2].padStart(2, '0') };
    }
    return null;
}

function formatDateForDisplay(rawDate) {
    const parsed = parseDate(rawDate);
    if (!parsed) return rawDate || '';
    return `${parsed.day}.${parsed.month}.${parsed.year}`;
}

function formatDateForInput(rawDate) {
    const parsed = parseDate(rawDate);
    if (!parsed) return new Date().toISOString().split('T')[0];
    return `${parsed.year}-${parsed.month}-${parsed.day}`;
}

// ==========================================
// ІНІЦІАЛІЗАЦІЯ ФІЛЬТРІВ ДАТИ ТА ДЕБАГУ
// ==========================================
const currentMonth = new Date().toISOString().slice(0, 7); // YYYY-MM

const myBudgetMonthEl = document.getElementById('my-budget-month');
if (myBudgetMonthEl) myBudgetMonthEl.value = currentMonth;

const adminBudgetMonthEl = document.getElementById('admin-budget-month');
if (adminBudgetMonthEl) adminBudgetMonthEl.value = currentMonth;

const mainMonthFilter = document.getElementById('main-month-filter');
if (mainMonthFilter) {
    mainMonthFilter.value = currentMonth;
}

function openDatePicker(inputId) {
    const input = document.getElementById(inputId);
    if (!input) return;
    try {
        if (typeof input.showPicker === 'function') {
            input.showPicker();
        } else {
            input.focus();
        }
    } catch (e) {
        input.focus();
    }
}

function resetMonthFilter() {
    const currentMonth = new Date().toISOString().slice(0, 7);
    const mainMonthFilter = document.getElementById('main-month-filter');
    if (mainMonthFilter) {
        mainMonthFilter.value = currentMonth;
    }
    // loadExpenses() сам вирішує: зведення по центрах чи список витрат
    loadExpenses();
}

function toggleDebug(panelId) {
    const panel = document.getElementById(panelId);
    if (panel) {
        panel.style.display = panel.style.display === 'none' ? 'block' : 'none';
    }
}

let currentUserRole = 'user';
let currentUserCenterId = null;
let isRoleChecked = false;

// Чи це «свій» ЦН адміна. Прапорець is_my_center з сервера має пріоритет.
function isOwnCenter(centerId, serverFlag) {
    if (serverFlag === true) return true;
    if (!currentUserCenterId) return false;
    if (centerId === null || centerId === undefined || centerId === '') return false;
    return String(centerId) === String(currentUserCenterId);
}

// Свій ЦН завжди першим у списку (сервер уже сортує — це підстраховка)
function sortOwnCenterFirst(centers) {
    return centers.slice().sort((a, b) => {
        const aOwn = isOwnCenter(a.id, a.is_my_center) ? 0 : 1;
        const bOwn = isOwnCenter(b.id, b.is_my_center) ? 0 : 1;
        return aOwn - bOwn;
    });
}

// Обраний у фільтрі ЦН (тільки для адміна). null = «Всі центри (Зведений)»
function getSelectedCenterId() {
    const sel = document.getElementById('main-center-filter');
    const val = sel ? String(sel.value) : '0';
    if (currentUserRole === 'admin' && val && val !== '0') return parseInt(val);
    return null;
}

// Адмін на «зведенні»: показуємо картки центрів, а не список витрат
function isAdminSummaryMode() {
    return currentUserRole === 'admin' && !getSelectedCenterId();
}

// Для бюджету завжди потрібен конкретний ЦН: обраний у фільтрі, інакше — власний ЦН адміна
function getBudgetCenterId() {
    const selected = getSelectedCenterId();
    if (selected) return selected;
    return currentUserCenterId ? parseInt(currentUserCenterId) : null;
}

// Кнопки дій: додавати витрати можна лише у свій ЦН
function updateActionButtons() {
    const btnAdd = document.getElementById('btn-add-expense');
    const btnBudget = document.getElementById('btn-my-budget');
    const hasOwnCenter = !!currentUserCenterId;
    const selected = getSelectedCenterId();
    const viewingOwnCenter = !selected || String(selected) === String(currentUserCenterId);

    if (btnAdd) btnAdd.style.display = (hasOwnCenter && viewingOwnCenter) ? 'inline-block' : 'none';
    if (btnBudget) btnBudget.style.display = hasOwnCenter ? 'inline-block' : 'none';
}

function checkUserRole() {
    if (!userId) return;
    fetch(`/api/user/${userId}/role`)
        .then(r => {
            if (r.status === 401 || r.status === 403) {
                if (!tgUser) {
                    window.location.href = '/login';
                    return;
                }
            }
            if (!r.ok) throw new Error(`Role HTTP error ${r.status}`);
            return r.json();
        })
        .then(res => {
            if (!res) return;
            isRoleChecked = true;
            currentUserRole = res.role;
            currentUserCenterId = (res.center_id === null || res.center_id === undefined || res.center_id === '')
                ? null
                : Number(res.center_id);

            if (currentUserRole === 'admin') {
                const adminBtn = document.getElementById('btn-admin-panel') || document.getElementById('btn-admin-budgets');
                if (adminBtn) adminBtn.style.display = 'inline-block';
                loadCentersForAdmin();
                loadCentersForAdminFilter();
            }

            updateActionButtons();
            // loadExpenses() сам вирішує: зведення по центрах чи список витрат
            loadExpenses();
        })
        .catch(err => {
            console.error("Error fetching user role:", err);
            const expensesList = document.getElementById('expenses-list');
            if (expensesList) {
                expensesList.innerHTML = `<div style="color: red; padding: 15px;">Помилка отримання ролі: ${err.message}</div>`;
            }
        });
}

function resetCenterFilter() {
    const centerFilter = document.getElementById('main-center-filter');
    if (centerFilter) {
        centerFilter.value = "0";
    }
    loadExpenses();
}

function loadAdminCentersSummary() {
    const filterMonth = document.getElementById('main-month-filter');
    const monthVal = filterMonth ? filterMonth.value : '';
    const summaryView = document.getElementById('admin-centers-summary-view');
    const summaryList = document.getElementById('admin-centers-summary-list');
    const expensesList = document.getElementById('expenses-list');

    if (!summaryView || !summaryList) return;

    summaryView.style.display = 'block';
    if (expensesList) expensesList.style.display = 'none';

    let url = '/api/admin/centers/summary';
    if (monthVal) url += `?month=${monthVal}`;

    summaryList.innerHTML = '<div style="text-align: center; color: var(--tg-theme-hint-color, #888); padding: 15px;">Завантаження зведення по центрах...</div>';

    fetch(url)
        .then(r => {
            if (r.status === 401 || r.status === 403) {
                if (!tgUser) {
                    window.location.href = '/login';
                    return;
                }
            }
            if (!r.ok) throw new Error(`HTTP помилка ${r.status}: ${r.statusText}`);
            return r.json();
        })
        .then(res => {
            if (!res) return;
            if (res.status !== 'ok') throw new Error(res.detail || "Сервер повернув помилку");
            
            const centers = sortOwnCenterFirst(res.data || []);
            if (centers.length === 0) {
                summaryList.innerHTML = '<div style="color: #888; text-align: center; padding: 15px;">Немає зареєстрованих або активних центрів.</div>';
                return;
            }

            let html = '';
            centers.forEach(c => {
                const isMyCenter = isOwnCenter(c.id, c.is_my_center);
                const spent = c.total_spent || 0;
                const budget = c.total_budget || 0;
                const hasBudget = c.has_budget;

                let percent = 0;
                if (hasBudget && budget > 0) percent = Math.min(100, Math.round((spent / budget) * 100));
                else if (spent > 0) percent = 100;

                const barColor = getProgressBarColor(percent);
                const budgetText = hasBudget ? (budget > 0 ? budget.toFixed(0) + ' грн' : '0 грн') : 'не встановлено';

                html += `
                    <div class="expense-card" style="cursor: pointer; margin-bottom: 12px; transition: transform 0.1s; ${isMyCenter ? 'border: 2px solid #4CAF50;' : ''}" onclick="selectCenterForAdmin(${c.id})" title="Натисніть, щоб переглянути витрати ЦН">
                        <div class="header" style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 6px;">
                            <strong>🏢 ${c.name} (${c.city || 'ЦН'})${isMyCenter ? ' <span style="background: #4CAF50; color: white; font-size: 0.75em; padding: 2px 6px; border-radius: 10px; vertical-align: middle;">⭐ Мій ЦН</span>' : ''}</strong>
                            <button type="button" class="btn-sm" style="background: #9c27b0; color: white; border: none; padding: 5px 10px; border-radius: 5px; font-weight: bold; cursor: pointer;" onclick="event.stopPropagation(); openAdminModal(${c.id});" title="Панель керування бюджетом та категоріями">⚙️ Керувати</button>
                        </div>
                        <div style="display: flex; justify-content: space-between; font-size: 0.9em; margin-bottom: 4px;">
                            <span>Витрати: <b>${spent.toFixed(0)} грн</b></span>
                            <span>Бюджет: <b>${budgetText}</b></span>
                        </div>
                        <div style="width: 100%; background: #e0e0e0; border-radius: 4px; height: 8px; overflow: hidden;">
                            <div style="width: ${hasBudget ? percent : (spent > 0 ? 100 : 0)}%; background: ${hasBudget ? barColor : '#9e9e9e'}; height: 100%;"></div>
                        </div>
                    </div>
                `;
            });

            summaryList.innerHTML = html;
        })
        .catch(err => {
            console.error("loadAdminCentersSummary error:", err);
            summaryList.innerHTML = `
                <div style="color: red; padding: 15px; background: #ffebee; border-radius: 8px; border: 1px solid #ffcdd2;">
                    <b>⚠️ Помилка завантаження зведення центрів:</b><br>
                    <code>${err.message}</code>
                </div>
            `;
        });
}

function selectCenterForAdmin(centerId) {
    const centerFilter = document.getElementById('main-center-filter');
    if (centerFilter) {
        centerFilter.value = centerId;
    }
    loadExpenses();
}

function loadCentersForAdminFilter() {
    fetch(`/api/admin/centers?admin_id=${userId}`)
        .then(r => r.json())
        .then(res => {
            const select = document.getElementById('main-center-filter');
            const container = document.getElementById('admin-center-filter-container');
            if (!res.data || !select || !container) return;

            // Прибираємо раніше додані ЦН (лишаємо тільки «Всі центри»), щоб не дублювати опції
            Array.from(select.options).forEach(o => { if (o.value !== '0') o.remove(); });

            const prevValue = select.value || '0';

            // Свій ЦН — першим у списку
            sortOwnCenterFirst(res.data).forEach(c => {
                const opt = document.createElement('option');
                opt.value = c.id;
                const own = isOwnCenter(c.id, c.is_my_center);
                opt.textContent = c.name + (own ? ' ⭐' : '');
                if (own) opt.style.fontWeight = 'bold';
                select.appendChild(opt);
            });

            if (prevValue && Array.from(select.options).some(o => o.value === prevValue)) {
                select.value = prevValue;
            }
            container.style.display = 'flex';
        });
}

let allExpenses = [];      
let currentEditIndex = -1; 

function loadCentersForAdmin() {
    fetch(`/api/admin/centers?admin_id=${userId}`)
        .then(r => r.json())
        .then(res => {
            const select = document.getElementById('admin-center-select');
            if (select) {
                select.innerHTML = '<option value="">-- Оберіть центр --</option>';
                if (res.data) {
                    res.data.forEach(c => {
                        const opt = document.createElement('option');
                        opt.value = c.id;
                        opt.textContent = c.name;
                        select.appendChild(opt);
                    });
                }
            }
        });
}

// ==========================================
// БЮДЖЕТИ (КОРИСТУВАЧ)
// ==========================================
function openMyBudgetModal() {
    document.getElementById('my-budget-modal').style.display = 'block';
    const centerFilter = document.getElementById('main-center-filter');
    const titleEl = document.getElementById('my-budget-title');
    if (centerFilter && centerFilter.value && centerFilter.value !== "0" && currentUserRole === 'admin') {
        const centerName = centerFilter.options[centerFilter.selectedIndex] ? centerFilter.options[centerFilter.selectedIndex].text.replace(/ ⭐/g, '') : '';
        if (titleEl) titleEl.textContent = `Бюджет ЦН ${centerName}`;
    } else {
        fetch(`/api/user/${userId}/center`)
            .then(r => r.json())
            .then(res => {
                if (titleEl) titleEl.textContent = `Бюджет ЦН ${res.center || ''}`;
            })
            .catch(() => {
                if (titleEl) titleEl.textContent = 'Бюджет мого ЦН';
            });
    }
    loadMyBudget();
}

function getProgressBarColor(percent) {
    if (percent <= 25) return '#4CAF50';
    if (percent <= 50) return '#8BC34A';
    if (percent <= 75) return '#FFC107';
    if (percent <= 99) return '#FF9800';
    return '#F44336';
}

function loadMyBudget() {
    const month = document.getElementById('my-budget-month').value;
    if (!month || !userId) return;
    
    const list = document.getElementById('my-budget-list');
    list.innerHTML = 'Завантаження...';
    
    // Бюджет завжди показуємо для конкретного ЦН: обраного у фільтрі,
    // а якщо обрано «Всі центри» — для власного ЦН адміна
    const centerId = getBudgetCenterId();
    const budgetUrl = centerId
        ? `/api/budgets/center/${centerId}?month=${month}`
        : `/api/budgets/${userId}?month=${month}`;
    const expensesUrl = centerId
        ? `/api/expenses/${userId}?center_id=${centerId}`
        : `/api/expenses/${userId}`;
    const categoriesUrl = (centerId && String(centerId) !== String(currentUserCenterId))
        ? `/api/categories/${centerId}`
        : `/api/categories`;

    Promise.all([
        fetch(budgetUrl).then(r => r.json()),
        fetch(expensesUrl).then(r => r.json()),
        fetch(categoriesUrl).then(r => r.json()).catch(() => ({ data: currentCategories }))
    ])
        .then(([budgetRes, expRes, catRes]) => {
            const budgets = budgetRes.data || {};
            const budgetExpenses = expRes.data || [];
            const categories = sortCategories(catRes.data || []);
            
            const debugPanel = document.getElementById('budget-debug-panel');
            if (debugPanel) {
                debugPanel.textContent = JSON.stringify({
                    "currentMonthSelected": month,
                    "expensesCount": budgetExpenses.length,
                    "firstExpenseRaw": budgetExpenses[0] || null,
                    "parsedFirstDate": budgetExpenses[0] ? parseDate(budgetExpenses[0].Date || budgetExpenses[0].date) : null,
                    "budgetsResult": budgets
                }, null, 2);
            }
            
            const expensesByCat = {};
            let totalSpent = 0;
            let totalPlanned = 0;
            
            budgetExpenses.forEach(exp => {
                const rawDate = exp.Date || exp.date;
                const expDate = parseDate(rawDate);
                if (expDate && `${expDate.year}-${expDate.month}` === month) {
                    const catName = exp.category_name || exp.Category_Name || exp.Category || 'Інше';
                    const amount = parseFloat(exp.amount || exp.Amount) || 0;
                    
                    let catId = String(exp.category_id || exp.Category_ID || '').trim();
                    
                    if (!catId || !catId.startsWith('cat_')) {
                        catId = 'cat_other';
                        const matchedCat = categories.find(c => {
                            const cName = typeof c === 'object' ? String(c.name).trim() : String(c).trim();
                            return cName.toLowerCase() === String(catName).trim().toLowerCase();
                        });
                        if (matchedCat) {
                            catId = typeof matchedCat === 'object' ? matchedCat.id : matchedCat;
                        }
                    }
            
                    const cleanCatId = String(catId).trim();
                    if (!expensesByCat[cleanCatId]) expensesByCat[cleanCatId] = 0;
                    expensesByCat[cleanCatId] += amount;
                }
            });

            if (categories.length === 0) {
                list.innerHTML = 'Категорії не завантажено.';
                return;
            }
            
            let html = '';
            categories.forEach(cat => {
                const catId = typeof cat === 'object' ? cat.id : cat;
                const catName = typeof cat === 'object' ? cat.name : cat;
                
                const cleanCatId = String(catId).trim();
                const hasBudget = Object.prototype.hasOwnProperty.call(budgets, cleanCatId);
                const planned = hasBudget ? budgets[cleanCatId] : 0;
                const spent = expensesByCat[cleanCatId] || 0;
                const remaining = planned - spent;
                        
                if (hasBudget) totalPlanned += planned;
                totalSpent += spent;
                
                let percent = 0;
                if (hasBudget && planned > 0) percent = Math.min(100, Math.round((spent / planned) * 100));
                else if (spent > 0) percent = 100;
                
                let barColor = getProgressBarColor(percent);
                const plannedDisplay = hasBudget ? (planned > 0 ? planned.toFixed(0) + ' грн' : '0 грн') : 'не встановлено';
                let remainingDisplay = '';
                if (hasBudget) {
                    remainingDisplay = remaining < 0 ? 'Перевитрата: ' + Math.abs(remaining).toFixed(0) + ' грн' : 'Залишок: ' + remaining.toFixed(0) + ' грн';
                }
                
                html += `
                    <div style="margin-bottom: 12px;">
                        <div style="display: flex; justify-content: space-between; font-size: 0.9em; margin-bottom: 4px;">
                            <strong>${catName}</strong>
                            <span>${spent.toFixed(0)} / ${plannedDisplay}</span>
                        </div>
                        <div style="width: 100%; background: #e0e0e0; border-radius: 4px; height: 8px; overflow: hidden;">
                            <div style="width: ${hasBudget ? percent : (spent > 0 ? 100 : 0)}%; background: ${hasBudget ? barColor : '#9e9e9e'}; height: 100%;"></div>
                        </div>
                        <div style="font-size: 0.8em; color: ${remaining < 0 ? '#F44336' : 'var(--tg-theme-hint-color, #888)'}; margin-top: 2px; text-align: right;">
                            ${remainingDisplay}
                        </div>
                    </div>
                `;
            });
            
            if (html === '') {
                list.innerHTML = '<div style="text-align:center; color: #888;">Немає запланованих бюджетів та витрат у цьому місяці.</div>';
            } else {
                let totalPercent = 0;
                if (totalPlanned > 0) totalPercent = Math.min(100, Math.round((totalSpent / totalPlanned) * 100));
                let totalBarColor = getProgressBarColor(totalPercent);
                
                html += `
                    <hr style="border-top: 1px solid #ccc; margin: 15px 0;">
                    <div style="margin-bottom: 12px;">
                        <div style="display: flex; justify-content: space-between; font-size: 1em; margin-bottom: 4px;">
                            <strong>ВСЬОГО</strong>
                            <strong>${totalSpent.toFixed(0)} / ${totalPlanned > 0 ? totalPlanned.toFixed(0) : '—'} грн</strong>
                        </div>
                        <div style="width: 100%; background: #e0e0e0; border-radius: 4px; height: 10px; overflow: hidden;">
                            <div style="width: ${totalPercent}%; background: ${totalBarColor}; height: 100%;"></div>
                        </div>
                    </div>
                `;
                list.innerHTML = html;
            }
        })
        .catch(err => {
            list.innerHTML = 'Помилка завантаження бюджетів: ' + err.message;
            const debugPanel = document.getElementById('budget-debug-panel');
            if (debugPanel) {
                debugPanel.textContent = 'Error parsing data:\n' + err.stack;
                debugPanel.style.display = 'block';
            }
            console.error(err);
        });
}

// ==========================================
// ПАНЕЛЬ АДМІНІСТРАТОРА (БЮДЖЕТИ ТА КАТЕГОРІЇ)
// ==========================================
let adminCurrentTab = 'budgets';
let adminTargetCategories = [];

function openAdminModal(specificCenterId = null) {
    const modal = document.getElementById('admin-budgets-modal');
    const selectContainer = document.getElementById('admin-center-select-container');
    const adminSelect = document.getElementById('admin-center-select');
    const titleEl = document.getElementById('admin-modal-title');

    modal.style.display = 'block';

    if (specificCenterId) {
        if (selectContainer) selectContainer.style.display = 'none';
        if (adminSelect) adminSelect.value = specificCenterId;
        
        const optText = adminSelect && adminSelect.options[adminSelect.selectedIndex] ? adminSelect.options[adminSelect.selectedIndex].text : '';
        if (titleEl) titleEl.textContent = `Панель ЦН: ${optText}`;
    } else {
        if (selectContainer) selectContainer.style.display = 'block';
        if (titleEl) titleEl.textContent = 'Панель адміністратора';
    }

    onAdminCenterChange();
}

function openAdminBudgetsModal() {
    openAdminModal();
}

function closeAdminModal() {
    document.getElementById('admin-budgets-modal').style.display = 'none';
}

function onAdminCenterChange() {
    const targetCenterId = document.getElementById('admin-center-select').value;
    const actionsDiv = document.getElementById('admin-user-actions');
    const tabBudgets = document.getElementById('admin-tab-budgets');
    const tabCategories = document.getElementById('admin-tab-categories');
    
    if (!targetCenterId) {
        if (actionsDiv) actionsDiv.style.display = 'none';
        if (tabBudgets) tabBudgets.style.display = 'none';
        if (tabCategories) tabCategories.style.display = 'none';
        return;
    }

    if (actionsDiv) actionsDiv.style.display = 'block';
    switchAdminTab(adminCurrentTab);
}

function switchAdminTab(tabName) {
    adminCurrentTab = tabName;
    const tabBudgets = document.getElementById('admin-tab-budgets');
    const tabCategories = document.getElementById('admin-tab-categories');
    const btnBudgets = document.getElementById('tab-btn-budgets');
    const btnCategories = document.getElementById('tab-btn-categories');

    if (tabName === 'budgets') {
        if (tabBudgets) tabBudgets.style.display = 'block';
        if (tabCategories) tabCategories.style.display = 'none';
        if (btnBudgets) { btnBudgets.style.background = '#4CAF50'; btnBudgets.style.opacity = '1'; }
        if (btnCategories) { btnCategories.style.background = '#666'; btnCategories.style.opacity = '0.7'; }
        loadAdminBudgetsForCenter();
    } else {
        if (tabBudgets) tabBudgets.style.display = 'none';
        if (tabCategories) tabCategories.style.display = 'block';
        if (btnBudgets) { btnBudgets.style.background = '#666'; btnBudgets.style.opacity = '0.7'; }
        if (btnCategories) { btnCategories.style.background = '#4CAF50'; btnCategories.style.opacity = '1'; }
        loadAdminCategoriesForCenter();
    }
}

function loadAdminCategoriesForCenter() {
    const targetCenterId = document.getElementById('admin-center-select').value;
    const listBox = document.getElementById('admin-categories-list-box');
    if (!targetCenterId) {
        if (listBox) listBox.innerHTML = 'Оберіть центр.';
        return;
    }

    if (listBox) listBox.innerHTML = 'Завантаження категорій...';

    fetch('/api/admin/matrix')
        .then(r => r.json())
        .then(res => {
            if (res.status === 'ok' && res.data) {
                renderAdminCategoriesListBox(targetCenterId, res.data);
            } else {
                if (listBox) listBox.innerHTML = 'Помилка завантаження даних.';
            }
        })
        .catch(err => {
            if (listBox) listBox.innerHTML = 'Помилка завантаження категорій: ' + err.message;
        });
}

function renderAdminCategoriesListBox(targetCenterId, matrixData) {
    const box = document.getElementById('admin-categories-list-box');
    if (!box) return;

    const categories = sortCategories(matrixData.categories || []);
    const links = matrixData.links || [];

    if (categories.length === 0) {
        box.innerHTML = '<div style="text-align:center; color:#888;">Категорій немає.</div>';
        return;
    }

    const headerEl = document.getElementById('admin-categories-list-header');
    if (headerEl) {
        headerEl.textContent = 'Налаштування категорій';
    }

    let html = '';
    categories.forEach((cat) => {
        const catId = cat.id;
        const catName = cat.name;
        
        const isChecked = links.some(l => 
            String(l.center_id) === String(targetCenterId) && 
            String(l.category_id) === String(catId)
        );

        html += `
            <div style="display: flex; justify-content: space-between; align-items: center; padding: 8px 4px; border-bottom: 1px solid var(--tg-theme-hint-color, #eee);">
                <span style="font-weight: 500;">${catName}</span>
                <input type="checkbox" style="transform: scale(1.3); cursor: pointer;" 
                    ${isChecked ? 'checked' : ''} 
                    onchange="toggleCategory(${targetCenterId}, '${catId}', this.checked)">
            </div>
        `;
    });

    box.innerHTML = html;
}

async function toggleCategory(centerId, categoryId, isEnabled) {
    try {
        const res = await fetch('/api/admin/matrix/toggle', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                center_id: parseInt(centerId),
                category_id: categoryId,
                is_enabled: isEnabled
            })
        });
        
        if (!res || !res.ok) {
            alert('Помилка оновлення категорії');
            loadAdminCategoriesForCenter();
        }
    } catch (err) {
        alert('Помилка оновлення: ' + err.message);
        loadAdminCategoriesForCenter();
    }
}

function startAdminInlineEdit(catName) {
    renderAdminCategoriesListBox(catName);
}

function saveAdminCategoryRename(oldCat) {
    const targetCenterId = document.getElementById('admin-center-select').value;
    const input = document.getElementById('admin-inline-edit-input');
    if (!input || !targetCenterId) return;
    const newName = input.value.trim();
    if (!newName || newName === oldCat) {
        renderAdminCategoriesListBox();
        return;
    }

    fetch(`/api/categories/${targetCenterId}/rename?admin_id=${userId}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ old_category: oldCat, category: newName })
    }).then(r => {
        if (!r.ok) {
            alert("Помилка перейменування категорії!");
            return;
        }
        loadAdminCategoriesForCenter();
        if (String(targetCenterId) === String(userId)) {
            loadCategories();
        }
    });
}

function addAdminCenterCategory() {
    const targetCenterId = document.getElementById('admin-center-select').value;
    const input = document.getElementById('admin-new-cat-input');
    if (!input || !targetCenterId) return;
    const newCat = input.value.trim();
    if (!newCat) return;
    input.value = '';

    fetch(`/api/categories/${targetCenterId}/add?admin_id=${userId}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ category: newCat })
    }).then(r => {
        if (!r.ok) {
            alert("Помилка додавання категорії!");
            return;
        }
        loadAdminCategoriesForCenter();
        if (String(targetCenterId) === String(userId)) {
            loadCategories();
        }
    });
}

function removeAdminCenterCategory(catName) {
    const targetCenterId = document.getElementById('admin-center-select').value;
    if (!targetCenterId || catName === 'Інше') return;
    if (confirm(`Ви дійсно хочете видалити категорію "${catName}" для обраного користувача?`)) {
        fetch(`/api/categories/${targetCenterId}/delete?admin_id=${userId}`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ category: catName })
        }).then(r => {
            if (!r.ok) {
                alert("Помилка видалення категорії!");
                return;
            }
            loadAdminCategoriesForCenter();
            if (String(targetCenterId) === String(userId)) {
                loadCategories();
            }
        });
    }
}

function loadAdminBudgetsForCenter() {
    const targetCenterId = document.getElementById('admin-center-select').value;
    const month = document.getElementById('admin-budget-month').value;
    const list = document.getElementById('admin-budget-list');
    
    if (!targetCenterId) {
        list.innerHTML = 'Оберіть центр.';
        return;
    }
    if (!month) {
        list.innerHTML = 'Оберіть місяць.';
        return;
    }
    
    list.innerHTML = 'Завантаження категорій, бюджетів та витрат...';
    
    Promise.all([
        fetch(`/api/categories/${targetCenterId}`).then(r => r.json()),
        fetch(`/api/budgets/center/${targetCenterId}?month=${month}`).then(r => r.json()),
        fetch(`/api/expenses/${userId}?center_id=${targetCenterId}`).then(r => r.json())
    ])
    .then(([catRes, budgetRes, expRes]) => {
        const userCats = sortCategories(catRes.data || []);
        const budgets = budgetRes.data || {};
        const targetExpenses = expRes.data || [];
        
        const debugPanel = document.getElementById('admin-debug-panel');
        if (debugPanel) {
            debugPanel.textContent = JSON.stringify({
                "monthSelected": month,
                "targetExpensesCount": targetExpenses.length,
                "firstTargetExpenseRaw": targetExpenses[0] || null,
                "parsedFirstDate": targetExpenses[0] ? parseDate(targetExpenses[0].Date || targetExpenses[0].date) : null,
                "budgetsResult": budgets
            }, null, 2);
        }
        
        const expensesByCat = {};
        let totalSpent = 0;
        let totalPlanned = 0;
        
        targetExpenses.forEach(exp => {
            const rawDate = exp.Date || exp.date;
            const expDate = parseDate(rawDate);
            if (expDate && `${expDate.year}-${expDate.month}` === month) {
                const catName = exp.category_name || exp.Category_Name || exp.Category || 'Інше';
                const amount = parseFloat(exp.amount || exp.Amount) || 0;
                
                let catId = String(exp.category_id || exp.Category_ID || '').trim();
                if (!catId || !catId.startsWith('cat_')) {
                    catId = 'cat_other';
                    const matchedCat = userCats.find(c => {
                        const cName = typeof c === 'object' ? String(c.name).trim() : String(c).trim();
                        return cName.toLowerCase() === String(catName).trim().toLowerCase();
                    });
                    if (matchedCat) {
                        catId = typeof matchedCat === 'object' ? matchedCat.id : matchedCat;
                    }
                }
                
                const cleanCatId = String(catId).trim();
                if (!expensesByCat[cleanCatId]) expensesByCat[cleanCatId] = 0;
                expensesByCat[cleanCatId] += amount;
            }
        });
        
        let html = '';
        userCats.forEach(cat => {
            const catId = typeof cat === 'object' ? cat.id : cat;
            const catName = typeof cat === 'object' ? cat.name : cat;
        
            const cleanCatId = String(catId).trim();
            const planned = budgets[cleanCatId] || 0;
            const spent = expensesByCat[cleanCatId] || 0;
            const remaining = planned - spent;
            
            totalPlanned += planned;
            totalSpent += spent;
            
            let percent = 0;
            if (planned > 0) percent = Math.min(100, Math.round((spent / planned) * 100));
            else if (spent > 0) percent = 100;
            
            let barColor = getProgressBarColor(percent);
            
            html += `
                <div style="margin-bottom: 15px; border-bottom: 1px solid var(--tg-theme-hint-color, #eee); padding-bottom: 10px;">
                    <div style="display: flex; align-items: center; margin-bottom: 5px; gap: 10px;">
                        <div style="flex: 2; font-weight: bold; font-size: 0.9em;">${catName}</div>
                        <div style="flex: 1; display: flex; align-items: center; justify-content: flex-end;">
                            <input type="number" id="budget-input-${catId}" value="${planned || ''}" placeholder="0" style="width: 70px; text-align: right; margin: 0; padding: 4px;" oninput="updateAdminBudgetPreview('${catId}', ${spent})">
                        </div>
                        <button class="btn-sm" style="background-color: #4CAF50; padding: 4px 8px;" onclick="saveAdminBudget('${targetCenterId}', '${catId}', '${month}')">💾</button>
                    </div>
                    <div style="display: flex; justify-content: space-between; font-size: 0.8em; margin-bottom: 4px; color: var(--tg-theme-hint-color, #888);">
                        <span>Витрачено: ${spent.toFixed(0)} грн</span>
                        <span id="budget-remaining-${catId}" style="color: ${remaining < 0 ? '#F44336' : ''};">${remaining < 0 ? 'Перевитрата: ' + Math.abs(remaining).toFixed(0) : 'Залишок: ' + remaining.toFixed(0)} грн</span>
                    </div>
                    <div style="width: 100%; background: #e0e0e0; border-radius: 4px; height: 6px; overflow: hidden;">
                        <div id="budget-bar-${catId}" style="width: ${percent}%; background: ${barColor}; height: 100%; transition: width 0.3s, background-color 0.3s;"></div>
                    </div>
                </div>
            `;
        });
        
        if (html === '') {
            list.innerHTML = 'У центру немає активних категорій.';
        } else {
            let totalPercent = 0;
            if (totalPlanned > 0) totalPercent = Math.min(100, Math.round((totalSpent / totalPlanned) * 100));
            let totalBarColor = getProgressBarColor(totalPercent);
            
            html += `
                <div style="margin-top: 15px; padding-top: 10px;" id="admin-total-block" data-total-spent="${totalSpent}">
                    <div style="display: flex; justify-content: space-between; font-size: 1em; margin-bottom: 4px;">
                        <strong>ВСЬОГО</strong>
                        <strong id="admin-total-text">${totalSpent.toFixed(0)} / ${totalPlanned > 0 ? totalPlanned.toFixed(0) : '—'} грн</strong>
                    </div>
                    <div style="width: 100%; background: #e0e0e0; border-radius: 4px; height: 8px; overflow: hidden;">
                        <div id="admin-total-bar" style="width: ${totalPercent}%; background: ${totalBarColor}; height: 100%; transition: width 0.3s, background-color 0.3s;"></div>
                    </div>
                </div>
            `;
            list.innerHTML = html;
        }
    })
    .catch(err => {
        list.innerHTML = 'Помилка завантаження даних: ' + err.message;
        const debugPanel = document.getElementById('admin-debug-panel');
        if (debugPanel) {
            debugPanel.textContent = 'Error parsing admin data:\n' + err.stack;
            debugPanel.style.display = 'block';
        }
        console.error(err);
    });
}

function updateAdminBudgetPreview(catId, spent) {
    const input = document.getElementById(`budget-input-${catId}`);
    if (!input) return;
    
    let planned = parseFloat(input.value);
    if (isNaN(planned) || planned < 0) planned = 0;
    
    const remaining = planned - spent;
    const remainingSpan = document.getElementById(`budget-remaining-${catId}`);
    if (remainingSpan) {
        if (remaining < 0) {
            remainingSpan.textContent = 'Перевитрата: ' + Math.abs(remaining).toFixed(0) + ' грн';
            remainingSpan.style.color = '#F44336';
        } else {
            remainingSpan.textContent = 'Залишок: ' + remaining.toFixed(0) + ' грн';
            remainingSpan.style.color = '';
        }
    }
    
    const bar = document.getElementById(`budget-bar-${catId}`);
    if (bar) {
        let percent = 0;
        if (planned > 0) percent = Math.min(100, Math.round((spent / planned) * 100));
        else if (spent > 0) percent = 100;
        
        bar.style.width = percent + '%';
        bar.style.backgroundColor = getProgressBarColor(percent);
    }
    
    recalculateAdminTotals();
}

function recalculateAdminTotals() {
    const totalBlock = document.getElementById('admin-total-block');
    if (!totalBlock) return;
    
    const totalSpent = parseFloat(totalBlock.getAttribute('data-total-spent')) || 0;
    let totalPlanned = 0;
    
    const inputs = document.querySelectorAll('[id^="budget-input-"]');
    inputs.forEach(input => {
        let val = parseFloat(input.value);
        if (!isNaN(val) && val > 0) {
            totalPlanned += val;
        }
    });
    
    const totalText = document.getElementById('admin-total-text');
    if (totalText) {
        totalText.textContent = `${totalSpent.toFixed(0)} / ${totalPlanned > 0 ? totalPlanned.toFixed(0) : '—'} грн`;
    }
    
    const totalBar = document.getElementById('admin-total-bar');
    if (totalBar) {
        let totalPercent = 0;
        if (totalPlanned > 0) totalPercent = Math.min(100, Math.round((totalSpent / totalPlanned) * 100));
        
        totalBar.style.width = totalPercent + '%';
        totalBar.style.backgroundColor = getProgressBarColor(totalPercent);
    }
}

function saveAdminBudget(targetCenterId, categoryId, month) {
    const input = document.getElementById(`budget-input-${categoryId}`);
    let amount = parseFloat(input.value);
    if (isNaN(amount) || amount < 0) amount = 0;
    
    fetch(`/api/admin/budgets?admin_id=${userId}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
            target_center_id: parseInt(targetCenterId),
            month: month,
            category_id: categoryId,
            amount: amount
        })
    }).then(r => {
        if (r.ok) {
            input.style.backgroundColor = '#d4edda';
            setTimeout(() => input.style.backgroundColor = '', 1000);
        } else {
            alert("Помилка збереження бюджету!");
        }
    });
}

function updateMainBudgetSummary(month, totalSpent) {
    const summaryBox = document.getElementById('main-budget-summary');
    if (!summaryBox) return;
    
    if (!month) {
        summaryBox.style.display = 'none';
        return;
    }

    const centerFilter = document.getElementById('main-center-filter');
    if (centerFilter && centerFilter.value === "0" && currentUserRole === 'admin') {
        summaryBox.style.display = 'none';
        return;
    }

    let budgetUrl = `/api/budgets/${userId}?month=${month}`;
    if (centerFilter && centerFilter.value && centerFilter.value !== "0" && currentUserRole === 'admin') {
        budgetUrl = `/api/budgets/center/${centerFilter.value}?month=${month}`;
    }
    
    fetch(budgetUrl)
        .then(r => r.json())
        .then(res => {
            const budgets = res.data || {};
            let totalPlanned = 0;
            for (const catId in budgets) {
                totalPlanned += parseFloat(budgets[catId]) || 0;
            }
            
            if (totalPlanned > 0) {
                summaryBox.style.display = 'block';
                
                let percent = Math.min(100, Math.round((totalSpent / totalPlanned) * 100));
                let remaining = totalPlanned - totalSpent;
                
                const textEl = document.getElementById('main-budget-text');
                if (textEl) textEl.textContent = `${totalSpent.toFixed(0)} / ${totalPlanned.toFixed(0)} грн`;
                
                const bar = document.getElementById('main-budget-bar');
                if (bar) {
                    bar.style.width = percent + '%';
                    bar.style.backgroundColor = getProgressBarColor(percent);
                }
                
                const remainingEl = document.getElementById('main-budget-remaining');
                if (remainingEl) {
                    if (remaining < 0) {
                        remainingEl.textContent = 'Перевитрата: ' + Math.abs(remaining).toFixed(0) + ' грн';
                        remainingEl.style.color = '#F44336';
                    } else {
                        remainingEl.textContent = 'Залишок: ' + remaining.toFixed(0) + ' грн';
                        remainingEl.style.color = 'var(--tg-theme-hint-color, #888)';
                    }
                }
            } else {
                summaryBox.style.display = 'none';
            }
        })
        .catch(err => {
            summaryBox.style.display = 'none';
        });
}

// ==========================================
// ВИТРАТИ (CRUD)
// ==========================================
function loadExpenses(targetExpenseId = null) {
    const summaryView = document.getElementById('admin-centers-summary-view');
    const centerFilterEl = document.getElementById('main-center-filter');
    const backBtn = document.getElementById('btn-back-to-summary');

    if (backBtn) {
        if (currentUserRole === 'admin' && centerFilterEl && centerFilterEl.value !== "0") {
            backBtn.style.display = 'inline-block';
        } else {
            backBtn.style.display = 'none';
        }
    }
    
    updateActionButtons();

    if (isAdminSummaryMode()) {
        if (summaryView) summaryView.style.display = 'block';
        const expensesList = document.getElementById('expenses-list');
        if (expensesList) expensesList.style.display = 'none';
        // Зведення не стосується бюджету конкретного ЦН — ховаємо блок бюджету
        const budgetBox = document.getElementById('main-budget-summary');
        if (budgetBox) budgetBox.style.display = 'none';
        loadAdminCentersSummary();
        return;
    } else {
        if (summaryView) summaryView.style.display = 'none';
        const expensesList = document.getElementById('expenses-list');
        if (expensesList) expensesList.style.display = 'block';
    }

    const list = document.getElementById('expenses-list');
    const loadingIndicator = document.getElementById('loading-indicator');

    if (list.children.length === 0) {
        list.innerHTML = '<div style="text-align:center; padding: 20px; color: var(--tg-theme-hint-color, #888);">Завантаження...</div>';
    } else if (loadingIndicator) {
        loadingIndicator.style.display = 'flex';
    }

    let fetchUrl = `/api/expenses/${userId}`;
    const centerFilter = document.getElementById('main-center-filter');
    if (centerFilter && centerFilter.value !== "0" && currentUserRole === 'admin') {
        fetchUrl += `?center_id=${centerFilter.value}`;
    } else if (currentUserRole === 'admin') {
        fetchUrl += `?center_id=0`;
    }

    fetch(fetchUrl)
        .then(response => {
            if (response.status === 401 || response.status === 403) {
                if (!tgUser) {
                    window.location.href = '/login';
                    return;
                }
            }
            if (!response.ok) throw new Error("Помилка доступу");
            return response.json();
        })
        .then(result => {
            if (!result) return;
            if (loadingIndicator) loadingIndicator.style.display = 'none';
            allExpenses = result.data || [];

            let totalSum = 0;
            
            const filterMonth = document.getElementById('main-month-filter');
            const monthVal = filterMonth ? filterMonth.value : '';
            
            let filteredExpenses = allExpenses;
            if (monthVal) {
                filteredExpenses = allExpenses.filter(item => {
                    const d = parseDate((item.Date || item.date));
                    return d && d.year + '-' + d.month === monthVal;
                });
            }

            if (filteredExpenses.length === 0) {
                list.innerHTML = '<div style="text-align:center; padding: 20px; color: var(--tg-theme-hint-color, #888);">Витрат за цей період немає.</div>';
                document.getElementById('total-header').innerText = 'Витрати: 0.00 грн';
                updateMainBudgetSummary(monthVal, 0);
                return;
            }

            const fragment = document.createDocumentFragment();

            filteredExpenses.forEach(item => {
                const amountNum = parseFloat((item.Amount || item.amount)) || 0;
                totalSum += amountNum;
                
                let receiptIconHtml = '';
                if ((item.receipt_path || item.Receipt_Path) && (item.receipt_path || item.Receipt_Path).trim() !== '') {
                    receiptIconHtml = `<button class="receipt-btn" onclick="openReceipt('${(item.receipt_path || item.Receipt_Path)}')" title="Переглянути чек">📄 Чек</button>`;
                }
                
                const displayDate = formatDateForDisplay((item.Date || item.date));
                const expId = (item.expense_id || item.Expense_ID);
                
                const card = document.createElement('div');
                card.className = 'expense-card';
                card.id = `expense-card-${expId}`;

                const safeName = ((item.Expense_Name || item.expense_name) || '').replace(/'/g, "\\'");
                const safeCat = ((item.category_name || item.Category) || '').replace(/'/g, "\\'");

                const debugInfo = ``;

                card.innerHTML = `
                    <div class="header">
                        <span>${(item.Expense_Name || item.expense_name)}</span>
                        <span>${amountNum.toFixed(2)} грн</span>
                    </div>
                    <div class="details">
                        <span>${displayDate} | ${item.category_name || (item.category_name || item.Category) || 'Інше'}</span>
                        ${receiptIconHtml}
                    </div>
                    <!-- ${debugInfo} -->
                    <div class="card-actions">
                        <button class="btn-sm" onclick="openForm('${expId}', '${(item.Date || item.date)}', ${amountNum}, '${safeName}', '${safeCat}', '${(item.receipt_path || item.Receipt_Path) || ''}')">✏️ Редагувати</button>
                        <button class="btn-sm btn-danger" onclick="deleteExpense('${expId}')">🗑 Видалити</button>
                    </div>
                `;

                fragment.appendChild(card);
            });

            list.innerHTML = '';
            list.appendChild(fragment);

            document.getElementById('total-header').innerText = `Витрати`;
            updateMainBudgetSummary(monthVal, totalSum);

            if (targetExpenseId) {
                const targetCard = document.getElementById(`expense-card-${targetExpenseId}`);
                if (targetCard) targetCard.style.animation = 'highlight 1.2s ease';
            }
        })
        .catch(err => {
            if (loadingIndicator) loadingIndicator.style.display = 'none';
            document.getElementById('expenses-list').innerHTML = `<div style="color:red; text-align:center; padding:20px;">Помилка завантаження даних.<br><br><span style="font-size:0.8em; color:gray;">Деталі: ${err.message}<br>${err.stack}</span></div>`;
        });
}

function openReceipt(url) {
    document.getElementById('receipt-image').src = url;
    document.getElementById('receipt-external-link').href = url;
    document.getElementById('receipt-modal').style.display = 'flex';
}

function closeReceipt() {
    document.getElementById('receipt-modal').style.display = 'none';
    document.getElementById('receipt-image').src = '';
}

function openForm(expenseId = '', date = '', amount = '', name = '', category = '', path = '') {
    document.getElementById('f-expense-id').value = expenseId;
    document.getElementById('f-date').value = formatDateForInput(date);
    
    if (amount !== '') {
        const amountNum = parseFloat(amount) || 0;
        const hryvnia = Math.floor(amountNum);
        const kopeck = Math.round((amountNum - hryvnia) * 100);
        document.getElementById('f-hryvnia').value = hryvnia;
        document.getElementById('f-kopeck').value = kopeck.toString().padStart(2, '0');
    } else {
        document.getElementById('f-hryvnia').value = '';
        document.getElementById('f-kopeck').value = '';
    }

    document.getElementById('f-name').value = name;
    
    const catSelect = document.getElementById('f-category');
    let matchedOption = Array.from(catSelect.options).find(
        opt => opt.value === category || opt.textContent.trim() === String(category).trim()
    );
    
    if (matchedOption) {
        catSelect.value = matchedOption.value;
    } else if (category) {
        const option = document.createElement('option');
        option.value = category;
        option.textContent = category;
        catSelect.appendChild(option);
        catSelect.value = category;
    } else {
        catSelect.value = catSelect.options[0] ? catSelect.options[0].value : "";
    }
    
    document.getElementById('f-path').value = path;
    const fileInput = document.getElementById('f-file');
    fileInput.value = '';
    
    if (path && path.trim() !== '') {
        document.getElementById('receipt-preview-box').style.display = 'flex';
        fileInput.style.display = 'none';
    } else {
        document.getElementById('receipt-preview-box').style.display = 'none';
        fileInput.style.display = 'block';
    }
    
    updateNavButtons(expenseId);
    document.getElementById('form-title').innerText = expenseId ? 'Редагувати витрату' : 'Нова витрата';
    document.getElementById('modal').style.display = 'block';
}

function removeAttachedReceipt() {
    document.getElementById('f-path').value = '';
    document.getElementById('receipt-preview-box').style.display = 'none';
    document.getElementById('f-file').style.display = 'block';
    document.getElementById('f-file').value = ''; 
}

function viewAttachedReceipt() {
    const currentPath = document.getElementById('f-path').value;
    if (currentPath) openReceipt(currentPath);
}

function closeForm() { document.getElementById('modal').style.display = 'none'; }
function closeMyBudgetModal() { document.getElementById('my-budget-modal').style.display = 'none'; }
function closeSettingsModal() { document.getElementById('settings-modal').style.display = 'none'; }

async function saveExpense() {
    const fileInput = document.getElementById('f-file');
    let currentPath = document.getElementById('f-path').value;
    
    if (fileInput.files.length > 0) {
        const formData = new FormData();
        formData.append("file", fileInput.files[0]);
        try {
            const uploadRes = await fetch(`/api/upload/${userId}`, { method: "POST", body: formData });
            const uploadData = await uploadRes.json();
            if (uploadData.status === "ok") currentPath = uploadData.file_path;
        } catch (err) {
            alert("Помилка під час завантаження чека.");
            return;
        }
    }

    const expenseId = document.getElementById('f-expense-id').value;
    const hryvnia = parseInt(document.getElementById('f-hryvnia').value) || 0;
    const kopeck = parseInt(document.getElementById('f-kopeck').value) || 0;
    const totalAmount = hryvnia + (kopeck / 100);

    const msgId = urlParams.get('msg_id');
    const selectedCategoryId = document.getElementById('f-category').value;

    const payload = {
        date: document.getElementById('f-date').value,
        amount: totalAmount,
        expense_name: document.getElementById('f-name').value,
        category: selectedCategoryId,
        file_path: currentPath,
        msg_id: msgId ? parseInt(msgId) : null
    };
    
    const method = expenseId ? 'PUT' : 'POST';
    const url = expenseId ? `/api/expenses/${userId}/${expenseId}` : `/api/expenses/${userId}`;
    
    fetch(url, {
        method: method,
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload)
    }).then(r => {
        if (!r.ok) { alert("Помилка збереження! Можливо, ви намагаєтеся відредагувати чужий запис."); return; }
        closeForm();
        // Якщо адмін був на «зведенні» — перемикаємось на свій ЦН, щоб побачити щойно додану витрату
        if (isAdminSummaryMode() && currentUserCenterId) {
            const centerFilter = document.getElementById('main-center-filter');
            if (centerFilter) centerFilter.value = String(currentUserCenterId);
        }
        loadExpenses(expenseId);
        if (urlParams.get('draft') === '1') tg.close();
    });
}

function deleteExpense(expenseId) {
    if (confirm("Ви дійсно хочете видалити цей запис?")) {
        fetch(`/api/expenses/${userId}/${expenseId}`, { method: 'DELETE' })
            .then(r => {
                if (!r.ok) alert("Помилка видалення!");
                loadExpenses();
            });
    }
}

function openSettings() {
    fetch(`/api/user/${userId}/center`)
        .then(r => r.json())
        .then(res => {
            document.getElementById('s-center').value = res.center || '';
            document.getElementById('settings-modal').style.display = 'block';
        });
}

function saveSettings() {
    const center = document.getElementById('s-center').value;
    fetch(`/api/user/${userId}/center`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ center: center })
    }).then(() => {
        document.getElementById('settings-modal').style.display = 'none';
        tg.showAlert("Назву центру оновлено!");
    });
}

function updateNavButtons(expenseId) {
    const navBox = document.getElementById('modal-nav-box');
    const btnPrev = document.getElementById('btn-prev');
    const btnNext = document.getElementById('btn-next');

    if (!expenseId || allExpenses.length === 0) {
        if (navBox) navBox.style.display = 'none';
        currentEditIndex = -1;
        return;
    }

    currentEditIndex = allExpenses.findIndex(item => String((item.expense_id || item.Expense_ID)) === String(expenseId));

    if (currentEditIndex !== -1) {
        if (navBox) navBox.style.display = 'flex';
        btnPrev.disabled = (currentEditIndex <= 0);
        btnNext.disabled = (currentEditIndex >= allExpenses.length - 1);
    } else {
        if (navBox) navBox.style.display = 'none';
    }
}

function navExpense(direction) {
    const newIdx = currentEditIndex + direction;
    if (newIdx >= 0 && newIdx < allExpenses.length) {
        const item = allExpenses[newIdx];
        const amountNum = parseFloat((item.Amount || item.amount)) || 0;
        openForm((item.expense_id || item.Expense_ID), (item.Date || item.date), amountNum, (item.Expense_Name || item.expense_name), (item.category_name || item.Category), (item.receipt_path || item.Receipt_Path) || '');
    }
}

// ==========================================
// КАТЕГОРІЇ КОРИСТУВАЧА
// ==========================================
let currentCategories = [];

function sortCategories(cats) {
    return cats.sort((a, b) => {
        const nameA = typeof a === 'object' ? (a.name || '') : String(a);
        const nameB = typeof b === 'object' ? (b.name || '') : String(b);
        if (nameA === 'Інше') return 1;
        if (nameB === 'Інше') return -1;
        return nameA.localeCompare(nameB, 'uk');
    });
}

function loadCategories() {
    if (!userId) return;
    fetch(`/api/categories`)
        .then(response => response.json())
        .then(result => {
            currentCategories = sortCategories(result.data || []);
            renderCategorySelectOptions();
        });
}

function renderCategorySelectOptions() {
    const catSelect = document.getElementById('f-category');
    if (!catSelect) return;
    const currentVal = catSelect.value;
    catSelect.innerHTML = '';
    
    currentCategories.forEach(cat => {
        const catId = typeof cat === 'object' ? cat.id : cat;
        const catName = typeof cat === 'object' ? cat.name : cat;
        const option = document.createElement('option');
        option.value = catId;
        option.textContent = catName;
        catSelect.appendChild(option);
    });

    if (currentVal && Array.from(catSelect.options).some(opt => opt.value === currentVal)) {
        catSelect.value = currentVal;
    }
}

// ==========================================
// F2. ЗАКРИТТЯ МОДАЛОК ПО ESC ТА КЛІКУ ПО BACKDROP
// ==========================================
// Порядок у списку = порядок «зверху вниз»: першою закривається та, що відкрита зверху
const MODAL_CLOSERS = [
    { id: 'receipt-modal', close: () => closeReceipt() },
    { id: 'admin-budgets-modal', close: () => closeAdminModal() },
    { id: 'my-budget-modal', close: () => closeMyBudgetModal() },
    { id: 'settings-modal', close: () => closeSettingsModal() },
    { id: 'modal', close: () => closeForm() }
];

function isModalVisible(el) {
    return !!el && getComputedStyle(el).display !== 'none';
}

function initModalDismiss() {
    MODAL_CLOSERS.forEach(({ id, close }) => {
        const el = document.getElementById(id);
        if (!el) return;

        // Клік по backdrop (поза .modal-content) закриває модалку.
        // mousedown/touchstart перевіряємо окремо, щоб виділення тексту з відпусканням
        // мишки поза вікном не закривало форму випадково.
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
        const top = MODAL_CLOSERS.find(m => isModalVisible(document.getElementById(m.id)));
        if (top) {
            e.preventDefault();
            top.close();
        }
    });
}

initModalDismiss();

// ==========================================
// F3. СВАЙП МІЖ ВИТРАТАМИ У ФОРМІ
// ==========================================
// Свайп вліво -> наступна витрата, вправо -> попередня (аналог кнопок navExpense)
function initFormSwipe() {
    const content = document.querySelector('#modal .modal-content');
    if (!content) return;

    let startX = 0, startY = 0, startTime = 0;

    content.addEventListener('touchstart', (e) => {
        if (e.touches.length !== 1) return;
        startX = e.touches[0].clientX;
        startY = e.touches[0].clientY;
        startTime = Date.now();
    }, { passive: true });

    content.addEventListener('touchend', (e) => {
        if (!e.changedTouches.length) return;
        const dx = e.changedTouches[0].clientX - startX;
        const dy = e.changedTouches[0].clientY - startY;
        const dt = Date.now() - startTime;

        // Свайп має бути швидким, горизонтальним і достатньо довгим
        if (dt > 800 || Math.abs(dx) < 60 || Math.abs(dy) > 50) return;
        // Перемикання доступне лише для існуючої витрати (коли є кнопки prev/next)
        const navBox = document.getElementById('modal-nav-box');
        if (!navBox || navBox.style.display === 'none') return;

        navExpense(dx < 0 ? 1 : -1);
    }, { passive: true });
}

initFormSwipe();

// ==========================================
// СТАРТ ТА ІНІЦІАЛІЗАЦІЯ
// ==========================================
if (urlParams.get('draft') === '1') {
    const d_date = urlParams.get('date') || '';
    const d_amount = urlParams.get('amount') || '';
    const d_name = urlParams.get('name') || '';
    const d_category = urlParams.get('category') || '';
    const d_path = urlParams.get('path') || '';
    setTimeout(() => { openForm('', d_date, d_amount, d_name, d_category, d_path); }, 500);
}

if (userId) {
    checkUserRole();
    loadCategories();
} else {
    loadExpenses();
}