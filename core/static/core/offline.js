// NFR-03: local database on the teacher's device (IndexedDB) + outbox that is sent to the server later.
//   lessons : copy of the teacher's schedule, students and pre-filled absences (pulled from /api/roster/)
//   outbox  : attendance records entered on the device, waiting to be pushed to /api/push/
//   meta    : clock offset between device and server
window.ITmatic = (() => {
  let dbp;
  const open = () => dbp || (dbp = new Promise((res, rej) => {
    const r = indexedDB.open('itmatic', 1);
    r.onupgradeneeded = () => { const d = r.result;
      d.createObjectStore('lessons', {keyPath: 'id'}); d.createObjectStore('outbox', {keyPath: 'uuid'}); d.createObjectStore('meta', {keyPath: 'k'}); };
    r.onsuccess = () => res(r.result); r.onerror = () => rej(r.error);
  }));
  const tx = async (store, mode, fn) => { const d = await open();
    return new Promise((res, rej) => { const t = d.transaction(store, mode); const rq = fn(t.objectStore(store));
      t.oncomplete = () => res(rq && rq.result); t.onerror = () => rej(t.error); }); };
  const DB = {all: s => tx(s, 'readonly', o => o.getAll()), get: (s, k) => tx(s, 'readonly', o => o.get(k)),
              put: (s, v) => tx(s, 'readwrite', o => o.put(v)), del: (s, k) => tx(s, 'readwrite', o => o.delete(k))};

  const csrf = () => (document.cookie.match(/csrftoken=([^;]+)/) || [])[1] || '';
  const uuid = () => (crypto.randomUUID ? crypto.randomUUID() : 'u' + Date.now() + Math.random().toString(16).slice(2));
  let skew = 0;                                    // server clock - device clock
  const now = () => new Date(Date.now() + skew);
  const state = {online: navigator.onLine, lastSync: null, conflicts: 0, rejected: 0, onUpdate: () => {}};

  async function badge() {
    const n = (await DB.all('outbox')).length, el = document.getElementById('sync');
    if (el) { el.hidden = !n; el.textContent = n ? `⟳ ${n}` : ''; }
    return n;
  }

  async function push() {
    const items = (await DB.all('outbox')).sort((a, b) => a.saved_at.localeCompare(b.saved_at));
    for (const it of items) {
      const fd = new FormData();
      fd.append('uuid', it.uuid); fd.append('lesson', it.lesson); fd.append('topic', it.topic);
      fd.append('homework', it.homework); fd.append('due', it.due || ''); fd.append('statuses', JSON.stringify(it.statuses)); fd.append('saved_at', it.saved_at);
      (it.files || []).slice(0, 3).forEach(f => fd.append('homework_file', f, f.name));
      let r;
      try { r = await fetch('/api/push/', {method: 'POST', headers: {'X-CSRFToken': csrf()}, body: fd}); }
      catch (e) { return false; }                                   // still offline -> keep everything
      if (!r.ok) return false;                                      // session expired / server error -> retry later
      const j = await r.json();
      if (j.status === 'conflict') state.conflicts++;
      if (j.status === 'rejected') state.rejected++;
      await DB.del('outbox', it.uuid);                              // ok, duplicate, conflict, rejected are all final
    }
    return true;
  }

  async function pull() {
    const r = await fetch('/api/roster/', {headers: {'X-Requested-With': 'XMLHttpRequest'}});
    if (!r.ok) return;
    const j = await r.json();
    skew = new Date(j.server_time) - Date.now(); await DB.put('meta', {k: 'skew', v: skew});
    const pending = new Set((await DB.all('outbox')).map(i => i.lesson));
    const ids = new Set(j.lessons.map(l => l.id));
    for (const l of await DB.all('lessons')) if (!ids.has(l.id) && !pending.has(l.id)) await DB.del('lessons', l.id);
    for (const l of j.lessons) if (!pending.has(l.id)) await DB.put('lessons', l);   // never overwrite unsent edits
  }

  let busy = false;
  async function sync() {
    state.online = navigator.onLine;
    if (busy || !navigator.onLine) { await badge(); state.onUpdate(); return; }
    busy = true;
    try { if (await push()) { await pull(); state.lastSync = new Date(); } } catch (e) {} finally { busy = false; }
    await badge(); state.onUpdate();
  }

  // Save locally first (works offline), then try to send.
  async function queue({lesson, topic, homework, due, statuses, files}) {
    const old = (await DB.all('outbox')).find(i => i.lesson === lesson);
    if (old) await DB.del('outbox', old.uuid);
    const saved_at = now().toISOString();
    const keep = (files && files.length) ? files : (old && old.files) || [];
    await DB.put('outbox', {uuid: uuid(), lesson, topic, homework, due, statuses, saved_at, files: keep.slice(0, 3)});
    await DB.del('meta', 'draft:' + lesson);
    const l = await DB.get('lessons', lesson);
    if (l) { l.topic = topic; l.homework = homework; l.due = due; l.saved_at = saved_at;
             l.students.forEach(s => s.status = statuses[s.id] || 'absent'); await DB.put('lessons', l); }
    await badge(); state.onUpdate(); sync();
  }

  window.addEventListener('online', sync);
  window.addEventListener('offline', () => { state.online = false; state.onUpdate(); });
  setInterval(sync, 30000);                                          // NFR-03: sync well within 1 minute
  document.addEventListener('DOMContentLoaded', async () => {
    try { const m = await DB.get('meta', 'skew'); if (m) skew = m.v; } catch (e) {}
    badge(); sync();
  });
  const saveDraft = (lesson, v) => DB.put('meta', {k: 'draft:' + lesson, v});
  const getDraft = async lesson => { const m = await DB.get('meta', 'draft:' + lesson); return m && m.v; };
  return {DB, now, queue, sync, state, badge, saveDraft, getDraft};
})();
