/* StudySpot web arayüzü — derleme adımı olmayan vanilla JS.
 * Tüm veriler mevcut /api/v1 endpoint'lerinden gelir; JWT tarayıcının localStorage'ında tutulur.
 * Sayfalar hash ile yönlendirilir: #/login, #/rooms[/<oda id>/<gün>], #/me, #/admin[/<bölüm>]
 * Sunucudaki zamanlar kampüs yerel saatinde ve tz'sizdir ("2026-03-03T10:00:00"); burada da
 * metin olarak işlenir, tarayıcının saat dilimine çevrilmez.
 * Dosyalar: i18n.js (TR/EN metinler, t()), app.js (ortak yardımcılar ve öğrenci sayfaları), admin.js (Yönetim).
 */
"use strict";

const API = "/api/v1";
const MAX_RESERVATION_MINUTES = 180; // sunucudaki MAX_RESERVATION_HOURS varsayılanı; asıl kontrol sunucuda
const BOOKING_DAYS = 14;             // MAX_ADVANCE_DAYS varsayılanı

const state = { token: null, user: null, rooms: [] };
const roomFilterState = { search: "", roomType: "", minCapacity: "", onlyAvailable: false, favoritesOnly: false };
const roomAvailabilityStatuses = new Map();
const roomAvailabilityRequested = new Set();
const roomAvailabilityPending = new Set();
const roomAvailabilityBadgeElements = new Map();
let reapplyRoomFilters = () => {};

const FIELD_KEYS = { email: "auth.email", password: "auth.password", full_name: "auth.fullName", username: "auth.email" };
const STATUS_KIND = { confirmed: "ok", checked_in: "ok", completed: "", cancelled: "danger", no_show: "danger" };
const WAIT_KIND = { waiting: "warn", promoted: "ok", cancelled: "", expired: "" };
const statusBadge = (s) => badge(t(`status.${s}`), STATUS_KIND[s] || "");
const waitBadge = (s) => badge(t(`wait.${s}`), WAIT_KIND[s] || "");

// ---------------------------------------------------------------- Yardımcılar
const $ = (sel) => document.querySelector(sel);
const normalizeRoomSearch = (value) => value.toLocaleLowerCase("tr-TR").normalize("NFD")
  .replace(/[\u0300-\u036f]/g, "").replace(/ı/g, "i");

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
const ROOM_FAVORITES_KEY = "studyspot_favorite_rooms";
const roomFavorites = new Set((store.get(ROOM_FAVORITES_KEY) || "").split(",")
  .map(Number).filter((id) => Number.isInteger(id) && id > 0));

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
  parseNaive(iso).toLocaleDateString(i18n.locale, opts);
const fmtRange = (start, end) => `${fmtDay(dayOf(start), { day: "numeric", month: "long", weekday: "short" })} · ${hm(start)}–${hm(end)}`;
const fmtDateTime = (s) => `${fmtDay(dayOf(s), { day: "numeric", month: "short", year: "numeric" })} ${hm(s)}`;
const pct = (x) => (i18n.lang === "en" ? `${Math.round(x * 100)}%` : `%${Math.round(x * 100)}`);
const fmtNum = (x) => Number(x).toLocaleString(i18n.locale);
const weekdayOf = (iso) => (parseNaive(iso).getDay() + 6) % 7; // 0 = Pazartesi (sunucuyla aynı)
const weekdayName = (i) => WEEKDAY_NAMES[i18n.lang][i];
const roomName = (id) => (state.rooms.find((r) => r.id === id) || {}).name || t("common.roomN", { id });
const fmtMinutes = (m) => [Math.floor(m / 60) && t("common.hours", { n: Math.floor(m / 60) }), m % 60 && t("common.minutes", { n: m % 60 })].filter(Boolean).join(" ");
const seatText = (r) => (r.seat_number ? t("common.seat", { n: r.seat_number }) : null);

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
    throw new ApiError(0, { detail: t("err.network") });
  }
  if (!res.ok) {
    let data = {};
    try { data = await res.json(); } catch { /* gövde JSON değil */ }
    if (res.status === 401 && state.token) {
      logout(t("err.sessionExpired"));
    }
    throw new ApiError(res.status, data);
  }
  if (raw) return res;
  const type = res.headers.get("content-type") || "";
  return type.includes("json") ? res.json() : res.text();
}

// 422 doğrulama hatasındaki alan adı (loc'un son parçası)
const errorField = (d) => d.loc[d.loc.length - 1];

function describeError(err, fieldLabel = (name) => (FIELD_KEYS[name] ? t(FIELD_KEYS[name]) : name)) {
  if (!(err instanceof ApiError)) return { title: t("err.unexpected"), detail: String(err), hint: "" };
  const detail = err.body.detail;
  if (Array.isArray(detail)) {
    // FastAPI doğrulama hatası (422): alan adlarını seçili dile çevir
    const lines = detail.map((d) => `${fieldLabel(errorField(d))}: ${validationMessage(d)}`);
    return { title: t("err.invalidInput"), detail: lines.join(" · "), hint: "" };
  }
  const fallback = err.status >= 500 ? t("err.server") : err.status === 401 ? t("err.login")
    : err.status === 403 ? t("err.forbidden") : err.status === 404 ? t("err.notFound") : t("err.failed");
  const params = { days: BOOKING_DAYS, ...(err.body.params || {}) };
  const [title, hint] = errorTexts(err.code, params) || [fallback, ""];
  return { title, detail: errorDetail(err.code, detail || err.message, params), hint };
}

function errorBox(err, fieldLabel) {
  const { title, detail, hint } = describeError(err, fieldLabel);
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
    return true;
  } catch (err) { toastError(err); return false; }
}

// ---------------------------------------------------------------- Modal
const modal = $("#modal");
function openModal(title, ...content) {
  $("#modal-title").textContent = title;
  $("#modal-body").replaceChildren(...content);
  if (!modal.open) modal.showModal();
}
const setModalBody = (...content) => $("#modal-body").replaceChildren(...content);

// Tarayıcının confirm() penceresi yerine uygulama içi onay; true/false ile çözülür.
// `extra` verilirse (ör. iptal nedeni alanı) soru ile düğmeler arasına eklenir.
function confirmModal(title, question, okLabel, extra = null, okClass = "btn danger") {
  return new Promise((resolve) => {
    let answered = false;
    const answer = (value) => { if (answered) return; answered = true; resolve(value); closeModal(); };
    modal.addEventListener("close", () => answer(false), { once: true });
    openModal(title,
      h("div", { class: "stack" },
        typeof question === "string" ? h("p", null, question) : question,
        extra,
        h("div", { class: "row" },
          h("button", { class: okClass, type: "button", onclick: () => answer(true) }, okLabel),
          h("button", { class: "btn ghost", type: "button", onclick: () => answer(false) }, t("common.cancel")),
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

// ---------------------------------------------------------------- Tema ve dil
const darkQuery = window.matchMedia("(prefers-color-scheme: dark)");
const currentTheme = () => document.documentElement.dataset.theme || (darkQuery.matches ? "dark" : "light");

function renderToggles() {
  const dark = currentTheme() === "dark";
  const themeBtn = $("#theme-toggle");
  themeBtn.textContent = dark ? "☀" : "☾";
  themeBtn.setAttribute("aria-label", t(dark ? "theme.toLight" : "theme.toDark"));
  themeBtn.title = themeBtn.getAttribute("aria-label");
  const langBtn = $("#lang-toggle");
  langBtn.textContent = t("lang.other");
  langBtn.setAttribute("aria-label", t("lang.switch"));
  langBtn.title = t("lang.switch");
}

$("#theme-toggle").addEventListener("click", () => {
  const next = currentTheme() === "dark" ? "light" : "dark";
  document.documentElement.dataset.theme = next;
  store.set("studyspot_theme", next);
  renderToggles();
});
darkQuery.addEventListener("change", renderToggles);

$("#lang-toggle").addEventListener("click", () => {
  i18n.set(i18n.lang === "en" ? "tr" : "en");
  applyStaticTexts();
  renderToggles();
  closeModal();
  route();
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
  if (logged) $("#user-name").textContent = state.user.full_name + (state.user.role === "admin" ? t("nav.adminSuffix") : "");
  const route_ = location.hash.split("/")[1] || "rooms";
  document.querySelectorAll("#nav a").forEach((a) => a.classList.toggle("active", a.dataset.route === route_));
}
$("#logout").addEventListener("click", () => logout());

// ---------------------------------------------------------------- Giriş / kayıt
function renderLogin(message) {
  const main = $("#app");
  let mode = "login";
  const box = h("div");
  const tabLogin = h("button", { type: "button", role: "tab", "aria-selected": "true", onclick: () => switchTo("login") }, t("auth.login"));
  const tabRegister = h("button", { type: "button", role: "tab", "aria-selected": "false", onclick: () => switchTo("register") }, t("auth.register"));

  function field(label, attrs) {
    const id = `f-${attrs.name}`;
    return h("div", { class: "field" }, h("label", { for: id }, label), h("input", { id, required: true, ...attrs }));
  }

  function switchTo(next) {
    mode = next;
    tabLogin.setAttribute("aria-selected", String(mode === "login"));
    tabRegister.setAttribute("aria-selected", String(mode === "register"));
    form.replaceChildren(
      ...(mode === "register" ? [field(t("auth.fullName"), { name: "full_name", autocomplete: "name", minlength: 2 })] : []),
      field(t("auth.email"), { name: "email", type: "email", autocomplete: "email" }),
      field(t("auth.password"), {
        name: "password", type: "password", minlength: mode === "register" ? 8 : null,
        autocomplete: mode === "register" ? "new-password" : "current-password",
      }),
      h("div", { class: "field" }, h("button", { class: "btn", type: "submit", style: "width:100%" }, mode === "login" ? t("auth.login") : t("auth.create"))),
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
          toast(t("auth.created"));
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
      h("div", null, h("h1", null, t("auth.title")), h("p", { class: "muted" }, t("auth.lead"))),
      message && h("div", { class: "alert info" }, message),
      h("div", { class: "card" }, h("div", { class: "tabs", role: "tablist" }, tabLogin, tabRegister), form, box),
      h("p", { class: "hint" }, t("auth.hint")),
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
  const [rooms, myRatings] = await Promise.all([ensureRooms(), api("/feedback/room-ratings/me")]);
  const myRatingsByRoom = new Map(myRatings.map((item) => [item.room_id, item]));
  const room = rooms.find((r) => r.id === roomId);
  day = day || today();
  const availabilityBadges = new Map();
  const cards = new Map();

  const list = h("div", { class: "grid rooms" },
    rooms.map((r) => {
      const placeholder = h("span", { class: "badge room-availability room-availability-loading", "aria-hidden": "true" });
      availabilityBadges.set(r.id, placeholder);
      roomAvailabilityBadgeElements.set(r.id, placeholder);
      const isFavorite = roomFavorites.has(r.id);
      const favoriteButton = h("button", {
        type: "button", class: "room-favorite-toggle", "aria-pressed": String(isFavorite),
        "aria-label": t(isFavorite ? "rooms.favorite.remove" : "rooms.favorite.add", { room: r.name }),
        title: t(isFavorite ? "rooms.favorite.remove" : "rooms.favorite.add", { room: r.name }),
        onclick: () => {
          const favorited = toggleRoomFavorite(r.id);
          const label = t(favorited ? "rooms.favorite.remove" : "rooms.favorite.add", { room: r.name });
          favoriteButton.textContent = favorited ? "★" : "☆";
          favoriteButton.setAttribute("aria-pressed", String(favorited));
          favoriteButton.setAttribute("aria-label", label);
          favoriteButton.title = label;
          if (!favorited && roomFilterState.favoritesOnly && r.id !== roomId) favoritesOnlyInput.focus();
          applyRoomFilters();
        },
      }, isFavorite ? "★" : "☆");
      const card = h("div", { class: `card room-card${r.id === roomId ? " selected" : ""}` },
        h("button", {
          type: "button", class: "room-card-open", "aria-pressed": String(r.id === roomId),
          onclick: () => {
            location.hash = r.id === roomId ? "#/rooms" : `#/rooms/${r.id}/${day}`;
          },
        },
        h("div", { class: "room-card-heading" },
          h("h3", null, r.name),
          h("div", { class: "muted small" }, r.location || "—"),
          placeholder,
        ),
        h("div", { class: "meta" },
          badge(t(`type.${r.room_type}`)),
          badge(t("common.people", { n: r.capacity })),
          badge(`${r.open_time.slice(0, 5)}–${r.close_time.slice(0, 5)}`),
          badge(r.average_rating == null
            ? t("rooms.rating.none")
            : t("rooms.rating.average", {
              rating: Number(r.average_rating).toLocaleString(i18n.locale, { minimumFractionDigits: 1, maximumFractionDigits: 1 }),
            })),
        )),
        favoriteButton,
      );
      const currentRating = myRatingsByRoom.get(r.id);
      const rateButton = h("button", {
        type: "button",
        class: "btn ghost small room-rate-button",
        onclick: (event) => {
          event.stopPropagation();
          const ratingSelect = h("select", { id: `room-rating-${r.id}`, required: true },
            [5, 4, 3, 2, 1].map((value) =>
              h("option", { value, selected: value === (currentRating ? currentRating.rating : 5) },
                t("feedback.stars", { n: value }))),
          );
          const comment = h("textarea", {
            id: `room-rating-comment-${r.id}`,
            rows: "2",
            maxlength: "1000",
            placeholder: t("feedback.commentOptional"),
          });
          comment.value = currentRating ? currentRating.comment || "" : "";
          const ratingForm = h("form", {
            class: "feedback-form room-rating-form",
            onclick: (event) => event.stopPropagation(),
            onsubmit: async (event) => {
              event.preventDefault();
              const submitButton = event.currentTarget.querySelector('button[type="submit"]');
              submitButton.disabled = true;
              try {
                await api(`/feedback/rooms/${r.id}/rating`, {
                  method: "POST",
                  json: { rating: Number(ratingSelect.value), comment: comment.value || null },
                });
                toast(t("feedback.rated"));
                await renderRooms(roomId, day);
              } catch (err) {
                submitButton.disabled = false;
                toastError(err);
              }
            },
          },
          h("label", { for: `room-rating-${r.id}` }, t("feedback.rating")),
          ratingSelect,
          h("label", { for: `room-rating-comment-${r.id}` }, t("feedback.comment")),
          comment,
          h("div", { class: "row" },
            h("button", { class: "btn small", type: "submit" }, t("feedback.submitRating")),
            h("button", {
              class: "btn ghost small",
              type: "button",
              onclick: () => { ratingForm.remove(); rateButton.hidden = false; },
            }, t("common.cancel"))),
          );
          card.append(ratingForm);
          rateButton.hidden = true;
        },
      }, t(currentRating ? "feedback.updateRoomRating" : "feedback.rateRoom"));
      card.append(rateButton);
      cards.set(r.id, card);
      return card;
    }),
  );

  const searchInput = h("input", {
    id: "rooms-filter-search", type: "search",
    placeholder: t("rooms.filter.searchPlaceholder"), value: roomFilterState.search,
  });
  const roomTypeSelect = h("select", { id: "rooms-filter-type" },
    h("option", { value: "" }, t("common.all")),
    ...[...new Set(rooms.map((r) => r.room_type))].map((type) =>
      h("option", { value: type }, t(`type.${type}`))),
  );
  roomTypeSelect.value = roomFilterState.roomType;
  const capacityInput = h("input", {
    id: "rooms-filter-capacity", type: "number", min: "1", step: "1", value: roomFilterState.minCapacity,
  });
  const availableOnlyInput = h("input", {
    id: "rooms-filter-available", type: "checkbox", checked: roomFilterState.onlyAvailable,
  });
  const favoritesOnlyInput = h("input", {
    id: "rooms-filter-favorites", type: "checkbox", checked: roomFilterState.favoritesOnly,
  });
  const resultCount = h("span", { class: "room-filter-count", "aria-live": "polite" });
  const clearButton = h("button", {
    type: "button", class: "btn ghost small", onclick: clearRoomFilters,
  }, t("rooms.filter.clear"));
  const noMatches = h("div", { class: "alert info room-filter-empty", hidden: true },
    h("span", null, t("rooms.filter.noResults")),
    h("button", { type: "button", class: "btn ghost small", onclick: clearRoomFilters }, t("rooms.filter.clear")),
  );
  const filterBar = h("section", { class: "card room-filter-bar" },
    h("div", { class: "room-filter-fields" },
      h("div", { class: "room-filter-field" },
        h("label", { for: "rooms-filter-search" }, t("rooms.filter.search")),
        searchInput,
      ),
      h("div", { class: "room-filter-field" },
        h("label", { for: "rooms-filter-type" }, t("rooms.filter.type")),
        roomTypeSelect,
      ),
      h("div", { class: "room-filter-field" },
        h("label", { for: "rooms-filter-capacity" }, t("rooms.filter.minCapacity")),
        capacityInput,
      ),
    ),
    h("div", { class: "room-filter-actions" },
      h("label", { class: "room-filter-toggle", for: "rooms-filter-available" },
        availableOnlyInput, t("rooms.filter.availableOnly")),
      h("label", { class: "room-filter-toggle", for: "rooms-filter-favorites" },
        favoritesOnlyInput, t("rooms.filter.favoritesOnly")),
      clearButton,
      resultCount,
    ),
  );

  function applyRoomFilters() {
    const query = normalizeRoomSearch(roomFilterState.search.trim());
    const minCapacity = Number(roomFilterState.minCapacity);
    let matchesCount = 0;
    for (const r of rooms) {
      const availability = roomAvailabilityStatuses.get(r.id);
      const status = availability ? availability.status : "unknown";
      const matches = (!query || normalizeRoomSearch(`${r.name} ${r.location}`).includes(query))
        && (!roomFilterState.roomType || r.room_type === roomFilterState.roomType)
        && (!roomFilterState.minCapacity || (Number.isFinite(minCapacity) && r.capacity >= minCapacity))
        && (!roomFilterState.onlyAvailable || status === "available" || status === "unknown")
        && (!roomFilterState.favoritesOnly || roomFavorites.has(r.id));
      if (matches) matchesCount++;
      cards.get(r.id).hidden = !matches && r.id !== roomId;
    }
    resultCount.textContent = t("rooms.filter.count", {
      shown: fmtNum(matchesCount), total: fmtNum(rooms.length),
    });
    noMatches.hidden = matchesCount !== 0;
    clearButton.disabled = !roomFiltersActive();
  }

  function clearRoomFilters() {
    roomFilterState.search = "";
    roomFilterState.roomType = "";
    roomFilterState.minCapacity = "";
    roomFilterState.onlyAvailable = false;
    roomFilterState.favoritesOnly = false;
    searchInput.value = "";
    roomTypeSelect.value = "";
    capacityInput.value = "";
    availableOnlyInput.checked = false;
    favoritesOnlyInput.checked = false;
    applyRoomFilters();
  }

  searchInput.addEventListener("input", () => {
    roomFilterState.search = searchInput.value;
    applyRoomFilters();
  });
  roomTypeSelect.addEventListener("change", () => {
    roomFilterState.roomType = roomTypeSelect.value;
    applyRoomFilters();
  });
  capacityInput.addEventListener("input", () => {
    roomFilterState.minCapacity = capacityInput.value;
    applyRoomFilters();
  });
  availableOnlyInput.addEventListener("change", () => {
    roomFilterState.onlyAvailable = availableOnlyInput.checked;
    applyRoomFilters();
  });
  favoritesOnlyInput.addEventListener("change", () => {
    roomFilterState.favoritesOnly = favoritesOnlyInput.checked;
    applyRoomFilters();
  });

  const detail = h("section", { class: "card stack", id: "room-detail" });
  reapplyRoomFilters = applyRoomFilters;
  applyRoomFilters();
  main.replaceChildren(
    h("div", { class: "stack" },
      h("div", null, h("h1", null, t("rooms.title")), h("p", { class: "muted" }, t("rooms.lead"))),
      rooms.length ? filterBar : null,
      rooms.length ? noMatches : null,
      rooms.length ? list : h("div", { class: "alert info" }, t("rooms.empty")),
      room ? detail : null,
    ),
  );
  loadRoomAvailabilityBadges(rooms, availabilityBadges);
  if (!room) return;
  // Telefonda oda kartları yatay şerit: seçili kart görünür olsun
  const selected = list.querySelector('[aria-pressed="true"]');
  if (selected) list.scrollLeft = selected.offsetLeft - list.offsetLeft;
  await renderRoomDetail(detail, room, day);
}

function roomFiltersActive() {
  return Boolean(roomFilterState.search.trim() || roomFilterState.roomType
    || roomFilterState.minCapacity || roomFilterState.onlyAvailable || roomFilterState.favoritesOnly);
}

function toggleRoomFavorite(roomId) {
  if (roomFavorites.has(roomId)) roomFavorites.delete(roomId);
  else roomFavorites.add(roomId);
  store.set(ROOM_FAVORITES_KEY, [...roomFavorites].join(","));
  return roomFavorites.has(roomId);
}

function classifyRoomAvailability(room, slots) {
  const closedReasons = ["holiday", "room_inactive", "too_far"];
  if (!room.is_active || !slots.length || slots.every((slot) => closedReasons.includes(slot.reason))) {
    return { status: "closed" };
  }
  const availableSlot = slots.find((slot) => slot.available === true);
  if (availableSlot) {
    return {
      status: "available",
      time: hm(availableSlot.start_time),
      remainingSeats: availableSlot.remaining_seats,
    };
  }
  if (slots.some((slot) => slot.reason === "slot_full")) return { status: "full" };
  return { status: "closedToday" };
}

function roomAvailabilityBadge(room, availability) {
  let label, kind = "";
  if (availability.status === "available") {
    label = t("rooms.availability.availableFrom", { time: availability.time });
    kind = "ok";
  } else if (availability.status === "full") {
    label = t("rooms.availability.full");
    kind = "danger";
  } else if (availability.status === "closed") {
    label = t("rooms.availability.closed");
  } else {
    label = t("rooms.availability.closedToday");
  }
  const result = badge(label, kind);
  result.classList.add("room-availability");
  if (availability.status === "available" && room.booking_mode === "shared"
      && Number.isFinite(availability.remainingSeats)) {
    result.replaceChildren(
      h("span", null, label),
      h("span", { class: "room-availability-seats" },
        t("rooms.availability.seatsFree", { n: fmtNum(availability.remainingSeats) })),
    );
  }
  return result;
}

function loadRoomAvailabilityBadges(rooms, placeholders) {
  const day = today();
  Promise.all(rooms.map(async (room) => {
    const placeholder = placeholders.get(room.id);
    const cached = roomAvailabilityStatuses.get(room.id);
    if (cached && cached.status !== "unknown") {
      const result = roomAvailabilityBadge(room, cached);
      placeholder.replaceWith(result);
      roomAvailabilityBadgeElements.set(room.id, result);
      return;
    }
    if (roomAvailabilityRequested.has(room.id)) {
      if (!roomAvailabilityPending.has(room.id)) {
        placeholder.remove();
        roomAvailabilityBadgeElements.delete(room.id);
      }
      return;
    }

    roomAvailabilityStatuses.set(room.id, { status: "unknown" });
    roomAvailabilityRequested.add(room.id);
    roomAvailabilityPending.add(room.id);
    try {
      const slots = await api(`/rooms/${room.id}/availability?day=${day}`);
      const availability = classifyRoomAvailability(room, slots);
      roomAvailabilityStatuses.set(room.id, availability);
      roomAvailabilityPending.delete(room.id);
      const currentBadge = roomAvailabilityBadgeElements.get(room.id);
      if (currentBadge) {
        const result = roomAvailabilityBadge(room, availability);
        currentBadge.replaceWith(result);
        roomAvailabilityBadgeElements.set(room.id, result);
      }
    } catch {
      roomAvailabilityStatuses.set(room.id, { status: "unknown" });
      roomAvailabilityPending.delete(room.id);
      const currentBadge = roomAvailabilityBadgeElements.get(room.id);
      if (currentBadge) currentBadge.remove();
      roomAvailabilityBadgeElements.delete(room.id);
    } finally {
      reapplyRoomFilters();
    }
  }));
}

async function renderRoomDetail(container, room, day) {
  const days = h("div", { class: "days", role: "group", "aria-label": t("rooms.daySelect") });
  for (let i = 0; i <= BOOKING_DAYS; i++) {
    const d = addDays(today(), i);
    days.append(h("button", {
      type: "button", class: "day-btn", "aria-pressed": String(d === day),
      onclick: () => { location.hash = `#/rooms/${room.id}/${d}`; },
    }, h("span", null, i === 0 ? t("common.today") : fmtDay(d, { weekday: "short" })), h("b", null, fmtDay(d, { day: "numeric" })), h("span", null, fmtDay(d, { month: "short" }))));
  }
  const slotsBox = h("div", { class: "slots", "aria-live": "polite" }, h("p", { class: "muted" }, t("rooms.loadingSlots")));
  const quietBox = h("div", { class: "chips" });

  container.replaceChildren(
    h("div", { class: "row spread" },
      h("div", null, h("h2", null, room.name), h("div", { class: "muted small" }, [room.location, room.description].filter(Boolean).join(" · "))),
      h("div", { class: "row" }, badge(t(`mode.${room.booking_mode}`)), badge(t("common.minutesSlot", { n: room.slot_minutes }))),
    ),
    days,
    h("div", null, h("h3", null, fmtDay(day)), slotsBox),
    h("div", { class: "legend" },
      h("span", null, h("i", { style: "background:var(--ok-bg);border:1px solid var(--ok)" }), t("rooms.legendFree")),
      h("span", null, h("i", { style: "background:var(--danger-bg)" }), t("rooms.legendFull")),
      h("span", null, h("i", { style: "background:var(--mine-bg)" }), t("rooms.legendMine")),
      h("span", null, h("i", { style: "background:var(--surface-2)" }), t("rooms.legendOff")),
    ),
    h("div", null, h("h3", null, t("rooms.quietTitle", { day: weekdayName(weekdayOf(day)) })), quietBox),
  );

  api(`/rooms/${room.id}/quiet-hours?weekday=${weekdayOf(day)}&limit=5`)
    .then((cells) => quietBox.replaceChildren(
      ...(cells.length ? cells.map((c) => badge(t("rooms.quietCell", { hour: pad(c.hour), rate: pct(c.occupancy_rate) }), c.occupancy_rate < 0.25 ? "ok" : ""))
        : [h("span", { class: "muted small" }, t("rooms.quietNone"))]),
      h("div", { class: "muted small", style: "flex-basis:100%" }, t("rooms.quietNote")),
    ))
    .catch(() => quietBox.replaceChildren(h("span", { class: "muted small" }, t("rooms.quietError"))));

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
  if (!slots.length) { box.replaceChildren(h("p", { class: "muted" }, t("rooms.noSlots"))); return; }

  box.replaceChildren(...slots.map((slot, index) => {
    const own = myActive.find((r) => overlaps(r, slot));
    const queued = myWaiting.find((w) => overlaps(w, slot));
    let cls = "off", label = slot.reason ? t(`reason.${slot.reason}`) : "", onclick = null;
    if (own) {
      cls = "mine"; label = own.seat_number ? `${t("slot.yours")} · ${seatText(own)}` : t("slot.yours");
      onclick = () => { location.hash = "#/me"; };
    } else if (slot.available) {
      cls = "free";
      label = room.booking_mode === "shared" ? t("slot.seatsFree", { n: slot.remaining_seats, total: slot.total_seats }) : t("slot.free");
      onclick = () => openBookModal(room, slots, index);
    } else if (slot.reason === "slot_full") {
      cls = "full";
      label = queued ? t("slot.fullQueued") : t("slot.full");
      onclick = () => openFullModal(room, slot.start_time, slot.end_time);
    }
    return h("button", { type: "button", class: `slot ${cls}`, disabled: !onclick, onclick, "aria-label": `${hm(slot.start_time)}–${hm(slot.end_time)}: ${label}` },
      h("span", { class: "time" }, `${hm(slot.start_time)}–${hm(slot.end_time)}`),
      h("span", { class: "state" }, label),
    );
  }));
}

function refreshCurrent() { route(); }

// ---------------------------------------------------------------- Koltuk haritası
/* Koltuk bazlı odalarda seçilen aralık için koltukları ızgara olarak çizer.
 * onChange(seçilen koltuk | null): null = otomatik (sunucu ilk boş koltuğu verir). */
function seatPicker(room, onChange) {
  let selected = null;
  let requestId = 0;
  const info = h("div", { class: "muted small", "aria-live": "polite" });
  const grid = h("div", { class: "seat-grid", role: "group", "aria-label": t("seat.title") });
  const autoBtn = h("button", { type: "button", class: "btn ghost small", "aria-pressed": "true" }, t("seat.auto"));
  const chosen = h("b");

  function choose(number) {
    selected = number;
    autoBtn.setAttribute("aria-pressed", String(number == null));
    grid.querySelectorAll(".seat").forEach((el) => el.setAttribute("aria-pressed", String(Number(el.dataset.seat) === number)));
    chosen.textContent = number == null ? t("seat.auto") : t("seat.chosen", { n: number });
    onChange(number);
  }
  autoBtn.addEventListener("click", () => choose(null));

  async function load(start, end) {
    const mine = ++requestId;
    grid.replaceChildren(h("p", { class: "muted small" }, t("seat.loading")));
    try {
      const data = await api(`/rooms/${room.id}/seats?${new URLSearchParams({ start_time: start, end_time: end })}`);
      if (mine !== requestId) return; // süre değişti, eski yanıt
      grid.style.setProperty("--cols", Math.min(data.seats_per_row, data.capacity));
      grid.replaceChildren(...data.seats.map((s) => {
        const stateKey = s.mine ? "seat.mine" : s.available ? "seat.free" : "seat.taken";
        return h("button", {
          type: "button", class: `seat ${s.mine ? "mine" : s.available ? "free" : "taken"}`, "data-seat": s.number,
          disabled: !s.available, "aria-pressed": "false", "aria-label": t("seat.label", { n: s.number, state: t(stateKey) }),
          title: t("seat.label", { n: s.number, state: t(stateKey) }),
          onclick: () => choose(s.number),
        }, s.number);
      }));
      info.textContent = t("seat.remaining", { n: data.remaining_seats });
      // Seçili koltuk yeni aralıkta doluysa otomatiğe dön
      const still = data.seats.find((s) => s.number === selected && s.available);
      choose(still ? selected : null);
    } catch (err) {
      if (mine === requestId) grid.replaceChildren(errorBox(err));
    }
  }

  const element = h("div", { class: "seat-picker stack" },
    h("div", { class: "row spread" }, h("h3", { style: "margin:0" }, t("seat.title")), autoBtn),
    h("div", { class: "seat-front" }, t("seat.front")),
    grid,
    h("div", { class: "legend" },
      h("span", null, h("i", { class: "seat-key free" }), t("seat.free")),
      h("span", null, h("i", { class: "seat-key taken" }), t("seat.taken")),
      h("span", null, h("i", { class: "seat-key mine" }), t("seat.mine")),
      h("span", null, h("i", { class: "seat-key sel" }), t("seat.selected")),
    ),
    h("div", { class: "row spread" }, chosen, info),
  );
  chosen.textContent = t("seat.auto");
  return { element, load, get selected() { return selected; } };
}

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
  const select = h("select", { id: "duration" }, options.map((m) => h("option", { value: m }, fmtMinutes(m))));
  const endLabel = h("b");
  const shared = room.booking_mode === "shared";
  const picker = shared ? seatPicker(room, () => {}) : null;
  const endOf = () => addMinutes(start, Number(select.value));
  const updateEnd = () => {
    endLabel.textContent = hm(endOf());
    if (picker) picker.load(start, endOf());
  };
  select.addEventListener("change", updateEnd);
  const feedback = h("div");
  const submit = h("button", { class: "btn", type: "submit" }, t("book.submit"));

  const form = h("form", {
    class: "stack",
    onsubmit: async (ev) => {
      ev.preventDefault();
      submit.disabled = true;
      feedback.replaceChildren();
      const end = endOf();
      const payload = { room_id: room.id, start_time: start, end_time: end };
      if (picker && picker.selected != null) payload.seat_number = picker.selected;
      try {
        const reservation = await api("/reservations", { method: "POST", json: payload });
        showBooked(reservation);
      } catch (err) {
        submit.disabled = false;
        if (err.code === "slot_full") {
          openFullModal(room, start, end, err.body.suggestions);
        } else {
          feedback.replaceChildren(errorBox(err));
          if (err.code === "seat_taken" && picker) picker.load(start, end);
        }
      }
    },
  },
  h("div", null, h("div", { class: "muted small" }, room.name), h("div", null, fmtDay(dayOf(start)))),
  h("div", { class: "row" },
    h("div", { style: "flex:1;min-width:140px" }, h("label", { for: "duration" }, t("book.duration")), select),
    h("div", null, h("div", { class: "muted small" }, t("book.time")), h("div", null, `${hm(start)} – `, endLabel)),
  ),
  picker && picker.element,
  h("p", { class: "muted small" }, t("book.checkinNote")),
  feedback,
  h("div", { class: "row" }, submit, h("button", { class: "btn ghost", type: "button", onclick: closeModal }, t("common.cancel"))),
  );
  openModal(t("book.title"), form);
  updateEnd();
}

function showBooked(reservation) {
  toast(t("book.toast", { room: reservation.room_name }));
  setModalBody(
    h("div", { class: "stack" },
      h("div", { class: "alert ok" }, h("b", null, t("book.confirmed")),
        [reservation.room_name, seatText(reservation), fmtRange(reservation.start_time, reservation.end_time)].filter(Boolean).join(" · ")),
      h("div", { class: "row" },
        h("button", { class: "btn", type: "button", onclick: () => showQr(reservation) }, t("book.showQr")),
        h("button", { class: "btn ghost", type: "button", onclick: () => download(`/reservations/${reservation.id}/ics`, `rezervasyon-${reservation.id}.ics`) }, t("book.addCal")),
        h("button", { class: "btn ghost", type: "button", onclick: closeModal }, t("common.close")),
      ),
    ),
  );
  $("#modal-title").textContent = t("book.done");
  refreshCurrent();
}

async function openFullModal(room, start, end, preloaded) {
  const list = h("div", null, h("p", { class: "muted" }, t("full.computing")));
  const waitBox = h("div");
  const joinBtn = h("button", { class: "btn ghost", type: "button" }, t("full.join"));
  joinBtn.addEventListener("click", async () => {
    joinBtn.disabled = true;
    try {
      const entry = await api("/waitlist", { method: "POST", json: { room_id: room.id, start_time: start, end_time: end } });
      waitBox.replaceChildren(h("div", { class: "alert ok" }, h("b", null, t("full.queued", { n: entry.position })), t("full.queuedNote")));
      toast(t("full.joinedToast"));
      refreshCurrent();
    } catch (err) {
      joinBtn.disabled = false;
      waitBox.replaceChildren(errorBox(err));
    }
  });

  openModal(t("full.title"),
    h("div", { class: "stack" },
      h("div", { class: "alert info" }, h("b", null, `${room.name} · ${fmtRange(start, end)}`), errorTexts("slot_full")[1]),
      h("div", null, h("h3", null, t("full.suggested")), list),
      h("div", null, h("h3", null, t("full.orWait")), h("p", { class: "muted small" }, t("full.waitNote")), joinBtn, waitBox),
    ),
  );

  try {
    const query = new URLSearchParams({ room_id: room.id, start_time: start, end_time: end, limit: 5 });
    const items = preloaded || await api(`/suggestions?${query}`);
    renderSuggestions(list, items, room, start);
  } catch (err) {
    list.replaceChildren(errorBox(err));
  }
}

// Öneri gerekçeleri: Türkçede sunucunun metni, İngilizcede aynı bilgiler alanlardan yeniden kurulur
function suggestionReasons(s, requested, requestedStart) {
  if (i18n.lang !== "en") return s.reasons;
  const reasons = [];
  if (s.same_room) {
    const minutes = Math.round((parseNaive(s.start_time) - parseNaive(requestedStart)) / 60000);
    const d = fmtMinutes(Math.abs(minutes));
    reasons.push(t("sug.r.same", { delta: t(minutes > 0 ? "sug.r.later" : "sug.r.earlier", { d }) }));
  } else {
    const candidate = state.rooms.find((r) => r.id === s.room_id);
    reasons.push(t("sug.r.sameTime"));
    reasons.push(t(s.room_type === requested.room_type ? "sug.r.sameType" : "sug.r.otherType", { type: t(`type.${s.room_type}`) }));
    if (candidate) reasons.push(t("sug.r.capacity", { n: candidate.capacity, req: requested.capacity }));
  }
  reasons.push(t("sug.r.history", { rate: pct(s.historical_occupancy) }));
  const mode = (state.rooms.find((r) => r.id === s.room_id) || {}).booking_mode;
  if (mode === "shared") reasons.push(t("sug.r.seats", { n: s.remaining_seats }));
  return reasons;
}

function renderSuggestions(box, items, requested, requestedStart) {
  if (!items.length) {
    box.replaceChildren(h("p", { class: "muted" }, t("full.none")));
    return;
  }
  box.replaceChildren(...items.map((s) => {
    const button = h("button", { class: "btn", type: "button" }, t("book.submit"));
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
        h("div", { class: "row" }, h("b", null, s.room_name), badge(s.same_room ? t("sug.sameRoom") : t("sug.otherRoom"), s.same_room ? "" : "mine")),
        h("div", null, fmtRange(s.start_time, s.end_time)),
        h("div", { class: "scorebar", title: t("sug.fit", { n: pct(s.score) }) }, h("span", { style: `width:${Math.round(s.score * 100)}%` })),
        h("div", { class: "muted small" }, t("sug.scores", { score: pct(s.score), prox: pct(s.proximity_score), fit: pct(s.fit_score), quiet: pct(s.quiet_score) })),
        h("ul", null, suggestionReasons(s, requested, requestedStart).map((r) => h("li", null, r))),
      ),
      button,
      feedback,
    );
  }));
}

async function showQr(reservation) {
  openModal(t("qr.title"), h("p", { class: "muted" }, t("app.loading")));
  try {
    const res = await api(`/reservations/${reservation.id}/qr`, { raw: true });
    const url = URL.createObjectURL(await res.blob());
    setModalBody(
      h("div", { class: "stack", style: "text-align:center" },
        h("div", null, h("b", null, [reservation.room_name, seatText(reservation)].filter(Boolean).join(" · ")),
          h("div", { class: "muted small" }, fmtRange(reservation.start_time, reservation.end_time))),
        h("img", { class: "qr", src: url, alt: t("qr.alt"), "data-blob": "1" }),
        h("p", { class: "muted small" }, t("qr.note"), h("code", { class: "code" }, reservation.checkin_code)),
      ),
    );
  } catch (err) {
    setModalBody(errorBox(err));
  }
}

// ---------------------------------------------------------------- Rezervasyonlarım
async function renderMe() {
  const main = $("#app");
  main.replaceChildren(h("p", { class: "muted" }, t("app.loading")));
  const [reservations, waitlist, user, demoMode] = await Promise.all([
    api("/reservations/me"), api("/waitlist/me"), api("/auth/me"), api("/feedback/demo-mode"), ensureRooms(),
  ]);
  state.user = user;
  const now = naive(new Date());
  const active = reservations.filter((r) => (r.status === "confirmed" || r.status === "checked_in") && r.end_time > now);
  const past = reservations.filter((r) => !active.includes(r)).reverse().slice(0, 15);

  const cancel = async (r, button) => {
    const late = (parseNaive(r.start_time) - new Date()) / 60000 < 30;
    const question = late ? t("me.cancelLate") : t("me.cancelAsk", { what: `${r.room_name} · ${fmtRange(r.start_time, r.end_time)}` });
    if (!(await confirmModal(t("me.cancelTitle"), question, t("me.cancel")))) return;
    button.disabled = true;
    try {
      await api(`/reservations/${r.id}`, { method: "DELETE" });
      toast(t("me.cancelled"));
      renderMe();
    } catch (err) { button.disabled = false; toastError(err); }
  };

  const reservationItem = (r, actions, extra) => h("div", { class: "list-item" },
    h("div", null,
      h("div", { class: "row" }, h("b", null, r.room_name || roomName(r.room_id)), statusBadge(r.status),
        r.seat_number && badge(seatText(r)), r.source === "waitlist" && badge(t("source.waitlist"), "mine"),
        r.is_demo && badge(t("feedback.demo.badge"), "warn")),
      h("div", { class: "muted small" }, fmtRange(r.start_time, r.end_time)),
    ),
    actions && h("div", { class: "row" }, actions),
    extra,
  );

  const feedbackForms = (r) => {
    if (r.status !== "completed" || !r.checked_in_at) return null;
    const issue = h("textarea", { id: `issue-${r.id}`, rows: "2", maxlength: "500", minlength: "3", required: true, placeholder: t("feedback.issuePlaceholder") });
    const form = h("form", {
      class: "feedback-form",
      onsubmit: async (event) => {
        event.preventDefault();
        const button = event.currentTarget.querySelector("button");
        button.disabled = true;
        try {
          await api(`/feedback/reservations/${r.id}/issues`, { method: "POST", json: { description: issue.value } });
          issue.value = "";
          toast(t("feedback.issueReported"));
          button.disabled = false;
        } catch (err) { button.disabled = false; toastError(err); }
      },
    },
    h("label", { for: `issue-${r.id}` }, t("feedback.reportIssue")),
    issue,
    h("button", { class: "btn ghost small", type: "submit" }, t("feedback.submitIssue")));
    return h("div", { class: "feedback-actions" }, form);
  };

  const activeList = active.length
    ? active.map((r) => {
      const cancelBtn = r.status === "confirmed" && r.start_time > now
        ? h("button", { class: "btn danger small", type: "button" }, t("me.cancel")) : null;
      cancelBtn && cancelBtn.addEventListener("click", () => cancel(r, cancelBtn));
      return reservationItem(r, [
        h("button", { class: "btn small", type: "button", onclick: () => showQr(r) }, "QR"),
        h("button", { class: "btn ghost small", type: "button", onclick: () => download(`/reservations/${r.id}/ics`, `rezervasyon-${r.id}.ics`) }, ".ics"),
        cancelBtn,
      ]);
    })
    : [h("p", { class: "muted" }, t("me.noUpcoming"), h("a", { href: "#/rooms" }, t("me.pickRoom")), ".")];

  const leave = async (entry, button) => {
    button.disabled = true;
    try {
      await api(`/waitlist/${entry.id}`, { method: "DELETE" });
      toast(t("me.left"));
      renderMe();
    } catch (err) { button.disabled = false; toastError(err); }
  };
  const waitingFirst = [...waitlist].sort((a, b) => (a.status === "waiting" ? 0 : 1) - (b.status === "waiting" ? 0 : 1) || (a.start_time < b.start_time ? -1 : 1));
  const waitList = waitingFirst.length
    ? waitingFirst.slice(0, 15).map((w) => {
      const leaveBtn = w.status === "waiting" ? h("button", { class: "btn ghost small", type: "button" }, t("me.leave")) : null;
      leaveBtn && leaveBtn.addEventListener("click", () => leave(w, leaveBtn));
      return h("div", { class: "list-item" },
        h("div", null,
          h("div", { class: "row" }, h("b", null, roomName(w.room_id)), waitBadge(w.status), w.position && badge(t("me.position", { n: w.position }), "warn")),
          h("div", { class: "muted small" }, fmtRange(w.start_time, w.end_time)),
        ),
        leaveBtn,
      );
    })
    : [h("p", { class: "muted" }, t("me.noWait"))];

  const banned = user.banned_until && user.banned_until > now;
  const demoRoomSelect = h("select", { id: "feedback-demo-room" },
    state.rooms.map((room) => h("option", { value: room.id }, room.name)),
  );
  const demoPanel = demoMode.enabled && state.rooms.length
    ? h("div", { class: "feedback-demo" },
      h("p", { class: "muted small" }, t("feedback.demo.note")),
      h("div", { class: "row" },
        h("label", { for: "feedback-demo-room" }, t("feedback.demo.room")),
        demoRoomSelect,
        h("button", {
          class: "btn ghost small",
          type: "button",
          onclick: async (event) => {
            const button = event.currentTarget;
            button.disabled = true;
            try {
              await api("/feedback/demo-reservations", {
                method: "POST", json: { room_id: Number(demoRoomSelect.value) },
              });
              toast(t("feedback.demo.created"));
              await renderMe();
            } catch (err) { button.disabled = false; toastError(err); }
          },
        }, t("feedback.demo.create")),
      ),
    )
    : null;
  main.replaceChildren(
    h("div", { class: "stack" },
      h("div", { class: "row spread" },
        h("h1", null, t("me.title")),
        h("button", { class: "btn ghost", type: "button", onclick: () => download("/reservations/me/calendar.ics", "studyspot.ics") }, t("me.allCal")),
      ),
      h("div", { class: "card row spread" },
        h("div", null, h("b", null, user.full_name), h("div", { class: "muted small" }, user.email)),
        h("div", { class: "row" },
          badge(t("me.penalty", { n: user.penalty_points }), user.penalty_points ? "warn" : ""),
          banned && badge(t("me.bannedUntil", { date: `${fmtDay(dayOf(user.banned_until), { day: "numeric", month: "long" })} ${hm(user.banned_until)}` }), "danger"),
        ),
      ),
      h("section", { class: "card" }, h("h2", null, t("me.upcoming")), activeList),
      h("section", { class: "card" }, h("h2", null, t("me.waitlist")), waitList),
      h("section", { class: "card" }, h("h2", null, t("me.history")),
        demoPanel,
        past.length ? past.map((r) => reservationItem(r, null, feedbackForms(r))) : h("p", { class: "muted" }, t("me.noHistory"))),
    ),
  );
}

// ---------------------------------------------------------------- Yönlendirme
async function route() {
  const [, page = "rooms", a, b] = location.hash.split("/");
  if (!state.user) { renderLogin(); renderChrome(); return; }
  renderChrome();
  try {
    if (page === "me") await renderMe();
    else if (page === "admin") await renderAdmin(a);
    else if (page === "login") { history.replaceState(null, "", "#/rooms"); await renderRooms(null); }
    else await renderRooms(a ? Number(a) : null, b);
  } catch (err) {
    if (state.user) $("#app").replaceChildren(errorBox(err));
  }
}

window.addEventListener("hashchange", () => { closeModal(); route(); });

// admin.js da yüklendikten sonra başla (renderAdmin orada tanımlı)
window.addEventListener("DOMContentLoaded", async () => {
  applyStaticTexts();
  renderToggles();
  state.token = store.get("studyspot_token");
  if (state.token) {
    try { await loadUser(); } catch { state.token = null; store.del("studyspot_token"); }
  }
  if (!location.hash) history.replaceState(null, "", state.user ? "#/rooms" : "#/login");
  route();
});
