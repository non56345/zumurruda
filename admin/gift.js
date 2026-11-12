/* =====================================================
   لوحة تحكم الزُمردة — طلبات بطاقة الإهداء وتجهيز البطاقة
   ملف مستقل يعمل عبر الجسر window.ZUM_ADMIN المُعرَّف في app.js (لا يغيّر أي شاشة أخرى).
   صورة البطاقة الأصلية لا تُعدَّل: تُرسم النصوص فوقها على canvas، وتُحفظ كإحداثيات ونصوص فقط.
   ===================================================== */
(() => {
'use strict';
const A = window.ZUM_ADMIN;
if (!A) return;
const { api, toast, esc, fmtTime, openModal, closeModal } = A;
const $ = (s, r = document) => r.querySelector(s);
const $$ = (s, r = document) => [...r.querySelectorAll(s)];
const CARD_SRC = '/images/zumurruda_gift_card_page_1.png';
const STATUS = { new: 'جديد', preparing: 'قيد التجهيز', ready: 'جاهز', delivered: 'تم التسليم' };
const STATUS_CLS = { new: 'dark', preparing: '', ready: 'green', delivered: 'green' };
const EL_LABEL = { to: 'إلى', from: 'من', gift: 'الهدية', message: 'الرسالة', value: 'القيمة' };
const FONT_LABEL = { 'IBM Plex Sans Arabic': 'IBM Plex (عصري)', 'El Messiri': 'المسيري (زخرفي)', serif: 'نسخ (كلاسيكي)' };
let filter = 'all', token = 0, ed = null;

/* ---------------- صورة البطاقة والخطوط ---------------- */
let cardImg = null;
function loadCard() {
  if (cardImg) return cardImg;
  cardImg = new Promise((res, rej) => { const im = new Image(); im.onload = () => res(im); im.onerror = () => rej(new Error('تعذّر تحميل صورة البطاقة الأصلية.')); im.src = CARD_SRC; });
  return cardImg;
}
const family = f => f === 'serif' ? 'serif' : `"${f}", "IBM Plex Sans Arabic", Tahoma, sans-serif`;
async function loadFonts(card) {
  const used = new Set(Object.values(card).map(e => e.font + '|' + e.weight));
  await Promise.all([...used].map(u => { const [f, w] = u.split('|'); return f === 'serif' ? 0 : document.fonts.load(`${w} 30px "${f}"`, 'أبجد هوز').catch(() => 0); }));
}

/* ---------------- الرسم (نفس الدالة للمعاينة والتصدير) ---------------- */
function wrap(ctx, text, maxW) {
  const lines = [];
  String(text).split('\n').forEach(par => {
    const words = par.split(/\s+/).filter(Boolean); let cur = '';
    if (!words.length) { lines.push(''); return; }
    words.forEach(w => { const t = cur ? cur + ' ' + w : w; if (cur && ctx.measureText(t).width > maxW) { lines.push(cur); cur = w; } else cur = t; });
    lines.push(cur);
  });
  return lines;
}
/* يرسم البطاقة على ctx بعرض W وارتفاع H، ويعيد مستطيلات العناصر (بنسب من W,H) لاختبار النقر */
function draw(ctx, img, card, W, H, { guides = false, selected = null } = {}) {
  ctx.setTransform(1, 0, 0, 1, 0, 0); ctx.clearRect(0, 0, W, H);
  ctx.imageSmoothingEnabled = true; ctx.imageSmoothingQuality = 'high';
  ctx.drawImage(img, 0, 0, W, H);
  const k = W / 1242, boxes = {};
  Object.entries(card).forEach(([name, e]) => {
    const text = (e.text || '').trim();
    if (!e.visible || !text) return;
    const px = e.size * k;
    ctx.font = `${e.weight} ${px}px ${family(e.font)}`;
    ctx.direction = 'rtl'; ctx.textAlign = e.align; ctx.textBaseline = 'alphabetic'; ctx.fillStyle = e.color;
    const lines = wrap(ctx, text, e.width * W), lh = e.lh * px, ax = e.x * W, ay = e.y * H;
    lines.forEach((ln, i) => ctx.fillText(ln, ax, ay + i * lh));
    const w = Math.max(...lines.map(l => ctx.measureText(l).width), 10);
    const left = e.align === 'right' ? ax - w : e.align === 'center' ? ax - w / 2 : ax;
    boxes[name] = { x: left / W, y: (ay - px * 1.0) / H, w: w / W, h: (px * 1.4 + (lines.length - 1) * lh) / H };
  });
  if (guides && selected && boxes[selected]) {
    const b = boxes[selected]; ctx.save(); ctx.setLineDash([6, 4]); ctx.lineWidth = 1.5; ctx.strokeStyle = '#0a6b3a';
    ctx.strokeRect(b.x * W - 5, b.y * H - 3, b.w * W + 10, b.h * H + 6); ctx.restore();
  }
  return boxes;
}

/* ---------------- القائمة ---------------- */
function vGift(arg) {
  token++;
  return /^\d+$/.test(arg || '') ? `<div class="empty">جارٍ تحميل الطلب…</div>` : `<div class="empty">جارٍ تحميل الطلبات…</div>`;
}
async function afterGift() {
  const my = token, arg = A.getArg(), view = $('#view');
  if (/^\d+$/.test(arg || '')) {
    const r = await api('GET', '/api/admin/gift-orders/' + arg);
    if (my !== token || !$('#view')) return;
    if (!r.ok) { view.innerHTML = `<div class="empty">${esc(r.data.message || 'تعذّر تحميل الطلب.')}<br><a class="btn btn-gold btn-sm" style="margin-top:12px" href="#/gift">العودة إلى الطلبات</a></div>`; return; }
    try { await renderEditor(view, r.data, my); } catch (e) { if (my === token) view.innerHTML = `<div class="empty">${esc(e.message)}</div>`; }
  } else {
    const r = await api('GET', '/api/admin/gift-orders');
    if (my !== token || !$('#view')) return;
    if (!r.ok) { view.innerHTML = `<div class="empty">${esc(r.data.message || 'تعذّر تحميل الطلبات.')}</div>`; return; }
    renderList(view, r.data);
    setBadge(r.data.counts.new);
  }
}
function setBadge(n) { const b = $('#giftBadge'); if (b) { b.textContent = n; b.hidden = !n; } }
function renderList(view, { orders, counts }) {
  const total = orders.length;
  const chip = (k, l, n) => `<button class="chip${filter === k ? ' on' : ''}" data-gfilter="${k}">${l} <span class="gc-n">${n}</span></button>`;
  const shown = orders.filter(o => filter === 'all' || o.status === filter);
  const row = o => `<article class="card gc-row" data-gopen="${o.id}">
    <div class="gc-id">#${o.id}</div>
    <div class="gc-main"><b>إلى ${esc(o.to)} <span class="muted">— من ${esc(o.from)}</span></b><span>${esc(o.gift)}</span>${o.message ? `<small class="muted">«${esc(o.message)}»</small>` : ''}</div>
    <div class="gc-meta"><span dir="ltr">${esc(o.phone)}</span><time>${fmtTime(o.created_at)}</time></div>
    <div class="gc-st"><span class="badge ${STATUS_CLS[o.status]}">${STATUS[o.status]}</span>${o.prepared ? '<span class="badge green">مُجهّزة</span>' : ''}</div>
    <a class="btn btn-gold btn-sm" href="#/gift/${o.id}">فتح وتجهيز</a></article>`;
  view.innerHTML = `<div class="page-head"><div><h2>طلبات بطاقة الإهداء</h2><p>الطلبات الواردة من قسم الإهداء في الموقع. افتحي الطلب لرؤية بيانات الزبونة وتجهيز البطاقة وتحميلها للطباعة.</p></div>
    <div class="actions"><button class="btn btn-ghost btn-sm" data-gact="refresh">تحديث</button></div></div>
    <div class="chips" role="tablist">${chip('all', 'الكل', total)}${Object.keys(STATUS).map(s => chip(s, STATUS[s], counts[s] || 0)).join('')}</div>
    ${shown.length ? `<div class="gc-list">${shown.map(row).join('')}</div>` : `<div class="empty">${total ? 'لا توجد طلبات بهذه الحالة.' : 'لا توجد طلبات بعد. ستظهر هنا فور أن ترسل إحدى الزبونات طلبًا من الموقع.'}</div>`}`;
}

/* ---------------- المحرّر ---------------- */
async function renderEditor(view, data, my) {
  const img = await loadCard();
  if (my !== token) return;
  const o = data.order;
  ed = { id: o.id, order: o, card: JSON.parse(JSON.stringify(o.card)), defaults: data.default_layout, sel: 'to', dirty: false, preview: false, img, boxes: {}, drag: null };
  await loadFonts(ed.card);
  if (my !== token) return;
  view.innerHTML = `
  <div class="page-head"><div><h2>طلب بطاقة #${o.id}</h2><p><a href="#/gift">← العودة إلى الطلبات</a></p></div>
    <div class="actions"><label class="gc-statuslbl">الحالة
      <select id="gcStatus">${Object.entries(STATUS).map(([k, l]) => `<option value="${k}"${k === o.status ? ' selected' : ''}>${l}</option>`).join('')}</select></label>
      <button class="btn btn-ghost btn-sm" data-gact="save-status">حفظ الحالة</button></div></div>
  <section class="card card-b gc-info"><h3 class="sec-title" style="margin-top:0">بيانات الطلب</h3>
    <dl>
      <div><dt>إلى</dt><dd>${esc(o.to)}</dd></div><div><dt>من</dt><dd>${esc(o.from)}</dd></div>
      <div><dt>الهدية</dt><dd>${esc(o.gift)}</dd></div><div><dt>هاتف الزبونة</dt><dd dir="ltr" style="text-align:right"><a href="tel:${esc(o.phone.replace(/[^\d+]/g, ''))}">${esc(o.phone)}</a></dd></div>
      <div class="wide"><dt>الرسالة</dt><dd>${o.message ? esc(o.message) : '<span class="muted">لم تكتب رسالة</span>'}</dd></div>
      <div><dt>وقت الطلب</dt><dd>${fmtTime(o.created_at)}</dd></div>${o.prepared ? `<div><dt>آخر تجهيز محفوظ</dt><dd>${fmtTime(o.updated_at)}</dd></div>` : ''}
    </dl></section>
  <div class="gc-editor">
    <section class="card card-b gc-stage"><div class="gc-stagebar"><h3 class="sec-title" style="margin:0">تجهيز البطاقة</h3><span id="gcDirty" class="badge" hidden>تعديلات غير محفوظة</span></div>
      <p class="small muted">اسحبي أي نص بالفأرة أو الإصبع لتحريكه، أو اضغطي عليه ثم استخدمي أسهم لوحة المفاتيح (Shift للحركة الأكبر). صورة البطاقة الأصلية لا تتغيّر.</p>
      <div class="gc-canvaswrap"><canvas id="gcCanvas" tabindex="0" role="img" aria-label="معاينة البطاقة"></canvas></div>
      <div class="actions gc-bar">
        <button class="btn btn-primary" data-gact="save-card">حفظ التجهيز</button>
        <button class="btn btn-ghost" data-gact="preview">معاينة البطاقة</button>
        <span class="gc-dl"><select id="gcScale" aria-label="جودة الصورة"><option value="2">جودة طباعة (2×)</option><option value="3">أعلى جودة (3×)</option></select>
        <button class="btn btn-gold" data-gact="download">تحميل البطاقة PNG</button></span>
      </div></section>
    <aside class="card card-b gc-panel" id="gcPanel"></aside>
  </div>`;
  ed.canvas = $('#gcCanvas'); ed.ctx = ed.canvas.getContext('2d');
  wireCanvas(); renderPanel(); redraw();
  if (window.ResizeObserver) { ed.ro = new ResizeObserver(() => redraw()); ed.ro.observe($('.gc-canvaswrap')); }
}
function markDirty(v = true) { if (!ed) return; ed.dirty = v; const b = $('#gcDirty'); if (b) b.hidden = !v; }
function redraw() {
  if (!ed || !ed.canvas.isConnected) return;
  const wrapW = $('.gc-canvaswrap').clientWidth || 600, dpr = window.devicePixelRatio || 1;
  const W = Math.round(wrapW * dpr), H = Math.round(W * ed.img.naturalHeight / ed.img.naturalWidth);
  if (ed.canvas.width !== W || ed.canvas.height !== H) { ed.canvas.width = W; ed.canvas.height = H; }
  ed.canvas.style.height = (wrapW * ed.img.naturalHeight / ed.img.naturalWidth) + 'px';
  ed.boxes = draw(ed.ctx, ed.img, ed.card, W, H, { guides: !ed.preview, selected: ed.sel });
}
function wireCanvas() {
  const c = ed.canvas, pos = e => { const r = c.getBoundingClientRect(); return [(e.clientX - r.left) / r.width, (e.clientY - r.top) / r.height]; };
  c.addEventListener('pointerdown', e => {
    if (ed.preview) return;
    const [fx, fy] = pos(e); const hit = Object.entries(ed.boxes).reverse().find(([, b]) => fx >= b.x - 0.01 && fx <= b.x + b.w + 0.01 && fy >= b.y - 0.01 && fy <= b.y + b.h + 0.01);
    if (!hit) return;
    ed.sel = hit[0]; const el = ed.card[ed.sel]; ed.drag = { dx: el.x - fx, dy: el.y - fy };
    c.setPointerCapture(e.pointerId); c.focus(); renderPanel(); redraw(); e.preventDefault();
  });
  c.addEventListener('pointermove', e => {
    if (!ed.drag) return; const [fx, fy] = pos(e), el = ed.card[ed.sel];
    el.x = Math.min(1, Math.max(0, fx + ed.drag.dx)); el.y = Math.min(1, Math.max(0, fy + ed.drag.dy));
    markDirty(); syncPos(); redraw();
  });
  const end = () => { ed.drag = null; };
  c.addEventListener('pointerup', end); c.addEventListener('pointercancel', end);
  c.addEventListener('keydown', e => {
    const step = (e.shiftKey ? 0.01 : 0.002), el = ed.card[ed.sel]; let used = true;
    if (e.key === 'ArrowLeft') el.x -= step; else if (e.key === 'ArrowRight') el.x += step; else if (e.key === 'ArrowUp') el.y -= step; else if (e.key === 'ArrowDown') el.y += step; else used = false;
    if (used) { e.preventDefault(); el.x = Math.min(1, Math.max(0, el.x)); el.y = Math.min(1, Math.max(0, el.y)); markDirty(); syncPos(); redraw(); }
  });
}
const pct = v => Math.round(v * 1000) / 10;
function syncPos() { const el = ed.card[ed.sel], x = $('#gcX'), y = $('#gcY'); if (x) x.value = pct(el.x); if (y) y.value = pct(el.y); }
function renderPanel() {
  const el = ed.card[ed.sel], tabs = Object.keys(EL_LABEL).map(k => `<button class="chip${k === ed.sel ? ' on' : ''}" data-gsel="${k}">${EL_LABEL[k]}</button>`).join('');
  const num = (id, label, v, min, max, step) => `<label class="gc-f"><span>${label}</span><input type="number" id="${id}" value="${v}" min="${min}" max="${max}" step="${step}" inputmode="decimal"></label>`;
  $('#gcPanel').innerHTML = `<h3 class="sec-title" style="margin-top:0">عناصر الكتابة</h3><div class="chips gc-tabs">${tabs}</div>
    <label class="gc-f"><span>النص على البطاقة (${EL_LABEL[ed.sel]})</span>${ed.sel === 'message' ? `<textarea id="gcText" rows="3" maxlength="300">${esc(el.text)}</textarea>` : `<input type="text" id="gcText" maxlength="300" value="${esc(el.text)}">`}</label>
    <label class="check gc-vis"><input type="checkbox" id="gcVis"${el.visible ? ' checked' : ''}> إظهار هذا العنصر على البطاقة</label>
    <div class="gc-grid">${num('gcX', 'الموضع الأفقي %', pct(el.x), 0, 100, 0.1)}${num('gcY', 'الموضع الرأسي %', pct(el.y), 0, 100, 0.1)}
      ${num('gcSize', 'حجم الخط', el.size, 8, 160, 1)}${num('gcWidth', 'عرض السطر %', pct(el.width), 5, 120, 1)}${num('gcLh', 'ارتفاع السطر', el.lh, 1, 3.5, 0.05)}
      <label class="gc-f"><span>المحاذاة</span><select id="gcAlign">${[['right', 'يمين'], ['center', 'وسط'], ['left', 'يسار']].map(([v, l]) => `<option value="${v}"${v === el.align ? ' selected' : ''}>${l}</option>`).join('')}</select></label>
      <label class="gc-f"><span>الخط</span><select id="gcFont">${Object.entries(FONT_LABEL).map(([v, l]) => `<option value="${v}"${v === el.font ? ' selected' : ''}>${l}</option>`).join('')}</select></label>
      <label class="gc-f"><span>السُّمك</span><select id="gcWeight">${[400, 500, 600, 700].map(v => `<option value="${v}"${v === el.weight ? ' selected' : ''}>${v}</option>`).join('')}</select></label>
      <label class="gc-f"><span>اللون</span><input type="color" id="gcColor" value="${esc(el.color)}"></label></div>
    <input type="range" id="gcSizeR" min="8" max="100" value="${Math.min(100, el.size)}" aria-label="حجم الخط">
    <div class="actions gc-tools"><button class="btn btn-ghost btn-sm" data-gact="layout-default">حفظ المواضع كإعداد افتراضي لكل البطاقات</button>
      <button class="btn btn-ghost btn-sm" data-gact="reset-card">إعادة التجهيز من بيانات الطلب</button></div>`;
  const upd = (fn) => ev => { fn(ev.target); markDirty(); redraw(); };
  const set = (id, fn, evt = 'input') => $(id).addEventListener(evt, upd(fn));
  set('#gcText', t => el.text = t.value); set('#gcVis', t => el.visible = t.checked, 'change');
  set('#gcX', t => el.x = Math.min(1, Math.max(0, (+t.value || 0) / 100))); set('#gcY', t => el.y = Math.min(1, Math.max(0, (+t.value || 0) / 100)));
  set('#gcSize', t => { el.size = Math.min(160, Math.max(8, +t.value || 8)); $('#gcSizeR').value = Math.min(100, el.size); });
  set('#gcSizeR', t => { el.size = +t.value; $('#gcSize').value = el.size; });
  set('#gcWidth', t => el.width = Math.min(1.2, Math.max(0.05, (+t.value || 5) / 100)));
  set('#gcLh', t => el.lh = Math.min(3.5, Math.max(1, +t.value || 1)));
  set('#gcAlign', t => el.align = t.value, 'change'); set('#gcColor', t => el.color = t.value);
  set('#gcWeight', t => el.weight = +t.value, 'change');
  $('#gcFont').addEventListener('change', async ev => { el.font = ev.target.value; markDirty(); await loadFonts(ed.card); redraw(); });
}
function cardPayload() { const o = {}; Object.entries(ed.card).forEach(([k, e]) => o[k] = { text: e.text, x: e.x, y: e.y, size: e.size, align: e.align, color: e.color, font: e.font, weight: e.weight, width: e.width, lh: e.lh, visible: e.visible }); return o; }

/* ---------------- التصدير والمعاينة ---------------- */
async function renderBlob(scale) {
  await loadFonts(ed.card);
  const W = Math.round(ed.img.naturalWidth * scale), H = Math.round(ed.img.naturalHeight * scale);
  const cv = document.createElement('canvas'); cv.width = W; cv.height = H;
  draw(cv.getContext('2d'), ed.img, ed.card, W, H, { guides: false });
  const blob = await new Promise(res => cv.toBlob(res, 'image/png'));
  if (!blob) throw new Error('تعذّر إنشاء الصورة. جرّبي جودة أقل.');
  return { blob, W, H };
}
function download(blob, name) { const a = document.createElement('a'); a.href = URL.createObjectURL(blob); a.download = name; document.body.appendChild(a); a.click(); a.remove(); setTimeout(() => URL.revokeObjectURL(a.href), 4000); }

const gactions = {
  refresh: () => rerenderGift(),
  'save-status': async () => {
    const r = await api('PUT', '/api/admin/gift-orders/' + ed.id, { status: $('#gcStatus').value });
    if (!r.ok) return toast(r.data.message || 'تعذّر حفظ الحالة.', 'err');
    ed.order = r.data.order; toast('تم حفظ حالة الطلب.');
  },
  'save-card': async () => {
    const r = await api('PUT', '/api/admin/gift-orders/' + ed.id, { card: cardPayload() });
    if (!r.ok) return toast(r.data.message || 'تعذّر حفظ التجهيز.', 'err');
    ed.order = r.data.order; $('#gcStatus').value = r.data.order.status; markDirty(false); toast('تم حفظ تجهيز البطاقة.');
  },
  preview: async () => {
    try {
      const { blob, W, H } = await renderBlob(1.5), url = URL.createObjectURL(blob);
      openModal({ title: 'معاينة البطاقة النهائية', hideSubmit: true, body: `<img class="gc-prev" src="${url}" alt="معاينة البطاقة النهائية" width="${W}" height="${H}"><p class="small muted" style="margin-top:8px">هذه هي البطاقة كما ستُطبع، بدون خطوط التحديد.</p>` });
      const m = $('.modal'); const obs = new MutationObserver(() => { if (!m.isConnected) { URL.revokeObjectURL(url); obs.disconnect(); } }); obs.observe(document.body, { childList: true, subtree: true });
    } catch (e) { toast(e.message, 'err'); }
  },
  download: async () => {
    try {
      toast('جارٍ تجهيز الصورة…'); const s = +$('#gcScale').value || 2, { blob, W, H } = await renderBlob(s);
      download(blob, `zumurruda-gift-card-${ed.id}.png`); toast(`تم تحميل البطاقة (${W}×${H} بكسل).`);
    } catch (e) { toast(e.message, 'err'); }
  },
  'layout-default': () => openModal({ title: 'حفظ المواضع كإعداد افتراضي', submitLabel: 'نعم، احفظ',
    body: '<p>ستُستخدم مواضع وأحجام وألوان الكتابة الحالية كبداية لكل بطاقة جديدة. لا يتغيّر تجهيز الطلبات المحفوظة سابقًا ولا نصوصها.</p>',
    onSubmit: async () => {
      const layout = {}; Object.entries(cardPayload()).forEach(([k, e]) => { const { text, ...g } = e; layout[k] = g; });
      const r = await api('PUT', '/api/admin/gift-card-layout', { layout }); if (!r.ok) return r.data.message || 'تعذّر الحفظ.';
      ed.defaults = r.data.layout; toast('تم حفظ المواضع كإعداد افتراضي.'); return true;
    } }),
  'reset-card': () => openModal({ title: 'إعادة التجهيز', submitLabel: 'نعم، أعيدي', danger: true,
    body: '<p>ستُعاد النصوص إلى ما كتبته الزبونة، والمواضع إلى الإعداد الافتراضي. لن يُحفظ ذلك إلا عند الضغط على «حفظ التجهيز».</p>',
    onSubmit: () => {
      const o = ed.order, t = { to: o.to, from: o.from, gift: o.gift, message: o.message, value: '' };
      Object.keys(ed.card).forEach(k => ed.card[k] = { text: t[k], ...JSON.parse(JSON.stringify(ed.defaults[k])) });
      markDirty(); renderPanel(); redraw(); return true;
    } })
};
function rerenderGift() { if (A.getRoute() === 'gift') A.rerender(); }
document.addEventListener('click', e => {
  const t = e.target.closest('[data-gact],[data-gsel],[data-gfilter],[data-gopen]'); if (!t) return;
  if (t.dataset.gact && gactions[t.dataset.gact]) { gactions[t.dataset.gact](t); return; }
  if (t.dataset.gsel && ed) { ed.sel = t.dataset.gsel; renderPanel(); redraw(); return; }
  if (t.dataset.gfilter) { filter = t.dataset.gfilter; rerenderGift(); return; }
  if (t.dataset.gopen && !e.target.closest('a,button')) location.hash = '#/gift/' + t.dataset.gopen;
});
/* في وضع المعاينة داخل المحرّر: لا شيء إضافي؛ نافذة المعاينة تعرض الصورة النهائية */
window.addEventListener('beforeunload', e => { if (ed && ed.dirty && A.getRoute() === 'gift') { e.preventDefault(); e.returnValue = ''; } });
window.addEventListener('hashchange', () => { if (ed && ed.ro) { ed.ro.disconnect(); } ed = A.getRoute() === 'gift' ? ed : null; });

A.ROUTES.gift = { title: 'طلبات بطاقة الإهداء', view: vGift, after: afterGift };
/* عدّاد الطلبات الجديدة بجانب عنوان القائمة */
(async () => { try { const r = await api('GET', '/api/admin/gift-orders'); if (r.ok) setBadge(r.data.counts.new); } catch (e) { /* تجاهل */ } })();
})();
