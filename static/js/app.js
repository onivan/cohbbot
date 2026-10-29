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

        const tg = window.Telegram.WebApp;
        tg.ready();
        tg.expand();

        if (tg.colorScheme === 'dark') {
            document.body.classList.add('dark');
        }

        // БЕЗПЕЧНА АВТОРИЗАЦІЯ ВІД TELEGRAM (без хардкоду)
                const user = tg.initDataUnsafe && tg.initDataUnsafe.user ? tg.initDataUnsafe.user : null;
        let userId = user ? user.id : null;
        
        // Якщо WebApp відкрито у звичайному браузері, спробуємо отримати ID з мета-тега, куди бекенд міг його покласти
        if (!userId) {
            const metaUserId = document.querySelector('meta[name="user-id"]');
            if (metaUserId && metaUserId.content) {
                userId = metaUserId.content;
            }
        }
        
// Перевизначаємо fetch для автоматичного додавання заголовка авторизації
const originalFetch = window.fetch;
window.fetch = function() {
    let [resource, config] = arguments;
    if(userId) {
        if(!config) config = {};
        if(!config.headers) config.headers = {};
        // Додаємо заголовок x-telegram-user-id якщо він не існує
        if(config.headers instanceof Headers) {
            config.headers.set('x-telegram-user-id', userId);
        } else {
            config.headers['x-telegram-user-id'] = userId;
        }
    }
    return originalFetch(resource, config);
};

                const currentMonth = new Date().toISOString().slice(0, 7); // YYYY-MM
        document.getElementById('my-budget-month').value = currentMonth;
        document.getElementById('admin-budget-month').value = currentMonth;
        
                // Встановлюємо поточний місяць і для головного фільтра
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
            if (currentUserRole === 'admin' && !currentUserCenterId && (!document.getElementById('main-center-filter') || document.getElementById('main-center-filter').value === "0")) {
                loadAdminCentersSummary();
            } else {
                loadExpenses();
            }
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

        function checkUserRole() {
            if (!userId) {
                console.warn("checkUserRole: userId is null");
                return;
            }
            fetch(`/api/user/${userId}/role`)
                .then(r => {
                    if (!r.ok) throw new Error(`Role HTTP error ${r.status}`);
                    return r.json();
                })
                .then(res => {
                    isRoleChecked = true;
                    currentUserRole = res.role;
                    currentUserCenterId = res.center_id;

                    const btnMyBudget = document.getElementById('btn-my-budget');
                    const btnAddExpense = document.getElementById('btn-add-expense');

                    // Показуємо кнопки дій лише користувачам, які мають призначений ЦН
                    if (currentUserCenterId) {
                        if (btnMyBudget) btnMyBudget.style.display = 'inline-block';
                        if (btnAddExpense) btnAddExpense.style.display = 'inline-block';
                    } else {
                        if (btnMyBudget) btnMyBudget.style.display = 'none';
                        if (btnAddExpense) btnAddExpense.style.display = 'none';
                    }

                    if (currentUserRole === 'admin') {
                        const adminBtn = document.getElementById('btn-admin-panel') || document.getElementById('btn-admin-budgets');
                        if (adminBtn) adminBtn.style.display = 'inline-block';
                        loadCentersForAdmin();
                        loadCentersForAdminFilter();

                        // Якщо це адмін БЕЗ центру, за замовчуванням показуємо зведення центрів
                        if (!currentUserCenterId) {
                            loadAdminCentersSummary();
                        } else {
                            loadExpenses();
                        }
                    } else {
                        loadExpenses();
                    }
                })
                .catch(err => {
                    console.error("Error fetching user role:", err);
                    const expensesList = document.getElementById('expenses-list');
                    if (expensesList) {
                        expensesList.innerHTML = `<div style="color: red; padding: 15px;">Помилка отримання ролі: ${err.message}</div>`;
                    }
                });
        }

        function loadAdminCentersSummary() {
            const filterMonth = document.getElementById('main-month-filter');
            const monthVal = filterMonth ? filterMonth.value : '';
            const summaryView = document.getElementById('admin-centers-summary-view');
            const summaryList = document.getElementById('admin-centers-summary-list');
            const expensesList = document.getElementById('expenses-list');
            const totalHeader = document.getElementById('total-header');

            if (!summaryView || !summaryList) {
                console.error("Summary elements not found in DOM");
                if (expensesList) expensesList.innerHTML = '<div style="color: red; padding: 20px;">Помилка розмітки: admin-centers-summary-view не знайдено</div>';
                return;
            }

            summaryView.style.display = 'block';
            if (expensesList) expensesList.style.display = 'none';

            let url = '/api/admin/centers/summary';
            if (monthVal) url += `?month=${monthVal}`;

            summaryList.innerHTML = '<div style="text-align: center; color: var(--tg-theme-hint-color, #888); padding: 15px;">Завантаження зведення по центрах...</div>';

            fetch(url)
                .then(r => {
                    if (!r.ok) {
                        throw new Error(`HTTP помилка ${r.status}: ${r.statusText}`);
                    }
                    return r.json();
                })
                .then(res => {
                    if (res.status !== 'ok') {
                        throw new Error(res.detail || "Сервер повернув помилку");
                    }
                    const centers = res.data || [];
                    if (centers.length === 0) {
                        summaryList.innerHTML = '<div style="color: #888; text-align: center; padding: 15px;">Немає зареєстрованих або активних центрів.</div>';
                        return;
                    }

                    let html = '';
                    let grandSpent = 0;
                    let grandBudget = 0;

                    centers.forEach(c => {
                        const spent = c.total_spent || 0;
                        const budget = c.total_budget || 0;
                        const hasBudget = c.has_budget;
                        grandSpent += spent;
                        if (hasBudget) grandBudget += budget;

                        let percent = 0;
                        if (hasBudget && budget > 0) percent = Math.min(100, Math.round((spent / budget) * 100));
                        else if (spent > 0) percent = 100;

                        const barColor = getProgressBarColor(percent);
                        const budgetText = hasBudget ? (budget > 0 ? budget.toFixed(0) + ' грн' : '0 грн') : 'не встановлено';

                        html += `
                            <div class="expense-card" style="cursor: pointer; margin-bottom: 12px; transition: transform 0.1s;" onclick="selectCenterForAdmin(${c.id})" title="Натисніть, щоб відкрити панель ЦН">
                                <div class="header" style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 6px;">
                                    <strong>🏢 ${c.name} (${c.city || 'ЦН'})</strong>
                                    <span style="font-weight: bold; color: var(--tg-theme-button-color, #2481cc);">⚙️ Керувати ➔</span>
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
                            <code>${err.message}</code><br><br>
                            <span style="font-size: 0.85em; color: #555;">URL: ${url}</span>
                        </div>
                    `;
                });
        }

        function selectCenterForAdmin(centerId) {
            // Встановлюємо фільтр центрів і завантажуємо витрати цього центру
            const centerFilter = document.getElementById('main-center-filter');
            if (centerFilter) {
                centerFilter.value = centerId;
            }
            // Відкриваємо модальне вікно адміна для обраного центру
            const adminSelect = document.getElementById('admin-center-select');
            if (adminSelect) {
                adminSelect.value = centerId;
            }
            openAdminModal(centerId);
        }
        
        

        
        function loadCentersForAdminFilter() {
            fetch(`/api/admin/centers?admin_id=${userId}`)
                .then(r => r.json())
                .then(res => {
                    const select = document.getElementById('main-center-filter');
                    const container = document.getElementById('admin-center-filter-container');
                    if (res.data && select && container) {
                        res.data.forEach(c => {
                            const opt = document.createElement('option');
                            opt.value = c.id;
                            opt.textContent = c.name;
                            select.appendChild(opt);
                        });
                        container.style.display = 'flex';
                    }
                });
        }

        let allExpenses = [];      
        let currentEditIndex = -1; 
        
        function loadCentersForAdmin() {
            fetch(`/api/admin/centers?admin_id=${userId}`)
                .then(r => r.json())
                .then(res => {
                    const select = document.getElementById('admin-center-select');
                    if(select) {
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
            // Оновлюємо заголовок з назвою центру
            const centerFilter = document.getElementById('main-center-filter');
            const titleEl = document.getElementById('my-budget-title');
            if (centerFilter && centerFilter.value && centerFilter.value !== "0" && currentUserRole === 'admin') {
                const centerName = centerFilter.options[centerFilter.selectedIndex] ? centerFilter.options[centerFilter.selectedIndex].text : '';
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
            if (percent <= 25) return '#4CAF50'; // Зелений (до 25%)
            if (percent <= 50) return '#8BC34A'; // Світло-зелений (26-50%)
            if (percent <= 75) return '#FFC107'; // Бурштиновий (51-75%)
            if (percent <= 99) return '#FF9800'; // Помаравневий (76-99%)
            return '#F44336'; // Червоний (100% і більше)
        }
        
        function loadMyBudget() {
            const month = document.getElementById('my-budget-month').value;
            if (!month || !userId) return;
            
            const list = document.getElementById('my-budget-list');
            list.innerHTML = 'Завантаження...';
            
            // Якщо адмін обрав конкретний центр на головній сторінці, дивимось бюджет цього центру
            const centerFilter = document.getElementById('main-center-filter');
            let budgetUrl = `/api/budgets/${userId}?month=${month}`;
            if (centerFilter && centerFilter.value && centerFilter.value !== "0" && currentUserRole === 'admin') {
                budgetUrl = `/api/budgets/center/${centerFilter.value}?month=${month}`;
            }
            
            // Отримуємо бюджети
            fetch(budgetUrl)
                .then(r => r.json())
                .then(budgetRes => {
                    const budgets = budgetRes.data || {};
                    
                    // Виводимо дебаг в панель (можна розкоментувати за потреби)
                    
                                        const debugPanel = document.getElementById('budget-debug-panel');
                    if (debugPanel) {
                        debugPanel.textContent = JSON.stringify({
                            "currentMonthSelected": month,
                            "expensesCount": allExpenses.length,
                            "firstExpenseRaw": allExpenses[0] || null,
                            "parsedFirstDate": allExpenses[0] ? parseDate(allExpenses[0].Date || allExpenses[0].date) : null,
                            "budgetsResult": budgets
                        }, null, 2);
                    }
                    
                    
                    // Обчислюємо фактичні витрати за обраний місяць
                    const expensesByCat = {};
                    let totalSpent = 0;
                    let totalPlanned = 0;
                    
                    allExpenses.forEach(exp => {
                        const rawDate = exp.Date || exp.date;
                        const expDate = parseDate(rawDate);
                        if (expDate && `${expDate.year}-${expDate.month}` === month) {
                            const catName = exp.category_name || exp.Category_Name || exp.Category || 'Інше';
                            const amount = parseFloat(exp.amount || exp.Amount) || 0;
                            
                            // З новою структурою таблиці Expenses намагаємося взяти Category_ID / category_id
                            let catId = String(exp.category_id || exp.Category_ID || '').trim();
                            
                            // Fallback: шукаємо ID за іменем категорії
                            if (!catId || !catId.startsWith('cat_')) {
                                catId = 'cat_other';
                                const matchedCat = currentCategories.find(c => {
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
            
            if (currentCategories.length === 0) {
                list.innerHTML = 'Категорії не завантажено.';
                return;
            }
            
            let html = '';
            currentCategories.forEach(cat => {
                const catId = typeof cat === 'object' ? cat.id : cat;
                const catName = typeof cat === 'object' ? cat.name : cat;
                
                const cleanCatId = String(catId).trim();
                const hasBudget = Object.prototype.hasOwnProperty.call(budgets, cleanCatId);
                const planned = hasBudget ? budgets[cleanCatId] : 0;
                const spent = expensesByCat[cleanCatId] || 0;
                const remaining = planned - spent;
                        
                if (hasBudget) {
                    totalPlanned += planned;
                }
                totalSpent += spent;
                
                let percent = 0;
                if (hasBudget && planned > 0) percent = Math.min(100, Math.round((spent / planned) * 100));
                else if (spent > 0) percent = 100; // Витрати без бюджету
                
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
                        // Додаємо підсумок
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
                // Приховуємо вибір центру, адже центр уже обрано з картки
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
                if (listBox) listBox.innerHTML = 'Оберіть користувача.';
                return;
            }

            if (listBox) listBox.innerHTML = 'Завантаження категорій...';

            fetch(`/api/categories/${targetCenterId}`)
                .then(r => r.json())
                .then(res => {
                    adminTargetCategories = sortCategories(res.data || []);
                    renderAdminCategoriesListBox();
                })
                .catch(err => {
                    if (listBox) listBox.innerHTML = 'Помилка завантаження категорій: ' + err.message;
                });
        }

        function renderAdminCategoriesListBox(editingCat = null) {
            const box = document.getElementById('admin-categories-list-box');
            if (!box) return;
            box.innerHTML = '';

            if (adminTargetCategories.length === 0) {
                box.innerHTML = '<div style="text-align:center; color:#888;">Категорій немає.</div>';
                return;
            }

            adminTargetCategories.forEach((cat) => {
                const catName = typeof cat === 'object' ? cat.name : cat;
                const item = document.createElement('div');
                item.style.cssText = 'display: flex; justify-content: space-between; align-items: center; padding: 6px 0; border-bottom: 1px solid rgba(128,128,128,0.2);';

                if (editingCat && editingCat === catName) {
                    const safeOldName = catName.replace(/'/g, "\\'");
                    item.innerHTML = `
                        <input type="text" id="admin-inline-edit-input" value="${catName.replace(/"/g, '&quot;')}" style="flex: 1; margin-right: 8px; padding: 4px 6px; margin-top: 0;" onkeydown="if(event.key==='Enter') saveAdminCategoryRename('${safeOldName}')">
                        <div style="display: flex; gap: 5px;">
                            <button type="button" class="btn-sm" style="background-color: #4CAF50; color: white;" onclick="saveAdminCategoryRename('${safeOldName}')">💾</button>
                            <button type="button" class="btn-sm btn-danger" onclick="renderAdminCategoriesListBox()">❌</button>
                        </div>
                    `;
                } else {
                    let actionsHtml = '';
                    if (catName !== 'Інше') {
                        const safeName = catName.replace(/'/g, "\\'");
                        actionsHtml = `
                            <div style="display: flex; gap: 5px;">
                                <button type="button" class="btn-sm" onclick="startAdminInlineEdit('${safeName}')">✏️</button>
                                <button type="button" class="btn-sm btn-danger" onclick="removeAdminCenterCategory('${safeName}')">🗑</button>
                            </div>
                        `;
                    }
                    item.innerHTML = `<span>${catName}</span>${actionsHtml}`;
                }

                box.appendChild(item);
            });
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
                list.innerHTML = 'Оберіть користувача.';
                return;
            }
            if (!month) {
                list.innerHTML = 'Оберіть місяць.';
                return;
            }
            
            list.innerHTML = 'Завантаження категорій, бюджетів та витрат...';
            
            // Отримуємо категорії, бюджети та фактичні витрати паралельно
            Promise.all([
                fetch(`/api/categories/${targetCenterId}`).then(r => r.json()),
                fetch(`/api/budgets/center/${targetCenterId}?month=${month}`).then(r => r.json()),
                fetch(`/api/expenses/${userId}?center_id=${targetCenterId}`).then(r => r.json())
        ])
        .then(([catRes, budgetRes, expRes]) => {
                const userCats = sortCategories(catRes.data || []);
                const budgets = budgetRes.data || {};
                const targetExpenses = expRes.data || [];
                
                // Виводимо дебаг в панель адміна (можна розкоментувати за потреби)
                
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
                
            
                // Обчислюємо фактичні витрати обраного центру
                const expensesByCat = {};
                let totalSpent = 0;
                let totalPlanned = 0;
                
                targetExpenses.forEach(exp => {
                    const rawDate = exp.Date || exp.date;
                    const expDate = parseDate(rawDate);
                    if (expDate && `${expDate.year}-${expDate.month}` === month) {
                        const catName = exp.category_name || exp.Category_Name || exp.Category || 'Інше';
                        const amount = parseFloat(exp.amount || exp.Amount) || 0;
                        
                        // Беремо category_id / Category_ID якщо воно є
                        let catId = String(exp.category_id || exp.Category_ID || '').trim();
                        
                        // Fallback для старих даних
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
                
                    // Нормалізуємо catId для надійного пошуку в budgets
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
                    list.innerHTML = 'У користувача немає категорій.';
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
            
            // Збираємо суми з усіх інпутів бюджету
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
                    input.style.backgroundColor = '#d4edda'; // green highlight
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
            // Якщо обрано "Всі центри (Зведений)", не показуємо одиночний бюджет або приховуємо
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
                    console.error("Error loading budget summary:", err);
                    summaryBox.style.display = 'none';
                });
        }

        function loadExpenses(targetExpenseId = null) {
            const summaryView = document.getElementById('admin-centers-summary-view');
            const centerFilterEl = document.getElementById('main-center-filter');
            
            // Якщо це адмін без центру і вибрано "Всі центри (Зведений)" або фільтр не задано
            if (currentUserRole === 'admin' && !currentUserCenterId && (!centerFilterEl || centerFilterEl.value === "0")) {
                if (summaryView) summaryView.style.display = 'block';
                const expensesList = document.getElementById('expenses-list');
                if (expensesList) expensesList.style.display = 'none';
                loadAdminCentersSummary();
                return;
            } else {
                if (summaryView) summaryView.style.display = 'none';
                const expensesList = document.getElementById('expenses-list');
                if (expensesList) expensesList.style.display = 'block';
            }

            if (!userId) {
                const debugData = JSON.stringify(tg.initDataUnsafe, null, 2);
                const currentUrl = window.location.href;
                debugDataFull = "Full URL:" + window.location.href + "<br>Hash:" + window.location.hash + "<br>Raw initData:" + tg.initData + "<br>initDataUnsafe:" + tg.initDataUnsafe;
                
                document.getElementById('expenses-list').innerHTML = 
                    '<div style="color: red; text-align: center; padding: 20px;">' +
                    '⚠️ Авторизація недійсна.<br><br>' +
                    '<div style="color: black; text-align: left; font-size: 12px; background: #eee; padding: 10px; border-radius: 5px; overflow-x: auto;">' +
                    '<b>URL:</b><br>' + currentUrl + '<br><br>' +
                    '<b>Full Debug Data:</b><br><pre>' + debugDataFull + '</pre>' +
                    '</div></div>';
                document.getElementById('total-header').innerText = 'Помилка доступу';
                return;
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
                    if (!response.ok) throw new Error("Помилка доступу");
                    return response.json();
                })
                .then(result => {
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
                        
                                                // ДІАГНОСТИЧНИЙ ВИВІД (можна видалити після виправлення)
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

            const urlParams = new URLSearchParams(window.location.search);
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
                loadExpenses(expenseId);
                if (urlParams.get('draft') === '1') tg.close();
            });
        }

        function deleteExpense(expenseId) {
            if(confirm("Ви дійсно хочете видалити цей запис?")) {
                fetch(`/api/expenses/${userId}/${expenseId}`, { method: 'DELETE' })
                    .then(r => {
                        if(!r.ok) alert("Помилка видалення!");
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

        // Керування персональними категоріями
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

        // Старт та авто-відкриття чернетки з URL
        const urlParams = new URLSearchParams(window.location.search);
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
            console.warn("userId not found on start, calling loadExpenses()");
            loadExpenses(); // відобразить застереження про відсутність авторизації
        }
