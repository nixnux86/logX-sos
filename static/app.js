let currentCase = localStorage.getItem("sosinsight_flask_current_case") || "";
let charts = {};
let activeMsgFilter = { category: "total", keyword: "" };
let msgPage = 1;
let msgPerPage = 45;
let msgTimer = null;
let droppedFile = null;
let modalChart = null;
let modalChartSource = null;
let consoleCwd = "";
let consoleHistory = [];
let consoleHistoryIndex = -1;

function api(url, params) { return $.getJSON(url, params); }
function setTitle(t) { $("#pageTitle").text(t); $("#caseLabel").text(currentCase ? `Current case: ${currentCase}` : "No sosreport loaded"); }
function setActive(v) { $(".nav").removeClass("active"); $(`.nav[data-view="${v}"]`).addClass("active"); }
function esc(s) { if (s === null || s === undefined) return ""; return String(s).replaceAll("&", "&amp;").replaceAll("<", "&lt;").replaceAll(">", "&gt;").replaceAll('"', "&quot;").replaceAll("'", "&#039;"); }
function num(v, d=0) { const n = Number(v); return Number.isFinite(n) ? n.toFixed(d) : "-"; }
function requireCase() {
  if (!currentCase) {
    setActive("dashboard");
    setTitle("Dashboard");
    setContent(`<div class="no-case-placeholder"><div class="card"><h3>No sosreport loaded</h3><p>Please upload a sosreport archive to start analysis.</p><button onclick="openUploadModal()"><i class="bi bi-cloud-arrow-up"></i> Upload sosreport</button></div></div>`);
    setTimeout(openUploadModal, 120);
    return false;
  }
  return true;
}
function destroyCharts() { Object.values(charts).forEach(c => { try { c.destroy(); } catch(e){} }); charts = {}; if (modalChart) { try { modalChart.destroy(); } catch(e){} modalChart=null; modalChartSource=null; } }
function resetAllZoom() { Object.values(charts).forEach(c => { if (c.resetZoom) c.resetZoom(); }); }
function gbFromKBpsSum(kbps){ const n=Number(kbps||0); if(!Number.isFinite(n)) return "0.00"; return (n/1024/1024).toFixed(2); }

function pageFooter() { return `<div class="app-footer">logX sosreport tool v1.0 | © 2026 – ideas by nixnux</div>`; }
function setContent(html) { $("#content").html(html + pageFooter()); }
function ansiToHtml(text) {
  let out = esc(text);
  const map = {
    '0;31':'ansi-red','1;31':'ansi-bold ansi-red','0;32':'ansi-green','1;32':'ansi-bold ansi-green',
    '0;33':'ansi-yellow','1;33':'ansi-bold ansi-yellow','0;34':'ansi-blue','1;34':'ansi-bold ansi-blue',
    '0;35':'ansi-magenta','1;35':'ansi-bold ansi-magenta','0;36':'ansi-cyan','1;36':'ansi-bold ansi-cyan',
    '1':'ansi-bold'
  };
  out = out.replace(/\[0;0m|\[0m/g, '</span>');
  out = out.replace(/\[([0-9;]+)m/g, function(_, code){ return `<span class="${map[code] || 'ansi-bold'}">`; });
  return out;
}



function renderSarPanel() {
  return `<div class="dashboard-section-title"><h3>SAR Graphs</h3><button id="resetZoom" class="mini-action"><i class="bi bi-arrow-clockwise"></i> Reset Zoom</button></div>
    <div class="dash-chart-grid">
      <div class="card chart-card dash-chart-card"><h3>CPU Usage</h3><canvas id="sarCpuChart"></canvas><div id="sarCpuEmpty"></div></div>
      <div class="card chart-card dash-chart-card"><h3>Memory Usage</h3><canvas id="sarMemChart"></canvas><div id="sarMemEmpty"></div></div>
      <div class="card chart-card dash-chart-card"><h3>Disk Throughput</h3><canvas id="sarDiskChart"></canvas><div id="sarDiskEmpty"></div></div>
      <div class="card chart-card dash-chart-card"><h3>Network Throughput</h3><canvas id="sarNetChart"></canvas><div id="sarNetEmpty"></div></div>
    </div>`;
}


function resetUploadState() {
  droppedFile = null;
  const input = document.getElementById('sosFile');
  if (input) input.value = '';
  const dz = $('#dropZone');
  dz.removeClass('has-file uploading done drag-over');
  dz.find('.drop-icon').html('<i class="bi bi-cloud-arrow-up"></i>');
  dz.find('strong').text('Choose or drag-drop sosreport file');
  $('#selectedFile').text('No file selected');
  setUploadProgress(0, '0%');
  $('#uploadStatus').text('');
}
function noDataChartSvg() {
  return `<svg viewBox="0 0 140 96" fill="none" xmlns="http://www.w3.org/2000/svg" aria-hidden="true">
    <rect x="8" y="12" width="124" height="72" rx="14" stroke="currentColor" stroke-width="5" stroke-dasharray="8 8" opacity=".28"/>
    <path d="M28 66c13-18 24-6 34-18 12-14 20-16 31 5 6 12 13 8 19 2" stroke="currentColor" stroke-width="7" stroke-linecap="round" stroke-linejoin="round" opacity=".42"/>
    <circle cx="101" cy="34" r="8" fill="currentColor" opacity=".28"/>
  </svg>`;
}
function setNoChart(chartId, emptyId, title, detail) {
  const canvas = $('#' + chartId);
  canvas.closest('.chart-card').addClass('no-chart');
  canvas.hide();
  $('#' + emptyId).html(`<div class="no-data-chart">${noDataChartSvg()}<b>No data available</b><small>${esc(detail || title || '')}</small></div>`);
}
function prepareChart(chartId, emptyId) {
  const canvas = $('#' + chartId);
  canvas.closest('.chart-card').removeClass('no-chart');
  canvas.show();
  $('#' + emptyId).empty();
}

function loadDashboardCharts() {
  $('#resetZoom').on('click', resetAllZoom);
  api("/api/sar_cpu", { case: currentCase }).done(resp => {
    const rows = resp.data || [];
    if (!rows.length) { setNoChart("sarCpuChart", "sarCpuEmpty", "No CPU SAR data", "No CPU SAR data found in parsed sar/sadf output."); return; }
    prepareChart("sarCpuChart", "sarCpuEmpty");
    const labels = rows.map(r => r.sample_time);
    charts.cpu = makeLineChart("sarCpuChart", labels, [
      {label:"%user",data:rows.map(r=>Number(r.user_pct))},
      {label:"%system",data:rows.map(r=>Number(r.system_pct))},
      {label:"%iowait",data:rows.map(r=>Number(r.iowait_pct))},
      {label:"%idle",data:rows.map(r=>Number(r.idle_pct))}
    ], 100, "CPU Usage");
  });
  api("/api/sar_mem", { case: currentCase }).done(resp => {
    const rows = resp.data || [];
    if (!rows.length) { setNoChart("sarMemChart", "sarMemEmpty", "No memory SAR data", "No memory or swap samples found."); return; }
    prepareChart("sarMemChart", "sarMemEmpty");
    const labels = rows.map(r => r.sample_time);
    charts.mem = makeLineChart("sarMemChart", labels, [
      {label:"%memused",data:rows.map(r=>Number(r.mem_used_pct))},
      {label:"%swapused",data:rows.map(r=>Number(r.swap_used_pct))}
    ], 100, "Memory Usage");
  });
  api("/api/sar_disk", { case: currentCase }).done(resp => {
    const rows = resp.data || [];
    if (!rows.length) { setNoChart("sarDiskChart", "sarDiskEmpty", "No disk SAR data", "No block-device throughput samples found."); return; }
    prepareChart("sarDiskChart", "sarDiskEmpty");
    const agg = aggregateByTime(rows, "sample_time", ["read_kbps","write_kbps","util_pct"]);
    charts.disk = makeLineChart("sarDiskChart", agg.labels, [
      {label:"Read kB/s",data:agg.labels.map(t=>agg.values[t].read_kbps)},
      {label:"Write kB/s",data:agg.labels.map(t=>agg.values[t].write_kbps)},
      {label:"Total %util",data:agg.labels.map(t=>agg.values[t].util_pct)}
    ], undefined, "Disk Throughput");
  });
  api("/api/sar_net", { case: currentCase }).done(resp => {
    const rows = resp.data || [];
    if (!rows.length) { setNoChart("sarNetChart", "sarNetEmpty", "No network SAR data", "No network throughput samples found."); return; }
    prepareChart("sarNetChart", "sarNetEmpty");
    const agg = aggregateByTime(rows, "sample_time", ["rx_kbps","tx_kbps"], r => String(r.interface).toLowerCase()==="lo");
    charts.net = makeLineChart("sarNetChart", agg.labels, [
      {label:"RX kB/s",data:agg.labels.map(t=>agg.values[t].rx_kbps)},
      {label:"TX kB/s",data:agg.labels.map(t=>agg.values[t].tx_kbps)}
    ], undefined, "Network Throughput");
  });
}

function procTable(title, rows, mode){
  let html = `<div class="card process-card"><div class="process-title"><h3>${esc(title)}</h3><span>Top 10</span></div>`;
  if(!rows || !rows.length){ html += `<div class="empty-note">No process data found from ps/xsos output.</div></div>`; return html; }
  html += `<div class="table-wrap"><table class="process-table"><thead><tr><th>Rank</th><th>User</th><th>PID</th><th>%CPU</th><th>%MEM</th><th>RSS</th><th>Command</th></tr></thead><tbody>`;
  rows.forEach((r,i)=>{ html += `<tr><td>${i+1}</td><td>${esc(r.user)}</td><td>${esc(r.pid)}</td><td><b class="${mode==='cpu'?'orange':'blue'}">${esc(r.cpu_pct)}</b></td><td><b class="${mode==='mem'?'green':'blue'}">${esc(r.mem_pct)}</b></td><td>${esc(r.rss)}</td><td class="cmd-cell">${esc(r.command)}</td></tr>`; });
  html += `</tbody></table></div></div>`;
  return html;
}

function loadProcessTables(){
  api('/api/top_processes', {case: currentCase}).done(resp => {
    const d = resp.data || {};
    $('#processTables').html(procTable('Top CPU-using processes', d.cpu || [], 'cpu') + procTable('Top MEM-using processes', d.mem || [], 'mem'));
  });
}

function loadDashboard() {
  destroyCharts(); setActive("dashboard"); setTitle("Dashboard"); if (!requireCase()) return;
  api("/api/dashboard", { case: currentCase }).done(resp => {
    const d = resp.data || {};
    const cpu = d.cpu || {};
    const memPressure = parseFloat(String((d.memory||{}).pressure || "").replace('%',''));
    const memUsed = Number.isFinite(memPressure) ? memPressure.toFixed(0) + "%" : "-";
    const disks = d.disks || [];
    const diskHtml = disks.length ? disks.map((x,i)=>`<div class="mini-stat"><b class="${i===0?'blue':i===1?'teal':'green'}">${esc(x.pct)}%</b><span>${esc(x.mount)}</span></div>`).join('') : `<div class="mini-stat"><b>-</b><span>No df data</span></div>`;
    const os = d.os_release || "Unknown";
    const arch = (d.kernel || "").includes("x86_64") ? "x86_64" : "";
    const kernelShort = (d.kernel || "").replace(/^Linux\s+\S+\s+/, '').slice(0,80);
    const html = `
      <div class="dashboard-section-title dashboard-section-title-system"><h3>System Info</h3></div>
      <div class="dash-meta"><b>hostname:</b> ${esc(d.hostname)} <span>·</span> <b>kernel version:</b> ${esc(kernelShort || d.kernel || '-')} <span>·</span> <b>sosreport parsed date:</b> ${esc(d.collection_date || '-')}</div>
      <div class="dashboard-surface dashboard-surface-compact">
        <div class="dash-card soft-pink">
          <h3>OS Version</h3>
          <div class="big-line red os-version-line">${esc(os)} <span>/ ${esc(arch)}</span></div>
          <div class="sub-label">OS / Arch</div>
        </div>
        <div class="dash-card soft-blue">
          <h3>CPU Usage</h3>
          <div class="stat-row four">
            <div><b class="blue">${num(cpu.user_pct,0)}%</b><span>User</span></div>
            <div><b class="orange">${num(cpu.system_pct,0)}%</b><span>System</span></div>
            <div><b class="green">${num(cpu.idle_pct,0)}%</b><span>Idle</span></div>
            <div><b class="pink">${num(cpu.iowait_pct,0)}%</b><span>IO Wait</span></div>
          </div>
        </div>
        <div class="dash-card soft-blue center">
          <h3>Memory Usage</h3>
          <div class="big-line red">${memUsed}<span> / ${esc((d.memory||{}).total || '-')}</span></div>
          <div class="sub-label">Mem Used / Mem Total</div>
        </div>
        <div class="dash-card soft-lavender">
          <h3>Disk Usage</h3>
          <div class="disk-grid">${diskHtml}</div>
        </div>
      </div>
      ${renderSarPanel()}
      <div class="dashboard-section-title"><h3>Process Snapshot</h3><span class="muted">from ps/xsos-style process data</span></div>
      <div id="processTables" class="process-grid"><div class="card"><div class="empty-note">Loading process tables...</div></div></div>`;
    setContent(html);
    loadDashboardCharts();
    loadProcessTables();
  });
}


function loadTroubleshooting() {
  destroyCharts(); setActive("troubleshooting"); setTitle("Troubleshooting"); if (!requireCase()) return;
  $.when(api("/api/findings", { case: currentCase }), api("/api/facts", { case: currentCase })).done(function(fr, far) {
    const findings = fr[0].data || [], facts = far[0].data || [];
    const critical = findings.filter(x => x.severity === "critical").length;
    const warning = findings.filter(x => x.severity === "warning").length;
    let html = `<div class="trouble-grid"><div class="kpi"><div class="num">${critical}</div><div class="label">Critical Findings</div></div><div class="kpi"><div class="num">${warning}</div><div class="label">Warning Findings</div></div><div class="kpi"><div class="num">${facts.length}</div><div class="label">Collected Facts</div></div></div><div class="card trouble-card"><h3>Troubleshooting Findings</h3>`;
    if (!findings.length) html += `<p>No critical troubleshooting finding detected by current parser rules.</p>`;
    findings.forEach(f => { html += `<div class="card finding ${esc(f.severity)}"><div class="finding-head"><span class="badge ${esc(f.severity)}">${esc(f.severity)}</span><span class="finding-module">${esc(f.module)}</span></div><h3>${esc(f.title)}</h3><div class="recommend-box"><b>Recommended troubleshooting</b><br>${esc(f.recommendation)}</div><details class="evidence-box" open><summary>Evidence / raw lines</summary><pre>${esc(f.detail)}</pre></details></div>`; });
    html += `</div>`;
    setContent(html);
  });
}

function loadFacts(section) {
  destroyCharts(); setActive(section); setTitle(section); if (!requireCase()) return;
  api("/api/facts", { case: currentCase, section }).done(resp => {
    const rows = resp.data || [];
    let html = `<div class="card"><h3>${esc(section)}</h3>`;
    if (!rows.length) html += `<p>No data found for this section.</p>`;
    rows.forEach(r => { html += `<div class="fact-row"><div class="fact-key">${esc(r.key)}</div><div class="fact-value">${esc(r.value)}</div></div>`; });
    html += `</div>`;
    setContent(html);
  });
}

function loadSystemInformation() {
  destroyCharts(); setActive("systeminfo"); setTitle("System Information"); if (!requireCase()) return;
  $.when(
    api("/api/facts", { case: currentCase, section: "System Identity" }),
    api("/api/facts", { case: currentCase, section: "Hardware" }),
    api("/api/facts", { case: currentCase, section: "Kernel & Logs" }),
    api("/api/facts", { case: currentCase, section: "Services" })
  ).done(function(sr, hr, kr, svc) {
    const sections = [
      {title:"System Identity", rows:sr[0].data || []},
      {title:"Hardware", rows:hr[0].data || []},
      {title:"Kernel & Logs", rows:kr[0].data || []},
      {title:"Services", rows:svc[0].data || []}
    ];
    let html = `<div class="system-info-grid system-info-grid-4">`;
    sections.forEach(sec => {
      html += `<div class="card"><h3>${esc(sec.title)}</h3>`;
      if (!sec.rows.length) html += `<p>No data found for this section.</p>`;
      sec.rows.forEach(r => { html += `<div class="fact-row compact"><div class="fact-key">${esc(r.key)}</div><div class="fact-value">${esc(r.value)}</div></div>`; });
      html += `</div>`;
    });
    html += `</div>`;
    setContent(html);
  });
}

function loadSummary() {
  destroyCharts(); setActive("Summary"); setTitle("SOSREPORT Summary"); if (!requireCase()) return;
  api("/api/facts", { case: currentCase, section: "Summary" }).done(resp => {
    const rows = resp.data || [];
    let xsosOutput = "";
    rows.forEach(r => {
      const key = String(r.key).toLowerCase();
      if (key.includes("xsos output") || key.includes("xsos warnings")) {
        xsosOutput += (xsosOutput ? "\n" : "") + String(r.value || "");
      }
    });
    let html = `<div class="card summary-simple"><h3>SOSREPORT Summary</h3>`;
    if (xsosOutput) {
      html += `<pre class="xsos-output">${ansiToHtml(xsosOutput)}</pre>`;
    } else {
      html += `<pre class="xsos-output">No xsos output found. Install xsos and parse the sosreport again.</pre>`;
    }
    html += `</div>`;
    setContent(html);
  });
}

function badgeClassByCategory(cat){ return cat === 'errors' ? 'error' : cat === 'warnings' ? 'warning' : cat === 'failed' ? 'failed' : cat === 'info' ? 'info' : 'total'; }

function logSeverityClass(row){
  const text = [row && row.severity, row && row.log_time, row && row.hostname, row && row.process, row && row.message].filter(Boolean).join(' ').toLowerCase();
  if(/panic|oops|bug:|segfault|oom-killer|out of memory|killed process|critical/.test(text)) return 'critical';
  if(/failed|failure/.test(text)) return 'failed';
  if(/error|err:/.test(text)) return 'error';
  if(/warn|warning/.test(text)) return 'warning';
  if(/info|notice|started|starting|finished|success|successfully/.test(text)) return 'info';
  return row && row.severity ? row.severity : 'info';
}

function highlightLog(text){
  // Preserve raw log lines exactly. Do not inject keyword markup into Messages/Dmesg output.
  return esc(text);
}
function searchBoxHtml(id, placeholder){
  return `<div class="search-wrap"><input id="${id}" class="full-log-search" placeholder="${placeholder}"><button class="search-clear" data-target="${id}" title="Clear search"><i class="bi bi-x-lg"></i></button></div>`;
}
function bindSearchClear(inputSelector, onClear){
  const input = $(inputSelector);
  const btn = input.closest('.search-wrap').find('.search-clear');
  const sync = () => btn.toggleClass('show', !!input.val());
  input.on('input', sync);
  input.on('keydown', function(e){ if(e.key === 'Escape'){ e.preventDefault(); input.val(''); sync(); if(onClear) onClear(); }});
  btn.on('click', function(){ input.val(''); sync(); if(onClear) onClear(); input.trigger('focus'); });
  sync();
}
function loadMessages() {
  destroyCharts(); setActive("messages"); setTitle("Messages"); if (!requireCase()) return;
  msgPage = 1; activeMsgFilter = { category: "total", keyword: "" };
  setContent(`
    <div class="messages-page">
      ${searchBoxHtml("msgSearchFull", "Search log...")}
      <div id="msgCounterBar" class="msg-counter-bar">
        <button class="msg-counter active" data-cat="total">Total Lines <span>0</span></button>
        <button class="msg-counter error" data-cat="errors">ERROR <span>0</span></button>
        <button class="msg-counter warning" data-cat="warnings">WARNING <span>0</span></button>
        <button class="msg-counter failed" data-cat="failed">FAILED <span>0</span></button>
        <button class="msg-counter info" data-cat="info">INFO <span>0</span></button>
      </div>
      <div class="log-box" id="messagesLogBox"></div>
      <div class="pagination-bar">
        <button id="msgFirst"><i class="bi bi-skip-backward-fill"></i> First</button>
        <button id="msgPrev"><i class="bi bi-chevron-left"></i> Prev</button>
        <span id="msgPageLabel">Page 1 / 1</span>
        <button id="msgNext">Next <i class="bi bi-chevron-right"></i></button>
        <button id="msgLast">Last <i class="bi bi-skip-forward-fill"></i></button>
      </div>
    </div>`);
  $('#msgCounterBar').on('click', '.msg-counter', function(){ $('.msg-counter').removeClass('active'); $(this).addClass('active'); activeMsgFilter.category = $(this).data('cat'); msgPage = 1; fetchMessages(); });
  $('#msgSearchFull').on('input', function(){ clearTimeout(msgTimer); msgTimer=setTimeout(()=>{ msgPage=1; activeMsgFilter.keyword = $('#msgSearchFull').val() || ''; fetchMessages(); }, 220); });
  bindSearchClear('#msgSearchFull', ()=>{ msgPage=1; activeMsgFilter.keyword=''; fetchMessages(); });
  $('#msgFirst').on('click', ()=>{ msgPage=1; fetchMessages(); });
  $('#msgPrev').on('click', ()=>{ msgPage=Math.max(1,msgPage-1); fetchMessages(); });
  $('#msgNext').on('click', ()=>{ msgPage=Number($('#msgNext').data('next')||msgPage); fetchMessages(); });
  $('#msgLast').on('click', ()=>{ msgPage=Number($('#msgLast').data('last')||msgPage); fetchMessages(); });
  fetchMessages();
}
function fetchMessages() {
  api("/api/messages", { case: currentCase, category: activeMsgFilter.category, keyword: activeMsgFilter.keyword, page: msgPage, per_page: msgPerPage }).done(resp => {
    const rows = resp.data || [];
    const counters = resp.counters || {};
    ['total','errors','warnings','failed','info'].forEach(cat => { $(`.msg-counter[data-cat="${cat}"] span`).text(counters[cat] || 0); });
    let html = rows.length ? rows.map(r => `<div class="log-line sev-${esc(logSeverityClass(r))}"><span class="log-time">${esc(r.log_time)}</span> ${highlightLog([r.hostname,r.process ? r.process + ':' : '',r.message].filter(Boolean).join(' '))}</div>`).join('') : '<div class="empty-note">No messages found.</div>';
    $('#messagesLogBox').html(html);
    const totalPages = resp.total_pages || 1;
    msgPage = resp.page || 1;
    $('#msgPageLabel').text(`Page ${msgPage} / ${totalPages}`);
    $('#msgFirst,#msgPrev').prop('disabled', msgPage <= 1);
    $('#msgNext,#msgLast').prop('disabled', msgPage >= totalPages);
    $('#msgNext').data('next', Math.min(totalPages, msgPage+1));
    $('#msgLast').data('last', totalPages);
  });
}

function loadDmesg(){
  destroyCharts(); setActive('dmesg'); setTitle('Dmesg'); if(!requireCase()) return;
  setContent(`<div class="dmesg-page">${searchBoxHtml("dmesgSearch", "Search dmesg...")}<div id="dmesgBox" class="log-box dmesg-box"></div></div>`);
  $('#dmesgSearch').on('input', function(){ clearTimeout(msgTimer); msgTimer=setTimeout(fetchDmesg, 220); });
  bindSearchClear('#dmesgSearch', fetchDmesg);
  fetchDmesg();
}
function fetchDmesg(){
  api('/api/dmesg', {case: currentCase, keyword: $('#dmesgSearch').val() || ''}).done(resp => {
    const rows = resp.data || [];
    const html = rows.length ? rows.map(r => `<div class="log-line sev-${esc(logSeverityClass(r))}">${highlightLog(r.message)}</div>`).join('') : '<div class="empty-note">No dmesg lines found.</div>';
    $('#dmesgBox').html(html);
  });
}

function loadKernelServices(){
  destroyCharts(); setActive('kernelservices'); setTitle('Kernel & Services'); if(!requireCase()) return;
  $.when(api('/api/facts', {case: currentCase, section:'Kernel & Logs'}), api('/api/facts', {case: currentCase, section:'Services'})).done(function(kr, sr){
    const sections = [{title:'Kernel & Logs', rows: kr[0].data || []}, {title:'Services', rows: sr[0].data || []}];
    let html = `<div class="system-info-grid kernel-service-grid">`;
    sections.forEach(sec => {
      html += `<div class="card"><h3>${esc(sec.title)}</h3>`;
      if(!sec.rows.length) html += `<p>No data found for this section.</p>`;
      sec.rows.forEach(r => { html += `<div class="fact-row compact"><div class="fact-key">${esc(r.key)}</div><div class="fact-value">${esc(r.value)}</div></div>`; });
      html += `</div>`;
    });
    html += `</div>`;
    setContent(html);
  });
}

function makeLineChart(id, labels, datasets, yMax, title) {
  const canvas = document.getElementById(id);
  const chart = new Chart(canvas, {
    type:"line",
    data:{ labels, datasets },
    options:{
      responsive:true,
      maintainAspectRatio:false,
      interaction:{ mode:"index", intersect:false },
      plugins:{
        legend:{ display:true },
        zoom:{ pan:{ enabled:true, mode:"x" }, zoom:{ wheel:{ enabled:true }, pinch:{ enabled:true }, mode:"x" } }
      },
      scales:{ y:{ beginAtZero:true, suggestedMax:yMax || undefined } }
    }
  });
  $(canvas).closest('.chart-card').addClass('clickable-chart').attr('title', 'Click to enlarge chart').off('click').on('click', function(e){
    if ($(e.target).is('button')) return;
    openChartModal(title || $(this).find('h3').first().text() || 'SAR Chart', chart);
  });
  return chart;
}
function openChartModal(title, sourceChart) {
  modalChartSource = sourceChart;
  $('#chartModalTitle').text(title);
  $('#chartModal').addClass('show').attr('aria-hidden','false');
  if (modalChart) { try { modalChart.destroy(); } catch(e){} }
  const ctx = document.getElementById('chartModalCanvas');
  modalChart = new Chart(ctx, {
    type: sourceChart.config.type,
    data: JSON.parse(JSON.stringify(sourceChart.data)),
    options: {
      responsive:true,
      maintainAspectRatio:false,
      interaction:{ mode:'index', intersect:false },
      plugins:{
        legend:{ display:true },
        zoom:{ pan:{ enabled:true, mode:'x' }, zoom:{ wheel:{ enabled:true }, pinch:{ enabled:true }, mode:'x' } }
      },
      scales: JSON.parse(JSON.stringify(sourceChart.options.scales || {}))
    }
  });
}
function closeChartModal(){ $('#chartModal').removeClass('show').attr('aria-hidden','true'); if(modalChart){ try{ modalChart.destroy(); }catch(e){} modalChart=null; } }
function downloadModalChart(type){
  if(!modalChart) return;
  const link = document.createElement('a');
  const safeTitle = ($('#chartModalTitle').text() || 'sar-chart').toLowerCase().replace(/[^a-z0-9]+/g,'-').replace(/^-|-$/g,'');
  if(type === 'jpg') {
    const src = modalChart.canvas;
    const tmp = document.createElement('canvas'); tmp.width = src.width; tmp.height = src.height;
    const ctx = tmp.getContext('2d'); ctx.fillStyle = '#ffffff'; ctx.fillRect(0,0,tmp.width,tmp.height); ctx.drawImage(src,0,0);
    link.href = tmp.toDataURL('image/jpeg', 0.92); link.download = safeTitle + '.jpg';
  } else {
    link.href = modalChart.toBase64Image('image/png', 1); link.download = safeTitle + '.png';
  }
  link.click();
}
function aggregateByTime(rows, timeKey, fields, skip) {
  const bucket = {};
  rows.forEach(r => { if (skip && skip(r)) return; const t = r[timeKey]; if (!bucket[t]) bucket[t] = Object.fromEntries(fields.map(f => [f, 0])); fields.forEach(f => bucket[t][f] += Number(r[f] || 0)); });
  const labels = Object.keys(bucket); return { labels, values: bucket };
}
function loadSar() {
  destroyCharts(); setActive("sar"); setTitle("SAR Graphs"); if (!requireCase()) return;
  setContent(`<div class="card"><h3>SAR Graphs</h3><p class="muted">Mouse wheel or pinch to zoom. Drag to pan. Use reset to restore all charts.</p><button id="resetZoom">Reset All Zoom</button></div><div class="chart-grid"><div class="card chart-card"><h3>CPU Usage</h3><canvas id="sarCpuChart"></canvas><div id="sarCpuEmpty"></div></div><div class="card chart-card"><h3>Memory / Swap Usage</h3><canvas id="sarMemChart"></canvas><div id="sarMemEmpty"></div></div><div class="card chart-card"><h3>Disk Throughput</h3><canvas id="sarDiskChart"></canvas><div id="sarDiskEmpty"></div></div><div class="card chart-card"><h3>Network Throughput</h3><canvas id="sarNetChart"></canvas><div id="sarNetEmpty"></div></div></div>`);
  $("#resetZoom").on("click", resetAllZoom);
  api("/api/sar_cpu", { case: currentCase }).done(resp => { const rows = resp.data || []; if (!rows.length) { setNoChart("sarCpuChart", "sarCpuEmpty", "No CPU SAR data", "No CPU SAR data found in parsed sar/sadf output."); return; } prepareChart("sarCpuChart", "sarCpuEmpty"); const labels = rows.map(r => r.sample_time); charts.cpu = makeLineChart("sarCpuChart", labels, [{label:"%user",data:rows.map(r=>Number(r.user_pct))},{label:"%system",data:rows.map(r=>Number(r.system_pct))},{label:"%iowait",data:rows.map(r=>Number(r.iowait_pct))},{label:"%idle",data:rows.map(r=>Number(r.idle_pct))}], 100, "CPU Usage"); });
  api("/api/sar_mem", { case: currentCase }).done(resp => { const rows = resp.data || []; if (!rows.length) { setNoChart("sarMemChart", "sarMemEmpty", "No memory SAR data", "No memory or swap samples found."); return; } prepareChart("sarMemChart", "sarMemEmpty"); const labels = rows.map(r => r.sample_time); charts.mem = makeLineChart("sarMemChart", labels, [{label:"%memused",data:rows.map(r=>Number(r.mem_used_pct))},{label:"%swapused",data:rows.map(r=>Number(r.swap_used_pct))}], 100, "Memory Usage"); });
  api("/api/sar_disk", { case: currentCase }).done(resp => { const rows = resp.data || []; if (!rows.length) { setNoChart("sarDiskChart", "sarDiskEmpty", "No disk SAR data", "No block-device throughput samples found."); return; } prepareChart("sarDiskChart", "sarDiskEmpty"); const agg = aggregateByTime(rows, "sample_time", ["read_kbps","write_kbps","util_pct"]); charts.disk = makeLineChart("sarDiskChart", agg.labels, [{label:"Read kB/s",data:agg.labels.map(t=>agg.values[t].read_kbps)},{label:"Write kB/s",data:agg.labels.map(t=>agg.values[t].write_kbps)},{label:"Total %util",data:agg.labels.map(t=>agg.values[t].util_pct)}], undefined, "Disk Throughput"); });
  api("/api/sar_net", { case: currentCase }).done(resp => { const rows = resp.data || []; if (!rows.length) { setNoChart("sarNetChart", "sarNetEmpty", "No network SAR data", "No network throughput samples found."); return; } prepareChart("sarNetChart", "sarNetEmpty"); const agg = aggregateByTime(rows, "sample_time", ["rx_kbps","tx_kbps"], r => String(r.interface).toLowerCase()==="lo"); charts.net = makeLineChart("sarNetChart", agg.labels, [{label:"RX kB/s",data:agg.labels.map(t=>agg.values[t].rx_kbps)},{label:"TX kB/s",data:agg.labels.map(t=>agg.values[t].tx_kbps)}], undefined, "Network Throughput"); });
}


function shortPath(path){
  if(!path) return '';
  const parts = String(path).split('/').filter(Boolean);
  return parts.length > 3 ? '…/' + parts.slice(-3).join('/') : '/' + parts.join('/');
}
function formatWorkingDir(path){
  if(!path) return 'unavailable';
  const s = String(path);
  const marker = '/extracted/';
  const idx = s.indexOf(marker);
  if(idx >= 0) return '…' + s.slice(idx);
  return shortPath(s);
}
function promptWorkingDir(path){
  if(!path) return '…';
  const parts = String(path).split('/').filter(Boolean);
  return parts.length ? '…/' + parts[parts.length-1] : '/';
}
function renderPromptLine(command){
  return `<div class="terminal-prompt-line"><span class="terminal-user">logX</span><span class="terminal-cwd">${esc(promptWorkingDir(consoleCwd))}</span><span class="terminal-path">$</span><input id="consoleCommand" class="terminal-input" value="${esc(command || '')}" autocomplete="off" spellcheck="false"></div>`;
}
function autocompleteConsoleCommand(input){
  const current = input.val();
  $.ajax({
    url:'/api/console_complete',
    method:'POST',
    contentType:'application/json',
    data:JSON.stringify({case:currentCase, line:current, cwd:consoleCwd})
  }).done(resp => {
    const suggestions = resp.suggestions || [];
    if(!suggestions.length) return;
    if(suggestions.length === 1){
      input.val(suggestions[0]);
      const el = input.get(0);
      if(el) el.setSelectionRange(input.val().length, input.val().length);
      return;
    }
    $('#consoleOutput').append(`<pre class="terminal-result completion-list">${esc(suggestions.join('    '))}</pre>`);
    const out = document.getElementById('consoleOutput');
    out.scrollTop = out.scrollHeight;
  });
}

function loadConsole(){
  destroyCharts(); setActive('console'); setTitle('Console'); if(!requireCase()) return;
  consoleCwd = '';
  setContent(`<div class="console-page terminal-shell">
    <div id="consolePath" class="console-path"><span>Working directory: loading...</span><small>Enter = run · Tab = autocomplete · ↑/↓ history · Ctrl+L/clear = clear · cd is persistent inside sosreport root</small></div>
    <div id="consoleOutput" class="console-output" tabindex="0"><div class="terminal-line muted">logX console ready. Commands run from the extracted sosreport root.</div>${renderPromptLine('pwd && ls -la')}</div>
  </div>`);
  $('#consoleCommand').trigger('focus').select();
  $('#consoleOutput').on('click', function(){ $('#consoleCommand').last().trigger('focus'); });
  $('#consoleOutput').on('keydown', '#consoleCommand', function(e){
    if(e.key === 'Tab'){
      e.preventDefault();
      autocompleteConsoleCommand($(this));
    } else if(e.key === 'Enter'){
      e.preventDefault();
      const cmd = $(this).val();
      runConsoleCommand(cmd);
    } else if(e.key === 'ArrowUp'){
      e.preventDefault();
      if(consoleHistory.length){ consoleHistoryIndex = Math.max(0, consoleHistoryIndex < 0 ? consoleHistory.length - 1 : consoleHistoryIndex - 1); $(this).val(consoleHistory[consoleHistoryIndex]); }
    } else if(e.key === 'ArrowDown'){
      e.preventDefault();
      if(consoleHistory.length){ consoleHistoryIndex = Math.min(consoleHistory.length, consoleHistoryIndex + 1); $(this).val(consoleHistoryIndex >= consoleHistory.length ? '' : consoleHistory[consoleHistoryIndex]); }
    } else if(e.ctrlKey && String(e.key).toLowerCase() === 'l'){
      e.preventDefault();
      $('#consoleOutput').html(renderPromptLine(''));
      $('#consoleCommand').trigger('focus');
    }
  });
}
function appendPrompt(command){
  $('#consoleOutput').append(renderPromptLine(command || ''));
  const out = document.getElementById('consoleOutput');
  out.scrollTop = out.scrollHeight;
  $('#consoleCommand').last().trigger('focus');
}
function updateConsolePath(resp){
  consoleCwd = resp.cwd || consoleCwd || '';
  $('#consolePath span').text('Working directory: ' + formatWorkingDir(consoleCwd));
}
function runConsoleCommand(command){
  command = (command || '').trim();
  const oldInput = $('#consoleCommand').last();
  oldInput.replaceWith(`<span class="terminal-command">${esc(command)}</span>`);
  if(command){ consoleHistory.push(command); consoleHistoryIndex = consoleHistory.length; }
  if(command === 'clear'){
    $('#consoleOutput').html(renderPromptLine(''));
    $('#consoleCommand').last().trigger('focus');
    return;
  }
  $('#consoleOutput').append(`<div class="terminal-line terminal-running">Running...</div>`);
  $.ajax({url:'/api/console', method:'POST', contentType:'application/json', data:JSON.stringify({case:currentCase, command, cwd:consoleCwd})})
    .done(resp => {
      updateConsolePath(resp);
      $('.terminal-running').last().remove();
      if(resp.output === '__CLEAR__'){
        $('#consoleOutput').html(renderPromptLine(''));
        $('#consoleCommand').last().trigger('focus');
        return;
      }
      const output = resp.output ? esc(resp.output) : '';
      if(output) $('#consoleOutput').append(`<pre class="terminal-result">${output}</pre>`);
      appendPrompt('');
    })
    .fail(xhr => {
      let resp = xhr.responseJSON || {};
      updateConsolePath(resp);
      $('.terminal-running').last().remove();
      $('#consoleOutput').append(`<pre class="terminal-result terminal-error">${esc((resp.error ? resp.error + '\n\n' : '') + (resp.output || xhr.responseText || 'Command failed'))}</pre>`);
      appendPrompt('');
    });
}

function loadRecent() {
  destroyCharts(); setActive("recent"); setTitle("Recent Files");
  api("/api/recent", {}).done(resp => {
    const rows = resp.data || [];
    let html = `<div class="card"><h3>Last 5 Recent Files Opened</h3>`;
    if (!rows.length) html += `<p>No recent sosreport files.</p>`;
    rows.forEach(r => {
      html += `<div class="recent-item"><div><b>${esc(r.filename)}</b><br><small>${esc(r.case_id)}</small><br><small>Last opened: ${esc(r.last_opened_at)}</small></div><div class="recent-actions"><button class="openCase" data-case="${esc(r.case_id)}"><i class="bi bi-folder2-open"></i> Open</button><button class="deleteCase danger-btn" data-case="${esc(r.case_id)}"><i class="bi bi-trash3"></i> Delete</button></div></div>`;
    });
    html += `</div>`;
    setContent(html);
    $(".openCase").on("click", function(){
      currentCase=$(this).data("case");
      localStorage.setItem("sosinsight_flask_current_case", currentCase);
      $.ajax({url:"/api/open_case", method:"POST", contentType:"application/json", data:JSON.stringify({case:currentCase})}).done(()=>loadDashboard());
    });
    $(".deleteCase").on("click", function(){
      const caseId = $(this).data("case");
      if(!confirm(`Delete ${caseId}? This removes parsed data and extracted files for this case.`)) return;
      $.ajax({url:"/api/delete_case", method:"POST", contentType:"application/json", data:JSON.stringify({case:caseId})}).done(resp=>{
        if(resp.ok){
          if(currentCase === caseId){ currentCase=""; localStorage.removeItem("sosinsight_flask_current_case"); }
          loadRecent();
        } else { alert(resp.error || "Delete failed"); }
      }).fail(xhr=>alert("Delete failed: " + xhr.responseText));
    });
  });
}

function setUploadProgress(pct, text) { const safe = Math.max(0, Math.min(100, Math.round(pct))); $("#uploadProgressBar").css("width", safe + "%"); $("#uploadProgressText").text(text || safe + "%"); }
function openUploadModal() { resetUploadState(); $("#uploadModal").addClass("show").attr("aria-hidden", "false"); }
function closeUploadModal() { $("#uploadModal").removeClass("show").attr("aria-hidden", "true"); resetUploadState(); }
function updateSelectedFile(file){ droppedFile = file || null; const dz=$("#dropZone"); dz.removeClass("uploading done").toggleClass("has-file", !!file); dz.find(".drop-icon").html(file ? '<i class="bi bi-file-earmark-zip"></i>' : '<i class="bi bi-cloud-arrow-up"></i>'); dz.find("strong").text(file ? "Sosreport archive selected" : "Choose or drag-drop sosreport file"); $("#selectedFile").text(file ? `${file.name} (${(file.size/1024/1024).toFixed(1)} MB)` : "No file selected"); setUploadProgress(0, "0%"); }
function handleUpload() {
  const file = droppedFile || $("#sosFile")[0].files[0];
  if (!file) { alert("Please select or drop a sosreport file first."); return; }
  const fd = new FormData(); fd.append("sosfile", file); fd.append("case_name", $("#caseName").val() || "");
  let parseTimer = null; $("#dropZone").addClass("uploading").removeClass("done"); setUploadProgress(0, "Preparing upload..."); $("#uploadStatus").text("");
  $.ajax({ url:"/upload", type:"POST", data:fd, processData:false, contentType:false, xhr:function(){ const xhr=new window.XMLHttpRequest(); xhr.upload.addEventListener("progress", function(evt){ if(evt.lengthComputable){ const uploadPct=(evt.loaded/evt.total)*70; setUploadProgress(uploadPct, `Uploading ${Math.round(uploadPct)}%`); if(evt.loaded===evt.total){ $("#uploadStatus").text("Upload complete. Parsing sosreport..."); let fake=72; parseTimer=setInterval(()=>{ fake=Math.min(94, fake+Math.random()*4); setUploadProgress(fake, `Parsing ${Math.round(fake)}%`); },650); } } }); return xhr; }, success:function(resp){ if(parseTimer) clearInterval(parseTimer); if(!resp.ok){ $("#dropZone").removeClass("uploading done"); setUploadProgress(0,"Failed"); $("#uploadStatus").text("Error: "+resp.error); return; } $("#dropZone").removeClass("uploading").addClass("done"); setUploadProgress(100,"Completed 100%"); currentCase=resp.case_id; localStorage.setItem("sosinsight_flask_current_case", currentCase); $("#uploadStatus").text("Parsed successfully: "+currentCase); setTimeout(()=>{ closeUploadModal(); loadDashboard(); },700); }, error:function(xhr){ if(parseTimer) clearInterval(parseTimer); $("#dropZone").removeClass("uploading done"); setUploadProgress(0,"Failed"); $("#uploadStatus").text("Upload failed: "+xhr.responseText); } });
}

$(document).ready(function(){
  function updateThemeButton(){
    if($("body").hasClass("dark")) $("#themeToggle").html('<i class="bi bi-sun"></i> <span>Light Mode</span>');
    else $("#themeToggle").html('<i class="bi bi-moon-stars"></i> <span>Dark Mode</span>');
  }
  $("#themeToggle").on("click", function(){ $("body").toggleClass("dark").toggleClass("light"); localStorage.setItem("sosinsight_flask_theme", $("body").hasClass("dark") ? "dark" : "light"); updateThemeButton(); });
  if((localStorage.getItem("sosinsight_flask_theme")||"light")==="dark"){ $("body").removeClass("light").addClass("dark"); }
  updateThemeButton();
  if(localStorage.getItem("sosinsight_sidebar_collapsed")==="1") $(".app").addClass("sidebar-collapsed");
  $(".brand").on("click", function(){ $(".app").toggleClass("sidebar-collapsed"); localStorage.setItem("sosinsight_sidebar_collapsed", $(".app").hasClass("sidebar-collapsed") ? "1" : "0"); });
  $(".nav").on("click", function(){ const view=$(this).data("view"); if(view==="upload") openUploadModal(); else if(view==="dashboard") loadDashboard(); else if(view==="troubleshooting") loadTroubleshooting(); else if(view==="Summary") loadSummary(); else if(view==="systeminfo") loadSystemInformation(); else if(view==="messages") loadMessages(); else if(view==="dmesg") loadDmesg(); else if(view==="console") loadConsole(); else if(view==="recent") loadRecent(); else loadFacts(view); });
  $("#uploadBtn").on("click", handleUpload); $("#uploadClose,#uploadCancel").on("click", closeUploadModal); $("#sosFile").on("change", function(){ updateSelectedFile(this.files[0]); });
  const dz = $("#dropZone");
  dz.on("dragenter dragover", function(e){ e.preventDefault(); e.stopPropagation(); dz.addClass("drag-over"); });
  dz.on("dragleave drop", function(e){ e.preventDefault(); e.stopPropagation(); dz.removeClass("drag-over"); });
  dz.on("drop", function(e){ const file = e.originalEvent.dataTransfer.files[0]; if(file){ updateSelectedFile(file); } });
  $("#chartModalClose").on("click", closeChartModal);
  $("#chartModal").on("click", function(e){ if(e.target === this) closeChartModal(); });
  $("#chartResetZoom").on("click", function(){ if(modalChart && modalChart.resetZoom) modalChart.resetZoom(); });
  $("#downloadPng").on("click", function(){ downloadModalChart('png'); });
  $("#downloadJpg").on("click", function(){ downloadModalChart('jpg'); });
  $("#content").on("scroll", function(){ $(".topbar").toggleClass("shrink", this.scrollTop > 12); });
  loadDashboard();
});
