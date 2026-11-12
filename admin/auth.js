/* الخطوة 3: ربط لوحة التحكم بتسجيل الدخول (خروج، تغيير كلمة المرور، انتهاء الجلسة).
   ملف مستقل؛ لا يغيّر app.js ولا تصميم اللوحة (يستخدم أصناف admin.css الموجودة). */
(() => {
  'use strict';
  let csrf = '', idleMs = 30 * 60 * 1000, active = false;
  const toLogin = () => { location.replace('/admin/login'); };

  async function session(check) {
    const r = await fetch('/admin/session' + (check ? '?check=1' : ''), { credentials: 'same-origin', headers: { Accept: 'application/json' } });
    if (r.status === 401) { toLogin(); return null; }
    return r.ok ? r.json() : null;
  }

  function mount(info) {
    const foot = document.querySelector('.side-foot');
    if (!foot) return;
    const who = document.createElement('p');
    who.textContent = 'مسجّلة الدخول: ' + info.username;
    const pw = document.createElement('a');
    pw.className = 'btn btn-line btn-block'; pw.href = '/admin/account'; pw.textContent = 'تغيير كلمة المرور';
    const out = document.createElement('button');
    out.type = 'button'; out.className = 'btn btn-line btn-block'; out.textContent = 'تسجيل الخروج';
    out.addEventListener('click', async () => {
      out.disabled = true;
      try { await fetch('/admin/logout', { method: 'POST', credentials: 'same-origin', headers: { 'X-CSRF-Token': csrf } }); } catch (e) { /* تجاهل */ }
      toLogin();
    });
    foot.prepend(out); foot.prepend(pw); foot.prepend(who);
  }

  ['click', 'keydown', 'input'].forEach(e => document.addEventListener(e, () => { active = true; }, { passive: true }));

  session(false).then(info => {
    if (!info) return;
    csrf = info.csrf_token; idleMs = info.idle_seconds * 1000;
    mount(info);
    // كل 60 ثانية: إن كان هناك نشاط نجدّد الجلسة، وإلا نفحص فقط (دون تمديد) ونحوّل لصفحة الدخول عند الانتهاء
    setInterval(() => { const a = active; active = false; session(!a); }, 60 * 1000);
  });
})();
