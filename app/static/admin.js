/* StudySpot web arayüzü — Yönetim sekmesi (yalnızca admin).
 * Bölümler hash ile seçilir: #/admin/report | rooms | users | reservations | waitlist | holidays
 * app.js'teki h(), api(), t(), confirmModal() ve diğer yardımcıları kullanır; sunucu tarafı yetkiyi ayrıca denetler.
 */
"use strict";

const ADMIN_TABS = ["report", "rooms", "users", "reservations", "waitlist", "holidays"];
const RESERVATION_STATUSES = ["confirmed", "checked_in", "completed", "cancelled", "no_show"];
const WAIT_STATUSES = ["waiting", "promoted", "cancelled", "expired"];
const PAGE_SIZE = 100;

// Yönetim ekranlarının ortak önbelleği (her bölüm açılışında tazelenir)
const adminState = { users: [], rooms: [] };

async function loadAdminRooms() {
  adminState.rooms = await api("/rooms?include_inactive=true");
  return adminState.rooms;
}
async function loadAdminUsers() {
  adminState.users = await api("/admin/users?limit=500");
  return adminState.users;
}
const adminRoomName = (id) => (adminState.rooms.find((r) => r.id === id) || {}).name || roomName(id);
const adminUser = (id) => adminState.users.find((u) => u.id === id);
const userLabel = (id) => { const u = adminUser(id); return u ? u.full_name : t("common.userN", { id }); };
const isSelf = (u) => state.user && u.id === state.user.id;

/* Telefonda karta dönüşen tablo. columns: [{ label, cls }], rows: hücre dizileri.
 * Her hücreye data-label verilir; dar ekranda CSS bu etiketi hücrenin başında gösterir. */
function rtable(columns, rows, caption) {
  return h("div", { class: "table-wrap" }, h("table", { class: "rtable" },
    caption && h("caption", { class: "sr-only" }, caption),
    h("thead", null, h("tr", null, columns.map((c) => h("th", { class: c.cls || null, scope: "col" }, c.label)))),
    h("tbody", null, rows.map((cells) => h("tr", null, cells.map((cell, i) =>
      h("td", { class: columns[i].cls || null, "data-label": columns[i].label }, cell))))),
  ));
}

const selectOptions = (items, selected) => items.map(([value, label]) => h("option", { value, selected: String(value) === String(selected) || null }, label));
const labeled = (id, label, control, style = "flex:1;min-width:150px") => h("div", { style }, h("label", { for: id }, label), control);
const actionBtn = (label, onclick, cls = "btn ghost small", extra = {}) => h("button", { type: "button", class: cls, onclick, ...extra }, label);

// Düğmeyi işlem süresince kilitler; hata olursa toast gösterir
async function busy(button, work) {
  button.disabled = true;
  try { await work(); } catch (err) { toastError(err); } finally { button.disabled = false; }
}

// ---------------------------------------------------------------- Çerçeve
async function renderAdmin(tab) {
  const main = $("#app");
  if (!state.user || state.user.role !== "admin") {
    main.replaceChildren(h("div", { class: "alert error" }, h("b", null, t("admin.unauthorized")), t("admin.onlyAdmins")));
    return;
  }
  if (!ADMIN_TABS.includes(tab)) tab = "report";
  const nav = h("nav", { class: "subnav", "aria-label": t("admin.sections") },
    ADMIN_TABS.map((name) => h("a", { href: `#/admin/${name}`, "aria-current": name === tab ? "page" : null }, t(`admin.tab.${name}`))));
  const body = h("div", { class: "stack" }, h("p", { class: "muted" }, t("app.loading")));
  main.replaceChildren(h("div", { class: "stack" }, h("h1", null, t("admin.title")), nav, body));
  const current = nav.querySelector("[aria-current]");
  if (current) nav.scrollLeft = current.offsetLeft - nav.offsetLeft - 16;

  const renderers = {
    report: adminReport, rooms: adminRooms, users: adminUsers,
    reservations: adminReservations, waitlist: adminWaitlist, holidays: adminHolidays,
  };
  try {
    await renderers[tab](body);
  } catch (err) {
    body.replaceChildren(errorBox(err));
  }
}

// ---------------------------------------------------------------- Rapor (v2'deki özet ekranı)
async function adminReport(body) {
  await ensureRooms();
  const to = today();
  const from = addDays(to, -29);
  const fromInput = h("input", { type: "date", id: "a-from", value: from });
  const toInput = h("input", { type: "date", id: "a-to", value: to });
  const roomSelect = h("select", { id: "a-room" }, h("option", { value: "" }, t("report.allRooms")), state.rooms.map((r) => h("option", { value: r.id }, r.name)));
  const content = h("div", { class: "stack" });
  const jobsBox = h("div");
  const jobsBtn = h("button", { class: "btn", type: "button" }, t("report.runJobs"));
  jobsBtn.addEventListener("click", async () => {
    jobsBtn.disabled = true;
    try {
      const r = await api("/admin/jobs/run", { method: "POST" });
      jobsBox.replaceChildren(h("div", { class: "alert ok" }, h("b", null, t("report.jobsRan")), t("report.jobsResult", r)));
      load();
    } catch (err) { jobsBox.replaceChildren(errorBox(err)); }
    finally { jobsBtn.disabled = false; }
  });

  async function load() {
    content.replaceChildren(h("p", { class: "muted" }, t("report.preparing")));
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
          h("div", { class: "row spread" }, h("h2", null, t("report.heatTitle")),
            h("div", { class: "heat-legend" }, pct(0), h("span", { class: "ramp" }), pct(1))),
          heatmapTable(heat),
        ),
        roomStatsCard(stats),
        emailCard(emails),
      );
    } catch (err) {
      content.replaceChildren(errorBox(err));
    }
  }

  body.replaceChildren(
    h("div", { class: "row" }, jobsBtn),
    jobsBox,
    h("form", { class: "card row", onsubmit: (ev) => { ev.preventDefault(); load(); } },
      labeled("a-from", t("common.from"), fromInput, "flex:1;min-width:140px"),
      labeled("a-to", t("common.to"), toInput, "flex:1;min-width:140px"),
      labeled("a-room", t("report.heatRoom"), roomSelect, "flex:1;min-width:160px"),
      h("div", { style: "align-self:flex-end" }, h("button", { class: "btn ghost", type: "submit" }, t("common.update"))),
    ),
    content,
  );
  roomSelect.addEventListener("change", load);
  await load();
}

function stat(value, label) {
  return h("div", { class: "card stat" }, h("div", { class: "value" }, value), h("div", { class: "label" }, label));
}

function summaryCard(s) {
  const statuses = Object.entries(s.reservations_by_status).map(([k, v]) => badge(`${t(`status.${k}`)}: ${v}`, STATUS_KIND[k] || ""));
  const waits = Object.entries(s.waitlist_by_status).map(([k, v]) => badge(`${t(`wait.${k}`)}: ${v}`));
  // Sunucu en yoğun günü Türkçe adla döndürür; seçili dile çevir
  const busiestIndex = WEEKDAY_NAMES.tr.indexOf(s.busiest_weekday);
  return h("section", { class: "stack" },
    h("h2", null, t("report.summary", { from: fmtDay(s.date_from, { day: "numeric", month: "short" }), to: fmtDay(s.date_to, { day: "numeric", month: "short" }) })),
    h("div", { class: "grid stats" },
      stat(pct(s.occupancy_rate), t("report.avgOcc")),
      stat(fmtNum(s.reserved_hours), t("report.usedHours")),
      stat(pct(s.no_show_rate), t("report.noShowRate")),
      stat(s.busiest_hour != null ? `${pad(s.busiest_hour)}:00` : "—", t("report.busiestHour")),
      stat(busiestIndex >= 0 ? weekdayName(busiestIndex) : (s.busiest_weekday || "—"), t("report.busiestDay")),
      stat(s.total_users, t("report.users")),
      stat(s.total_rooms, t("report.activeRooms")),
      stat(s.penalty_points_given, t("report.penaltyGiven")),
      stat(s.banned_users, t("report.banned")),
    ),
    h("div", { class: "card stack" },
      h("div", null, h("div", { class: "muted small" }, t("report.resStatuses")), h("div", { class: "chips" }, statuses.length ? statuses : "—")),
      h("div", null, h("div", { class: "muted small" }, t("report.waitlist")), h("div", { class: "chips" }, waits.length ? waits : "—")),
    ),
  );
}

function heatmapTable(cells) {
  if (!cells.length) return h("p", { class: "muted" }, t("report.noData"));
  const hours = cells.map((c) => c.hour);
  const lo = Math.min(...hours), hi = Math.max(...hours);
  const byKey = new Map(cells.map((c) => [`${c.weekday}-${c.hour}`, c]));
  const head = h("tr", null, h("th"), Array.from({ length: hi - lo + 1 }, (_, i) => h("th", { scope: "col" }, pad(lo + i))));
  const rows = WEEKDAY_NAMES[i18n.lang].map((name, wd) => h("tr", null,
    h("th", { class: "day", scope: "row", title: name }, WEEKDAY_SHORT[i18n.lang][wd]),
    Array.from({ length: hi - lo + 1 }, (_, i) => {
      const c = byKey.get(`${wd}-${lo + i}`);
      if (!c) return h("td", { class: "empty" });
      const rate = Math.min(1, c.occupancy_rate);
      return h("td", {
        class: rate > 0.55 ? "hot" : "",
        style: `--rate:${rate}`,
        title: t("report.heatCell", { day: name, hour: pad(c.hour), rate: pct(rate), used: c.reserved_hours, cap: c.capacity_hours }),
      }, Math.round(rate * 100));
    }),
  ));
  return h("div", { class: "table-wrap" }, h("table", { class: "heatmap", "aria-label": t("report.heatAria") }, h("thead", null, head), h("tbody", null, rows)));
}

function roomStatsCard(stats) {
  return h("section", { class: "card" },
    h("h2", null, t("report.roomStats")),
    h("div", { class: "table-wrap" }, h("table", null,
      h("thead", null, h("tr", null, h("th", null, t("report.col.room")), h("th", { class: "num" }, t("report.col.res")), h("th", { class: "num" }, t("report.col.hours")),
        h("th", { class: "num" }, t("report.col.occ")), h("th", { class: "num" }, t("report.col.cancel")), h("th", { class: "num" }, t("report.col.noShow")), h("th", { class: "num" }, t("report.col.noShowRate")))),
      h("tbody", null, stats.map((s) => h("tr", null,
        h("td", null, s.room_name), h("td", { class: "num" }, s.total_reservations), h("td", { class: "num" }, fmtNum(s.reserved_hours)),
        h("td", { class: "num" }, pct(s.occupancy_rate)), h("td", { class: "num" }, s.cancelled), h("td", { class: "num" }, s.no_show),
        h("td", { class: "num" }, pct(s.no_show_rate)),
      ))),
    )),
  );
}

function emailCard(emails) {
  return h("section", { class: "card" },
    h("h2", null, t("report.emails")),
    h("p", { class: "muted small" }, t("report.emailsNote")),
    emails.length ? h("div", { class: "table-wrap" }, h("table", null,
      h("thead", null, h("tr", null, h("th", null, t("common.time")), h("th", null, t("report.col.to")), h("th", null, t("report.col.subject")), h("th", null, t("report.col.kind")), h("th", null, t("common.status")))),
      h("tbody", null, emails.map((e) => h("tr", null,
        h("td", null, `${fmtDay(dayOf(e.created_at), { day: "numeric", month: "short" })} ${hm(e.created_at)}`),
        h("td", null, e.to_email),
        h("td", { class: "wrap" }, h("details", null, h("summary", null, e.subject), h("div", { class: "muted small" }, e.body))),
        h("td", null, badge(e.kind)),
        h("td", null, badge(e.status, e.status === "failed" ? "danger" : e.status === "sent" ? "ok" : "")),
      ))),
    )) : h("p", { class: "muted" }, t("report.noEmails")),
  );
}

// ---------------------------------------------------------------- Odalar
async function adminRooms(body) {
  const rooms = await loadAdminRooms();
  const reload = () => adminRooms(body);
  const hours = (r) => t("ar.hours", { open: r.open_time.slice(0, 5), close: r.close_time.slice(0, 5) });

  const rows = rooms.map((r) => [
    h("div", null, h("b", null, r.name), h("div", { class: "muted small" }, r.location || "—")),
    h("div", { class: "chips" }, badge(t(`type.${r.room_type}`)), badge(t(`mode.${r.booking_mode}`), r.booking_mode === "shared" ? "mine" : "")),
    r.booking_mode === "shared" ? `${r.capacity} · ${t("ar.f.seats_per_row").toLowerCase()} ${r.seats_per_row}` : String(r.capacity),
    `${hours(r)} · ${t("common.minutes", { n: r.slot_minutes })}`,
    r.is_active ? badge(t("ar.active"), "ok") : badge(t("ar.inactive"), "danger"),
    h("div", { class: "row" },
      actionBtn(t("ar.edit"), () => openRoomForm(r, reload)),
      r.is_active
        ? actionBtn(t("ar.close"), (ev) => closeRoom(r, ev.currentTarget, reload), "btn danger small")
        : actionBtn(t("ar.reopen"), (ev) => reopenRoom(r, ev.currentTarget, reload), "btn small"),
    ),
  ]);

  body.replaceChildren(
    h("div", { class: "row spread" },
      h("p", { class: "muted small", style: "flex:1;min-width:220px;margin:0" }, t("ar.lead")),
      h("button", { class: "btn", type: "button", onclick: () => openRoomForm(null, reload) }, `+ ${t("ar.new")}`),
    ),
    h("section", { class: "card" }, rooms.length
      ? rtable([
        { label: t("common.room") }, { label: t("ar.col.kind") }, { label: t("ar.f.capacity") },
        { label: t("ar.col.hours") }, { label: t("common.status") }, { label: t("common.actions") },
      ], rows)
      : h("p", { class: "muted" }, t("ar.empty"))),
  );
}

async function closeRoom(room, button, reload) {
  // Kaç rezervasyonun iptal edileceğini önceden söylemek için yaklaşan onaylı kayıtlar sayılır
  let upcoming = null;
  try {
    const query = new URLSearchParams({ room_id: room.id, status: "confirmed", date_from: today(), limit: 500 });
    const now = naive(new Date());
    upcoming = (await api(`/reservations?${query}`)).filter((r) => r.start_time > now).length;
  } catch { /* sayı alınamazsa genel uyarı gösterilir */ }
  const question = h("div", { class: "stack" },
    h("p", null, t("ar.closeAsk", { name: room.name })),
    h("p", { class: "muted small" }, upcoming === 0 ? t("ar.closeNone") : t("ar.closeUpcoming", { n: upcoming == null ? "?" : upcoming })),
  );
  if (!(await confirmModal(t("ar.closeTitle"), question, t("ar.close")))) return;
  await busy(button, async () => {
    await api(`/rooms/${room.id}`, { method: "DELETE" });
    toast(t("ar.closed", { name: room.name }));
    reload();
  });
}

async function reopenRoom(room, button, reload) {
  await busy(button, async () => {
    await api(`/rooms/${room.id}`, { method: "PATCH", json: { is_active: true } });
    toast(t("ar.reopened", { name: room.name }));
    reload();
  });
}

const ROOM_DEFAULTS = {
  name: "", location: "", description: "", room_type: "study_room", booking_mode: "exclusive",
  capacity: 4, seats_per_row: 6, open_time: "08:00", close_time: "22:00", slot_minutes: 60,
};
const ROOM_NUMBER_FIELDS = ["capacity", "seats_per_row", "slot_minutes"];

function openRoomForm(room, onSaved) {
  const original = room ? { ...room, open_time: room.open_time.slice(0, 5), close_time: room.close_time.slice(0, 5) } : ROOM_DEFAULTS;
  const controls = {};
  const errors = {};
  const fieldLabel = (name) => (STRINGS[`ar.f.${name}`] ? t(`ar.f.${name}`) : name);

  function field(name, control, help) {
    control.id = `rf-${name}`;
    control.name = name;
    controls[name] = control;
    errors[name] = h("div", { class: "field-error", id: `rf-${name}-err`, role: "alert" });
    control.setAttribute("aria-describedby", `rf-${name}-err`);
    const label = h("label", { for: control.id }, fieldLabel(name));
    return h("div", { class: "field", "data-field": name }, label, control, help && h("div", { class: "muted small" }, help), errors[name]);
  }

  const typeSelect = h("select", null, selectOptions(["study_room", "lab", "hall"].map((v) => [v, t(`type.${v}`)]), original.room_type));
  const modeSelect = h("select", null, selectOptions(["exclusive", "shared"].map((v) => [v, t(`mode.${v}`)]), original.booking_mode));
  const capacityField = field("capacity", h("input", { type: "number", min: 1, max: 1000, required: true, value: original.capacity, inputmode: "numeric" }));
  const seatsField = field("seats_per_row", h("input", { type: "number", min: 1, max: 50, required: true, value: original.seats_per_row, inputmode: "numeric" }));
  const syncMode = () => {
    const shared = modeSelect.value === "shared";
    seatsField.hidden = !shared;
    capacityField.querySelector("label").textContent = t(shared ? "ar.f.capacityShared" : "ar.f.capacity");
  };
  modeSelect.addEventListener("change", syncMode);

  const general = h("div");
  const submit = h("button", { class: "btn", type: "submit" }, room ? t("common.save") : t("ar.new"));
  const form = h("form", { class: "stack room-form", onsubmit: (ev) => { ev.preventDefault(); save(); } },
    field("name", h("input", { required: true, minlength: 2, maxlength: 100, value: original.name, autocomplete: "off" })),
    h("div", { class: "form-grid" },
      field("location", h("input", { maxlength: 200, value: original.location })),
      field("room_type", typeSelect),
    ),
    field("description", h("input", { maxlength: 500, value: original.description })),
    field("booking_mode", modeSelect, t("ar.modeHelp")),
    h("div", { class: "form-grid" }, capacityField, seatsField),
    h("div", { class: "form-grid" },
      field("open_time", h("input", { type: "time", required: true, value: original.open_time, step: 60 })),
      field("close_time", h("input", { type: "time", required: true, value: original.close_time, step: 60 })),
    ),
    field("slot_minutes", h("input", { type: "number", min: 15, max: 240, step: 5, required: true, value: original.slot_minutes, inputmode: "numeric" }), t("ar.slotHelp")),
    general,
    h("div", { class: "row" }, submit, h("button", { class: "btn ghost", type: "button", onclick: closeModal }, t("common.cancel"))),
  );
  syncMode();

  function clearErrors() {
    Object.values(errors).forEach((el) => { el.textContent = ""; });
    Object.values(controls).forEach((el) => el.removeAttribute("aria-invalid"));
    general.replaceChildren();
  }
  function showFieldError(name, message) {
    if (!errors[name]) return false;
    errors[name].textContent = message;
    controls[name].setAttribute("aria-invalid", "true");
    return true;
  }
  const focusFirstError = () => { const bad = form.querySelector("[aria-invalid=true]"); if (bad) bad.focus(); };

  async function save() {
    clearErrors();
    const values = {};
    for (const [name, control] of Object.entries(controls)) {
      values[name] = ROOM_NUMBER_FIELDS.includes(name) ? Number(control.value) : control.value.trim();
    }
    if (values.close_time <= values.open_time) {
      showFieldError("close_time", t("ar.hoursError"));
      focusFirstError();
      return;
    }
    // Düzenlemede yalnızca değişen alanlar gönderilir (PATCH)
    const payload = {};
    for (const [name, value] of Object.entries(values)) {
      if (!room || String(value) !== String(original[name])) payload[name] = value;
    }
    if (room && !Object.keys(payload).length) { toast(t("ar.noChanges")); closeModal(); return; }

    submit.disabled = true;
    try {
      const saved = room
        ? await api(`/rooms/${room.id}`, { method: "PATCH", json: payload })
        : await api("/rooms", { method: "POST", json: payload });
      toast(t(room ? "ar.saved" : "ar.created", { name: saved.name }));
      closeModal();
      onSaved();
    } catch (err) {
      submit.disabled = false;
      if (err.status === 409) {
        showFieldError("name", t("ar.nameTaken"));
      } else if (err.status === 422 && Array.isArray(err.body.detail)) {
        // Pydantic hataları: her mesajı ilgili alanın altına yaz, alanı olmayanları genel kutuya
        const rest = err.body.detail.filter((d) => {
          const name = errorField(d);
          const target = name === "body" || name === "__root__" ? "close_time" : name;
          return !showFieldError(target, validationMessage(d));
        });
        if (rest.length) general.replaceChildren(errorBox(new ApiError(422, { detail: rest }), fieldLabel));
      } else if (err.status === 422) {
        // update_room'daki saat kontrolü düz metin döner
        showFieldError("close_time", errorDetail(null, err.body.detail)) || general.replaceChildren(errorBox(err, fieldLabel));
      } else {
        general.replaceChildren(errorBox(err, fieldLabel));
      }
      focusFirstError();
    }
  }

  openModal(room ? t("ar.editTitle", { name: room.name }) : t("ar.createTitle"), form);
  controls.name.focus();
}

// ---------------------------------------------------------------- Kullanıcılar
async function adminUsers(body) {
  const [users, penalties] = await Promise.all([loadAdminUsers(), api("/admin/penalties?limit=100")]);
  const reload = () => adminUsers(body);
  const now = naive(new Date());
  const search = h("input", { type: "search", id: "u-search", placeholder: t("au.search"), autocomplete: "off" });
  const listBox = h("div");
  const count = h("span", { class: "muted small" });

  const changeRole = async (u, button) => {
    const role = u.role === "admin" ? "student" : "admin";
    const question = h("div", { class: "stack" },
      h("p", null, t("au.roleAsk", { name: u.full_name, role: t(`role.${role}`) })),
      role === "admin" && h("p", { class: "muted small" }, t("au.roleAdminNote")));
    if (!(await confirmModal(t("au.roleTitle"), question, role === "admin" ? t("au.makeAdmin") : t("au.makeStudent")))) return;
    await busy(button, async () => {
      await api(`/admin/users/${u.id}`, { method: "PATCH", json: { role } });
      toast(t("au.updated", { name: u.full_name }));
      reload();
    });
  };
  const toggleActive = async (u, button) => {
    const activate = !u.is_active;
    const ok = await confirmModal(t("au.statusTitle"), t(activate ? "au.activateAsk" : "au.deactivateAsk", { name: u.full_name }),
      t(activate ? "au.activate" : "au.deactivate"), null, activate ? "btn" : "btn danger");
    if (!ok) return;
    await busy(button, async () => {
      await api(`/admin/users/${u.id}`, { method: "PATCH", json: { is_active: activate } });
      toast(t("au.updated", { name: u.full_name }));
      reload();
    });
  };
  const resetPenalty = async (u, button) => {
    if (!(await confirmModal(t("au.resetTitle"), t("au.resetAsk", {
      name: u.full_name, n: u.penalty_points,
      ban: u.banned_until && u.banned_until > naive(new Date()) ? t("au.resetBan", { date: fmtDateTime(u.banned_until) }) : "",
    }), t("au.resetPenalty")))) return;
    await busy(button, async () => {
      await api(`/admin/users/${u.id}/reset-penalty`, { method: "POST" });
      toast(t("au.reset", { name: u.full_name }));
      reload();
    });
  };

  function userRow(u) {
    const self = isSelf(u);
    const banned = u.banned_until && u.banned_until > now;
    const lock = self ? { disabled: true, title: t("au.self") } : {};
    return [
      h("div", null, h("b", null, u.full_name), self && badge(t("common.you"), "mine"), h("div", { class: "muted small" }, u.email)),
      badge(t(`role.${u.role}`), u.role === "admin" ? "mine" : ""),
      u.is_active ? badge(t("au.active"), "ok") : badge(t("au.inactive"), "danger"),
      badge(String(u.penalty_points), u.penalty_points ? "warn" : ""),
      banned ? badge(fmtDateTime(u.banned_until), "danger") : h("span", { class: "muted small" }, t("au.notBanned")),
      h("div", { class: "row" },
        actionBtn(u.role === "admin" ? t("au.makeStudent") : t("au.makeAdmin"), (ev) => changeRole(u, ev.currentTarget), "btn ghost small", lock),
        actionBtn(u.is_active ? t("au.deactivate") : t("au.activate"), (ev) => toggleActive(u, ev.currentTarget),
          u.is_active ? "btn danger small" : "btn small", lock),
        actionBtn(t("au.resetPenalty"), (ev) => resetPenalty(u, ev.currentTarget), "btn ghost small",
          { disabled: !(u.penalty_points || u.banned_until) || null }),
        actionBtn(t("au.penaltyLog"), () => showPenaltyLog(u)),
      ),
    ];
  }

  function renderList() {
    const q = search.value.trim().toLocaleLowerCase(i18n.locale);
    const shown = users.filter((u) => !q || `${u.full_name} ${u.email}`.toLocaleLowerCase(i18n.locale).includes(q));
    count.textContent = t("au.count", { n: shown.length });
    listBox.replaceChildren(shown.length
      ? rtable([
        { label: t("common.user") }, { label: t("au.role") }, { label: t("common.status") },
        { label: t("au.points"), cls: "num" }, { label: t("au.bannedUntil") }, { label: t("common.actions") },
      ], shown.map(userRow))
      : h("p", { class: "muted" }, t("au.empty")));
  }
  search.addEventListener("input", renderList);

  body.replaceChildren(
    h("section", { class: "card stack" },
      h("div", { class: "row spread" }, labeled("u-search", t("au.search"), search, "flex:1;min-width:200px;max-width:420px"), count),
      listBox,
    ),
    h("section", { class: "card stack" },
      h("h2", null, t("au.logTitle")),
      penaltyTable(penalties, true),
    ),
  );
  renderList();
}

function penaltyTable(penalties, withUser) {
  if (!penalties.length) return h("p", { class: "muted" }, t("au.logEmpty"));
  const columns = [{ label: t("common.time") }, ...(withUser ? [{ label: t("common.user") }] : []),
    { label: t("au.col.points"), cls: "num" }, { label: t("au.col.reason") }, { label: t("au.col.reservation") }];
  return rtable(columns, penalties.map((p) => [
    fmtDateTime(p.created_at), ...(withUser ? [userLabel(p.user_id)] : []),
    badge(`+${p.points}`, "warn"), serverText(p.reason), p.reservation_id ? `#${p.reservation_id}` : "—",
  ]));
}

async function showPenaltyLog(u) {
  openModal(t("au.logUserTitle", { name: u.full_name }), h("p", { class: "muted" }, t("app.loading")));
  try {
    const items = await api(`/admin/penalties?user_id=${u.id}&limit=100`);
    setModalBody(h("div", { class: "stack" },
      h("div", { class: "row" }, badge(t("me.penalty", { n: u.penalty_points }), u.penalty_points ? "warn" : ""),
        u.banned_until && badge(`${t("au.bannedUntil")}: ${fmtDateTime(u.banned_until)}`, "danger")),
      penaltyTable(items, false)));
  } catch (err) { setModalBody(errorBox(err)); }
}

// ---------------------------------------------------------------- Rezervasyonlar
async function adminReservations(body) {
  await Promise.all([loadAdminRooms(), loadAdminUsers()]);
  const roomSelect = h("select", { id: "r-room" }, selectOptions([["", t("ares.allRooms")], ...adminState.rooms.map((r) => [r.id, r.name])]));
  const userSelect = h("select", { id: "r-user" }, selectOptions([["", t("ares.allUsers")], ...adminState.users.map((u) => [u.id, `${u.full_name} · ${u.email}`])]));
  const statusSelect = h("select", { id: "r-status" }, selectOptions([["", t("ares.allStatuses")], ...RESERVATION_STATUSES.map((s) => [s, t(`status.${s}`)])]));
  const fromInput = h("input", { type: "date", id: "r-from", value: addDays(today(), -7) });
  const toInput = h("input", { type: "date", id: "r-to", value: addDays(today(), BOOKING_DAYS) });
  const results = h("div", { class: "stack" });
  const feedback = h("div");
  const csvBtn = h("button", { class: "btn ghost", type: "button" }, t("ares.csv"));
  let offset = 0;
  let items = [];

  const validRange = () => {
    feedback.replaceChildren();
    if (fromInput.value && toInput.value && toInput.value < fromInput.value) {
      feedback.replaceChildren(h("div", { class: "alert error", role: "alert" }, t("ares.datesInvalid")));
      return false;
    }
    return true;
  };

  function query() {
    const q = new URLSearchParams({ limit: PAGE_SIZE, offset });
    if (roomSelect.value) q.set("room_id", roomSelect.value);
    if (userSelect.value) q.set("user_id", userSelect.value);
    if (statusSelect.value) q.set("status", statusSelect.value);
    if (fromInput.value) q.set("date_from", fromInput.value);
    if (toInput.value) q.set("date_to", toInput.value);
    return q;
  }

  async function load(append = false) {
    if (!validRange()) return;
    offset = append ? offset + PAGE_SIZE : 0;
    if (!append) results.replaceChildren(h("p", { class: "muted" }, t("app.loading")));
    try {
      const page = await api(`/reservations?${query()}`);
      items = append ? items.concat(page) : page;
      renderResults(page.length === PAGE_SIZE);
    } catch (err) { results.replaceChildren(errorBox(err)); }
  }

  const cancel = async (r, button) => {
    const reason = h("input", { id: "cancel-reason", maxlength: 200, placeholder: t("ares.reasonPh") });
    const what = `${adminRoomName(r.room_id)} · ${fmtRange(r.start_time, r.end_time)}`;
    const ok = await confirmModal(t("ares.cancelTitle"), t("ares.cancelAsk", { id: r.id, user: userLabel(r.user_id), what }),
      t("ares.cancel"), h("div", null, h("label", { for: "cancel-reason" }, t("ares.reason")), reason));
    if (!ok) return;
    const text = reason.value.trim();
    await busy(button, async () => {
      await api(`/reservations/${r.id}${text ? `?${new URLSearchParams({ reason: text })}` : ""}`, { method: "DELETE" });
      toast(t("ares.cancelled", { id: r.id }));
      load();
    });
  };

  function renderResults(hasMore) {
    if (!items.length) { results.replaceChildren(h("p", { class: "muted" }, t("ares.empty"))); return; }
    const rows = items.map((r) => {
      const u = adminUser(r.user_id);
      return [
        `#${r.id}`,
        h("div", null, h("b", null, r.room_name || adminRoomName(r.room_id)), r.seat_number && h("div", { class: "muted small" }, seatText(r))),
        h("div", null, userLabel(r.user_id), u && h("div", { class: "muted small" }, u.email)),
        fmtRange(r.start_time, r.end_time),
        h("div", null, statusBadge(r.status), r.cancel_reason && h("div", { class: "muted small" }, serverText(r.cancel_reason))),
        t(`source.${r.source}`),
        r.status === "confirmed" ? actionBtn(t("ares.cancel"), (ev) => cancel(r, ev.currentTarget), "btn danger small") : "—",
      ];
    });
    results.replaceChildren(
      h("div", { class: "muted small" }, t("ares.count", { n: items.length })),
      rtable([
        { label: t("ares.col.id") }, { label: t("common.room") }, { label: t("common.user") }, { label: t("common.time") },
        { label: t("common.status") }, { label: t("ares.col.source") }, { label: t("common.actions") },
      ], rows),
      hasMore ? h("div", null, actionBtn(t("common.more"), () => load(true), "btn ghost")) : "",
    );
  }

  csvBtn.addEventListener("click", async () => {
    if (!fromInput.value || !toInput.value) {
      feedback.replaceChildren(h("div", { class: "alert error", role: "alert" }, t("ares.csvNeedsDates")));
      return;
    }
    if (!validRange()) return;
    await busy(csvBtn, () => download(`/admin/reports/reservations.csv?${new URLSearchParams({ date_from: fromInput.value, date_to: toInput.value })}`,
      `rezervasyonlar-${fromInput.value}-${toInput.value}.csv`));
  });

  body.replaceChildren(
    h("form", { class: "card stack", onsubmit: (ev) => { ev.preventDefault(); load(); } },
      h("div", { class: "row" },
        labeled("r-room", t("common.room"), roomSelect),
        labeled("r-user", t("common.user"), userSelect, "flex:2;min-width:200px"),
        labeled("r-status", t("common.status"), statusSelect),
      ),
      h("div", { class: "row" },
        labeled("r-from", t("common.from"), fromInput, "flex:1;min-width:140px"),
        labeled("r-to", t("common.to"), toInput, "flex:1;min-width:140px"),
        h("div", { class: "row", style: "align-self:flex-end" }, h("button", { class: "btn", type: "submit" }, t("common.filter")), csvBtn),
      ),
      h("div", { class: "muted small" }, t("ares.csvNote")),
      feedback,
    ),
    h("section", { class: "card" }, results),
  );
  await load();
}

// ---------------------------------------------------------------- Bekleme listesi
async function adminWaitlist(body) {
  await Promise.all([loadAdminRooms(), loadAdminUsers()]);
  const roomSelect = h("select", { id: "w-room" }, selectOptions([["", t("ares.allRooms")], ...adminState.rooms.map((r) => [r.id, r.name])]));
  const statusSelect = h("select", { id: "w-status" }, selectOptions([["", t("aw.allStatuses")], ...WAIT_STATUSES.map((s) => [s, t(`wait.${s}`)])], "waiting"));
  const results = h("div");

  async function load() {
    const q = new URLSearchParams();
    if (roomSelect.value) q.set("room_id", roomSelect.value);
    if (statusSelect.value) q.set("status_filter", statusSelect.value);
    results.replaceChildren(h("p", { class: "muted" }, t("app.loading")));
    try {
      const entries = await api(`/waitlist?${q}`);
      results.replaceChildren(entries.length
        ? rtable([
          { label: t("ares.col.id") }, { label: t("common.room") }, { label: t("common.user") }, { label: t("common.time") },
          { label: t("common.status") }, { label: t("aw.col.position"), cls: "num" }, { label: t("aw.col.created") }, { label: t("common.actions") },
        ], entries.map((w) => [
          `#${w.id}`, adminRoomName(w.room_id), userLabel(w.user_id), fmtRange(w.start_time, w.end_time),
          h("div", null, waitBadge(w.status), w.promoted_reservation_id && h("div", { class: "muted small" }, `→ #${w.promoted_reservation_id}`)),
          w.position ? String(w.position) : "—",
          fmtDateTime(w.created_at),
          w.status === "waiting" ? actionBtn(t("aw.remove"), (ev) => remove(w, ev.currentTarget), "btn danger small") : "—",
        ]))
        : h("p", { class: "muted" }, t("aw.empty")));
    } catch (err) { results.replaceChildren(errorBox(err)); }
  }

  const remove = async (w, button) => {
    const ok = await confirmModal(t("aw.removeTitle"),
      t("aw.removeAsk", { user: userLabel(w.user_id), room: adminRoomName(w.room_id), what: fmtRange(w.start_time, w.end_time) }), t("aw.remove"));
    if (!ok) return;
    await busy(button, async () => {
      await api(`/waitlist/${w.id}`, { method: "DELETE" });
      toast(t("aw.removed"));
      load();
    });
  };

  roomSelect.addEventListener("change", load);
  statusSelect.addEventListener("change", load);
  body.replaceChildren(
    h("div", { class: "card row" }, labeled("w-room", t("common.room"), roomSelect), labeled("w-status", t("common.status"), statusSelect)),
    h("section", { class: "card" }, results),
  );
  await load();
}

// ---------------------------------------------------------------- Resmi tatiller
async function adminHolidays(body) {
  const year = new Date().getFullYear();
  const yearSelect = h("select", { id: "h-year" }, selectOptions([year - 1, year, year + 1].map((y) => [y, y]), year));
  const results = h("div");
  const todayIso = today();

  async function load() {
    results.replaceChildren(h("p", { class: "muted" }, t("app.loading")));
    try {
      const items = await api(`/admin/holidays/${yearSelect.value}`);
      results.replaceChildren(items.length
        ? h("div", { class: "stack" },
          h("div", { class: "muted small" }, t("ah.count", { n: items.length })),
          rtable([{ label: t("ah.col.day") }, { label: t("ah.col.name") }, { label: t("common.status") }],
            items.map((d) => [fmtDay(d.day, { weekday: "short", day: "numeric", month: "long", year: "numeric" }), d.name,
              d.day < todayIso ? badge(t("ah.past")) : badge(t("ah.upcoming"), "warn")])))
        : h("div", { class: "alert info" }, t("ah.empty")));
    } catch (err) { results.replaceChildren(errorBox(err)); }
  }
  yearSelect.addEventListener("change", load);
  body.replaceChildren(
    h("div", { class: "card row spread" },
      h("p", { class: "muted small", style: "flex:1;min-width:220px;margin:0" }, t("ah.lead")),
      labeled("h-year", t("ah.year"), yearSelect, "min-width:120px")),
    h("section", { class: "card" }, results),
  );
  await load();
}
