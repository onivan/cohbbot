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
    const centerId = document.getElementById('u-center-select').value;
    
    if(!centerId) return alert('Оберіть ЦН');
    
    const res = await fetchWithAuth(`/api/admin/users/${userId}/center`, {
        method: 'PUT',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({center_id: parseInt(centerId)})
    });
    
    if(res && res.ok) {
        closeUserModal();
        loadUsers();
    } else {
        alert('Помилка оновлення');
    }
}

// Initialize
window.onload = async () => {
    // Load centers first to populate select
    await loadCenters();
    loadUsers();
};