/**
 * Expense Tracker – Node.js / Express server
 *
 * Endpoints:
 *   GET  /                  → dashboard UI
 *   POST /api/upload        → parse uploaded CSV/XLSX files, return JSON
 *   GET  /api/overrides     → list all overrides
 *   POST /api/override      → set a merchant override
 *   DELETE /api/overrides    → clear all overrides
 */

const express = require('express');
const multer = require('multer');
const path = require('path');
const fs = require('fs');
const { parse } = require('csv-parse/sync');
const XLSX = require('xlsx');

const app = express();
const PORT = 3000;
const upload = multer({ storage: multer.memoryStorage() });

app.use(express.json());
app.use(express.static(path.join(__dirname, 'public')));

// ---------------------------------------------------------------------------
// Config paths
// ---------------------------------------------------------------------------
const CONFIG_DIR = path.join(__dirname, 'config');
const CATEGORIES_PATH = path.join(CONFIG_DIR, 'categories.json');
const OVERRIDES_PATH = path.join(CONFIG_DIR, 'overrides.json');

// ---------------------------------------------------------------------------
// Load categories config
// ---------------------------------------------------------------------------
function loadCategories() {
  const data = JSON.parse(fs.readFileSync(CATEGORIES_PATH, 'utf-8'));
  const rules = {};
  const icons = {};
  for (const [name, info] of Object.entries(data.categories)) {
    rules[name] = info.keywords.map(k => k.toLowerCase());
    icons[name] = info.icon || '';
  }
  return {
    rules,
    icons,
    uncategorisedLabel: data.uncategorized?.label || 'Other / Uncategorised',
    uncategorisedIcon: data.uncategorized?.icon || '❓',
    itemisedThreshold: data.itemised_threshold_gbp || 30,
  };
}

// ---------------------------------------------------------------------------
// Overrides store
// ---------------------------------------------------------------------------
function loadOverrides() {
  try {
    if (fs.existsSync(OVERRIDES_PATH)) {
      return JSON.parse(fs.readFileSync(OVERRIDES_PATH, 'utf-8'));
    }
  } catch { /* ignore */ }
  return {};
}

function saveOverrides(data) {
  try {
    fs.mkdirSync(CONFIG_DIR, { recursive: true });
    fs.writeFileSync(OVERRIDES_PATH, JSON.stringify(data, null, 2));
  } catch (e) {
    console.warn('Could not persist overrides (read-only filesystem):', e.message);
  }
}

// ---------------------------------------------------------------------------
// Categoriser
// ---------------------------------------------------------------------------
function categorise(description, rules, overrides, uncatLabel) {
  const key = description.toLowerCase().trim();
  // 1. Exact match on full description
  if (overrides[key]) return overrides[key];
  // 2. Match on the name part (before |) for combined descriptions
  const namePart = key.includes('|') ? key.split('|')[0].trim() : null;
  if (namePart && overrides[namePart]) return overrides[namePart];
  // 3. Check if any override key is contained in the description
  for (const [oKey, oCat] of Object.entries(overrides)) {
    if (key.includes(oKey)) return oCat;
  }
  // 4. Keyword rules
  for (const [category, keywords] of Object.entries(rules)) {
    for (const kw of keywords) {
      if (key.includes(kw)) return category;
    }
  }
  return uncatLabel;
}

// ---------------------------------------------------------------------------
// Date parsing helpers
// ---------------------------------------------------------------------------
const DATE_FORMATS = [
  // dd/mm/yyyy
  { re: /^(\d{1,2})\/(\d{1,2})\/(\d{4})$/, parse: m => new Date(+m[3], +m[2] - 1, +m[1]) },
  // dd-mm-yyyy
  { re: /^(\d{1,2})-(\d{1,2})-(\d{4})$/, parse: m => new Date(+m[3], +m[2] - 1, +m[1]) },
  // yyyy-mm-dd
  { re: /^(\d{4})-(\d{1,2})-(\d{1,2})$/, parse: m => new Date(+m[1], +m[2] - 1, +m[3]) },
  // dd/mm/yy
  { re: /^(\d{1,2})\/(\d{1,2})\/(\d{2})$/, parse: m => new Date(2000 + +m[3], +m[2] - 1, +m[1]) },
  // mm/dd/yyyy (fallback)
  { re: /^(\d{1,2})\/(\d{1,2})\/(\d{4})$/, parse: m => new Date(+m[3], +m[1] - 1, +m[2]) },
];

function parseDate(str) {
  if (!str) return null;
  const s = String(str).trim();
  for (const { re, parse: fn } of DATE_FORMATS) {
    const m = s.match(re);
    if (m) {
      const d = fn(m);
      if (!isNaN(d.getTime())) return d;
    }
  }
  // try JS native
  const d = new Date(s);
  return isNaN(d.getTime()) ? null : d;
}

function toISODate(d) {
  if (!d) return null;
  return d.toISOString().slice(0, 10);
}

function fmtDate(d) {
  if (!d) return '';
  const months = ['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec'];
  return `${String(d.getDate()).padStart(2,'0')} ${months[d.getMonth()]} ${d.getFullYear()}`;
}

// ---------------------------------------------------------------------------
// CSV / XLSX Parsers  (mirrors Python parsers.py)
// ---------------------------------------------------------------------------

function normaliseRows(rows, source) {
  return rows
    .filter(r => r.date && r.amount > 0)
    .map(r => ({
      date: toISODate(r.date),
      dateObj: r.date,
      description: String(r.description || '').trim(),
      amount: Math.round(r.amount * 100) / 100,
      type: r.type || 'debit',
      source_file: source,
    }));
}

function lowerCols(record) {
  const out = {};
  for (const [k, v] of Object.entries(record)) {
    out[k.toLowerCase().trim()] = v;
  }
  return out;
}

function toNum(val) {
  if (val == null) return NaN;
  const n = parseFloat(String(val).replace(/,/g, '').replace(/£/g, '').trim());
  return n;
}

// --- Monzo ---
function parseMonzo(records, source) {
  const first = lowerCols(records[0]);
  if (!('transaction id' in first)) return null;
  return normaliseRows(records.map(r => {
    const lr = lowerCols(r);
    const amt = toNum(lr.amount);
    if (amt === 0 || isNaN(amt)) return null;
    // Combine Name + raw Description for better keyword matching
    const name = (lr.name || '').trim();
    const rawDesc = (lr.description || '').trim();
    const monzoType = (lr.type || '').trim();
    // Build a rich description: Name | raw descriptor | Monzo type for matching
    let combined = name;
    if (rawDesc && rawDesc.toLowerCase() !== name.toLowerCase()) combined += ` | ${rawDesc}`;
    if (monzoType) combined += ` | ${monzoType}`;
    if (!combined) combined = rawDesc || monzoType;
    return {
      date: parseDate(lr.date),
      description: combined,
      amount: Math.abs(amt),
      type: amt < 0 ? 'debit' : 'credit',
    };
  }).filter(Boolean), source);
}

// --- Starling ---
function parseStarling(records, source) {
  const first = lowerCols(records[0]);
  const cpKey = 'counter party' in first ? 'counter party' : ('counterparty' in first ? 'counterparty' : null);
  if (!cpKey) return null;
  const amtKey = Object.keys(first).find(k => k.includes('amount') && k.includes('gbp')) ||
                 Object.keys(first).find(k => k.includes('amount')) || 'amount';
  return normaliseRows(records.map(r => {
    const lr = lowerCols(r);
    const amt = toNum(lr[amtKey]);
    if (amt === 0 || isNaN(amt)) return null;
    const desc = `${lr[cpKey] || ''} ${lr.reference || ''}`.trim();
    return { date: parseDate(lr.date), description: desc, amount: Math.abs(amt), type: amt < 0 ? 'debit' : 'credit' };
  }).filter(Boolean), source);
}

// --- Revolut ---
function parseRevolut(records, source) {
  const first = lowerCols(records[0]);
  if (!('completed date' in first) && !('started date' in first)) return null;
  const dateKey = 'completed date' in first ? 'completed date' : 'started date';
  return normaliseRows(records.map(r => {
    const lr = lowerCols(r);
    const amt = toNum(lr.amount);
    if (amt === 0 || isNaN(amt)) return null;
    return { date: parseDate(lr[dateKey]), description: lr.description || '', amount: Math.abs(amt), type: amt < 0 ? 'debit' : 'credit' };
  }).filter(Boolean), source);
}

// --- Lloyds / Halifax ---
function parseLloyds(records, source) {
  const first = lowerCols(records[0]);
  if (!('transaction description' in first) || !('debit amount' in first)) return null;
  return normaliseRows(records.map(r => {
    const lr = lowerCols(r);
    const debit = toNum(lr['debit amount']);
    const credit = toNum(lr['credit amount']);
    if (debit > 0) return { date: parseDate(lr['transaction date']), description: lr['transaction description'] || '', amount: debit, type: 'debit' };
    if (credit > 0) return { date: parseDate(lr['transaction date']), description: lr['transaction description'] || '', amount: credit, type: 'credit' };
    return null;
  }).filter(Boolean), source);
}

// --- HSBC ---
function parseHSBC(records, source) {
  const first = lowerCols(records[0]);
  if (!('debit' in first) || !('credit' in first)) return null;
  const descKey = 'description' in first ? 'description' : Object.keys(first)[1];
  return normaliseRows(records.map(r => {
    const lr = lowerCols(r);
    const debit = toNum(lr.debit);
    const credit = toNum(lr.credit);
    if (debit > 0) return { date: parseDate(lr.date), description: lr[descKey] || '', amount: debit, type: 'debit' };
    if (credit > 0) return { date: parseDate(lr.date), description: lr[descKey] || '', amount: credit, type: 'credit' };
    return null;
  }).filter(Boolean), source);
}

// --- Amex detailed ---
function parseAmexDetailed(records, source) {
  const first = lowerCols(records[0]);
  if (!('billing amount' in first) || !('merchant' in first) || !('debit or credit' in first)) return null;
  const dateKey = 'transaction date' in first ? 'transaction date' : 'posting date';
  return normaliseRows(records.map(r => {
    const lr = lowerCols(r);
    const amt = toNum(lr['billing amount']);
    if (!(amt > 0)) return null;
    const dc = (lr['debit or credit'] || '').toUpperCase();
    const type = dc === 'CRDT' ? 'credit' : 'debit';
    return { date: parseDate(lr[dateKey]), description: (lr.merchant || '').trim(), amount: amt, type };
  }).filter(Boolean), source);
}

// --- Amex simple ---
function parseAmex(records, source) {
  const first = lowerCols(records[0]);
  const keys = Object.keys(first);
  if (!('amount' in first) || !('description' in first) || keys.length > 6) return null;
  return normaliseRows(records.map(r => {
    const lr = lowerCols(r);
    const amt = toNum(lr.amount);
    if (amt === 0 || isNaN(amt)) return null;
    // Amex: positive = charge (debit), negative = refund (credit)
    return { date: parseDate(lr.date), description: lr.description || '', amount: Math.abs(amt), type: amt > 0 ? 'debit' : 'credit' };
  }).filter(Boolean), source);
}

// --- Generic fallback ---
function parseGeneric(records, source) {
  if (!records.length) return [];
  const first = lowerCols(records[0]);
  const keys = Object.keys(first);

  // Find date column
  let dateCol = ['date', 'transaction date', 'trans date', 'posted date', 'value date'].find(c => c in first);
  if (!dateCol) dateCol = keys.find(k => k.includes('date'));
  if (!dateCol) dateCol = keys[0];

  // Find description column
  let descCol = ['description', 'transaction description', 'narrative', 'details', 'memo', 'name', 'payee', 'merchant'].find(c => c in first);
  if (!descCol) descCol = keys.find(k => /desc|narr|detail|memo/.test(k));
  if (!descCol) descCol = keys[1] || keys[0];

  // Find amount column
  let amtCol = ['amount', 'debit', 'debit amount', 'value', 'transaction amount'].find(c => c in first);
  if (!amtCol) amtCol = keys.find(k => /amount|debit|value/.test(k));
  if (!amtCol) amtCol = keys[keys.length - 1];

  return normaliseRows(records.map(r => {
    const lr = lowerCols(r);
    const raw = toNum(lr[amtCol]);
    if (isNaN(raw) || raw === 0) return null;
    return { date: parseDate(lr[dateCol]), description: String(lr[descCol] || ''), amount: Math.abs(raw), type: raw < 0 ? 'debit' : 'credit' };
  }).filter(Boolean), source);
}

const PARSERS = [parseAmexDetailed, parseMonzo, parseStarling, parseRevolut, parseLloyds, parseHSBC, parseAmex];

function parseFile(buffer, filename) {
  const ext = path.extname(filename).toLowerCase();
  let records;

  if (ext === '.xlsx' || ext === '.xls') {
    const wb = XLSX.read(buffer, { type: 'buffer' });
    const ws = wb.Sheets[wb.SheetNames[0]];
    records = XLSX.utils.sheet_to_json(ws);
  } else {
    // CSV
    let text;
    try { text = buffer.toString('utf-8'); }
    catch { text = buffer.toString('latin1'); }

    // Skip leading blank/header lines
    const lines = text.trim().split(/\r?\n/);
    let start = 0;
    for (let i = 0; i < lines.length; i++) {
      if (lines[i].includes(',') && lines[i].split(',').length >= 3) { start = i; break; }
    }
    const cleaned = lines.slice(start).join('\n');
    records = parse(cleaned, { columns: true, skip_empty_lines: true, relax_column_count: true, trim: true });
  }

  if (!records || !records.length) return [];

  // Try specialised parsers
  for (const fn of PARSERS) {
    const result = fn(records, filename);
    if (result && result.length) return result;
  }

  // Fallback
  return parseGeneric(records, filename);
}

// ---------------------------------------------------------------------------
// API: Upload & parse
// ---------------------------------------------------------------------------
app.post('/api/upload', upload.array('files'), (req, res) => {
  if (!req.files || !req.files.length) return res.json({ transactions: [], error: 'No files' });

  const cfg = loadCategories();
  const overrides = loadOverrides();
  let all = [];

  for (const f of req.files) {
    const rows = parseFile(f.buffer, f.originalname);
    all = all.concat(rows);
  }

  // Categorise
  all.forEach(t => {
    t.category = categorise(t.description, cfg.rules, overrides, cfg.uncategorisedLabel);
  });

  // Sort newest first
  all.sort((a, b) => (b.date || '').localeCompare(a.date || ''));

  res.json({
    transactions: all,
    config: {
      itemisedThreshold: cfg.itemisedThreshold,
      icons: cfg.icons,
      uncategorisedLabel: cfg.uncategorisedLabel,
      uncategorisedIcon: cfg.uncategorisedIcon,
      allCategories: [...Object.keys(cfg.rules), cfg.uncategorisedLabel],
    }
  });
});

// ---------------------------------------------------------------------------
// API: Overrides
// ---------------------------------------------------------------------------
app.get('/api/overrides', (_req, res) => {
  res.json(loadOverrides());
});

app.post('/api/override', (req, res) => {
  const { merchant, category } = req.body;
  if (!merchant || !category) return res.status(400).json({ error: 'merchant and category required' });
  const data = loadOverrides();
  // Save with clean name (before | if present) for robust matching
  let cleanKey = merchant.toLowerCase().trim();
  if (cleanKey.includes('|')) cleanKey = cleanKey.split('|')[0].trim();
  data[cleanKey] = category;
  saveOverrides(data);
  res.json({ ok: true });
});

app.delete('/api/overrides', (_req, res) => {
  saveOverrides({});
  res.json({ ok: true });
});

// ---------------------------------------------------------------------------
// Start
// ---------------------------------------------------------------------------
if (process.env.VERCEL !== '1') {
  app.listen(PORT, () => {
    console.log(`\n  💷 Expense Tracker running at http://localhost:${PORT}\n`);
  });
}

module.exports = app;
