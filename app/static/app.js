/* StudySpot web arayüzü — derleme adımı olmayan vanilla JS.
 * Tüm veriler mevcut /api/v1 endpoint'lerinden gelir; JWT tarayıcının localStorage'ında tutulur.
 * Sayfalar hash ile yönlendirilir: #/login, #/rooms[/<oda id>/<gün>], #/me, #/admin
 * Sunucudaki zamanlar kampüs yerel saatinde ve tz'sizdir ("2026-03-03T10:00:00"); burada da
 * metin olarak işlenir, tarayıcının saat dilimine çevrilmez.
 */
"use strict";

const API = "/api/v1";
const MAX_RESERVATION_MINUTES = 180; // sunucudaki MAX_RESERVATION_HOURS varsayılanı; asıl kontrol sunucuda
const BOOKING_DAYS = 14;             // MAX_ADVANCE_DAYS varsayılanı

const state = { token: null, user: null, rooms: [] };

// ---------------------------------------------------------------- Etiketler
const ROOM_TYPES = { study_room: "Grup çalışma odası", lab: "Laboratuvar", hall: "Salon" };
const MODES = { exclusive: "Tüm oda size ayrılır", shared: "Koltuk bazlı" };
const STATUS = {
  confirmed: ["Onaylı", "ok"],
  checked_in: ["Check-in yapıldı", "ok"],
  completed: ["Tamamlandı", ""],
  cancelled: ["İptal edildi", "danger"],
  no_show: ["Gelinmedi", "danger"],
};
const WAIT_STATUS = {
  waiting: ["Beklemede", "warn"],
  promoted: ["Rezervasyona dönüştü", "ok"],
  cancelled: ["Sıradan çıkıldı", ""],
  expired: ["Süresi doldu", ""],
};
const SLOT_REASONS = {
  in_past: "Geçmiş",
  too_far: "Henüz açılmadı",
  holiday: "Resmi tatil",
  room_inactive: "Oda kapalı",
  slot_full: "Dolu",
};
// İş kuralı hata kodları için kısa başlık ve kullanıcıya ne yapabileceğini söyleyen ipucu.
// Ayrıntılı mesaj ("detail") zaten sunucudan Türkçe gelir.
const ERRORS = {
  slot_full: ["Bu saat dolu", "Aşağıdaki alternatiflerden birini seçebilir ya da bekleme listesine katılabilirsiniz."],
  user_conflict: ["Saat çakışması", "Aynı saatte başka bir rezervasyonunuz var; Rezervasyonlarım sayfasından bakabilirsiniz."],
  daily_limit: ["Günlük limit doldu", "Başka bir gün deneyin ya da daha kısa bir süre seçin."],
  weekly_limit: ["Haftalık limit doldu", "Haftalık hakkınız yenilenince (Pazartesi) tekrar deneyin."],
  too_long: ["Süre çok uzun", "Daha kısa bir süre seçin."],
  outside_hours: ["Çalışma saatleri dışında", "Odanın açık olduğu saatlerden birini seçin."],
  slot_misaligned: ["Saat dilimine uymuyor", "Slot tablosundaki saatlerden birini seçin."],
  in_past: ["Geçmiş zaman", "İleri bir saat seçin."],
  too_far: ["Çok ileri bir tarih", `En fazla ${BOOKING_DAYS} gün sonrasına rezervasyon yapılabilir.`],
  holiday: ["Resmi tatil", "Bu gün kampüs kapalı; başka bir gün seçin."],
  user_banned: ["Rezervasyon yasağı", "Ceza süreniz bitince tekrar rezervasyon yapabilirsiniz."],
  user_inactive: ["Hesap pasif", "Yönetici ile iletişime geçin."],
  room_inactive: ["Oda kapalı", "Başka bir oda seçin."],
  already_waiting: ["Zaten sıradasınız", "Sıra durumunuzu Rezervasyonlarım sayfasında görebilirsiniz."],
  slot_available: ["Slot boşaldı", "Bekleme listesine gerek yok, doğrudan rezervasyon yapabilirsiniz."],
  already_started: ["Rezervasyon başladı", "Başlamış rezervasyon iptal edilemez."],
  not_cancellable: ["İptal edilemez", "Yalnızca onaylı rezervasyonlar iptal edilebilir."],
  invalid_interval: ["Geçersiz saat aralığı", ""],
};
const FIELD_NAMES = { email: "E-posta", password: "Şifre", full_name: "Ad soyad", username: "E-posta" };

// ---------------------------------------------------------------- Yardımcılar
const $ = (sel) => document.querySelector(sel);

function h(tag, props, ...children) {
  const el = document.createElement(tag);
  for (const [key, value] of Object.entries(props || {})) {
    if (value == null || value === false) continue;
    if (key === "class") el.className = value;
    else if (key.startsWith("on")) el.addEventListener(key.slice(2), value);
    else el.setAttribute(key, value === true ? "" : value);
  }
  for (const child of children.flat(Infinity)) {
    if (child == null || child === false) continue;
    el.append(child instanceof Node ? child : String(child));
  }
  return el;
}

const store = {
  get(key) { try { return localStorage.getItem(key); } catch { return null; } },
  set(key, value) { try { localStorage.setItem(key, value); } catch { /* gizli pencere vb. */ } },
  del(key) { try { localStorage.removeItem(key); } catch { /* yok say */ } },
};

const pad = (n) => String(n).padStart(2, "0");
const isoDate = (d) => `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
const naive = (d) => `${isoDate(d)}T${pad(d.getHours())}:${pad(d.getMinutes())}:00`;
function parseNaive(s) {
  const [y, mo, d, hh = 0, mi = 0] = s.split(/[-T:]/).map(Number);
  return new Date(y, mo - 1, d, hh, mi);
}
const today = () => isoDate(new Date());
const addDays = (iso, n) => { const d = parseNaive(iso); d.setDate(d.getDate() + n); return isoDate(d); };
const addMinutes = (s, n) => { const d = parseNaive(s); d.setMinutes(d.getMinutes() + n); return naive(d); };
const hm = (s) => s.slice(11, 16);
const dayOf = (s) => s.slice(0, 10);
const fmtDay = (iso, opts = { weekday: "long", day: "numeric", month: "long" }) =>
  parseNaive(iso).toLocaleDateString("tr-TR", opts);
const fmtRange = (start, end) => `${fmtDay(dayOf(start), { day: "numeric", month: "long", weekday: "short" })} · ${hm(start)}–${hm(end)}`;
const pct = (x) => `%${Math.round(x * 100)}`;
const weekdayOf = (iso) => (parseNaive(iso).getDay() + 6) % 7; // 0 = Pazartesi (sunucuyla aynı)
const roomName = (id) => (state.rooms.find((r) => r.id === id) || {}).name || `Oda #${id}`;

function badge(text, kind = "") { return h("span", { class: `badge ${kind}` }, text); }

// ---------------------------------------------------------------- API
class ApiError extends Error {
  constructor(status, body) {
    super(typeof body.detail === "string" ? body.detail : `HTTP ${status}`);
    this.status = status;
    this.body = body;
    this.code = body.code || null;
  }
}

async function api(path, { method = "GET", json, form, raw = false } = {}) {
  const headers = {};
  if (state.token) headers.Authorization = `Bearer ${state.token}`;
  let body;
  if (json !== undefined) { headers["Content-Type"] = "application/json"; body = JSON.stringify(json); }
  if (form) body = new URLSearchParams(form);
  let res;
  try {
    res = await fetch(API + path, { method, headers, body });
  } catch {
    throw new ApiError(0, { detail: "Sunucuya ulaşılamadı. Bağlantınızı kontrol edin." });
  }
  if (!res.ok) {
    let data = {};
    try { data = await res.json(); } catch { /* gövde JSON değil */ }
    if (res.status === 401 && state.token) {
      logout("Oturumunuzun süresi doldu, lütfen yeniden giriş yapın.");
    }
    throw new ApiError(res.status, data);
  }
  if (raw) return res;
  const type = res.headers.get("content-type") || "";
  return type.includes("json") ? res.json() : res.text();
}

function describeError(err) {
  if (!(err instanceof ApiError)) return { title: "Beklenmeyen hata", detail: String(err), hint: "" };
  const detail = err.body.detail;
  if (Array.isArray(detail)) {
    // FastAPI doğrulama hatası (422): alan adlarını Türkçeleştir
    const lines = detail.map((d) => {
      const field = FIELD_NAMES[d.loc[d.loc.length - 1]] || d.loc[d.loc.length - 1];
      return `${field}: ${d.msg}`;
    });
    return { title: "Girilen bilgiler geçersiz", detail: lines.join(" · "), hint: "" };
  }
  const fallback = err.status >= 500 ? "Sunucu hatası" : err.status === 401 ? "Giriş başarısız"
    : err.status === 403 ? "Yetkiniz yok" : err.status === 404 ? "Bulunamadı" : "İşlem yapılamadı";
  const [title, hint] = ERRORS[err.code] || [fallback, ""];
  return { title, detail: detail || err.message, hint };
}

function errorBox(err) {
  const { title, detail, hint } = describeError(err);
  return h("div", { class: "alert error", role: "alert" }, h("b", null, title), detail, hint && h("div", { class: "small" }, hint));
}

function toast(message, kind = "") {
  const el = h("div", { class: `toast ${kind}` }, message);
  $("#toasts").append(el);
  setTimeout(() => el.remove(), 4500);
}
const toastError = (err) => { const e = describeError(err); toast(`${e.title}: ${e.detail}`, "error"); };

async function download(path, filename) {
  try {
    const res = await api(path, { raw: true });
    const url = URL.createObjectURL(await res.blob());
    const a = h("a", { href: url, download: filename });
    document.body.append(a);
    a.click();
    a.remove();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  } catch (err) { toastError(err); }
}

// ---------------------------------------------------------------- Modal
const modal = $("#modal");
function openModal(title, ...content) {
  $("#modal-title").textContent = title;
  $("#modal-body").replaceChildren(...content);
  if (!modal.open) modal.showModal();
}
const setModalBody = (...content) => $("#modal-body").replaceChildren(...content);

// Tarayıcının confirm() penceresi yerine uygulama içi onay; true/false ile çözülür
function confirmModal(title, question, okLabel) {
  return new Promise((resolve) => {
    let answered = false;
    const answer = (value) => { if (answered) return; answered = true; resolve(value); closeModal(); };
    modal.addEventListener("close", () => answer(false), { once: true });
    openModal(title,
      h("div", { class: "stack" },
        h("p", null, question),
        h("div", { class: "row" },
          h("button", { class: "btn danger", type: "button", onclick: () => answer(true) }, okLabel),
          h("button", { class: "btn ghost", type: "button", onclick: () => answer(false) }, "Vazgeç"),
        ),
      ),
    );
  });
}
const closeModal = () => modal.open && modal.close();
modal.addEventListener("close", () => {
  // QR gibi blob URL'lerini serbest bırak
  modal.querySelectorAll("img[data-blob]").forEach((img) => URL.revokeObjectURL(img.src));
});

// ---------------------------------------------------------------- Oturum
function logout(message) {
  state.token = null;
  state.user = null;
  store.del("studyspot_token");
  closeModal();
  // replaceState hashchange tetiklemez; böylece mesajlı giriş ekranı ezilmez
  history.replaceState(null, "", "#/login");
  renderChrome();
  renderLogin(message);
}

async function loadUser() {
  state.user = await api("/auth/me");
  renderChrome();
}

function renderChrome() {
  const logged = Boolean(state.user);
  $("#nav").hidden = !logged;
  $("#userbox").hidden = !logged;
  $("#nav-admin").hidden = !(logged && state.user.role === "admin");
  if (logged) $("#user-name").textContent = state.user.full_name + (state.user.role === "admin" ? " (admin)" : "");
  const route = location.hash.split("/")[1] || "rooms";
  document.querySelectorAll("#nav a").forEach((a) => a.classList.toggle("active", a.dataset.route === route));
}
$("#logout").addEventListener("click", () => logout());

// ---------------------------------------------------------------- Giriş / kayıt
function renderLogin(message) {
  const main = $("#app");
  let mode = "login";
  const box = h("div");
  const tabLogin = h("button", { type: "button", role: "tab", "aria-selected": "true", onclick: () => switchTo("login") }, "Giriş yap");
  const tabRegister = h("button", { type: "button", role: "tab", "aria-selected": "false", onclick: () => switchTo("register") }, "Kayıt ol");

  function field(label, attrs) {
    const id = `f-${attrs.name}`;
    return h("div", { class: "field" }, h("label", { for: id }, label), h("input", { id, required: true, ...attrs }));
  }

  function switchTo(next) {
    mode = next;
    tabLogin.setAttribute("aria-selected", String(mode === "login"));
    tabRegister.setAttribute("aria-selected", String(mode === "register"));
    form.replaceChildren(
      ...(mode === "register" ? [field("Ad soyad", { name: "full_name", autocomplete: "name", minlength: 2 })] : []),
      field("E-posta", { name: "email", type: "email", autocomplete: "email" }),
      field("Şifre", {
        name: "password", type: "password", minlength: mode === "register" ? 8 : null,
        autocomplete: mode === "register" ? "new-password" : "current-password",
      }),
      h("div", { class: "field" }, h("button", { class: "btn", type: "submit", style: "width:100%" }, mode === "login" ? "Giriş yap" : "Hesap oluştur")),
    );
    box.replaceChildren();
  }

  const form = h("form", {
    onsubmit: async (ev) => {
      ev.preventDefault();
      const data = Object.fromEntries(new FormData(form));
      const button = form.querySelector("button[type=submit]");
      button.disabled = true;
      box.replaceChildren();
      try {
        if (mode === "register") {
          await api("/auth/register", { method: "POST", json: data });
          toast("Hesabınız oluşturuldu.");
        }
        const token = await api("/auth/login", { method: "POST", form: { username: data.email, password: data.password } });
        state.token = token.access_token;
        store.set("studyspot_token", state.token);
        await loadUser();
        if (location.hash === "#/rooms") route();
        else location.hash = "#/rooms";
      } catch (err) {
        box.replaceChildren(errorBox(err));
      } finally {
        button.disabled = false;
      }
    },
  });
  switchTo("login");

  main.replaceChildren(
    h("div", { class: "auth-wrap stack" },
      h("div", null, h("h1", null, "Çalışma odanı ayır"), h("p", { class: "muted" }, "Kütüphane odaları, laboratuvarlar ve çalışma salonları için saat bazlı rezervasyon.")),
      message && h("div", { class: "alert info" }, message),
      h("div", { class: "card" }, h("div", { class: "tabs", role: "tablist" }, tabLogin, tabRegister), form, box),
      h("p", { class: "hint" }, "Demo verisi yüklüyse öğrenci hesapları: ogrenci1@example.com … ogrenci6@example.com (şifre scripts/seed.py içinde). Swagger: /docs"),
    ),
  );
}

// ---------------------------------------------------------------- Odalar ve slot tablosu
async function ensureRooms() {
  state.rooms = await api("/rooms");
  return state.rooms;
}

async function renderRooms(roomId, day) {
  const main = $("#app");
  const rooms = await ensureRooms();
  const room = rooms.find((r) => r.id === roomId);
  day = day || today();

  const list = h("div", { class: "grid rooms" },
    rooms.map((r) => h("button", {
      type: "button", class: "card room-card", "aria-pressed": String(r.id === roomId),
      onclick: () => { location.hash = `#/rooms/${r.id}/${day}`; },
    },
    h("h3", null, r.name),
    h("div", { class: "muted small" }, r.location || "—"),
    h("div", { class: "meta" },
      badge(ROOM_TYPES[r.room_type] || r.room_type),
      badge(`${r.capacity} kişi`),
      badge(`${r.open_time.slice(0, 5)}–${r.close_time.slice(0, 5)}`),
    ))),
  );

  const detail = h("section", { class: "card stack", id: "room-detail" });
  main.replaceChildren(
    h("div", { class: "stack" },
      h("div", null, h("h1", null, "Odalar"), h("p", { class: "muted" }, "Bir oda ve gün seçin; boş slota tıklayınca rezervasyon yapılır, dolu slotta alternatif öneriler çıkar.")),
      rooms.length ? list : h("div", { class: "alert info" }, "Henüz rezervasyona açık oda yok."),
      room ? detail : null,
    ),
  );
  if (!room) return;
  // Telefonda oda kartları yatay şerit: seçili kart görünür olsun
  const selected = list.querySelector('[aria-pressed="true"]');
  if (selected) list.scrollLeft = selected.offsetLeft - list.offsetLeft;
  await renderRoomDetail(detail, room, day);
}

async function renderRoomDetail(container, room, day) {
  const days = h("div", { class: "days", role: "group", "aria-label": "Gün seçimi" });
  for (let i = 0; i <= BOOKING_DAYS; i++) {
    const d = addDays(today(), i);
    days.append(h("button", {
      type: "button", class: "day-btn", "aria-pressed": String(d === day),
      onclick: () => { location.hash = `#/rooms/${room.id}/${d}`; },
    }, h("span", null, i === 0 ? "Bugün" : fmtDay(d, { weekday: "short" })), h("b", null, fmtDay(d, { day: "numeric" })), h("span", null, fmtDay(d, { month: "short" }))));
  }
  const slotsBox = h("div", { class: "slots", "aria-live": "polite" }, h("p", { class: "muted" }, "Slotlar yükleniyor…"));
  const quietBox = h("div", { class: "chips" });

  container.replaceChildren(
    h("div", { class: "row spread" },
      h("div", null, h("h2", null, room.name), h("div", { class: "muted small" }, [room.location, room.description].filter(Boolean).join(" · "))),
      h("div", { class: "row" }, badge(MODES[room.booking_mode]), badge(`${room.slot_minutes} dk dilim`)),
    ),
    days,
    h("div", null, h("h3", null, fmtDay(day)), slotsBox),
    h("div", { class: "legend" },
      h("span", null, h("i", { style: "background:var(--ok-bg);border:1px solid var(--ok)" }), "Boş"),
      h("span", null, h("i", { style: "background:var(--danger-bg)" }), "Dolu (öneri / bekleme listesi)"),
      h("span", null, h("i", { style: "background:var(--mine-bg)" }), "Sizin rezervasyonunuz"),
      h("span", null, h("i", { style: "background:var(--surface-2)" }), "Kapalı / geçmiş"),
    ),
    h("div", null, h("h3", null, `${fmtDay(day, { weekday: "long" })} günleri en sakin saatler`), quietBox),
  );

  api(`/rooms/${room.id}/quiet-hours?weekday=${weekdayOf(day)}&limit=5`)
    .then((cells) => quietBox.replaceChildren(
      ...(cells.length ? cells.map((c) => badge(`${pad(c.hour)}:00 · doluluk ${pct(c.occupancy_rate)}`, c.occupancy_rate < 0.25 ? "ok" : ""))
        : [h("span", { class: "muted small" }, "Geçmiş veri yok.")]),
      h("div", { class: "muted small", style: "flex-basis:100%" }, "Son 4 haftanın verisine göre."),
    ))
    .catch(() => quietBox.replaceChildren(h("span", { class: "muted small" }, "Sakin saatler alınamadı.")));

  try {
    const [slots, mine, waiting] = await Promise.all([
      api(`/rooms/${room.id}/availability?day=${day}`),
      api("/reservations/me?upcoming=true"),
      api("/waitlist/me"),
    ]);
    renderSlots(slotsBox, room, day, slots, mine, waiting);
  } catch (err) {
    slotsBox.replaceChildren(errorBox(err));
  }
}

function renderSlots(box, room, day, slots, mine, waiting) {
  const overlaps = (a, b) => a.start_time < b.end_time && b.start_time < a.end_time;
  const myActive = mine.filter((r) => r.room_id === room.id && (r.status === "confirmed" || r.status === "checked_in"));
  const myWaiting = waiting.filter((w) => w.room_id === room.id && w.status === "waiting");
  if (!slots.length) { box.replaceChildren(h("p", { class: "muted" }, "Bu gün için slot yok.")); return; }

  box.replaceChildren(...slots.map((slot, index) => {
    const own = myActive.find((r) => overlaps(r, slot));
    const queued = myWaiting.find((w) => overlaps(w, slot));
    let cls = "off", state_ = SLOT_REASONS[slot.reason] || slot.reason, onclick = null, label;
    if (own) {
      cls = "mine"; state_ = "Rezervasyonunuz";
      onclick = () => { location.hash = "#/me"; };
    } else if (slot.available) {
      cls = "free";
      state_ = room.booking_mode === "shared" ? `${slot.remaining_seats}/${slot.total_seats} koltuk boş` : "Boş";
      onclick = () => openBookModal(room, slots, index);
    } else if (slot.reason === "slot_full") {
      cls = "full";
      state_ = queued ? "Dolu · sıradasınız" : "Dolu";
      onclick = () => openFullModal(room, slot.start_time, slot.end_time);
    }
    label = `${hm(slot.start_time)}–${hm(slot.end_time)}: ${state_}`;
    return h("button", { type: "button", class: `slot ${cls}`, disabled: !onclick, onclick, "aria-label": label },
      h("span", { class: "time" }, `${hm(slot.start_time)}–${hm(slot.end_time)}`),
      h("span", { class: "state" }, state_),
    );
  }));
}

function refreshCurrent() { route(); }

// ---------------------------------------------------------------- Rezervasyon akışı
function openBookModal(room, slots, index) {
  const start = slots[index].start_time;
  // Ardışık boş slotlar kadar süre seçilebilir (en fazla 3 saat)
  const options = [];
  for (let i = index; i < slots.length && slots[i].available; i++) {
    const minutes = (i - index + 1) * room.slot_minutes;
    if (minutes > MAX_RESERVATION_MINUTES) break;
    options.push(minutes);
  }
  const select = h("select", { id: "duration" },
    options.map((m) => h("option", { value: m }, m % 60 ? `${Math.floor(m / 60) ? Math.floor(m / 60) + " saat " : ""}${m % 60} dk` : `${m / 60} saat`)));
  const endLabel = h("b");
  const updateEnd = () => { endLabel.textContent = hm(addMinutes(start, Number(select.value))); };
  select.addEventListener("change", updateEnd);
  updateEnd();
  const feedback = h("div");
  const submit = h("button", { class: "btn", type: "submit" }, "Rezerve et");

  const form = h("form", {
    class: "stack",
    onsubmit: async (ev) => {
      ev.preventDefault();
      submit.disabled = true;
      feedback.replaceChildren();
      const end = addMinutes(start, Number(select.value));
      try {
        const reservation = await api("/reservations", { method: "POST", json: { room_id: room.id, start_time: start, end_time: end } });
        showBooked(reservation);
      } catch (err) {
        submit.disabled = false;
        if (err.code === "slot_full") {
          openFullModal(room, start, end, err.body.suggestions);
        } else {
          feedback.replaceChildren(errorBox(err));
        }
      }
    },
  },
  h("div", null, h("div", { class: "muted small" }, room.name), h("div", null, fmtDay(dayOf(start)))),
  h("div", { class: "row" },
    h("div", { style: "flex:1;min-width:140px" }, h("label", { for: "duration" }, "Süre"), select),
    h("div", null, h("div", { class: "muted small" }, "Saat"), h("div", null, `${hm(start)} – `, endLabel)),
  ),
  h("p", { class: "muted small" }, "Başlangıçtan 10 dk önce ile 15 dk sonrası arasında QR kodunuzla check-in yapmanız gerekir; gelmezseniz ceza puanı yazılır."),
  feedback,
  h("div", { class: "row" }, submit, h("button", { class: "btn ghost", type: "button", onclick: closeModal }, "Vazgeç")),
  );
  openModal("Rezervasyon yap", form);
}

function showBooked(reservation) {
  toast(`${reservation.room_name} rezerve edildi.`);
  setModalBody(
    h("div", { class: "stack" },
      h("div", { class: "alert ok" }, h("b", null, "Rezervasyonunuz onaylandı"), `${reservation.room_name} · ${fmtRange(reservation.start_time, reservation.end_time)}`),
      h("div", { class: "row" },
        h("button", { class: "btn", type: "button", onclick: () => showQr(reservation) }, "QR kodunu göster"),
        h("button", { class: "btn ghost", type: "button", onclick: () => download(`/reservations/${reservation.id}/ics`, `rezervasyon-${reservation.id}.ics`) }, "Takvime ekle (.ics)"),
        h("button", { class: "btn ghost", type: "button", onclick: closeModal }, "Kapat"),
      ),
    ),
  );
  $("#modal-title").textContent = "Rezervasyon tamam";
  refreshCurrent();
}

async function openFullModal(room, start, end, preloaded) {
  const list = h("div", null, h("p", { class: "muted" }, "Alternatifler hesaplanıyor…"));
  const waitBox = h("div");
  const joinBtn = h("button", { class: "btn ghost", type: "button" }, "Bekleme listesine katıl");
  joinBtn.addEventListener("click", async () => {
    joinBtn.disabled = true;
    try {
      const entry = await api("/waitlist", { method: "POST", json: { room_id: room.id, start_time: start, end_time: end } });
      waitBox.replaceChildren(h("div", { class: "alert ok" }, h("b", null, `Sıradasınız: ${entry.position}. sıra`), "Slot boşalırsa rezervasyon otomatik olarak adınıza yapılır ve e-posta gelir."));
      toast("Bekleme listesine katıldınız.");
      refreshCurrent();
    } catch (err) {
      joinBtn.disabled = false;
      waitBox.replaceChildren(errorBox(err));
    }
  });

  openModal("Bu saat dolu",
    h("div", { class: "stack" },
      h("div", { class: "alert info" }, h("b", null, `${room.name} · ${fmtRange(start, end)}`), ERRORS.slot_full[1]),
      h("div", null, h("h3", null, "Önerilen alternatifler"), list),
      h("div", null, h("h3", null, "Ya da sırada bekleyin"), h("p", { class: "muted small" }, "Biri iptal ederse ya da gelmezse slot sıradaki ilk uygun kişiye otomatik verilir."), joinBtn, waitBox),
    ),
  );

  try {
    const query = new URLSearchParams({ room_id: room.id, start_time: start, end_time: end, limit: 5 });
    const items = preloaded || await api(`/suggestions?${query}`);
    renderSuggestions(list, items);
  } catch (err) {
    list.replaceChildren(errorBox(err));
  }
}

function renderSuggestions(box, items) {
  if (!items.length) {
    box.replaceChildren(h("p", { class: "muted" }, "Kurallara uyan bir alternatif bulunamadı (limitleriniz veya o günkü doluluk nedeniyle). Bekleme listesine katılabilirsiniz."));
    return;
  }
  box.replaceChildren(...items.map((s) => {
    const button = h("button", { class: "btn", type: "button" }, "Rezerve et");
    const feedback = h("div", { style: "grid-column:1/-1" });
    button.addEventListener("click", async () => {
      button.disabled = true;
      feedback.replaceChildren();
      try {
        const reservation = await api("/reservations", { method: "POST", json: { room_id: s.room_id, start_time: s.start_time, end_time: s.end_time } });
        showBooked(reservation);
      } catch (err) {
        button.disabled = false;
        feedback.replaceChildren(errorBox(err));
      }
    });
    return h("div", { class: "suggestion" },
      h("div", null,
        h("div", { class: "row" }, h("b", null, s.room_name), badge(s.same_room ? "Aynı oda" : "Farklı oda", s.same_room ? "" : "mine")),
        h("div", null, fmtRange(s.start_time, s.end_time)),
        h("div", { class: "scorebar", title: `Uygunluk ${pct(s.score)}` }, h("span", { style: `width:${Math.round(s.score * 100)}%` })),
        h("div", { class: "muted small" }, `Uygunluk ${pct(s.score)} · yakınlık ${pct(s.proximity_score)} · oda uyumu ${pct(s.fit_score)} · sakinlik ${pct(s.quiet_score)}`),
        h("ul", null, s.reasons.map((r) => h("li", null, r))),
      ),
      button,
      feedback,
    );
  }));
}

async function showQr(reservation) {
  openModal("Check-in QR kodu", h("p", { class: "muted" }, "Yükleniyor…"));
  try {
    const res = await api(`/reservations/${reservation.id}/qr`, { raw: true });
    const url = URL.createObjectURL(await res.blob());
    setModalBody(
      h("div", { class: "stack", style: "text-align:center" },
        h("div", null, h("b", null, reservation.room_name), h("div", { class: "muted small" }, fmtRange(reservation.start_time, reservation.end_time))),
        h("img", { class: "qr", src: url, alt: "Check-in QR kodu", "data-blob": "1" }),
        h("p", { class: "muted small" }, "Odaya geldiğinizde bu kodu görevliye okutun. Kod: ", h("code", { class: "code" }, reservation.checkin_code)),
      ),
    );
  } catch (err) {
    setModalBody(errorBox(err));
  }
}

// ---------------------------------------------------------------- Rezervasyonlarım
async function renderMe() {
  const main = $("#app");
  main.replaceChildren(h("p", { class: "muted" }, "Yükleniyor…"));
  const [reservations, waitlist, user] = await Promise.all([api("/reservations/me"), api("/waitlist/me"), api("/auth/me"), ensureRooms()]);
  state.user = user;
  const now = naive(new Date());
  const active = reservations.filter((r) => (r.status === "confirmed" || r.status === "checked_in") && r.end_time > now);
  const past = reservations.filter((r) => !active.includes(r)).reverse().slice(0, 15);

  const cancel = async (r, button) => {
    const late = (parseNaive(r.start_time) - new Date()) / 60000 < 30;
    const question = late
      ? "Başlangıca 30 dakikadan az kaldı; iptal ederseniz 1 ceza puanı yazılır. Yine de iptal edilsin mi?"
      : `${r.room_name} · ${fmtRange(r.start_time, r.end_time)} rezervasyonu iptal edilsin mi?`;
    if (!(await confirmModal("Rezervasyonu iptal et", question, "İptal et"))) return;
    button.disabled = true;
    try {
      await api(`/reservations/${r.id}`, { method: "DELETE" });
      toast("Rezervasyon iptal edildi. Slot sıradaki kişiye açıldı.");
      renderMe();
    } catch (err) { button.disabled = false; toastError(err); }
  };

  const reservationItem = (r, actions) => {
    const [label, kind] = STATUS[r.status] || [r.status, ""];
    return h("div", { class: "list-item" },
      h("div", null,
        h("div", { class: "row" }, h("b", null, r.room_name || roomName(r.room_id)), badge(label, kind), r.source === "waitlist" && badge("Bekleme listesinden", "mine")),
        h("div", { class: "muted small" }, fmtRange(r.start_time, r.end_time)),
      ),
      actions && h("div", { class: "row" }, actions),
    );
  };

  const activeList = active.length
    ? active.map((r) => {
      const cancelBtn = r.status === "confirmed" && r.start_time > now
        ? h("button", { class: "btn danger small", type: "button" }, "İptal et") : null;
      cancelBtn && cancelBtn.addEventListener("click", () => cancel(r, cancelBtn));
      return reservationItem(r, [
        h("button", { class: "btn small", type: "button", onclick: () => showQr(r) }, "QR"),
        h("button", { class: "btn ghost small", type: "button", onclick: () => download(`/reservations/${r.id}/ics`, `rezervasyon-${r.id}.ics`) }, ".ics"),
        cancelBtn,
      ]);
    })
    : [h("p", { class: "muted" }, "Yaklaşan rezervasyonunuz yok. ", h("a", { href: "#/rooms" }, "Oda seçin"), ".")];

  const leave = async (entry, button) => {
    button.disabled = true;
    try {
      await api(`/waitlist/${entry.id}`, { method: "DELETE" });
      toast("Sıradan çıktınız.");
      renderMe();
    } catch (err) { button.disabled = false; toastError(err); }
  };
  const waitingFirst = [...waitlist].sort((a, b) => (a.status === "waiting" ? 0 : 1) - (b.status === "waiting" ? 0 : 1) || (a.start_time < b.start_time ? -1 : 1));
  const waitList = waitingFirst.length
    ? waitingFirst.slice(0, 15).map((w) => {
      const [label, kind] = WAIT_STATUS[w.status] || [w.status, ""];
      const leaveBtn = w.status === "waiting" ? h("button", { class: "btn ghost small", type: "button" }, "Sıradan çık") : null;
      leaveBtn && leaveBtn.addEventListener("click", () => leave(w, leaveBtn));
      return h("div", { class: "list-item" },
        h("div", null,
          h("div", { class: "row" }, h("b", null, roomName(w.room_id)), badge(label, kind), w.position && badge(`${w.position}. sıra`, "warn")),
          h("div", { class: "muted small" }, fmtRange(w.start_time, w.end_time)),
        ),
        leaveBtn,
      );
    })
    : [h("p", { class: "muted" }, "Bekleme listesi kaydınız yok.")];

  const banned = user.banned_until && user.banned_until > now;
  main.replaceChildren(
    h("div", { class: "stack" },
      h("div", { class: "row spread" },
        h("h1", null, "Rezervasyonlarım"),
        h("button", { class: "btn ghost", type: "button", onclick: () => download("/reservations/me/calendar.ics", "studyspot.ics") }, "Tümünü takvime ekle (.ics)"),
      ),
      h("div", { class: "card row spread" },
        h("div", null, h("b", null, user.full_name), h("div", { class: "muted small" }, user.email)),
        h("div", { class: "row" },
          badge(`Ceza puanı: ${user.penalty_points}`, user.penalty_points ? "warn" : ""),
          banned && badge(`${fmtDay(dayOf(user.banned_until), { day: "numeric", month: "long" })} ${hm(user.banned_until)} tarihine kadar yasaklı`, "danger"),
        ),
      ),
      h("section", { class: "card" }, h("h2", null, "Yaklaşan"), activeList),
      h("section", { class: "card" }, h("h2", null, "Bekleme listesi"), waitList),
      h("section", { class: "card" }, h("h2", null, "Geçmiş ve iptaller"),
        past.length ? past.map((r) => reservationItem(r)) : h("p", { class: "muted" }, "Henüz kayıt yok.")),
    ),
  );
}

// ---------------------------------------------------------------- Yönetim
const WEEKDAYS = ["Pazartesi", "Salı", "Çarşamba", "Perşembe", "Cuma", "Cumartesi", "Pazar"];
const WEEKDAYS_SHORT = ["Pzt", "Sal", "Çar", "Per", "Cum", "Cmt", "Paz"];

async function renderAdmin() {
  const main = $("#app");
  if (!state.user || state.user.role !== "admin") {
    main.replaceChildren(h("div", { class: "alert error" }, h("b", null, "Yetkisiz"), "Bu sayfa yalnızca yöneticilere açık."));
    return;
  }
  await ensureRooms();
  const to = today();
  const from = addDays(to, -29);
  const fromInput = h("input", { type: "date", id: "a-from", value: from });
  const toInput = h("input", { type: "date", id: "a-to", value: to });
  const roomSelect = h("select", { id: "a-room" }, h("option", { value: "" }, "Tüm odalar"), state.rooms.map((r) => h("option", { value: r.id }, r.name)));
  const content = h("div", { class: "stack" });
  const jobsBox = h("div");
  const jobsBtn = h("button", { class: "btn", type: "button" }, "Görevleri şimdi çalıştır");
  jobsBtn.addEventListener("click", async () => {
    jobsBtn.disabled = true;
    try {
      const r = await api("/admin/jobs/run", { method: "POST" });
      jobsBox.replaceChildren(h("div", { class: "alert ok" }, h("b", null, "Görevler çalıştı"),
        `No-show: ${r.no_shows} · tamamlanan: ${r.completed} · hatırlatma: ${r.reminders} · süresi dolan sıra: ${r.waitlist_expired}`));
      load();
    } catch (err) { jobsBox.replaceChildren(errorBox(err)); }
    finally { jobsBtn.disabled = false; }
  });

  async function load() {
    content.replaceChildren(h("p", { class: "muted" }, "Rapor hazırlanıyor…"));
    const range = new URLSearchParams({ date_from: fromInput.value, date_to: toInput.value });
    const heatQuery = new URLSearchParams(range);
    if (roomSelect.value) heatQuery.set("room_id", roomSelect.value);
    try {
      const [summary, heat, stats, emails] = await Promise.all([
        api(`/analytics/summary?${range}`),
        api(`/analytics/occupancy/heatmap?${heatQuery}`),
        api(`/analytics/rooms?${range}`),
        api("/admin/emails?limit=25"),
      ]);
      content.replaceChildren(
        summaryCard(summary),
        h("section", { class: "card stack" },
          h("div", { class: "row spread" }, h("h2", null, "Doluluk ısı haritası (gün × saat)"),
            h("div", { class: "heat-legend" }, "%0", h("span", { class: "ramp" }), "%100")),
          heatmapTable(heat),
        ),
        roomStatsCard(stats),
        emailCard(emails),
      );
    } catch (err) {
      content.replaceChildren(errorBox(err));
    }
  }

  main.replaceChildren(
    h("div", { class: "stack" },
      h("div", { class: "row spread" }, h("h1", null, "Yönetim"), h("div", { class: "row" }, jobsBtn)),
      jobsBox,
      h("form", {
        class: "card row", onsubmit: (ev) => { ev.preventDefault(); load(); },
      },
      h("div", { style: "flex:1;min-width:140px" }, h("label", { for: "a-from" }, "Başlangıç"), fromInput),
      h("div", { style: "flex:1;min-width:140px" }, h("label", { for: "a-to" }, "Bitiş"), toInput),
      h("div", { style: "flex:1;min-width:160px" }, h("label", { for: "a-room" }, "Isı haritası odası"), roomSelect),
      h("div", { style: "align-self:flex-end" }, h("button", { class: "btn ghost", type: "submit" }, "Güncelle")),
      ),
      content,
    ),
  );
  roomSelect.addEventListener("change", load);
  load();
}

function stat(value, label) {
  return h("div", { class: "card stat" }, h("div", { class: "value" }, value), h("div", { class: "label" }, label));
}

function summaryCard(s) {
  const statuses = Object.entries(s.reservations_by_status).map(([k, v]) => badge(`${(STATUS[k] || [k])[0]}: ${v}`, (STATUS[k] || [])[1] || ""));
  const waits = Object.entries(s.waitlist_by_status).map(([k, v]) => badge(`${(WAIT_STATUS[k] || [k])[0]}: ${v}`));
  return h("section", { class: "stack" },
    h("h2", null, `Özet rapor · ${fmtDay(s.date_from, { day: "numeric", month: "short" })} – ${fmtDay(s.date_to, { day: "numeric", month: "short" })}`),
    h("div", { class: "grid stats" },
      stat(pct(s.occupancy_rate), "Ortalama doluluk"),
      stat(s.reserved_hours.toLocaleString("tr-TR"), "Kullanılan saat"),
      stat(pct(s.no_show_rate), "Gelmeme oranı"),
      stat(s.busiest_hour != null ? `${pad(s.busiest_hour)}:00` : "—", "En yoğun saat"),
      stat(s.busiest_weekday || "—", "En yoğun gün"),
      stat(s.total_users, "Kullanıcı"),
      stat(s.total_rooms, "Aktif oda"),
      stat(s.penalty_points_given, "Verilen ceza puanı"),
      stat(s.banned_users, "Yasaklı kullanıcı"),
    ),
    h("div", { class: "card stack" },
      h("div", null, h("div", { class: "muted small" }, "Rezervasyon durumları"), h("div", { class: "chips" }, statuses.length ? statuses : "—")),
      h("div", null, h("div", { class: "muted small" }, "Bekleme listesi"), h("div", { class: "chips" }, waits.length ? waits : "—")),
    ),
  );
}

function heatmapTable(cells) {
  if (!cells.length) return h("p", { class: "muted" }, "Bu aralıkta veri yok.");
  const hours = cells.map((c) => c.hour);
  const lo = Math.min(...hours), hi = Math.max(...hours);
  const byKey = new Map(cells.map((c) => [`${c.weekday}-${c.hour}`, c]));
  const head = h("tr", null, h("th"), Array.from({ length: hi - lo + 1 }, (_, i) => h("th", { scope: "col" }, pad(lo + i))));
  const rows = WEEKDAYS.map((name, wd) => h("tr", null,
    h("th", { class: "day", scope: "row", title: name }, WEEKDAYS_SHORT[wd]),
    Array.from({ length: hi - lo + 1 }, (_, i) => {
      const c = byKey.get(`${wd}-${lo + i}`);
      if (!c) return h("td", { class: "empty" });
      const rate = Math.min(1, c.occupancy_rate);
      return h("td", {
        class: rate > 0.55 ? "hot" : "",
        style: `--rate:${rate}`,
        title: `${name} ${pad(c.hour)}:00 · doluluk ${pct(rate)} (${c.reserved_hours}/${c.capacity_hours} saat)`,
      }, Math.round(rate * 100));
    }),
  ));
  return h("div", { class: "table-wrap" }, h("table", { class: "heatmap", "aria-label": "Doluluk yüzdesi, satırlar gün, sütunlar saat" }, h("thead", null, head), h("tbody", null, rows)));
}

function roomStatsCard(stats) {
  return h("section", { class: "card" },
    h("h2", null, "Oda istatistikleri"),
    h("div", { class: "table-wrap" }, h("table", null,
      h("thead", null, h("tr", null, h("th", null, "Oda"), h("th", { class: "num" }, "Rezervasyon"), h("th", { class: "num" }, "Kullanılan saat"),
        h("th", { class: "num" }, "Doluluk"), h("th", { class: "num" }, "İptal"), h("th", { class: "num" }, "Gelmeme"), h("th", { class: "num" }, "Gelmeme oranı"))),
      h("tbody", null, stats.map((s) => h("tr", null,
        h("td", null, s.room_name), h("td", { class: "num" }, s.total_reservations), h("td", { class: "num" }, s.reserved_hours),
        h("td", { class: "num" }, pct(s.occupancy_rate)), h("td", { class: "num" }, s.cancelled), h("td", { class: "num" }, s.no_show),
        h("td", { class: "num" }, pct(s.no_show_rate)),
      ))),
    )),
  );
}

function emailCard(emails) {
  return h("section", { class: "card" },
    h("h2", null, "E-posta günlüğü"),
    h("p", { class: "muted small" }, "Son 25 bildirim. Varsayılan console modunda e-postalar gönderilmez, burada kayıt altına alınır."),
    emails.length ? h("div", { class: "table-wrap" }, h("table", null,
      h("thead", null, h("tr", null, h("th", null, "Zaman"), h("th", null, "Alıcı"), h("th", null, "Konu / içerik"), h("th", null, "Tür"), h("th", null, "Durum"))),
      h("tbody", null, emails.map((e) => h("tr", null,
        h("td", null, `${fmtDay(dayOf(e.created_at), { day: "numeric", month: "short" })} ${hm(e.created_at)}`),
        h("td", null, e.to_email),
        h("td", { class: "wrap" }, h("details", null, h("summary", null, e.subject), h("div", { class: "muted small" }, e.body))),
        h("td", null, badge(e.kind)),
        h("td", null, badge(e.status, e.status === "failed" ? "danger" : e.status === "sent" ? "ok" : "")),
      ))),
    )) : h("p", { class: "muted" }, "Henüz e-posta yok."),
  );
}

// ---------------------------------------------------------------- Yönlendirme
async function route() {
  const [, page = "rooms", a, b] = location.hash.split("/");
  if (!state.user) { renderLogin(); renderChrome(); return; }
  renderChrome();
  try {
    if (page === "me") await renderMe();
    else if (page === "admin") await renderAdmin();
    else if (page === "login") { history.replaceState(null, "", "#/rooms"); await renderRooms(null); }
    else await renderRooms(a ? Number(a) : null, b);
  } catch (err) {
    if (state.user) $("#app").replaceChildren(errorBox(err));
  }
}

window.addEventListener("hashchange", () => { closeModal(); route(); });

(async function boot() {
  state.token = store.get("studyspot_token");
  if (state.token) {
    try { await loadUser(); } catch { state.token = null; store.del("studyspot_token"); }
  }
  if (!location.hash) history.replaceState(null, "", state.user ? "#/rooms" : "#/login");
  route();
})();
