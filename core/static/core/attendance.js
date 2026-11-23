// Teacher phone form (design Figures 23-26). Reads ONLY from the local database (IndexedDB), so it works with no connection.
(() => {
  const T = window.T, I = ITmatic;
  const $ = s => document.querySelector(s);
  const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'}[c]));
  const hm = iso => new Date(iso).toLocaleTimeString([], {hour: '2-digit', minute: '2-digit'});
  const fmt = iso => new Date(iso).toLocaleString([], {weekday: 'short', day: '2-digit', month: '2-digit', hour: '2-digit', minute: '2-digit'});
  let lessons = [], pend = new Set();

  async function load() {
    lessons = (await I.DB.all('lessons')).sort((a, b) => a.start.localeCompare(b.start));
    pend = new Set((await I.DB.all('outbox')).map(i => i.lesson));
  }

  function netBar() {
    const s = I.state, n = pend.size;
    let h = s.online ? `<b>${T.online}</b>` : `⚠ ${T.offline}`;
    if (n) h += ` · ${n} ${T.pending}`;
    if (s.lastSync && s.online) h += ` · ${T.lastSync}: ${s.lastSync.toLocaleTimeString()}`;
    if (s.conflicts) h += `<br>${T.conflict}`;
    if (s.rejected) h += `<br>${T.rejected}`;
    const el = $('#net'); el.innerHTML = h; el.className = 'msg ' + (s.online ? (n ? 'warning' : 'success') : 'warning');
  }

  function renderList() {
    $('#form').hidden = true; const el = $('#list'); el.hidden = false;
    el.innerHTML = `<h1>${T.attendance}</h1>` + (lessons.length ? lessons.map(l => {
      const opens = I.now() < new Date(l.opens_at);
      const label = pend.has(l.id) ? T.pendingSave : l.saved_at ? T.saved : opens ? T.opens : T.open;
      const cls = pend.has(l.id) ? 'warn' : l.saved_at ? 'ok' : '';
      return `<a class="card row" href="#${l.id}"><div><b>${esc(l.group)}</b><br><small class="muted">${fmt(l.start)} · ${T.room} ${esc(l.room)}</small></div><span class="pill ${cls}">${label}</span></a>`;
    }).join('') : `<p class="muted">${T.none}</p>`);
  }

  const badge = s => {
    if (!s.pre) return '';
    const p = s.pre, txt = p.kind === 'late' ? `${T.late} ${p.minutes} ${T.min}` : `${T.absent}: ${esc(T.reasons[p.reason] || p.reason)}${p.note ? ' · ' + esc(p.note) : ''}`;
    return ` <span class="pill bad">${T.pre} · ${txt}</span>`;
  };

  async function renderForm(id) {
    const l = lessons.find(x => x.id === id); if (!l) return renderList();
    const ob = (await I.DB.all('outbox')).find(i => i.lesson === id);
    const dr = !ob && await I.getDraft(id);
    const src = ob || dr || {};
    const locked = I.now() < new Date(l.opens_at) || I.now() > new Date(l.closes_at);
    $('#list').hidden = true; const f = $('#form'); f.hidden = false;
    const cur = s => (src.statuses && src.statuses[s.id]) || s.status || (s.pre ? s.pre.kind : 'present');
    f.innerHTML = `<p><a class="btn alt big" href="#">← ${T.back}</a></p><h1>${esc(l.group)}</h1><p class="sub">${fmt(l.start)}–${hm(l.end)} · ${T.room} ${esc(l.room)}</p>
      ${locked ? `<div class="msg warning">${T.locked} (${hm(l.opens_at)})</div>` : ''}
      <form id="af" class="form"><div class="bar" style="margin-bottom:.6rem"><button type="button" class="btn alt big" id="allp" ${locked ? 'disabled' : ''}>${T.allPresent}</button></div>
      <h2>${T.attendance} · ${l.students.length} ${T.students}</h2>
      ${l.students.map((s, i) => `<div class="card stu"><div><b>${i + 1}. ${esc(s.name)}</b>${badge(s)}</div><div class="seg">
        ${['present', 'late', 'absent'].map(k => `<label><input type="radio" name="st_${s.id}" value="${k}" ${cur(s) === k ? 'checked' : ''} ${locked ? 'disabled' : ''}><span class="${k}">${T[k]}</span></label>`).join('')}</div></div>`).join('')}
      <div class="card"><label>${T.topic}<input name="topic" required value="${esc(src.topic ?? l.topic)}" ${locked ? 'disabled' : ''}></label>
      <label>${T.homework}<textarea name="homework" rows="3" ${locked ? 'disabled' : ''}>${esc(src.homework ?? l.homework)}</textarea></label>
      <label>${T.due}<input type="date" name="due" value="${esc(src.due ?? l.due)}" ${locked ? 'disabled' : ''}></label>
      <label>${T.attachment}<input type="file" name="files" multiple ${locked ? 'disabled' : ''}></label>
      <div id="picked" class="muted">${(src.files || []).map(x => '📎 ' + esc(x.name)).join('<br>')}</div>
      ${(l.files || []).map(u => `<div><a href="${esc(u)}" target="_blank">📎 ${esc(decodeURIComponent(u.split('/').pop()))}</a></div>`).join('')}</div>
      ${locked ? '' : `<div class="inline"><button type="button" class="btn alt" id="draft">${T.draft}</button><button class="btn" style="flex:2">${T.submit}</button></div>`}</form><div id="res" class="msg" hidden></div>`;
    const collect = form => {
      const statuses = {}; l.students.forEach(s => { const c = form.querySelector(`input[name=st_${s.id}]:checked`); statuses[s.id] = c ? c.value : 'absent'; });
      return {lesson: id, topic: form.topic.value, homework: form.homework.value, due: form.due.value, statuses, files: [...form.files.files].slice(0, 3)};
    };
    const form = $('#af');
    form.files && form.files.addEventListener('change', () => { $('#picked').innerHTML = [...form.files.files].slice(0, 3).map(x => '📎 ' + esc(x.name)).join('<br>'); });
    $('#allp').onclick = () => f.querySelectorAll('input[value=present]:not(:disabled)').forEach(r => r.checked = true);
    const dbtn = $('#draft'); if (dbtn) dbtn.onclick = async () => {
      await I.saveDraft(id, collect(form)); const r = $('#res'); r.hidden = false; r.className = 'msg'; r.textContent = T.draftSaved; };
    form.onsubmit = async e => {
      e.preventDefault();
      await I.queue(collect(form));
      const r = $('#res'); r.hidden = false; r.className = 'msg success'; r.textContent = T.savedLocal;
    };
  }

  async function route() {
    await load(); netBar();
    const id = parseInt(location.hash.slice(1)); if (id) renderForm(id); else renderList();
  }
  I.state.onUpdate = async () => { await load(); netBar(); if (!location.hash.slice(1)) renderList(); };
  window.addEventListener('hashchange', route);
  document.addEventListener('DOMContentLoaded', async () => {
    await route();
    if (!location.hash && window.OPEN_ID) location.hash = window.OPEN_ID;
  });
})();
