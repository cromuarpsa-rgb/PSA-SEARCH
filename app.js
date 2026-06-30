const searchInput = document.getElementById('searchInput');
const sheetSelect = document.getElementById('sheetSelect');
const clearButton = document.getElementById('clearButton');
const table = document.getElementById('resultsTable');
const statusText = document.getElementById('statusText');
const fileName = document.getElementById('fileName');
const resultCount = document.getElementById('resultCount');
const totalCount = document.getElementById('totalCount');
const sheetPills = document.getElementById('sheetPills');
const loginForm = document.getElementById('loginForm');
const loginError = document.getElementById('loginError');
const loginScreen = document.getElementById('loginScreen');
const appShell = document.getElementById('appShell');
const adminMenuWrapper = document.getElementById('adminMenuWrapper');
const adminMenuButton = document.getElementById('adminMenuButton');
const adminMenu = document.getElementById('adminMenu');
const adminAddUser = document.getElementById('adminAddUser');
const userModal = document.getElementById('userModal');
const modalBackdrop = document.getElementById('modalBackdrop');
const closeUserModal = document.getElementById('closeUserModal');
const cancelUserModal = document.getElementById('cancelUserModal');
const userForm = document.getElementById('userForm');
const newUsername = document.getElementById('newUsername');
const newPassword = document.getElementById('newPassword');
const userError = document.getElementById('userError');
const userSuccess = document.getElementById('userSuccess');

let workbook = null;
let activeSheet = 'all';
let loaded = false;
let currentUser = null;

const AUTH_USERNAME = 'admin';
const AUTH_PASSWORD = 'admin123';
const LOCAL_USERS_KEY = 'psa_search_users';

function escapeHtml(value) {
  return String(value ?? '')
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;');
}

function showApp() {
  loginScreen.classList.add('hidden');
  appShell.classList.remove('hidden');
}

function showLogin(message = '') {
  loginScreen.classList.remove('hidden');
  appShell.classList.add('hidden');
  loginError.textContent = message;
}

function openUserModal() {
  userModal.classList.remove('hidden');
  userError.textContent = '';
  userSuccess.textContent = '';
  newUsername.value = '';
  newPassword.value = '';
}

function closeUserModalDialog() {
  userModal.classList.add('hidden');
}

function renderSheets() {
  const sheets = workbook?.sheets || [];
  const values = ['all', ...sheets.map((sheet) => sheet.name)];
  const current = Array.from(sheetSelect.options).map((option) => option.value);
  if (JSON.stringify(values) !== JSON.stringify(current)) {
    sheetSelect.innerHTML = '<option value="all">All sheets</option>' + sheets.map((sheet) => `<option value="${escapeHtml(sheet.name)}">${escapeHtml(sheet.name)}</option>`).join('');
    sheetSelect.value = activeSheet;
  }
  sheetPills.innerHTML = ['<button type="button" data-sheet="all" class="' + (activeSheet === 'all' ? 'active' : '') + '">All sheets</button>']
    .concat(sheets.map((sheet) => `<button type="button" data-sheet="${escapeHtml(sheet.name)}" class="${activeSheet === sheet.name ? 'active' : ''}">${escapeHtml(sheet.name)} (${sheet.count})</button>`))
    .join('');
  sheetPills.querySelectorAll('button').forEach((button) => {
    button.addEventListener('click', () => {
      activeSheet = button.dataset.sheet;
      sheetSelect.value = activeSheet;
      renderResults();
    });
  });
}

function filterRows() {
  const term = searchInput.value.trim().toLowerCase();
  const sheets = workbook?.sheets || [];
  const selectedSheets = activeSheet === 'all' ? sheets : sheets.filter((sheet) => sheet.name === activeSheet);

  let columns = [];
  let rows = [];
  let totalMatches = 0;

  for (const sheet of selectedSheets) {
    const sheetColumns = sheet.columns || [];
    sheetColumns.forEach((column) => {
      if (!columns.includes(column)) columns.push(column);
    });
    const matchedRows = (sheet.rows || []).filter((row) => {
      if (!term) return true;
      const haystack = Object.values(row).join(' ').toLowerCase();
      return haystack.includes(term);
    });
    totalMatches += matchedRows.length;
    rows.push(...matchedRows.map((row) => ({ sheet: sheet.name, ...row })));
  }

  return { columns, rows, totalMatches };
}

function renderResults() {
  const { columns, rows, totalMatches } = filterRows();
  const thead = table.querySelector('thead');
  const tbody = table.querySelector('tbody');

  thead.innerHTML = columns.length ? `<tr>${columns.map((column) => `<th>${escapeHtml(column)}</th>`).join('')}</tr>` : '';

  if (!rows.length) {
    tbody.innerHTML = `<tr><td class="empty" colspan="${Math.max(columns.length, 1)}">No matching records found.</td></tr>`;
  } else {
    tbody.innerHTML = rows.slice(0, 250).map((row) => {
      const values = columns.map((column) => row[column] || '');
      return `<tr>${values.map((value) => `<td>${escapeHtml(value)}</td>`).join('')}</tr>`;
    }).join('');
  }

  resultCount.textContent = String(Math.min(rows.length, 250));
  totalCount.textContent = String(totalMatches);
}

function loadStoredUsers() {
  try {
    const raw = localStorage.getItem(LOCAL_USERS_KEY);
    return raw ? JSON.parse(raw) : {};
  } catch {
    return {};
  }
}

function saveStoredUsers(users) {
  localStorage.setItem(LOCAL_USERS_KEY, JSON.stringify(users));
}

async function loadWorkbook() {
  statusText.textContent = 'Loading workbook…';
  try {
    const response = await fetch('data/psa-data.json');
    if (!response.ok) throw new Error('Unable to load workbook data.');
    workbook = await response.json();
    fileName.textContent = workbook.file;
    statusText.textContent = `Loaded ${workbook.sheets.length} sheet(s)`;
    renderSheets();
    renderResults();
    loaded = true;
  } catch (error) {
    statusText.textContent = error.message;
    fileName.textContent = 'Workbook unavailable';
    resultCount.textContent = '0';
    totalCount.textContent = '0';
    table.querySelector('tbody').innerHTML = `<tr><td class="empty">${escapeHtml(error.message)}</td></tr>`;
  }
}

loginForm.addEventListener('submit', (event) => {
  event.preventDefault();
  const username = document.getElementById('username').value.trim();
  const password = document.getElementById('password').value;
  const users = loadStoredUsers();

  if (username === AUTH_USERNAME && password === AUTH_PASSWORD) {
    currentUser = username;
    loginError.textContent = '';
    showApp();
    adminMenuWrapper.classList.remove('hidden');
    if (!loaded) loadWorkbook();
    return;
  }

  if (users[username] && users[username] === password) {
    currentUser = username;
    loginError.textContent = '';
    showApp();
    adminMenuWrapper.classList.add('hidden');
    if (!loaded) loadWorkbook();
    return;
  }

  showLogin('Invalid username or password.');
});

searchInput.addEventListener('input', renderResults);
sheetSelect.addEventListener('change', (event) => {
  activeSheet = event.target.value;
  renderSheets();
  renderResults();
});
clearButton.addEventListener('click', () => {
  searchInput.value = '';
  activeSheet = 'all';
  sheetSelect.value = 'all';
  renderSheets();
  renderResults();
});

adminMenuButton.addEventListener('click', () => {
  const expanded = adminMenuButton.getAttribute('aria-expanded') === 'true';
  adminMenuButton.setAttribute('aria-expanded', String(!expanded));
  adminMenu.classList.toggle('hidden');
});

adminAddUser.addEventListener('click', () => {
  adminMenu.classList.add('hidden');
  adminMenuButton.setAttribute('aria-expanded', 'false');
  openUserModal();
});

closeUserModal.addEventListener('click', closeUserModalDialog);
cancelUserModal.addEventListener('click', closeUserModalDialog);
modalBackdrop.addEventListener('click', closeUserModalDialog);

userForm.addEventListener('submit', (event) => {
  event.preventDefault();
  userError.textContent = '';
  userSuccess.textContent = '';

  const username = newUsername.value.trim();
  const password = newPassword.value;

  if (!username || !password) {
    userError.textContent = 'Both username and password are required.';
    return;
  }
  if (username === AUTH_USERNAME) {
    userError.textContent = 'Cannot create another admin user.';
    return;
  }

  const users = loadStoredUsers();
  if (users[username]) {
    userError.textContent = 'This username already exists.';
    return;
  }

  users[username] = password;
  saveStoredUsers(users);
  userSuccess.textContent = `User "${username}" created successfully.`;
  newUsername.value = '';
  newPassword.value = '';
});

showLogin();
