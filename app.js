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

let workbook = null;
let activeSheet = 'all';
let loaded = false;

const AUTH_USERNAME = 'admin';
const AUTH_PASSWORD = 'admin123';

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

  const columnsToRender = [...columns];
  if (activeSheet === 'all' && !columnsToRender.includes('Sheet')) {
    columnsToRender.unshift('Sheet');
  }

  thead.innerHTML = columnsToRender.length ? `<tr>${columnsToRender.map((column) => `<th>${escapeHtml(column)}</th>`).join('')}</tr>` : '';

  if (!rows.length) {
    tbody.innerHTML = `<tr><td class="empty" colspan="${Math.max(columnsToRender.length, 1)}">No matching records found.</td></tr>`;
  } else {
    tbody.innerHTML = rows.slice(0, 250).map((row) => {
      const values = activeSheet === 'all'
        ? [row.sheet, ...columns.filter((column) => column !== 'Sheet').map((column) => row[column] || '')]
        : columns.map((column) => row[column] || '');
      return `<tr>${values.map((value) => `<td>${escapeHtml(value)}</td>`).join('')}</tr>`;
    }).join('');
  }

  resultCount.textContent = String(Math.min(rows.length, 250));
  totalCount.textContent = String(totalMatches);
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
  if (username === AUTH_USERNAME && password === AUTH_PASSWORD) {
    loginError.textContent = '';
    showApp();
    if (!loaded) loadWorkbook();
  } else {
    showLogin('Invalid username or password.');
  }
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

showLogin();
