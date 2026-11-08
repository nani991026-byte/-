import os, sqlite3, hashlib, hmac, json, time, urllib.parse, io
from aiohttp import web, ClientSession, ClientTimeout
from telegram import Bot

TOKEN = os.getenv('BOT_TOKEN') or os.getenv('MONNEY_TOKEN')
DATA_DIR = os.getenv('DATA_DIR', '/app/data')
DB = os.path.join(DATA_DIR, 'monney.db')
PORT = int(os.getenv('PORT', '3000'))
HTML = '<!doctype html>\n<html lang="ru">\n<head>\n  <meta charset="utf-8" />\n  <meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover" />\n  <meta name="theme-color" content="#0e1721" />\n  <title>MONNEY</title>\n  <link rel="stylesheet" href="/assets/style.css" />\n  <script src="https://telegram.org/js/telegram-web-app.js"></script>\n</head>\n<body>\n<div id="app" class="app">\n  <header class="topbar">\n    <div class="brand"><div class="logo">M</div><div><b>MONNEY</b><span>личное хранилище</span></div></div>\n    <button class="icon-btn" id="refresh">↻</button>\n  </header>\n\n  <main id="main" class="main"></main>\n\n  <nav class="bottom-nav">\n    <button data-nav="home" class="active"><span>⌂</span><small>Главная</small></button>\n    <button data-nav="gallery"><span>▦</span><small>Галерея</small></button>\n    <button data-nav="hidden"><span>🔒</span><small>Скрытое</small></button>\n    <button data-nav="trash"><span>♻</span><small>Корзина</small></button>\n  </nav>\n</div>\n\n<div id="toast" class="toast"></div>\n<div id="modal" class="modal hidden"></div>\n<script src="/assets/app.js"></script>\n</body>\n</html>\n'
CSS = ':root{--bg:#0e1721;--card:#162433;--card2:#1c2d3e;--text:#f3f6f8;--muted:#91a2b4;--accent:#5b8def;--danger:#ff5b68;--ok:#38c98b;--radius:22px}*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--text);font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,Arial,sans-serif;-webkit-font-smoothing:antialiased}.app{min-height:100vh;padding-bottom:86px}.topbar{position:sticky;top:0;z-index:5;display:flex;align-items:center;justify-content:space-between;padding:calc(12px + env(safe-area-inset-top)) 18px 12px;background:rgba(14,23,33,.93);backdrop-filter:blur(18px);border-bottom:1px solid rgba(255,255,255,.06)}.brand{display:flex;gap:11px;align-items:center}.logo{width:42px;height:42px;border-radius:14px;display:grid;place-items:center;font-weight:800;font-size:21px;background:linear-gradient(135deg,#6f8df5,#8d6ff0);box-shadow:0 8px 24px rgba(91,141,239,.25)}.brand b{display:block;font-size:16px;letter-spacing:.4px}.brand span{display:block;color:var(--muted);font-size:11px;margin-top:2px}.icon-btn{border:0;background:var(--card);color:var(--text);width:40px;height:40px;border-radius:14px;font-size:22px}.main{padding:18px}.hero{background:linear-gradient(135deg,#182b3f,#13202e);border:1px solid rgba(255,255,255,.07);border-radius:28px;padding:22px;margin-bottom:16px;box-shadow:0 14px 45px rgba(0,0,0,.2)}.hero .hello{font-size:14px;color:var(--muted)}.hero h1{margin:6px 0 8px;font-size:28px}.hero p{margin:0;color:#b5c1cc;line-height:1.45}.add{width:100%;border:0;border-radius:18px;padding:17px;font-size:16px;font-weight:800;color:#fff;background:linear-gradient(135deg,#5b8def,#7c6ff0);box-shadow:0 12px 28px rgba(91,141,239,.25);margin:14px 0}.stats{display:grid;grid-template-columns:repeat(3,1fr);gap:10px;margin-bottom:18px}.stat{background:var(--card);border:1px solid rgba(255,255,255,.05);border-radius:18px;padding:14px}.stat b{font-size:22px;display:block}.stat span{font-size:11px;color:var(--muted)}.grid{display:grid;grid-template-columns:1fr 1fr;gap:11px}.tile{border:0;background:var(--card);color:var(--text);border-radius:20px;padding:18px 13px;text-align:left;min-height:96px;border:1px solid rgba(255,255,255,.05)}.tile .emoji{font-size:25px;display:block;margin-bottom:10px}.tile b{display:block;font-size:14px}.tile span{display:block;color:var(--muted);font-size:11px;margin-top:4px}.section-title{display:flex;justify-content:space-between;align-items:end;margin:8px 0 14px}.section-title h2{font-size:22px;margin:0}.section-title span{color:var(--muted);font-size:12px}.gallery{display:grid;grid-template-columns:repeat(3,1fr);gap:4px}.media-card{position:relative;aspect-ratio:1/1;background:#172638;overflow:hidden;border-radius:10px}.media-card img,.media-card video{width:100%;height:100%;object-fit:cover;display:block}.media-card .badge{position:absolute;right:7px;top:7px;background:rgba(0,0,0,.58);border-radius:10px;padding:4px 6px;font-size:11px}.empty{padding:42px 20px;text-align:center;color:var(--muted);background:var(--card);border-radius:22px}.empty .big{font-size:42px;margin-bottom:10px}.row{display:flex;gap:10px}.row>*{flex:1}.back{background:transparent;border:0;color:var(--accent);font-size:14px;padding:0 0 15px}.list{display:flex;flex-direction:column;gap:10px}.list-item{background:var(--card);border:1px solid rgba(255,255,255,.05);border-radius:18px;padding:15px;display:flex;justify-content:space-between;gap:12px;align-items:center}.list-item b{font-size:14px}.list-item span{display:block;color:var(--muted);font-size:11px;margin-top:4px}.mini-actions{display:flex;gap:7px}.mini-actions button{border:0;background:var(--card2);color:var(--text);border-radius:12px;padding:9px;font-size:15px}.danger{color:#ff8990!important}.form{background:var(--card);border-radius:22px;padding:16px}.input,.textarea{width:100%;border:1px solid rgba(255,255,255,.1);background:#0f1b27;color:var(--text);border-radius:15px;padding:13px;font-size:15px;outline:0}.textarea{min-height:120px;resize:vertical}.primary{border:0;background:var(--accent);color:#fff;border-radius:15px;padding:13px 16px;font-weight:800}.secondary{border:0;background:var(--card2);color:var(--text);border-radius:15px;padding:13px 16px;font-weight:700}.bottom-nav{position:fixed;bottom:0;left:0;right:0;z-index:10;display:grid;grid-template-columns:repeat(4,1fr);padding:9px 8px calc(9px + env(safe-area-inset-bottom));background:rgba(14,23,33,.96);backdrop-filter:blur(18px);border-top:1px solid rgba(255,255,255,.07)}.bottom-nav button{border:0;background:transparent;color:var(--muted);padding:7px 2px;border-radius:14px}.bottom-nav button.active{color:#fff;background:rgba(91,141,239,.13)}.bottom-nav span{display:block;font-size:21px;line-height:22px}.bottom-nav small{font-size:10px}.toast{position:fixed;left:50%;bottom:95px;transform:translateX(-50%) translateY(20px);background:#f3f6f8;color:#0e1721;padding:11px 16px;border-radius:15px;font-size:13px;font-weight:700;opacity:0;pointer-events:none;transition:.25s;z-index:20;white-space:nowrap}.toast.show{opacity:1;transform:translateX(-50%) translateY(0)}.modal{position:fixed;inset:0;background:rgba(0,0,0,.65);display:flex;align-items:flex-end;z-index:30}.modal.hidden{display:none}.sheet{width:100%;background:#152535;border-radius:28px 28px 0 0;padding:22px 18px calc(24px + env(safe-area-inset-bottom));border-top:1px solid rgba(255,255,255,.08)}.sheet h3{margin:0 0 8px;font-size:20px}.sheet p{color:var(--muted);line-height:1.45}.sheet .actions{display:grid;gap:9px;margin-top:15px}.sheet button{border:0;border-radius:15px;padding:14px;font-weight:800;font-size:14px;background:var(--card2);color:var(--text)}.sheet .red{background:rgba(255,91,104,.15);color:#ff9aa1}.loading{text-align:center;padding:45px;color:var(--muted)}@media(min-width:600px){.main{max-width:620px;margin:auto}.gallery{grid-template-columns:repeat(4,1fr)}.bottom-nav{left:50%;right:auto;width:620px;transform:translateX(-50%);border-radius:22px 22px 0 0}}\n'
JS = 'const tg=window.Telegram?.WebApp; if(tg){tg.ready();tg.expand();tg.setHeaderColor(\'#0e1721\');tg.setBackgroundColor(\'#0e1721\')}\nconst state={user:null,section:\'home\'};const $=s=>document.querySelector(s);const api=async(path,opt={})=>{opt.headers={...(opt.headers||{}),\'X-Telegram-Init-Data\':tg?.initData||\'\'};const r=await fetch(path,opt);if(!r.ok){let t=await r.text();throw new Error(t||\'Ошибка сервера\')}return r.json()};\nfunction toast(t){const e=$(\'#toast\');e.textContent=t;e.classList.add(\'show\');setTimeout(()=>e.classList.remove(\'show\'),2200)}\nfunction modal(html){$(\'#modal\').innerHTML=`<div class="sheet">${html}</div>`;$(\'#modal\').classList.remove(\'hidden\')};function closeModal(){$(\'#modal\').classList.add(\'hidden\')};$(\'#modal\').addEventListener(\'click\',e=>{if(e.target.id===\'modal\')closeModal()});\nasync function init(){try{const a=await api(\'/api/auth\');state.user=a.user;await home()}catch(e){$(\'#main\').innerHTML=`<div class="empty"><div class="big">⚠️</div><b>MONNEY не смог открыть приложение</b><p>${e.message}</p></div>`}}\nfunction navActive(s){document.querySelectorAll(\'.bottom-nav button\').forEach(b=>b.classList.toggle(\'active\',b.dataset.nav===s));state.section=s}\nasync function home(){navActive(\'home\');$(\'#main\').innerHTML=\'<div class="loading">Загружаем MONNEY…</div>\';const s=await api(\'/api/stats\');const name=state.user?.first_name||\'друг\';$(\'#main\').innerHTML=`<section class="hero"><div class="hello">Привет, ${escapeHtml(name)} 👋</div><h1>Твоё хранилище</h1><p>Фото, видео, файлы, тексты и личные материалы — всё в одном месте.</p><button class="add" onclick="openAdd()">＋ Добавить файл</button></section><div class="stats"><div class="stat"><b>${s.photos}</b><span>Фото</span></div><div class="stat"><b>${s.videos}</b><span>Видео</span></div><div class="stat"><b>${s.total}</b><span>Всего</span></div></div><div class="grid"><button class="tile" onclick="gallery()"><span class="emoji">🖼</span><b>Галерея</b><span>Все обычные файлы</span></button><button class="tile" onclick="hiddenPage()"><span class="emoji">🔒</span><b>Скрытое</b><span>${s.hidden} защищённых</span></button><button class="tile" onclick="foldersPage()"><span class="emoji">📁</span><b>Папки</b><span>${s.folders} папок</span></button><button class="tile" onclick="trashPage()"><span class="emoji">🗑</span><b>Корзина</b><span>${s.trash} удалённых</span></button><button class="tile" onclick="openText()"><span class="emoji">📝</span><b>Текст / ссылка</b><span>Сохранить заметку</span></button><button class="tile" onclick="settings()"><span class="emoji">⚙️</span><b>Настройки</b><span>PIN и безопасность</span></button></div>`}\nfunction escapeHtml(s){return String(s).replace(/[&<>\'"]/g,c=>({\'&\':\'&amp;\',\'<\':\'&lt;\',\'>\':\'&gt;\',"\'":\'&#39;\',\'"\':\'&quot;\'}[c]))}\nfunction openAdd(){modal(`<h3>＋ Добавить</h3><p>Выбери, что хочешь сохранить.</p><div class="actions"><button onclick="uploadPicker(false)">📸 Фото / видео / файл</button><button onclick="uploadPicker(true)">🔒 Скрытый файл</button><button onclick="openText()">📝 Текст или ссылка</button><button onclick="closeModal()">Отмена</button></div>`)}\nfunction uploadPicker(hidden){closeModal();const i=document.createElement(\'input\');i.type=\'file\';i.accept=\'image/*,video/*,.pdf,.zip,.doc,.docx,.txt\';i.onchange=async()=>{if(!i.files[0])return;const f=i.files[0];toast(\'Загружаем…\');const fd=new FormData();fd.append(\'file\',f);fd.append(\'hidden\',hidden?\'1\':\'0\');try{await api(\'/api/upload\',{method:\'POST\',body:fd});toast(hidden?\'🔒 Сохранено в скрытое\':\'✅ Файл сохранён\');await home()}catch(e){toast(\'Ошибка загрузки\');console.error(e)}};i.click()}\nasync function gallery(){navActive(\'gallery\');await listPage(\'gallery\',\'🖼 Галерея\',\'Обычные файлы\')}\nasync function hiddenPage(){modal(`<h3>🔒 Скрытое хранилище</h3><p>Для входа нужен PIN.</p><input id="pin" class="input" inputmode="numeric" maxlength="6" placeholder="Введите PIN"><div class="actions"><button class="primary" onclick="unlockHidden()">Открыть</button><button onclick="closeModal()">Отмена</button></div>`)}\nasync function unlockHidden(){const p=$(\'#pin\').value;try{const r=await api(\'/api/pin/check\',{method:\'POST\',headers:{\'Content-Type\':\'application/json\'},body:JSON.stringify({pin:p})});if(!r.ok){toast(\'Неверный PIN\');return}closeModal();navActive(\'hidden\');await listPage(\'hidden\',\'🔒 Скрытые файлы\',\'Только после PIN\')}catch(e){toast(\'Ошибка\')}}\nasync function trashPage(){navActive(\'trash\');await listPage(\'trash\',\'🗑 Корзина\',\'Файлы, которые можно восстановить\')}\nasync function listPage(section,title,sub){$(\'#main\').innerHTML=\'<div class="loading">Загружаем…</div>\';const r=await api(\'/api/files?section=\'+section);if(!r.files.length){$(\'#main\').innerHTML=`<button class="back" onclick="home()">← Назад</button><div class="section-title"><h2>${title}</h2></div><div class="empty"><div class="big">${section===\'trash\'?\'🗑\':\'📭\'}</div><b>Здесь пока пусто</b><p>${sub}</p></div>`;return}let cards=\'\';for(const f of r.files){if(f.kind===\'photo\')cards+=`<div class="media-card" onclick="fileMenu(${f.id},\'photo\')"><img loading="lazy" src="${f.url}"/><span class="badge">📸</span></div>`;else if(f.kind===\'video\')cards+=`<div class="media-card" onclick="fileMenu(${f.id},\'video\')"><video preload="metadata" src="${f.url}"></video><span class="badge">🎥</span></div>`;else cards+=`<div class="list-item" onclick="fileMenu(${f.id},\'text\')"><div><b>📝 ${escapeHtml((f.text||\'Файл\').slice(0,50))}</b><span>#${f.id}</span></div><div>›</div></div>`}$(\'#main\').innerHTML=`<button class="back" onclick="home()">← Назад</button><div class="section-title"><h2>${title}</h2><span>${r.files.length} шт.</span></div>${section===\'gallery\'||section===\'hidden\'?`<div class="gallery">${cards}</div>`:`<div class="list">${cards}</div>`}`}\nasync function fileMenu(id,kind){const isTrash=state.section===\'trash\';let actions=\'\';if(isTrash)actions=`<button onclick="fileAction(${id},\'restore\')">♻️ Восстановить</button><button class="red" onclick="confirmAction(${id},\'purge\',\'Удалить навсегда?\')">🗑 Удалить навсегда</button>`;else actions=`<button onclick="fileAction(${id},\'hide\')">🔒 Скрыть</button><button onclick="moveFile(${id})">📁 Переместить в папку</button><button class="red" onclick="confirmAction(${id},\'delete\',\'Переместить в корзину?\')">🗑 Удалить</button>`;modal(`<h3>${kind===\'photo\'?\'📸 Фото\':kind===\'video\'?\'🎥 Видео\':\'📝 Текст\'}</h3><p>Файл #${id}</p><div class="actions">${actions}<button onclick="closeModal()">Закрыть</button></div>`)}\nfunction confirmAction(id,action,title){modal(`<h3>⚠️ ${title}</h3><p>${action===\'delete\'?\'Файл будет перемещён в корзину и его можно будет восстановить.\':\'Это действие нельзя отменить.\'}</p><div class="actions"><button class="red" onclick="fileAction(${id},\'${action}\')">Подтвердить</button><button onclick="closeModal()">Отмена</button></div>`)}\nasync function fileAction(id,action){try{await api(`/api/file/${id}/${action}`,{method:\'POST\'});closeModal();toast(action===\'delete\'?\'🗑 Перемещено в корзину\':action===\'restore\'?\'♻️ Восстановлено\':\'Готово\');if(state.section===\'hidden\')await hiddenPage();else await listPage(state.section,state.section===\'trash\'?\'🗑 Корзина\':state.section===\'gallery\'?\'🖼 Галерея\':\'🔒 Скрытые файлы\',\'\')}catch(e){toast(\'Ошибка\')}}\nasync function moveFile(id){const f=await api(\'/api/folders\');if(!f.folders.length){toast(\'Сначала создай папку\');return}modal(`<h3>📁 Переместить</h3><div class="actions">${f.folders.map(x=>`<button onclick="doMove(${id},${x.id})">📁 ${escapeHtml(x.name)}</button>`).join(\'\')}<button onclick="closeModal()">Отмена</button></div>`)}async function doMove(id,folder){await api(`/api/file/${id}/move`,{method:\'POST\',headers:{\'Content-Type\':\'application/json\'},body:JSON.stringify({folder_id:folder})});closeModal();toast(\'📁 Перемещено\')}\nasync function foldersPage(){const r=await api(\'/api/folders\');modal(`<h3>📁 Папки</h3><div class="actions">${r.folders.map(f=>`<button>📁 ${escapeHtml(f.name)}</button>`).join(\'\')||\'<p>Папок пока нет.</p>\'}<button class="primary" onclick="createFolder()">＋ Создать папку</button><button onclick="closeModal()">Закрыть</button></div>`)}async function createFolder(){const name=prompt(\'Название папки\');if(!name)return;await api(\'/api/folders\',{method:\'POST\',headers:{\'Content-Type\':\'application/json\'},body:JSON.stringify({name})});closeModal();toast(\'📁 Папка создана\')}\nfunction openText(){modal(`<h3>📝 Текст или ссылка</h3><textarea id="note" class="textarea" placeholder="Напиши текст или вставь ссылку…"></textarea><div class="actions"><button class="primary" onclick="saveText(false)">Сохранить</button><button onclick="saveText(true)">🔒 Сохранить скрытым</button><button onclick="closeModal()">Отмена</button></div>`)}async function saveText(hidden){const text=$(\'#note\').value.trim();if(!text)return;await api(\'/api/text\',{method:\'POST\',headers:{\'Content-Type\':\'application/json\'},body:JSON.stringify({text,hidden})});closeModal();toast(\'✅ Сохранено\');home()}\nfunction settings(){modal(`<h3>⚙️ Настройки</h3><p>PIN защищает скрытые файлы.</p><div class="actions"><button onclick="setPin()">🔐 Установить / изменить PIN</button><button onclick="closeModal()">Закрыть</button></div>`)}async function setPin(){const p=prompt(\'Новый PIN, 4–6 цифр\');if(!p)return;try{await api(\'/api/pin/set\',{method:\'POST\',headers:{\'Content-Type\':\'application/json\'},body:JSON.stringify({pin:p})});closeModal();toast(\'🔐 PIN сохранён\')}catch(e){toast(\'PIN должен быть 4–6 цифр\')}}\n$(\'#refresh\').onclick=home;document.querySelectorAll(\'.bottom-nav button\').forEach(b=>b.onclick=()=>({home,gallery,hidden:hiddenPage,trash:trashPage}[b.dataset.nav])());init();\n'
if not TOKEN:
    raise RuntimeError('BOT_TOKEN не задан')


def db():
    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row
    return con


def validate_init_data(init_data: str):
    if not init_data:
        raise web.HTTPUnauthorized(text='Telegram initData отсутствует')
    data = dict(urllib.parse.parse_qsl(init_data, keep_blank_values=True))
    received = data.pop('hash', None)
    if not received:
        raise web.HTTPUnauthorized(text='Telegram hash отсутствует')
    check = '\n'.join(f'{k}={data[k]}' for k in sorted(data))
    secret = hmac.new(b'WebAppData', TOKEN.encode(), hashlib.sha256).digest()
    calc = hmac.new(secret, check.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(calc, received):
        raise web.HTTPUnauthorized(text='Неверные данные Telegram')
    try:
        if time.time() - int(data.get('auth_date', '0')) > 86400:
            raise web.HTTPUnauthorized(text='Сессия Telegram устарела')
    except ValueError:
        raise web.HTTPUnauthorized(text='Некорректный auth_date')
    user = json.loads(data.get('user', '{}'))
    if not user.get('id'):
        raise web.HTTPUnauthorized(text='Пользователь Telegram не найден')
    return user


def user_from_request(request):
    return validate_init_data(request.headers.get('X-Telegram-Init-Data', ''))


def json_response(data):
    return web.json_response(data, headers={'Cache-Control': 'no-store'})


def file_row(fid, uid):
    con = db()
    row = con.execute('SELECT * FROM files WHERE id=? AND user_id=?', (fid, uid)).fetchone()
    con.close()
    return row


def serialize_file(r):
    return {
        'id': r['id'], 'kind': r['kind'], 'text': r['text'] or '',
        'hidden': bool(r['hidden']), 'deleted': bool(r['deleted']),
        'folder_id': r['folder_id'], 'created_at': r['created_at'],
        'url': f"/api/file/{r['id']}"
    }


async def index(request):
    return web.Response(text=HTML, content_type='text/html')

async def asset_css(request):
    return web.Response(text=CSS, content_type='text/css')

async def asset_js(request):
    return web.Response(text=JS, content_type='application/javascript')


async def auth(request):
    user = user_from_request(request)
    return json_response({'ok': True, 'user': user})


async def stats(request):
    user = user_from_request(request)
    uid = user['id']
    con = db()
    total = con.execute('SELECT COUNT(*) n FROM files WHERE user_id=? AND deleted=0 AND hidden=0', (uid,)).fetchone()['n']
    photos = con.execute("SELECT COUNT(*) n FROM files WHERE user_id=? AND kind='photo' AND deleted=0 AND hidden=0", (uid,)).fetchone()['n']
    videos = con.execute("SELECT COUNT(*) n FROM files WHERE user_id=? AND kind='video' AND deleted=0 AND hidden=0", (uid,)).fetchone()['n']
    hidden = con.execute('SELECT COUNT(*) n FROM files WHERE user_id=? AND hidden=1 AND deleted=0', (uid,)).fetchone()['n']
    trash = con.execute('SELECT COUNT(*) n FROM files WHERE user_id=? AND deleted=1', (uid,)).fetchone()['n']
    folders = con.execute('SELECT COUNT(*) n FROM folders WHERE user_id=?', (uid,)).fetchone()['n']
    con.close()
    return json_response({'total': total, 'photos': photos, 'videos': videos, 'hidden': hidden, 'trash': trash, 'folders': folders})


async def files(request):
    user = user_from_request(request)
    uid = user['id']
    section = request.query.get('section', 'gallery')
    if section == 'hidden':
        where, params = 'hidden=1 AND deleted=0', (uid,)
    elif section == 'trash':
        where, params = 'deleted=1', (uid,)
    else:
        where, params = 'hidden=0 AND deleted=0', (uid,)
    con = db()
    rows = con.execute(f'SELECT * FROM files WHERE user_id=? AND {where} ORDER BY id DESC', params).fetchall()
    con.close()
    return json_response({'files': [serialize_file(r) for r in rows]})


async def folders(request):
    user = user_from_request(request)
    con = db()
    rows = con.execute('SELECT * FROM folders WHERE user_id=? ORDER BY id DESC', (user['id'],)).fetchall()
    con.close()
    return json_response({'folders': [dict(r) for r in rows]})


async def create_folder(request):
    user = user_from_request(request)
    body = await request.json()
    name = str(body.get('name', '')).strip()
    if not name or len(name) > 80:
        raise web.HTTPBadRequest(text='Некорректное название папки')
    con = db()
    cur = con.execute('INSERT INTO folders(user_id,name) VALUES(?,?)', (user['id'], name))
    con.commit(); fid = cur.lastrowid; con.close()
    return json_response({'ok': True, 'id': fid, 'name': name})


async def text_save(request):
    user = user_from_request(request)
    body = await request.json()
    text = str(body.get('text', '')).strip()
    hidden = bool(body.get('hidden', False))
    if not text or len(text) > 10000:
        raise web.HTTPBadRequest(text='Текст пустой или слишком длинный')
    con = db(); cur = con.execute('INSERT INTO files(user_id,kind,text,hidden) VALUES(?,?,?,?)', (user['id'], 'text', text, int(hidden)))
    con.commit(); fid = cur.lastrowid; con.close()
    return json_response({'ok': True, 'id': fid})


async def upload(request):
    user = user_from_request(request)
    reader = await request.multipart()
    part = await reader.next()
    if not part or part.name != 'file':
        raise web.HTTPBadRequest(text='Файл не найден')
    filename = part.filename or 'file'
    content_type = part.headers.get('Content-Type', 'application/octet-stream')
    data = await part.read()
    if not data:
        raise web.HTTPBadRequest(text='Пустой файл')
    if len(data) > 50 * 1024 * 1024:
        raise web.HTTPRequestEntityTooLarge(max_size=50*1024*1024, actual_size=len(data))
    hidden = 0
    folder_id = None
    while True:
        p = await reader.next()
        if not p: break
        value = (await p.text()).strip()
        if p.name == 'hidden': hidden = 1 if value == '1' else 0
        elif p.name == 'folder_id' and value: folder_id = int(value)
    bot = Bot(TOKEN)
    bio = io.BytesIO(data); bio.name = filename
    try:
        if content_type.startswith('image/'):
            msg = await bot.send_photo(chat_id=user['id'], photo=bio)
            file_id = msg.photo[-1].file_id; kind = 'photo'
        elif content_type.startswith('video/'):
            msg = await bot.send_video(chat_id=user['id'], video=bio)
            file_id = msg.video.file_id; kind = 'video'
        else:
            msg = await bot.send_document(chat_id=user['id'], document=bio)
            file_id = msg.document.file_id; kind = 'document'
    finally:
        await bot.shutdown()
    con = db()
    cur = con.execute('INSERT INTO files(user_id,folder_id,kind,file_id,hidden) VALUES(?,?,?,?,?)', (user['id'], folder_id, kind, file_id, hidden))
    con.commit(); fid = cur.lastrowid; con.close()
    return json_response({'ok': True, 'id': fid, 'kind': kind})


async def set_file_state(request):
    user = user_from_request(request)
    fid = int(request.match_info['fid'])
    action = request.match_info['action']
    row = file_row(fid, user['id'])
    if not row:
        raise web.HTTPNotFound(text='Файл не найден')
    con = db()
    if action == 'delete':
        con.execute('UPDATE files SET deleted=1 WHERE id=? AND user_id=?', (fid, user['id']))
    elif action == 'restore':
        con.execute('UPDATE files SET deleted=0 WHERE id=? AND user_id=?', (fid, user['id']))
    elif action == 'hide':
        con.execute('UPDATE files SET hidden=1 WHERE id=? AND user_id=?', (fid, user['id']))
    elif action == 'unhide':
        con.execute('UPDATE files SET hidden=0 WHERE id=? AND user_id=?', (fid, user['id']))
    elif action == 'purge':
        con.execute('DELETE FROM files WHERE id=? AND user_id=?', (fid, user['id']))
    else:
        con.close(); raise web.HTTPBadRequest(text='Неизвестное действие')
    con.commit(); con.close()
    return json_response({'ok': True})


async def move_file(request):
    user = user_from_request(request)
    fid = int(request.match_info['fid'])
    body = await request.json()
    folder_id = body.get('folder_id')
    if folder_id is not None:
        folder_id = int(folder_id)
        con = db(); ok = con.execute('SELECT 1 FROM folders WHERE id=? AND user_id=?', (folder_id, user['id'])).fetchone(); con.close()
        if not ok: raise web.HTTPBadRequest(text='Папка не найдена')
    con = db(); con.execute('UPDATE files SET folder_id=? WHERE id=? AND user_id=?', (folder_id, fid, user['id'])); con.commit(); con.close()
    return json_response({'ok': True})


async def pin_check(request):
    user = user_from_request(request)
    body = await request.json(); pin = str(body.get('pin', ''))
    con = db(); row = con.execute('SELECT pin_hash FROM users WHERE user_id=?', (user['id'],)).fetchone(); con.close()
    if not row or not row['pin_hash'] or row['pin_hash'] != hashlib.sha256(pin.encode()).hexdigest():
        return json_response({'ok': False})
    return json_response({'ok': True})


async def pin_set(request):
    user = user_from_request(request)
    body = await request.json(); pin = str(body.get('pin', ''))
    if not pin.isdigit() or not 4 <= len(pin) <= 6:
        raise web.HTTPBadRequest(text='PIN: 4–6 цифр')
    con = db(); con.execute('UPDATE users SET pin_hash=? WHERE user_id=?', (hashlib.sha256(pin.encode()).hexdigest(), user['id'])); con.commit(); con.close()
    return json_response({'ok': True})


async def proxy_file(request):
    user = user_from_request(request)
    fid = int(request.match_info['fid'])
    row = file_row(fid, user['id'])
    if not row or row['deleted']:
        raise web.HTTPNotFound()
    if row['hidden']:
        raise web.HTTPForbidden(text='Скрытый файл')
    if not row['file_id']:
        raise web.HTTPBadRequest(text='Это не медиафайл')
    async with ClientSession(timeout=ClientTimeout(total=30)) as s:
        async with s.post(f'https://api.telegram.org/bot{TOKEN}/getFile', json={'file_id': row['file_id']}) as r:
            info = await r.json()
    if not info.get('ok'):
        raise web.HTTPBadGateway(text='Telegram getFile error')
    path = info['result']['file_path']
    async with ClientSession(timeout=ClientTimeout(total=60)) as s:
        async with s.get(f'https://api.telegram.org/file/bot{TOKEN}/{path}') as r:
            if r.status != 200: raise web.HTTPBadGateway(text='Telegram file download error')
            body = await r.read()
            ctype = r.headers.get('Content-Type', 'application/octet-stream')
    return web.Response(body=body, content_type=ctype.split(';')[0], headers={'Cache-Control': 'private, max-age=300'})


def create_app():
    app = web.Application(client_max_size=55 * 1024 * 1024)
    app.router.add_get('/', index)
    app.router.add_get('/api/auth', auth)
    app.router.add_get('/api/stats', stats)
    app.router.add_get('/api/files', files)
    app.router.add_get('/api/folders', folders)
    app.router.add_post('/api/folders', create_folder)
    app.router.add_post('/api/text', text_save)
    app.router.add_post('/api/upload', upload)
    app.router.add_post('/api/file/{fid}/{action}', set_file_state)
    app.router.add_post('/api/file/{fid}/move', move_file)
    app.router.add_post('/api/pin/check', pin_check)
    app.router.add_post('/api/pin/set', pin_set)
    app.router.add_get('/api/file/{fid}', proxy_file)
    app.router.add_get('/assets/style.css', asset_css)
    app.router.add_get('/assets/app.js', asset_js)
    return app


def start_server():
    web.run_app(create_app(), host='0.0.0.0', port=PORT, print=lambda x: print('[MONNEY WEB]', x))
