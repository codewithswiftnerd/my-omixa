const $ = (id) => document.getElementById(id);
const drop = $('drop'), fileInput = $('fileInput'), fileNameEl = $('fileName');
const runBtn = $('runBtn'), downloadBtn = $('downloadBtn'), resetBtn = $('resetBtn');
const stage = $('stage'), results = $('results'), stats = $('stats'), detailBlocks = $('detailBlocks');
const reportCard = $('reportCard'), scoreBadge = $('scoreBadge'), scoreNum = $('scoreNum');
const reportSub = $('reportSub'), findingsEl = $('findings'), noFindings = $('noFindings');
const stepEls = {
  upload: document.querySelector('.step[data-step="upload"]'),
  review: document.querySelector('.step[data-step="review"]'),
  clean: document.querySelector('.step[data-step="clean"]'),
  download: document.querySelector('.step[data-step="download"]'),
};

let selectedFile = null;
let lastJobId = null;
let preCleanScore = null;

function base(){
  return window.location.origin; // same origin the page was loaded from
}

function setStep(name, state){
  // state: 'active' | 'done' | 'err' | '' (reset)
  Object.values(stepEls).forEach(el => el && el.classList.remove('active','done','err'));
  const order = ['upload','review','clean','download'];
  const idx = order.indexOf(name);
  order.forEach((key, i) => {
    const el = stepEls[key];
    if(!el) return;
    if(i < idx) el.classList.add('done');
    if(i === idx && state) el.classList.add(state);
  });
}

drop.addEventListener('click', () => fileInput.click());
drop.addEventListener('keydown', e => { if(e.key === 'Enter' || e.key === ' '){ e.preventDefault(); fileInput.click(); } });
['dragover','dragenter'].forEach(evt => drop.addEventListener(evt, e => { e.preventDefault(); drop.classList.add('drag'); }));
['dragleave','drop'].forEach(evt => drop.addEventListener(evt, e => { e.preventDefault(); drop.classList.remove('drag'); }));
drop.addEventListener('drop', e => { if(e.dataTransfer.files[0]) setFile(e.dataTransfer.files[0]); });
fileInput.addEventListener('change', e => { if(e.target.files[0]) setFile(e.target.files[0]); });

async function setFile(f){
  selectedFile = f;
  lastJobId = null;
  preCleanScore = null;
  fileNameEl.textContent = f.name + '  ·  ' + (f.size/1024).toFixed(1) + ' KB';
  fileNameEl.style.display = 'block';
  runBtn.disabled = true;
  reportCard.classList.add('hidden');
  results.classList.add('hidden');
  downloadBtn.classList.add('hidden'); resetBtn.classList.add('hidden');

  try{
    setStep('upload', 'active');
    setStage('Uploading ' + f.name + ' …');
    const form = new FormData();
    form.append('file', f);
    const upRes = await fetch(base() + '/api/upload/', { method:'POST', body: form });
    const upJson = await upRes.json();
    if(!upRes.ok) throw new Error(upJson.error || 'upload failed');
    lastJobId = upJson.job_id;

    setStep('review', 'active');
    setStage('Analyzing file …', 'active');
    const repRes = await fetch(base() + '/api/report/' + lastJobId);
    const repJson = await repRes.json();
    if(!repRes.ok) throw new Error(repJson.error || 'analysis failed');

    renderReport(repJson.report);
    setStage('Review the report below, then choose rules to run.', '');
    runBtn.disabled = false;
  }catch(err){
    setStage('Error: ' + err.message, 'error');
    setStep(lastJobId ? 'review' : 'upload', 'err');
  }
}

const SEVERITY_ORDER = { critical: 0, warning: 1, info: 2 };

function renderReport(report){
  preCleanScore = report.score;
  reportCard.classList.remove('hidden');
  scoreNum.textContent = report.score;
  scoreBadge.className = 'score-badge ' + (report.score >= 85 ? 'good' : report.score >= 60 ? 'warn' : 'bad');
  const c = report.counts || {};
  reportSub.textContent = `${report.row_count} rows · ${report.column_count} columns, `
    + `${c.critical || 0} critical, ${c.warning || 0} warning, ${c.info || 0} info`;

  const findings = (report.findings || []).slice().sort((a,b) => SEVERITY_ORDER[a.severity] - SEVERITY_ORDER[b.severity]);
  findingsEl.innerHTML = '';
  noFindings.style.display = findings.length ? 'none' : 'block';

  findings.forEach(f => {
    const row = document.createElement('div');
    row.className = 'finding finding-' + f.severity;
    row.innerHTML = `
      <span class="badge ${f.severity}">${f.severity}</span>
      <div class="finding-body">
        <strong>${f.column ? f.column : 'Whole file'}</strong>
        <p>${f.detail}</p>
        <p class="suggestion">${f.suggestion}</p>
      </div>`;
    findingsEl.appendChild(row);
  });
}

function setStage(text, cls){
  stage.textContent = text;
  stage.className = 'stage' + (cls ? ' ' + cls : '');
}

function selectedRules(){
  return Array.from(document.querySelectorAll('.rule input:checked')).map(c => c.value);
}

runBtn.addEventListener('click', async () => {
  if(!selectedFile || !lastJobId) return;
  runBtn.disabled = true;
  results.classList.add('hidden');
  downloadBtn.classList.add('hidden');
  try{
    setStep('clean', 'active');
    setStage('Running: ' + selectedRules().join(', ') + ' …', 'active');
    const procRes = await fetch(base() + '/api/process/' + lastJobId, {
      method:'POST',
      headers:{'Content-Type':'application/json'},
      body: JSON.stringify({ rules: selectedRules() })
    });
    const procJson = await procRes.json();
    if(!procRes.ok) throw new Error(procJson.error || 'processing failed');

    setStep('download', '');
    setStage('Done. Ready to download.', '');
    renderResults(procJson.summary);
    downloadBtn.classList.remove('hidden');
    resetBtn.classList.remove('hidden');
  }catch(err){
    setStage('Error: ' + err.message, 'error');
    setStep(lastJobId ? 'clean' : 'upload', 'err');
  }finally{
    runBtn.disabled = false;
  }
});

function renderResults(summary){
  results.classList.remove('hidden');
  const c = summary.changes || {};

  const post = summary.quality_report;
  let scoreHtml = '';
  if(post){
    const cls = post.score >= 85 ? 'good' : post.score >= 60 ? 'warn' : 'bad';
    const before = preCleanScore != null ? preCleanScore : post.score;
    const delta = post.score - before;
    const deltaText = delta > 0 ? `+${delta}` : delta === 0 ? 'no change' : `${delta}`;
    scoreHtml = `
      <div class="score-compare">
        <div class="score-compare-item">
          <div class="score-badge small ${before >= 85 ? 'good' : before >= 60 ? 'warn' : 'bad'}">${before}</div>
          <div class="l">before</div>
        </div>
        <span class="score-arrow">→</span>
        <div class="score-compare-item">
          <div class="score-badge small ${cls}">${post.score}</div>
          <div class="l">after (${deltaText})</div>
        </div>
      </div>`;
  }

  stats.innerHTML = scoreHtml + `
    <div class="stat"><div class="n">${summary.rows_in}</div><div class="l">rows in</div></div>
    <div class="stat"><div class="n">${summary.rows_out}</div><div class="l">rows out</div></div>
    <div class="stat"><div class="n">${c.formatting_changed ?? '-'}</div><div class="l">cells reformatted</div></div>
    <div class="stat"><div class="n">${c.missing_values_changed ?? '-'}</div><div class="l">values filled</div></div>
    <div class="stat"><div class="n">${c.duplicates_changed ?? '-'}</div><div class="l">duplicates removed</div></div>
  `;

  // Any other "<rule>_changed" counters (the newer standardization
  // rules) get their own small stat cards too, so nothing added to
  // the pipeline later silently fails to show up here.
  const KNOWN_STAT_KEYS = new Set(['formatting_changed','missing_values_changed','duplicates_changed']);
  const STAT_LABELS = {
    column_names_changed: 'headers cleaned',
    missing_token_normalization_changed: 'blanks recognized',
    numeric_text_cleaning_changed: 'numbers cleaned',
    boolean_standardization_changed: 'booleans standardized',
    categorical_standardization_changed: 'categories merged',
    email_cleaning_changed: 'emails normalized',
    phone_cleaning_changed: 'phone values cleaned',
    date_standardization_changed: 'dates standardized',
  };
  Object.entries(c).forEach(([key, val]) => {
    if(KNOWN_STAT_KEYS.has(key) || !val) return;
    const label = STAT_LABELS[key] || key.replace(/_changed$/, '').replace(/_/g, ' ');
    stats.innerHTML += `<div class="stat"><div class="n">${val}</div><div class="l">${label}</div></div>`;
  });

  detailBlocks.innerHTML = '';
  const d = summary.details || {};

  if(d.missing_values){
    const rows = Object.entries(d.missing_values.per_column || {});
    if(rows.length){
      const block = document.createElement('div');
      block.innerHTML = `<h3>Missing values by column</h3>` + tableFrom(
        ['column','action','missing %','filled'],
        rows.map(([col, v]) => [
          col,
          `<span class="badge ${v.action === 'median_imputation' ? 'median' : v.action === 'unknown_category' ? 'unknown' : 'review'}">${v.action.replace(/_/g,' ')}</span>`,
          v.missing_percentage + '%',
          v.filled ?? '-'
        ])
      );
      detailBlocks.appendChild(block);
    }
  }

  if(d.formatting && Object.keys(d.formatting.per_column_cells_changed || {}).length){
    const rows = Object.entries(d.formatting.per_column_cells_changed);
    const block = document.createElement('div');
    block.innerHTML = `<h3>Formatting by column</h3>` + tableFrom(
      ['column','cells changed'], rows.map(([col, n]) => [col, n])
    );
    detailBlocks.appendChild(block);
  }

  if(d.duplicates){
    const block = document.createElement('div');
    block.innerHTML = `<h3>Duplicates</h3><p class="hint">Found ${d.duplicates.duplicate_rows_found}, removed ${d.duplicates.removed}, kept "${d.duplicates.kept}" occurrence.</p>`;
    detailBlocks.appendChild(block);
  }

  if(d.column_names && Object.keys(d.column_names.renamed || {}).length){
    const rows = Object.entries(d.column_names.renamed);
    const block = document.createElement('div');
    block.innerHTML = `<h3>Column names cleaned up</h3>` + tableFrom(
      ['original', 'cleaned'], rows.map(([oldName, newName]) => [oldName, newName])
    );
    detailBlocks.appendChild(block);
  }

  // Generic renderer for every other per-column standardization rule
  // (numeric text, booleans, categories, emails, phone, dates, missing
  // tokens) so a new rule shows up here automatically without needing
  // a bespoke block; they all share the same { per_column: {...} } shape.
  const GENERIC_DETAIL_TITLES = {
    missing_token_normalization: 'Blank / N-A style values recognized',
    numeric_text_cleaning: 'Numeric text cleaned',
    boolean_standardization: 'Booleans standardized',
    categorical_standardization: 'Categories standardized',
    email_cleaning: 'Emails cleaned',
    phone_cleaning: 'Phone formatting cleaned',
    date_standardization: 'Dates standardized',
  };
  Object.entries(GENERIC_DETAIL_TITLES).forEach(([ruleName, title]) => {
    const detail = d[ruleName];
    const perColumn = detail && detail.per_column;
    const rows = perColumn ? Object.entries(perColumn) : [];
    if(!rows.length && !(detail && detail.skipped_ambiguous && detail.skipped_ambiguous.length)) return;

    const block = document.createElement('div');
    let html = rows.length ? `<h3>${title}</h3>` + tableFrom(
      ['column', 'cells changed'],
      rows.map(([col, v]) => [col, typeof v === 'object' ? (v.changed ?? '-') : v])
    ) : `<h3>${title}</h3>`;
    if(detail && detail.skipped_ambiguous && detail.skipped_ambiguous.length){
      html += `<p class="hint">Skipped (format too ambiguous to guess safely): ${detail.skipped_ambiguous.join(', ')}</p>`;
    }
    block.innerHTML = html;
    detailBlocks.appendChild(block);
  });

  if(post && post.findings && post.findings.length){
    const block = document.createElement('div');
    block.innerHTML = `<h3>Still worth a look</h3>`;
    const list = document.createElement('div');
    list.className = 'findings';
    post.findings
      .slice()
      .sort((a,b) => SEVERITY_ORDER[a.severity] - SEVERITY_ORDER[b.severity])
      .forEach(f => {
        const row = document.createElement('div');
        row.className = 'finding finding-' + f.severity;
        row.innerHTML = `
          <span class="badge ${f.severity}">${f.severity}</span>
          <div class="finding-body">
            <strong>${f.column ? f.column : 'Whole file'}</strong>
            <p>${f.detail}</p>
            <p class="suggestion">${f.suggestion}</p>
          </div>`;
        list.appendChild(row);
      });
    block.appendChild(list);
    detailBlocks.appendChild(block);
  }
}

function tableFrom(headers, rows){
  const th = headers.map(h => `<th>${h}</th>`).join('');
  const tr = rows.map(r => `<tr>${r.map(cell => `<td>${cell}</td>`).join('')}</tr>`).join('');
  return `<table><thead><tr>${th}</tr></thead><tbody>${tr}</tbody></table>`;
}

downloadBtn.addEventListener('click', async () => {
  if(!lastJobId) return;
  const r = await fetch(base() + '/api/download/' + lastJobId);
  if(!r.ok){
    let msg = 'download failed (HTTP ' + r.status + ')';
    try{
      const j = await r.json();
      msg = 'download failed: ' + (j.detail || j.error || msg);
    }catch(e){ /* response wasn't JSON, keep the generic message */ }
    setStage(msg, 'error');
    return;
  }
  const blob = await r.blob();
  const cd = r.headers.get('Content-Disposition') || '';
  const match = cd.match(/filename="?([^"]+)"?/);
  const filename = match ? match[1] : 'cleaned_output';
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url; a.download = filename;
  document.body.appendChild(a); a.click(); a.remove();
  URL.revokeObjectURL(url);
  downloadBtn.classList.add('hidden'); // job is deleted server-side after download
});

resetBtn.addEventListener('click', () => {
  selectedFile = null; lastJobId = null; preCleanScore = null;
  fileNameEl.style.display = 'none'; fileInput.value = '';
  runBtn.disabled = true;
  results.classList.add('hidden');
  reportCard.classList.add('hidden');
  downloadBtn.classList.add('hidden'); resetBtn.classList.add('hidden');
  setStage('');
  setStep('upload', '');
});
