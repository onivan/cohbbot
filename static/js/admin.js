async function fetchWithAuth(url, options = {}) {
    const res = await fetch(url, options);
    if (res.status === 401) {
        window.location.href = '/login';
        return null;
    }
    return res;
}

function switchTab(tabId) {
    document.querySelectorAll('.tab-content').forEach(el => el.classList.remove('active'));
    document.querySelectorAll('.tab-btn').forEach(el => el.classList.remove('active'));
    
    document.getElementById(tabId).classList.add('active');
    event.currentTarget.classList.add('active');
    
    if(tabId === 'users') loadUsers();
    if(tabId === 'centers') loadCenters();
    if(tabId === 'categories') loadCategories();
    if(tabId === 'matrix') loadMatrix();
}

let allCenters = [];

async function loadCenters() {
    const res = await fetchWithAuth('/api/admin/centers');
    if (!res) return;
    const data = await res.json();
    if (data.status === 'ok') {
        allCenters = data.data;
        const tbody = document.querySelector('#centers-table tbody');
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
        
        // Populate select for user modal
        const select = document.getElementById('u-center-select');
        select.innerHTML = '<option value="">-- Не призначено --</option>';
        data.data.filter(c => c.is_active).forEach(c => {
            select.innerHTML += `<option value="${c.id}">${c.name}</option>`;
        });
    }
}

async function loadUsers() {
    const res = await fetchWithAuth('/api/admin/users');
    if (!res) return;
    const data = await res.json();
    if (data.status === 'ok') {
        const tbody = document.querySelector('#users-table tbody');
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
}

// Center Modal logic
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
    
    if(!name) return alert('Назва обов\'язкова');
    
    const url = id ? `/api/admin/centers/${id}` : '/api/admin/centers';
    const method = id ? 'PUT' : 'POST';
    
    const res = await fetchWithAuth(url, {
        method: method,
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({name, city, is_active: isActive})
    });
    
    if(res && res.ok) {
        closeCenterModal();
        loadCenters();
    } else {
        alert('Помилка збереження');
    }
}

// User Modal logic
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
    
    if(res && res.ok) {
        closeUserModal();
        loadUsers();
    } else {
        alert('Помилка оновлення');
    }
}

// Categories logic
async function loadCategories() {
    const res = await fetchWithAuth('/api/admin/categories');
    if (!res) return;
    const data = await res.json();
    if (data.status === 'ok') {
        const tbody = document.querySelector('#categories-table tbody');
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
    
    if(!id || !name) return alert('ID та Назва обов\'язкові');
    if(!id.startsWith('cat_') && !isEditingCategory) return alert('ID має починатися з cat_');
    
    const url = isEditingCategory ? `/api/admin/categories/${id}` : '/api/admin/categories';
    const method = isEditingCategory ? 'PUT' : 'POST';
    
    const res = await fetchWithAuth(url, {
        method: method,
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({id, name, sort_order: sortOrder, is_active: isActive})
    });
    
    if(res && res.ok) {
        closeCategoryModal();
        loadCategories();
    } else {
        alert('Помилка збереження. Можливо, такий ID вже існує.');
    }
}

// Matrix logic
async function loadMatrix() {
    const res = await fetchWithAuth('/api/admin/matrix');
    if (!res) return;
    const data = await res.json();
    
    if (data.status === 'ok') {
        const centers = data.data.centers;
        const categories = data.data.categories;
        const links = data.data.links;
        
        const headerRow = document.getElementById('matrix-header');
        headerRow.innerHTML = '<th>Центр Надії \\ Категорії</th>';
        
        categories.forEach(cat => {
            headerRow.innerHTML += `<th>${cat.name}</th>`;
        });
        
        const tbody = document.getElementById('matrix-body');
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
    
    if(!res || !res.ok) {
        alert('Помилка оновлення матриці');
        loadMatrix(); // reload to reset checkbox state
    }
}
window.onload = async () => {
    // Load centers first to populate select
    await loadCenters();
    loadUsers();
};