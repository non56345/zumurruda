/* =====================================================
   لوحة تحكم الزُمردة — الواجهة من المرحلة الثانية، والحفظ على الخادم (المرحلة الثالثة – الخطوة 5)
   التخزين: قاعدة بيانات الخادم عبر /api/admin (جلسة + رمز CSRF). لا يُعتمد على localStorage.
   ===================================================== */
(() => {
'use strict';
const SEED = window.ZUM_SEED;
const KEY = 'zumurrud_admin_v1';
const clone = o => JSON.parse(JSON.stringify(o));
const $ = (s, r = document) => r.querySelector(s);
const $$ = (s, r = document) => [...r.querySelectorAll(s)];
const esc = t => String(t == null ? '' : t).replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const uid = () => Date.now().toString(36) + Math.random().toString(36).slice(2, 6);
const arNum = n => Number(n).toLocaleString('en-US');

const ICON = {
  edit: '<svg class="i" viewBox="0 0 24 24"><path d="M4 20h4L19 9l-4-4L4 16z M14 6l4 4"/></svg>',
  del: '<svg class="i" viewBox="0 0 24 24"><path d="M5 7h14M10 11v6M14 11v6M6 7l1 13h10l1-13M9 7V4h6v3"/></svg>',
  plus: '<svg class="i" viewBox="0 0 24 24"><path d="M12 5v14M5 12h14"/></svg>',
  img: '<svg class="i" viewBox="0 0 24 24"><rect x="3" y="4" width="18" height="16" rx="2"/><circle cx="9" cy="10" r="1.6"/><path d="M21 16l-5-5-8 8"/></svg>',
  star: '<svg class="i" viewBox="0 0 24 24" style="fill:currentColor;stroke:none;width:.95em;height:.95em"><path d="M12 3l2.6 5.6 6 .7-4.5 4.1 1.2 6L12 16.4 6.7 19.4l1.2-6L3.4 9.3l6-.7z"/></svg>'
};

/* ---------------- المخزن (الخادم) ---------------- */
const LEGACY_KEY = 'zumurrud_admin_v1';          // بيانات النسخة التجريبية القديمة في المتصفح (للنقل مرة واحدة فقط)
let state = null, rev = 0, csrf = '', queue = Promise.resolve();
async function api(method, url, body, form) {
  const headers = { Accept: 'application/json' };
  if (method !== 'GET') headers['X-CSRF-Token'] = csrf;
  if (body !== undefined && !form) headers['Content-Type'] = 'application/json';
  let r;
  try { r = await fetch(url, { method, headers, credentials: 'same-origin', body: form || (body === undefined ? undefined : JSON.stringify(body)) }); }
  catch (e) { return { ok: false, status: 0, data: { message: 'تعذّر الاتصال بالخادم. تحقّقي من الإنترنت وحاولي مرة أخرى.' } }; }
  if (r.status === 401) { location.replace('/admin/login?next=' + encodeURIComponent(location.pathname)); return { ok: false, status: 401, data: { message: 'انتهت الجلسة.' } }; }
  let data = {}; try { data = await r.json(); } catch (e) { /* ليس JSON */ }
  if (r.status === 403 && !url.endsWith('/admin/session') && await refreshCsrf()) return api(method, url, body, form);
  return { ok: r.ok, status: r.status, data };
}
async function refreshCsrf() {
  try { const r = await fetch('/admin/session', { credentials: 'same-origin', headers: { Accept: 'application/json' } }); if (!r.ok) return false; const j = await r.json(); if (j.csrf_token && j.csrf_token !== csrf) { csrf = j.csrf_token; return true; } } catch (e) { /* تجاهل */ }
  return false;
}
async function loadState() {
  const r = await api('GET', '/api/admin/state');
  if (!r.ok) throw new Error(r.data.message || 'تعذّر تحميل البيانات من الخادم.');
  state = r.data.state; rev = r.data.rev;
}
const payload = () => { const o = {}; ['version', 'content', 'contact', 'services', 'priceCats', 'products', 'images', 'gallery'].forEach(k => o[k] = state[k]); return o; };
/* ينفّذ التعديل محليًا ثم يحفظه على الخادم. يعيد Promise<boolean>.
   عند الفشل يُلغى التعديل محليًا، وتُغلق النافذة، وتظهر رسالة الخطأ. الحفظات تُنفَّذ بالتسلسل. */
function commit(mutator, msg, opts = {}) {
  const run = async () => {
    const backup = JSON.stringify(state);
    try { mutator(); } catch (e) { state = JSON.parse(backup); toast('حدث خطأ غير متوقع؛ لم يُحفظ التعديل.', 'err'); return false; }
    const r = await api('PUT', '/api/admin/state', { state: payload(), rev, msg: msg || 'تعديل البيانات', import: !!opts.import });
    if (r.ok) { rev = r.data.rev; state.log = r.data.log || state.log; return true; }
    state = JSON.parse(backup);
    if (r.status === 401) return false;
    closeModal();
    if (r.status === 409) { try { await loadState(); } catch (e) { /* تبقى النسخة الحالية */ } }
    rerender();
    toast((r.status === 409 ? '' : 'لم يُحفظ التعديل: ') + (r.data.message || 'تعذّر الحفظ على الخادم.'), 'err');
    return false;
  };
  const p = queue.then(run, run); queue = p.catch(() => false); return p;
}
/* ---------------- أدوات الواجهة ---------------- */
function toast(msg, type = 'ok') {
  const el = document.createElement('div');
  el.className = 'toast ' + type; el.setAttribute('role', type === 'err' ? 'alert' : 'status');
  el.textContent = (type === 'ok' ? '✓ ' : '⚠ ') + msg;
  $('#toasts').appendChild(el);
  setTimeout(() => { el.classList.add('out'); setTimeout(() => el.remove(), 350); }, type === 'err' ? 6000 : 3200);
}
const resolveSrc = s => !s ? '' : /^(data:|https?:|blob:)/.test(s) ? s : '../' + s;
function thumb(slot, cls = '') {
  const im = state.images[slot]; const src = im && im.src ? resolveSrc(im.src) : '';
  return `<div class="thumb ${cls}${src ? '' : ' empty-src'}">${src ? `<img src="${esc(src)}" alt="" loading="lazy" onerror="this.closest('.thumb').classList.add('noimg')">` : ''}</div>`;
}
function fmtTime(t) {
  const d = new Date(t);
  return d.toLocaleDateString('ar-LY', { day: 'numeric', month: 'short' }) + ' ' + d.toLocaleTimeString('ar-LY', { hour: '2-digit', minute: '2-digit' });
}
function mkField(o) {
  const { name, label, type = 'text', value = '', req = false, hint = '', dir = '', ph = '', options } = o;
  let ctl;
  if (type === 'textarea') ctl = `<textarea id="f_${name}" name="${name}" placeholder="${esc(ph)}">${esc(value)}</textarea>`;
  else if (type === 'select') ctl = `<select id="f_${name}" name="${name}">${options.map(([v, l]) => `<option value="${esc(v)}"${v === value ? ' selected' : ''}>${esc(l)}</option>`).join('')}</select>`;
  else ctl = `<input id="f_${name}" name="${name}" type="${type}" value="${esc(value)}" placeholder="${esc(ph)}" ${dir ? `dir="${dir}"` : ''} autocomplete="off">`;
  return `<div class="field" data-f="${name}"><label for="f_${name}">${esc(label)}${req ? ' <span class="req">*</span>' : ''}</label>${ctl}${hint ? `<span class="hint">${hint}</span>` : ''}<span class="err" role="alert"></span></div>`;
}
function setErr(form, name, msg) {
  const f = $(`[data-f="${name}"]`, form); if (!f) return;
  f.classList.toggle('bad', !!msg); $('.err', f).textContent = msg || '';
}
function clearErrs(form) { $$('.field.bad', form).forEach(f => f.classList.remove('bad')); }

/* ---------------- النوافذ ---------------- */
let modalEl = null, lastFocus = null;
function closeModal() {
  if (!modalEl) return; modalEl.remove(); modalEl = null; document.body.classList.remove('lock');
  if (lastFocus && document.contains(lastFocus)) lastFocus.focus();
}
/* onSubmit(form) → true للإغلاق، أو نص خطأ، أو false للبقاء */
function openModal({ title, body, submitLabel = 'حفظ', danger = false, onSubmit, onOpen, hideSubmit = false }) {
  closeModal(); lastFocus = document.activeElement;
  modalEl = document.createElement('div'); modalEl.className = 'modal' + (danger ? ' danger' : '');
  modalEl.innerHTML = `<form class="modal-box" role="dialog" aria-modal="true" aria-label="${esc(title)}" novalidate>
    <div class="modal-h"><h3>${esc(title)}</h3><button type="button" class="icon-btn" data-close aria-label="إغلاق"><svg class="i" viewBox="0 0 24 24"><path d="M6 6l12 12M18 6L6 18"/></svg></button></div>
    <div class="modal-b"><div class="form-err" role="alert"></div>${body}</div>
    <div class="modal-f">${hideSubmit ? '' : `<button type="submit" class="btn ${danger ? 'btn-danger' : 'btn-primary'}">${esc(submitLabel)}</button>`}<button type="button" class="btn btn-ghost" data-close>إلغاء</button></div></form>`;
  $('#modalRoot').appendChild(modalEl); document.body.classList.add('lock');
  const form = $('form', modalEl);
  modalEl.addEventListener('mousedown', e => { if (e.target === modalEl) closeModal(); });
  $$('[data-close]', modalEl).forEach(b => b.addEventListener('click', closeModal));
  form.addEventListener('submit', e => {
    e.preventDefault(); clearErrs(form); const fe = $('.form-err', form); fe.classList.remove('on');
    const done = r => { if (!modalEl || $('form', modalEl) !== form) return; if (r === true) closeModal(); else if (typeof r === 'string') { fe.textContent = r; fe.classList.add('on'); } };
    if (form.dataset.busy) return;
    const r = onSubmit ? onSubmit(form) : true;
    if (r && typeof r.then === 'function') {
      const btn = $('button[type=submit]', form); form.dataset.busy = '1'; if (btn) btn.disabled = true;
      r.then(x => { delete form.dataset.busy; if (btn) btn.disabled = false; done(x); }, () => { delete form.dataset.busy; if (btn) btn.disabled = false; done('تعذّر الحفظ.'); });
    } else done(r);
  });
  if (onOpen) onOpen(form);
  const first = $('input:not([type=file]):not([type=checkbox]),textarea,select', form) || $('button[type=submit]', form);
  setTimeout(() => first && first.focus(), 30);
}
function confirmDelete({ title, text, onConfirm }) {
  openModal({ title, danger: true, submitLabel: 'نعم، احذف', body: `<p>${text}</p><p class="small muted" style="margin-top:10px">لا يمكن التراجع عن هذا الإجراء.</p>`, onSubmit: () => { onConfirm(); return true; } });
}

/* ---------------- الصور ---------------- */
/* يرفع الصورة إلى الخادم (يتحقق منها ويصغّرها ويحفظها في uploads/) ويعيد مسارها مثل uploads/abc.jpg */
async function readImage(file, { png = false } = {}) {
  if (!file) throw new Error('لم يتم اختيار ملف.');
  if (!/^image\/(jpeg|png|webp|gif)$/.test(file.type)) throw new Error('نوع الملف غير مدعوم. اختاري صورة بصيغة JPG أو PNG أو WEBP.');
  if (file.size > 10 * 1024 * 1024) throw new Error('حجم الصورة أكبر من 10 ميغابايت.');
  const fd = new FormData(); fd.append('file', file, file.name || 'image'); fd.append('kind', png ? 'logo' : 'image');
  const r = await api('POST', '/api/admin/upload', undefined, fd);
  if (!r.ok) throw new Error(r.data.message || 'تعذّر رفع الصورة.');
  return r.data.src;
}
/* حقل رفع صورة داخل نموذج: يخزّن الناتج في form._img */
function imgFieldHTML(slot, label = 'الصورة') {
  return `<div class="field"><label>${esc(label)}</label><div class="imgfield"><div data-prev>${thumb(slot || '__none', 'sq')}</div>
  <div><input type="file" accept="image/*" data-imgin><div class="hint" style="margin-top:6px">JPG أو PNG أو WEBP، حتى 10 ميغابايت. تُرفع إلى الخادم وتُصغَّر تلقائيًا.</div></div></div><span class="err" role="alert"></span></div>`;
}
function wireImgField(form) {
  const inp = $('[data-imgin]', form); if (!inp) return;
  inp.addEventListener('change', async () => {
    const f = inp.files[0]; if (!f) return;
    const btn = $('button[type=submit]', form); if (btn) btn.disabled = true; form.dataset.busy = '1';
    $('[data-prev]', form).innerHTML = '<div class="thumb sq"></div><span class="small muted">جارٍ رفع الصورة…</span>';
    try { form._img = await readImage(f); $('[data-prev]', form).innerHTML = `<div class="thumb sq"><img src="${esc(resolveSrc(form._img))}" alt=""></div>`; }
    catch (e) { form._img = null; inp.value = ''; $('[data-prev]', form).innerHTML = thumb('__none', 'sq'); toast(e.message, 'err'); }
    finally { if (btn) btn.disabled = false; delete form.dataset.busy; }
  });
}

/* ---------------- المسارات ---------------- */
const ROUTES = {
  home: { title: 'الرئيسية', view: vHome },
  services: { title: 'إدارة الخدمات', view: vServices },
  prices: { title: 'إدارة الأسعار', view: vPrices },
  opal: { title: 'منتجات أوبال', view: vOpal },
  images: { title: 'إدارة الصور', view: vImages },
  content: { title: 'محتوى الموقع', view: vContent }
};
/* جسر صغير لملف gift.js (طلبات بطاقة الإهداء)؛ لا يغيّر سلوك أي شاشة أخرى */
window.ZUM_ADMIN = { ROUTES, api, toast, esc, fmtTime, openModal, closeModal, rerender: () => rerender(), getArg: () => currentArg, getRoute: () => currentRoute };
function route() {
  const parts = (location.hash.replace(/^#\/?/, '') || 'home').split('/');
  const name = ROUTES[parts[0]] ? parts[0] : 'home';
  $$('#nav a').forEach(a => a.classList.toggle('act', a.dataset.r === name));
  $('#pageTitle').textContent = ROUTES[name].title; document.title = ROUTES[name].title + ' | لوحة تحكم الزُمردة';
  currentArg = parts[1] || ''; currentRoute = name;
  rerender(); window.scrollTo(0, 0); setMenu(false);
}
let currentRoute = 'home', currentArg = '';
function rerender() { const v = $('#view'); v.innerHTML = ROUTES[currentRoute].view(currentArg); const after = ROUTES[currentRoute].after; if (after) after(); if (currentRoute === 'home') checkMissing(); if (currentRoute === 'content') wireContent(); }

/* ---------------- الرئيسية ---------------- */
function priceCounts() { let n = 0; state.priceCats.forEach(c => c.groups.forEach(g => n += g.items.length)); return n; }
function vHome() {
  const filled = ['facebook', 'whatsapp', 'map'].filter(k => state.contact[k]).length;
  const uploaded = Object.values(state.images).filter(i => i.src && i.src.startsWith('uploads/')).length;
  const stats = [
    ['الخدمات', state.services.length, 'خدمة معروضة', '#/services'],
    ['أقسام الأسعار', state.priceCats.length, `${priceCounts()} بندًا وباقة`, '#/prices'],
    ['منتجات أوبال', state.products.length, 'منتج', '#/opal'],
    ['الصور', Object.keys(state.images).length, `<span id="missingStat">جارٍ الفحص…</span>`, '#/images'],
    ['روابط التواصل', `${filled}/3`, filled === 3 ? 'كلها مضافة' : 'فيسبوك • واتساب • الخريطة', '#/content/contact-info']
  ];
  const secs = [
    ['من نحن', 'تعريف بالمركز وثلاث ميزات', ['content', 'about']],
    ['الخدمات', `${state.services.length} خدمات بصورها ووصفها`, ['services']],
    ['الأسعار', `${state.priceCats.length} أقسام و${priceCounts()} بندًا`, ['prices']],
    ['تجربتكِ والمزاج', 'خطوات اليوم الكامل واقتراحات المزاج', ['content', 'day']],
    ['بطاقة الإهداء', 'نصوص قسم الإهداء', ['content', 'gift']],
    ['متجر أوبال', `${state.products.length} منتجات (عرض فقط)`, ['opal']],
    ['المعرض', `${state.gallery.length} صور`, ['images']],
    ['المناسبات', 'نصوص مساحة المناسبات', ['content', 'events']],
    ['التواصل', 'روابط فيسبوك وواتساب والخريطة', ['content', 'contact-info']]
  ];
  return `
  <div class="stats">${stats.map(s => `<a class="card stat" href="${s[3]}"><span>${s[0]}</span><b>${s[1]}</b><small>${s[2]}</small></a>`).join('')}</div>
  <h2 class="sec-title">أقسام الموقع</h2>
  <div class="sec-list">${secs.map(s => `<div class="card sec-item"><b>${s[0]}</b><span>${s[1]}</span><div class="links"><a href="#/${s[2].join('/')}">إدارة القسم ←</a></div></div>`).join('')}</div>
  <div class="two" style="margin-top:8px;align-items:start">
    <div><h2 class="sec-title">آخر العمليات</h2><div class="card card-b">${state.log.length ? `<ul class="log">${state.log.slice(0, 8).map(l => `<li><span>${esc(l.m)}</span><time>${fmtTime(l.t)}</time></li>`).join('')}</ul>` : '<p class="muted">لا توجد عمليات بعد. ابدئي بتعديل أي قسم من القائمة.</p>'}</div></div>
    <div><h2 class="sec-title">أدوات البيانات</h2><div class="card card-b" style="display:grid;gap:12px">
      <p class="small muted">البيانات محفوظة في قاعدة بيانات الخادم وتظهر في الموقع العام مباشرة. يأخذ الخادم نسخة احتياطية تلقائيًا، ويمكنكِ أيضًا تصدير نسخة JSON. ${uploaded ? `(صور مرفوعة: ${uploaded})` : ''}</p>${legacyCard()}
      <div class="actions"><button class="btn btn-ghost btn-sm" data-act="export">تصدير نسخة JSON</button><button class="btn btn-ghost btn-sm" data-act="import">استيراد نسخة</button><input type="file" id="importFile" accept="application/json,.json" hidden><button class="btn btn-danger-ghost btn-sm" data-act="reset">استعادة البيانات الأصلية</button></div></div></div>
  </div>`;
}
/* نقل بيانات النسخة التجريبية القديمة (المحفوظة في هذا المتصفح) إلى الخادم — مرة واحدة وبموافقة */
function legacyData() { try { const d = JSON.parse(localStorage.getItem(LEGACY_KEY) || 'null'); return d && d.services && d.priceCats ? d : null; } catch (e) { return null; } }
function legacyCard() {
  return legacyData() ? `<div class="form-err on" style="display:block"><b>وُجدت تعديلات قديمة محفوظة في هذا المتصفح</b> من النسخة التجريبية (قبل الربط بالخادم). يمكنكِ نقلها إلى الخادم لتظهر في الموقع، أو حذفها من المتصفح.
    <div class="actions" style="margin-top:8px"><button class="btn btn-gold btn-sm" data-act="legacy-import">نقلها إلى الخادم</button><button class="btn btn-ghost btn-sm" data-act="legacy-drop">حذفها من المتصفح</button></div></div>` : '';
}
/* تحويل صور data: القديمة (من النسخة التجريبية أو ملفات التصدير القديمة) إلى ملفات مرفوعة على الخادم */
async function uploadDataImages(d) {
  for (const [k, im] of Object.entries(d.images || {})) {
    if (im && typeof im.src === 'string' && im.src.startsWith('data:')) {
      const blob = await (await fetch(im.src)).blob();
      im.src = await readImage(new File([blob], k + '.' + (blob.type.split('/')[1] || 'jpg'), { type: blob.type }), { png: k === 'logo' });
    }
  }
  return d;
}
function importData(d, label) {
  confirmDelete({ title: label, text: 'سيتم استبدال كل البيانات الحالية على الخادم بمحتوى هذه النسخة. يأخذ الخادم نسخة احتياطية من البيانات الحالية قبل الاستبدال.', onConfirm: async () => {
    try { toast('جارٍ تجهيز البيانات ورفع الصور…'); await uploadDataImages(d); } catch (e) { return toast(e.message || 'تعذّر رفع الصور.', 'err'); }
    delete d.log; const ok = await commit(() => { state = Object.assign(d, { log: state.log }); }, label, { import: true });
    if (ok) { if (label.includes('القديمة')) try { localStorage.removeItem(LEGACY_KEY); } catch (e) { /* تجاهل */ } toast('تم استيراد البيانات وحفظها على الخادم.'); rerender(); }
  } });
}
function checkMissing() {
  const slots = Object.entries(state.images).filter(([, i]) => i.src);
  let pending = slots.length, missing = [];
  const done = () => { const el = $('#missingStat'); if (!el) return; el.textContent = missing.length ? `${missing.length} بلا ملف: ${missing.map(m => state.images[m].label).join('، ')}` : 'كل الملفات موجودة'; };
  if (!pending) return done();
  slots.forEach(([k, i]) => { const im = new Image(); im.onload = () => { if (!--pending) done(); }; im.onerror = () => { missing.push(k); if (!--pending) done(); }; im.src = resolveSrc(i.src); });
}

/* ---------------- الخدمات ---------------- */
function vServices() {
  const card = s => `<article class="card item">${thumb(s.slot)}<div class="body">
    <div><span class="badge ${s.group === 'beauty' ? 'green' : ''}">${s.group === 'beauty' ? 'التجميل والعناية' : 'قسم آخر'}</span></div>
    <h3>${esc(s.name)}</h3>${s.en ? `<span class="small muted" dir="ltr" style="text-align:right">${esc(s.en)}</span>` : ''}
    <p>${esc(s.desc)}</p>${s.price ? `<span class="price-tag">${esc(s.price)} د.ل</span>` : ''}
    <div class="row"><button class="btn btn-ghost btn-sm" data-act="svc-edit" data-id="${s.id}">${ICON.edit}تعديل</button><button class="btn btn-danger-ghost btn-sm" data-act="svc-del" data-id="${s.id}">${ICON.del}حذف</button></div></div></article>`;
  const beauty = state.services.filter(s => s.group === 'beauty'), other = state.services.filter(s => s.group !== 'beauty');
  return `<div class="page-head"><div><h2>الخدمات</h2><p>الأقسام التي تظهر في قسم «خدماتنا» بالموقع. أسعار الخدمات التفصيلية تُدار من صفحة «الأسعار».</p></div>
    <div class="actions"><button class="btn btn-gold" data-act="svc-add">${ICON.plus}إضافة خدمة</button></div></div>
    <h2 class="sec-title">التجميل والعناية</h2>${beauty.length ? `<div class="grid">${beauty.map(card).join('')}</div>` : '<div class="empty">لا توجد خدمات في هذا التصنيف.</div>'}
    <h2 class="sec-title">أقسام أخرى</h2>${other.length ? `<div class="grid">${other.map(card).join('')}</div>` : '<div class="empty">لا توجد خدمات في هذا التصنيف.</div>'}`;
}
function svcForm(s) {
  s = s || { name: '', en: '', desc: '', group: 'beauty', price: '', slot: '' };
  return mkField({ name: 'name', label: 'اسم الخدمة', value: s.name, req: true }) +
    mkField({ name: 'en', label: 'الاسم بالإنجليزية (اختياري)', value: s.en, dir: 'ltr' }) +
    mkField({ name: 'desc', label: 'وصف الخدمة', type: 'textarea', value: s.desc, req: true }) +
    `<div class="two">${mkField({ name: 'group', label: 'التصنيف', type: 'select', value: s.group, options: [['beauty', 'التجميل والعناية'], ['other', 'قسم آخر']] })}
    ${mkField({ name: 'price', label: 'السعر (اختياري)', value: s.price, hint: 'غير معروض حاليًا في الموقع؛ أسعار الخدمات في صفحة الأسعار.' })}</div>` +
    imgFieldHTML(s.slot, 'صورة الخدمة');
}
function svcSubmit(form, existing) {
  const v = n => form.elements[n].value.trim(); let bad = false;
  if (!v('name')) { setErr(form, 'name', 'اسم الخدمة مطلوب.'); bad = true; }
  if (!v('desc')) { setErr(form, 'desc', 'الوصف مطلوب.'); bad = true; }
  if (v('price') && !isPrice(v('price'))) { setErr(form, 'price', 'اكتبي رقمًا أو نطاقًا مثل 50–100.'); bad = true; }
  if (bad) return false;
  const ok = commit(() => {
    let s = existing; if (!s) { s = { id: uid(), slot: '' }; s.slot = 'svc_' + s.id; state.services.push(s); }
    Object.assign(s, { name: v('name'), en: v('en'), desc: v('desc'), group: v('group'), price: normPrice(v('price')) });
    if (!state.images[s.slot]) state.images[s.slot] = { label: s.name, group: 'sections', src: '' };
    state.images[s.slot].label = s.name;
    if (form._img) state.images[s.slot].src = form._img;
  }, (existing ? 'تعديل الخدمة «' : 'إضافة الخدمة «') + v('name') + '»');
  return ok.then(ok => { if (!ok) return false; toast(existing ? 'تم حفظ تعديلات الخدمة.' : 'تمت إضافة الخدمة بنجاح.'); rerender(); return true; });
}

/* ---------------- الأسعار ---------------- */
const isPrice = p => /^\s*[\d٠-٩]+(\s*[–\-—]\s*[\d٠-٩]+)?\s*$/.test(p);
const normPrice = p => p.trim().replace(/\s*[\-—]\s*/g, '–').replace(/\s*–\s*/g, '–');
function vPrices(arg) {
  if (!state.priceCats.length) return `<div class="page-head"><div><h2>الأسعار</h2></div><div class="actions"><button class="btn btn-gold" data-act="cat-add">${ICON.plus}إضافة قسم</button></div></div><div class="empty">لا توجد أقسام أسعار.</div>`;
  const cat = state.priceCats.find(c => c.id === arg) || state.priceCats[0];
  const chips = state.priceCats.map(c => `<a class="chip${c.id === cat.id ? ' on' : ''}" href="#/prices/${c.id}">${esc(c.t)}</a>`).join('');
  const gi = cat.groups;
  const rows = (g, gx) => g.items.map((it, ix) => `<div class="prow"><div class="nm"><b>${esc(it.n)}${it.star ? `<span class="badge dark">${ICON.star} الأكثر طلبًا</span>` : ''}</b>${it.d ? `<small>${esc(it.d)}</small>` : ''}${it.inc && it.inc.length ? `<div class="inc">${it.inc.map(x => `<span>${esc(x)}</span>`).join('')}</div>` : ''}</div>
    <span class="pv">${esc(it.p)} د.ل</span><div class="row"><button class="icon-btn" data-act="item-edit" data-g="${gx}" data-i="${ix}" aria-label="تعديل ${esc(it.n)}">${ICON.edit}</button><button class="icon-btn del" data-act="item-del" data-g="${gx}" data-i="${ix}" aria-label="حذف ${esc(it.n)}">${ICON.del}</button></div></div>`).join('') || '<div class="prow muted">لا توجد بنود في هذه المجموعة.</div>';
  const groups = gi.map((g, gx) => `<section class="card group"><div class="group-h"><h4>${g.pk ? 'الباقات' : esc(g.g)} <span class="badge">${g.pk ? 'باقات بمزايا' : 'قائمة'}</span> <span class="small muted">${g.items.length} بند</span></h4>
    <div class="actions"><button class="btn btn-gold btn-sm" data-act="item-add" data-g="${gx}">${ICON.plus}إضافة بند</button>${g.pk ? '' : `<button class="btn btn-ghost btn-sm" data-act="grp-edit" data-g="${gx}">${ICON.edit}تعديل العنوان</button>`}<button class="btn btn-danger-ghost btn-sm" data-act="grp-del" data-g="${gx}">${ICON.del}حذف المجموعة</button></div></div>${rows(g, gx)}</section>`).join('');
  return `<div class="page-head"><div><h2>الأسعار</h2><p>الأسعار بالدينار الليبي، مصنّفة حسب القسم كما تظهر في الموقع. اختاري القسم ثم عدّلي أي بند.</p></div>
    <div class="actions"><button class="btn btn-gold" data-act="cat-add">${ICON.plus}إضافة قسم</button></div></div>
    <div class="chips" role="tablist">${chips}</div>
    <div class="card cat-head"><div><h3>${esc(cat.t)}</h3>${cat.note ? `<p class="cat-note">📌 ${esc(cat.note)}</p>` : '<p class="cat-note">لا توجد ملاحظة لهذا القسم.</p>'}</div>
      <div class="actions"><button class="btn btn-ghost btn-sm" data-act="cat-edit" data-id="${cat.id}">${ICON.edit}تعديل القسم</button><button class="btn btn-gold btn-sm" data-act="grp-add" data-id="${cat.id}">${ICON.plus}إضافة مجموعة</button><button class="btn btn-danger-ghost btn-sm" data-act="cat-del" data-id="${cat.id}">${ICON.del}حذف القسم</button></div></div>
    ${groups || '<div class="empty">هذا القسم بلا مجموعات. أضيفي مجموعة لتبدأي بإضافة البنود.</div>'}`;
}
const curCat = () => state.priceCats.find(c => c.id === currentArg) || state.priceCats[0];
function catForm(c) {
  c = c || { t: '', note: '' };
  return mkField({ name: 't', label: 'اسم القسم', value: c.t, req: true }) + mkField({ name: 'note', label: 'ملاحظة أسفل القسم (اختياري)', type: 'textarea', value: c.note || '' });
}
function itemForm(g, it) {
  it = it || { n: '', p: '', d: '', inc: [], star: false };
  return mkField({ name: 'n', label: 'اسم البند', value: it.n, req: true }) +
    mkField({ name: 'p', label: 'السعر (د.ل)', value: it.p, req: true, dir: 'ltr', hint: 'رقم أو نطاق، مثل 120 أو 50–100.' }) +
    (g.pk ? mkField({ name: 'inc', label: 'المزايا المشمولة (سطر لكل ميزة)', type: 'textarea', value: (it.inc || []).join('\n') }) + `<div class="field"><label class="check"><input type="checkbox" name="star"${it.star ? ' checked' : ''}> إظهار شارة «الأكثر طلبًا»</label></div>`
      : mkField({ name: 'd', label: 'تفاصيل / وصف (اختياري)', value: it.d || '' }));
}
function itemSubmit(form, g, existing, ix) {
  const v = n => form.elements[n].value.trim(); let bad = false;
  if (!v('n')) { setErr(form, 'n', 'اسم البند مطلوب.'); bad = true; }
  if (!v('p')) { setErr(form, 'p', 'السعر مطلوب.'); bad = true; } else if (!isPrice(v('p'))) { setErr(form, 'p', 'السعر يجب أن يكون رقمًا أو نطاقًا مثل 50–100.'); bad = true; }
  if (bad) return false;
  const o = { n: v('n'), p: normPrice(v('p')) };
  if (g.pk) { o.inc = form.elements.inc.value.split('\n').map(x => x.trim()).filter(Boolean); if (form.elements.star.checked) o.star = 1; }
  else if (v('d')) o.d = v('d');
  const ok = commit(() => { if (existing) g.items[ix] = o; else g.items.push(o); }, (existing ? 'تعديل بند «' : 'إضافة بند «') + o.n + '» (' + o.p + ' د.ل)');
  return ok.then(ok => { if (!ok) return false; toast(existing ? 'تم تحديث البند والسعر.' : 'تمت إضافة البند.'); rerender(); return true; });
}

/* ---------------- منتجات أوبال ---------------- */
function vOpal() {
  return `<div class="page-head"><div><h2>منتجات أوبال</h2><p>المنتجات المعروضة في «متجر أوبال». الموقع الحالي يعرض الاسم والصورة فقط، وحقلا الوصف والسعر محفوظان للاستخدام لاحقًا. لا توجد سلة ولا دفع.</p></div>
    <div class="actions"><button class="btn btn-gold" data-act="prod-add">${ICON.plus}إضافة منتج</button></div></div>
    ${state.products.length ? `<div class="grid sm">${state.products.map(p => `<article class="card item">${thumb(p.slot, 'tall')}<div class="body"><h3>${esc(p.name)}</h3>${p.desc ? `<p>${esc(p.desc)}</p>` : ''}${p.price ? `<span class="price-tag">${esc(p.price)} د.ل</span>` : '<span class="small muted">لا يوجد سعر</span>'}
      <div class="row"><button class="btn btn-ghost btn-sm" data-act="prod-edit" data-id="${p.id}">${ICON.edit}تعديل</button><button class="btn btn-danger-ghost btn-sm" data-act="prod-del" data-id="${p.id}">${ICON.del}حذف</button></div></div></article>`).join('')}</div>` : '<div class="empty">لا توجد منتجات. اضغطي «إضافة منتج».</div>'}`;
}
function prodForm(p) {
  p = p || { name: '', desc: '', price: '', slot: '' };
  return mkField({ name: 'name', label: 'اسم المنتج', value: p.name, req: true }) + mkField({ name: 'desc', label: 'الوصف (اختياري)', type: 'textarea', value: p.desc }) +
    mkField({ name: 'price', label: 'السعر (اختياري)', value: p.price, dir: 'ltr', hint: 'رقم أو نطاق مثل 50–100.' }) + imgFieldHTML(p.slot, 'صورة المنتج');
}
function prodSubmit(form, existing) {
  const v = n => form.elements[n].value.trim(); let bad = false;
  if (!v('name')) { setErr(form, 'name', 'اسم المنتج مطلوب.'); bad = true; }
  if (v('price') && !isPrice(v('price'))) { setErr(form, 'price', 'اكتبي رقمًا أو نطاقًا مثل 50–100.'); bad = true; }
  if (!existing && !form._img) { $('.imgfield', form).parentElement.classList.add('bad'); $('.imgfield', form).parentElement.querySelector('.err').textContent = 'اختاري صورة للمنتج.'; bad = true; }
  if (bad) return false;
  const ok = commit(() => {
    let p = existing; if (!p) { p = { id: uid(), slot: '' }; p.slot = 'prod_' + p.id; state.products.push(p); }
    Object.assign(p, { name: v('name'), desc: v('desc'), price: normPrice(v('price')) });
    if (!state.images[p.slot]) state.images[p.slot] = { label: p.name, group: 'products', src: '' };
    state.images[p.slot].label = p.name; if (form._img) state.images[p.slot].src = form._img;
  }, (existing ? 'تعديل المنتج «' : 'إضافة المنتج «') + v('name') + '»');
  return ok.then(ok => { if (!ok) return false; toast(existing ? 'تم حفظ المنتج.' : 'تمت إضافة المنتج.'); rerender(); return true; });
}

/* ---------------- الصور ---------------- */
function vImages() {
  const slotCard = (k, im) => { const orig = SEED.images[k]; const changed = !!(im.src && im.src.startsWith('uploads/'));
    return `<article class="card slot">${thumb(k)}<div class="body"><b>${esc(im.label)}</b><small>${changed ? 'صورة مرفوعة على الخادم' : esc(im.src || 'لا توجد صورة')}</small>
      <div class="row"><button class="btn btn-gold btn-sm" data-act="img-change" data-k="${k}">${ICON.img}تغيير الصورة</button>${changed && orig ? `<button class="btn btn-ghost btn-sm" data-act="img-restore" data-k="${k}">استعادة الأصلية</button>` : ''}</div></div></article>`; };
  const by = g => Object.entries(state.images).filter(([, i]) => i.group === g);
  const gal = state.gallery.map(g => `<div class="card gitem">${thumb(g.slot, 'mini')}<div class="nm"><b>${esc(g.cap)}</b><span class="badge ${g.cat === 'gym' ? '' : 'green'}">${g.cat === 'gym' ? 'الجيم' : 'التجميل والعناية'}</span></div>
    <div class="actions"><button class="btn btn-ghost btn-sm" data-act="gal-edit" data-id="${g.id}">${ICON.edit}تعديل</button><button class="btn btn-danger-ghost btn-sm" data-act="gal-del" data-id="${g.id}">${ICON.del}حذف</button></div></div>`).join('');
  return `<input type="file" id="slotFile" accept="image/*" hidden>
  <div class="page-head"><div><h2>الصور</h2><p>غيّري صور الأقسام والمنتجات والمعرض. الصور المرفوعة تُحفظ على الخادم وتظهر في الموقع العام مباشرة، والصور الأصلية تبقى محفوظة للاستعادة.</p></div></div>
  <h2 class="sec-title">الهوية وصور الأقسام</h2><div class="grid sm">${[...by('identity'), ...by('sections')].map(([k, i]) => slotCard(k, i)).join('')}</div>
  <h2 class="sec-title">صور المنتجات</h2><div class="grid sm">${by('products').map(([k, i]) => slotCard(k, i)).join('') || '<div class="empty">لا توجد منتجات.</div>'}</div>
  <h2 class="sec-title">صور إضافية للمعرض</h2><div class="grid sm">${by('gallery').map(([k, i]) => slotCard(k, i)).join('') || '<div class="empty">لا توجد صور إضافية.</div>'}</div>
  <div class="page-head" style="margin-top:34px"><h2 class="sec-title" style="margin:0">عناصر المعرض</h2><div class="actions"><button class="btn btn-gold" data-act="gal-add">${ICON.plus}إضافة إلى المعرض</button></div></div>
  <div class="glist">${gal || '<div class="empty">المعرض فارغ.</div>'}</div>`;
}
function galForm(g) {
  const isNew = !g; g = g || { cap: '', cat: 'beauty', slot: '' };
  const opts = Object.entries(state.images).filter(([, i]) => i.src).map(([k, i]) => [k, i.label]);
  return mkField({ name: 'cap', label: 'عنوان الصورة', value: g.cap, req: true }) +
    mkField({ name: 'cat', label: 'التصنيف', type: 'select', value: g.cat, options: [['beauty', 'التجميل والعناية'], ['gym', 'الجيم']] }) +
    (isNew ? mkField({ name: 'slot', label: 'استخدام صورة موجودة', type: 'select', value: '', options: [['', '— أو ارفعي صورة جديدة أدناه —'], ...opts] }) + imgFieldHTML('__none', 'أو رفع صورة جديدة')
      : `<p class="small muted">لتغيير الصورة نفسها استخدمي «تغيير الصورة» في الأعلى. الصورة ربما تُستخدم في أكثر من موضع.</p>`);
}

/* ---------------- محتوى الموقع ---------------- */
const CGROUPS = [['contact-info', 'بيانات التواصل'], ['identity', 'الاسم والشعار'], ['hero', 'الواجهة الرئيسية'], ['about', 'من نحن'], ['services', 'الخدمات'], ['prices', 'الأسعار'], ['day', 'تجربتكِ'], ['mood', 'المزاج'], ['gift', 'الإهداء'], ['opal', 'متجر أوبال'], ['gallery', 'المعرض'], ['events', 'المناسبات'], ['contact', 'نصوص التواصل'], ['footer', 'التذييل']];
function vContent(arg) {
  const g = CGROUPS.find(x => x[0] === arg) ? arg : 'contact-info';
  currentArg = g;
  const chips = CGROUPS.map(([k, l]) => `<a class="chip${k === g ? ' on' : ''}" href="#/content/${k}">${l}</a>`).join('');
  let fields;
  if (g === 'contact-info') {
    fields = mkField({ name: 'facebook', label: 'رابط صفحة فيسبوك', type: 'url', value: state.contact.facebook, dir: 'ltr', ph: 'https://facebook.com/اسم-الصفحة', hint: 'يبدأ بـ https://' }) +
      mkField({ name: 'whatsapp', label: 'رقم واتساب', type: 'tel', value: state.contact.whatsapp, dir: 'ltr', ph: '218XXXXXXXXX', hint: 'بصيغة دولية، أرقام فقط بدون + أو أصفار (8 إلى 15 رقمًا).' }) +
      mkField({ name: 'map', label: 'رابط الموقع على خرائط جوجل', type: 'url', value: state.contact.map, dir: 'ltr', ph: 'https://maps.google.com/…', hint: 'يبدأ بـ https://' });
  } else fields = SEED.contentFields.filter(f => f.group === g).map(f => mkField({ name: f.key, label: f.label, type: f.type === 'textarea' ? 'textarea' : 'text', value: state.content[f.key] ?? '', req: true })).join('');
  return `<div class="page-head"><div><h2>محتوى الموقع</h2><p>عدّلي النصوص والعناوين وبيانات التواصل. اختاري القسم من الشريط أدناه.</p></div></div>
  <div class="chips" role="tablist">${chips}</div>
  <form class="card panel" id="contentForm" novalidate><h3 class="sec-title" style="margin-top:0">${CGROUPS.find(x => x[0] === g)[1]}</h3><div class="form-err" role="alert"></div>
    <div class="${g === 'contact-info' ? '' : 'two'}">${fields}</div>
    <div class="form-bar"><button type="submit" class="btn btn-primary">حفظ التغييرات</button><button type="button" class="btn btn-ghost" data-act="content-cancel">إلغاء التعديلات</button>${g === 'contact-info' ? '' : '<button type="button" class="btn btn-danger-ghost" data-act="content-restore">استعادة النصوص الأصلية</button>'}</div></form>`;
}
function wireContent() {
  const form = $('#contentForm'); if (!form) return; const g = currentArg;
  form.addEventListener('submit', e => {
    e.preventDefault(); clearErrs(form); let bad = false; const v = n => form.elements[n].value.trim();
    if (g === 'contact-info') {
      if (v('facebook') && !/^https:\/\/\S+\.\S+/i.test(v('facebook'))) { setErr(form, 'facebook', 'الرابط غير صالح. يجب أن يبدأ بـ https://'); bad = true; }
      if (v('whatsapp') && !/^\d{8,15}$/.test(v('whatsapp'))) { setErr(form, 'whatsapp', 'الرقم غير صالح. استخدمي أرقامًا فقط بصيغة دولية (8 إلى 15 رقمًا) بدون + أو مسافات.'); bad = true; }
      if (v('map') && !/^https:\/\/\S+\.\S+/i.test(v('map'))) { setErr(form, 'map', 'الرابط غير صالح. يجب أن يبدأ بـ https://'); bad = true; }
    } else SEED.contentFields.filter(f => f.group === g).forEach(f => { if (!v(f.key)) { setErr(form, f.key, 'هذا الحقل مطلوب.'); bad = true; } });
    if (bad) { const fe = $('.form-err', form); fe.textContent = 'تحقّقي من الحقول المُعلَّمة بالأحمر.'; fe.classList.add('on'); toast('لم يتم الحفظ: توجد حقول تحتاج تصحيحًا.', 'err'); return; }
    $('.form-err', form).classList.remove('on');
    const ok = commit(() => { if (g === 'contact-info') ['facebook', 'whatsapp', 'map'].forEach(k => state.contact[k] = v(k)); else SEED.contentFields.filter(f => f.group === g).forEach(f => state.content[f.key] = v(f.key)); },
      'تعديل «' + CGROUPS.find(x => x[0] === g)[1] + '»');
    const btn = $('button[type=submit]', form); btn.disabled = true;
    ok.then(ok => { btn.disabled = false; if (ok) toast('تم حفظ التغييرات بنجاح.'); });
  });
}

/* ---------------- الإجراءات ---------------- */
const actions = {
  'svc-add': () => openModal({ title: 'إضافة خدمة', body: svcForm(), onOpen: wireImgField, onSubmit: f => svcSubmit(f, null) }),
  'svc-edit': t => { const s = state.services.find(x => x.id === t.dataset.id); openModal({ title: 'تعديل الخدمة', body: svcForm(s), onOpen: wireImgField, onSubmit: f => svcSubmit(f, s) }); },
  'svc-del': t => { const s = state.services.find(x => x.id === t.dataset.id); confirmDelete({ title: 'حذف الخدمة', text: `هل تريدين حذف خدمة «<b>${esc(s.name)}</b>»؟`, onConfirm: () => { commit(() => { state.services = state.services.filter(x => x !== s); if (s.slot.startsWith('svc_')) delete state.images[s.slot]; }, 'حذف الخدمة «' + s.name + '»').then(ok => { if (ok) { toast('تم حذف الخدمة.'); rerender(); } }) } }); },

  'cat-add': () => openModal({ title: 'إضافة قسم أسعار', body: catForm(), onSubmit: f => { const t = f.elements.t.value.trim(); if (!t) { setErr(f, 't', 'اسم القسم مطلوب.'); return false; } const c = { id: uid(), t, groups: [] }; const note = f.elements.note.value.trim(); if (note) c.note = note; return commit(() => state.priceCats.push(c), 'إضافة قسم أسعار «' + t + '»').then(ok => { if (!ok) return false; toast('تمت إضافة القسم. أضيفي له مجموعة لتبدئي.'); location.hash = '#/prices/' + c.id; return true; }); } }),
  'cat-edit': t => { const c = state.priceCats.find(x => x.id === t.dataset.id); openModal({ title: 'تعديل القسم', body: catForm(c), onSubmit: f => { const v = f.elements.t.value.trim(); if (!v) { setErr(f, 't', 'اسم القسم مطلوب.'); return false; } return commit(() => { c.t = v; const n = f.elements.note.value.trim(); if (n) c.note = n; else delete c.note; }, 'تعديل القسم «' + v + '»').then(ok => { if (!ok) return false; toast('تم حفظ القسم.'); rerender(); return true; }); } }); },
  'cat-del': t => { const c = state.priceCats.find(x => x.id === t.dataset.id); const n = c.groups.reduce((a, g) => a + g.items.length, 0); confirmDelete({ title: 'حذف قسم الأسعار', text: `سيتم حذف قسم «<b>${esc(c.t)}</b>» مع <b>${n}</b> بندًا فيه.`, onConfirm: () => { commit(() => state.priceCats = state.priceCats.filter(x => x !== c), 'حذف قسم الأسعار «' + c.t + '»').then(ok => { if (ok) { toast('تم حذف القسم.'); location.hash = '#/prices'; if (currentRoute === 'prices') rerender(); } }) } }); },
  'grp-add': t => { const c = state.priceCats.find(x => x.id === t.dataset.id); openModal({ title: 'إضافة مجموعة', body: mkField({ name: 'type', label: 'نوع المجموعة', type: 'select', value: 'list', options: [['list', 'قائمة بسيطة (اسم وسعر)'], ['pk', 'باقات بمزايا (بطاقات)']] }) + mkField({ name: 'g', label: 'عنوان المجموعة', hint: 'لا يُستخدم مع الباقات.' }), onSubmit: f => { const type = f.elements.type.value, g = f.elements.g.value.trim(); if (type === 'list' && !g) { setErr(f, 'g', 'عنوان المجموعة مطلوب للقوائم.'); return false; } if (type === 'pk' && c.groups.some(x => x.pk)) { return 'هذا القسم يحتوي مجموعة باقات بالفعل؛ أضيفي البنود إليها.'; } return commit(() => c.groups.push(type === 'pk' ? { pk: 1, items: [] } : { g, items: [] }), 'إضافة مجموعة إلى «' + c.t + '»').then(ok => { if (!ok) return false; toast('تمت إضافة المجموعة.'); rerender(); return true; }); } }); },
  'grp-edit': t => { const c = curCat(), g = c.groups[+t.dataset.g]; openModal({ title: 'تعديل عنوان المجموعة', body: mkField({ name: 'g', label: 'عنوان المجموعة', value: g.g, req: true }), onSubmit: f => { const v = f.elements.g.value.trim(); if (!v) { setErr(f, 'g', 'العنوان مطلوب.'); return false; } return commit(() => g.g = v, 'تعديل مجموعة «' + v + '»').then(ok => { if (!ok) return false; toast('تم حفظ العنوان.'); rerender(); return true; }); } }); },
  'grp-del': t => { const c = curCat(), g = c.groups[+t.dataset.g]; confirmDelete({ title: 'حذف المجموعة', text: `سيتم حذف المجموعة «<b>${esc(g.pk ? 'الباقات' : g.g)}</b>» مع <b>${g.items.length}</b> بندًا.`, onConfirm: () => { commit(() => c.groups.splice(+t.dataset.g, 1), 'حذف مجموعة من «' + c.t + '»').then(ok => { if (ok) { toast('تم حذف المجموعة.'); rerender(); } }) } }); },
  'item-add': t => { const g = curCat().groups[+t.dataset.g]; openModal({ title: 'إضافة بند', body: itemForm(g), onSubmit: f => itemSubmit(f, g, false) }); },
  'item-edit': t => { const g = curCat().groups[+t.dataset.g], i = +t.dataset.i; openModal({ title: 'تعديل البند', body: itemForm(g, g.items[i]), onSubmit: f => itemSubmit(f, g, true, i) }); },
  'item-del': t => { const g = curCat().groups[+t.dataset.g], i = +t.dataset.i, it = g.items[i]; confirmDelete({ title: 'حذف البند', text: `هل تريدين حذف «<b>${esc(it.n)}</b>» (${esc(it.p)} د.ل)؟`, onConfirm: () => { commit(() => g.items.splice(i, 1), 'حذف البند «' + it.n + '»').then(ok => { if (ok) { toast('تم حذف البند.'); rerender(); } }) } }); },

  'prod-add': () => openModal({ title: 'إضافة منتج', body: prodForm(), onOpen: wireImgField, onSubmit: f => prodSubmit(f, null) }),
  'prod-edit': t => { const p = state.products.find(x => x.id === t.dataset.id); openModal({ title: 'تعديل المنتج', body: prodForm(p), onOpen: wireImgField, onSubmit: f => prodSubmit(f, p) }); },
  'prod-del': t => { const p = state.products.find(x => x.id === t.dataset.id); confirmDelete({ title: 'حذف المنتج', text: `هل تريدين حذف «<b>${esc(p.name)}</b>» من متجر أوبال؟`, onConfirm: () => { commit(() => { state.products = state.products.filter(x => x !== p); state.gallery = state.gallery.filter(g => g.slot !== p.slot); delete state.images[p.slot]; }, 'حذف المنتج «' + p.name + '»').then(ok => { if (ok) { toast('تم حذف المنتج.'); rerender(); } }) } }); },

  'img-change': t => { const k = t.dataset.k; const inp = $('#slotFile'); inp.value = ''; inp.onchange = async () => { const f = inp.files[0]; if (!f) return; try { toast('جارٍ رفع الصورة…'); const data = await readImage(f, { png: k === 'logo' }); commit(() => state.images[k].src = data, 'تغيير صورة «' + state.images[k].label + '»').then(ok => { if (ok) { toast('تم تغيير الصورة وحفظها.'); rerender(); } }) } catch (e) { toast(e.message, 'err'); } }; inp.click(); },
  'img-restore': t => { const k = t.dataset.k; commit(() => state.images[k].src = SEED.images[k].src, 'استعادة الصورة الأصلية «' + state.images[k].label + '»').then(ok => { if (ok) { toast('تمت استعادة الصورة الأصلية.'); rerender(); } }) },
  'gal-add': () => openModal({ title: 'إضافة إلى المعرض', body: galForm(), onOpen: wireImgField, onSubmit: f => { const cap = f.elements.cap.value.trim(); if (!cap) { setErr(f, 'cap', 'العنوان مطلوب.'); return false; } const existing = f.elements.slot.value; if (!existing && !f._img) return 'اختاري صورة موجودة أو ارفعي صورة جديدة.'; if (existing && f._img) return 'اختاري إما صورة موجودة أو رفع صورة جديدة، وليس الاثنين.'; const id = uid(); return commit(() => { let slot = existing; if (!slot) { slot = 'gal_' + id; state.images[slot] = { label: cap, group: 'gallery', src: f._img }; } state.gallery.push({ id, slot, cat: f.elements.cat.value, cap }); }, 'إضافة «' + cap + '» إلى المعرض').then(ok => { if (!ok) return false; toast('تمت الإضافة إلى المعرض.'); rerender(); return true; }); } }),
  'gal-edit': t => { const g = state.gallery.find(x => x.id === t.dataset.id); openModal({ title: 'تعديل عنصر المعرض', body: galForm(g), onSubmit: f => { const cap = f.elements.cap.value.trim(); if (!cap) { setErr(f, 'cap', 'العنوان مطلوب.'); return false; } return commit(() => { g.cap = cap; g.cat = f.elements.cat.value; }, 'تعديل عنصر المعرض «' + cap + '»').then(ok => { if (!ok) return false; toast('تم حفظ عنصر المعرض.'); rerender(); return true; }); } }); },
  'gal-del': t => { const g = state.gallery.find(x => x.id === t.dataset.id); confirmDelete({ title: 'حذف من المعرض', text: `هل تريدين حذف «<b>${esc(g.cap)}</b>» من المعرض؟`, onConfirm: () => { commit(() => { state.gallery = state.gallery.filter(x => x !== g); if (g.slot.startsWith('gal_') && !state.gallery.some(x => x.slot === g.slot)) delete state.images[g.slot]; }, 'حذف «' + g.cap + '» من المعرض').then(ok => { if (ok) { toast('تم الحذف من المعرض.'); rerender(); } }) } }); },

  'content-cancel': () => { rerender(); toast('تم إلغاء التعديلات غير المحفوظة.'); },
  'content-restore': () => { const g = currentArg; confirmDelete({ title: 'استعادة النصوص الأصلية', text: `سيتم إرجاع نصوص «<b>${esc(CGROUPS.find(x => x[0] === g)[1])}</b>» إلى ما كانت عليه في الموقع.`, onConfirm: () => { commit(() => SEED.contentFields.filter(f => f.group === g).forEach(f => state.content[f.key] = SEED.content[f.key]), 'استعادة نصوص «' + CGROUPS.find(x => x[0] === g)[1] + '»').then(ok => { if (ok) { toast('تمت استعادة النصوص الأصلية.'); rerender(); } }) } }); },

  export: () => { const blob = new Blob([JSON.stringify(state, null, 1)], { type: 'application/json' }); const a = document.createElement('a'); a.href = URL.createObjectURL(blob); a.download = 'zumurrud-admin-data-' + new Date().toISOString().slice(0, 10) + '.json'; document.body.appendChild(a); a.click(); a.remove(); setTimeout(() => URL.revokeObjectURL(a.href), 1000); toast('تم تصدير نسخة البيانات.'); },
  import: () => { const inp = $('#importFile'); inp.value = ''; inp.onchange = () => { const f = inp.files[0]; if (!f) return; const r = new FileReader(); r.onload = () => { let d; try { d = JSON.parse(r.result); } catch (e) { return toast('الملف ليس بصيغة JSON صحيحة.', 'err'); } if (!d || d.version !== SEED.version || !Array.isArray(d.services) || !Array.isArray(d.priceCats) || !Array.isArray(d.products) || !d.images || !d.content || !d.contact || !Array.isArray(d.gallery)) return toast('الملف لا يطابق صيغة بيانات اللوحة.', 'err'); importData(d, 'استيراد نسخة بيانات'); }; r.readAsText(f); }; inp.click(); },
  'legacy-import': () => { const d = legacyData(); if (d) importData(d, 'نقل التعديلات القديمة من المتصفح'); },
  'legacy-drop': () => confirmDelete({ title: 'حذف التعديلات القديمة', text: 'سيتم حذف تعديلات النسخة التجريبية المحفوظة في هذا المتصفح فقط. بيانات الخادم لن تتأثر.', onConfirm: () => { try { localStorage.removeItem(LEGACY_KEY); } catch (e) { /* تجاهل */ } toast('تم حذف التعديلات القديمة من المتصفح.'); rerender(); } }),
  reset: () => confirmDelete({ title: 'استعادة البيانات الأصلية', text: 'سيتم إرجاع كل بيانات الموقع إلى البيانات الأصلية المستخرجة منه. يأخذ الخادم نسخة احتياطية من البيانات الحالية قبل الاستعادة.', onConfirm: async () => { const r = await api('POST', '/api/admin/reset', {}); if (!r.ok) return toast(r.data.message || 'تعذّرت الاستعادة.', 'err'); state = r.data.state; rev = r.data.rev; toast('تمت استعادة البيانات الأصلية.'); rerender(); } })
};
document.addEventListener('click', e => { const t = e.target.closest('[data-act]'); if (!t || !actions[t.dataset.act]) return; actions[t.dataset.act](t); });
document.addEventListener('keydown', e => { if (e.key === 'Escape') { closeModal(); setMenu(false); } });

/* ---------------- القائمة الجانبية ---------------- */
function setMenu(open) { $('#side').classList.toggle('open', open); $('#scrim').classList.toggle('on', open); $('#burger').setAttribute('aria-expanded', open); }
$('#burger').addEventListener('click', () => setMenu(!$('#side').classList.contains('open')));
$('#scrim').addEventListener('click', () => setMenu(false));
$$('#nav a').forEach(a => a.addEventListener('click', () => setMenu(false)));
window.addEventListener('hashchange', route);
(async () => {
  $('#view').innerHTML = '<div class="empty">جارٍ تحميل البيانات من الخادم…</div>';
  try { await refreshCsrf(); await loadState(); route(); }
  catch (e) { $('#view').innerHTML = `<div class="empty">${esc(e.message)}<br><button class="btn btn-gold btn-sm" style="margin-top:12px" onclick="location.reload()">إعادة المحاولة</button></div>`; }
})();
})();
