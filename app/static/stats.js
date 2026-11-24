/* StudySpot web arayüzü — Kişisel istatistikler (#/stats, "Profilim") ve oda doluluk tahmini.
 * Sunucu: GET /stats/me, GET /rooms/{id}/forecast?day=
 * app.js'teki h(), api(), t(), badge(), pct() yardımcılarını kullanır.
 */
"use strict";

const fmtHours = (x) => t("stats.hours", { n: Number(x).toLocaleString(i18n.locale, { maximumFractionDigits: 1 }) });
const hourRange = (h_) => `${pad(h_)}:00–${pad((h_ + 1) % 24)}:00`;

function meter(value, max, kind = "") {
  const ratio = max ? Math.min(1, value / max) : 0;
  return h("div", { class: `meter ${kind}`, role: "progressbar", "aria-valuemin": 0, "aria-valuemax": max, "aria-valuenow": value },
    h("i", { style: `width:${Math.round(ratio * 100)}%` }));
}

function statCard(label, value, sub, extra) {
  return h("div", { class: "card stat-card" },
    h("div", { class: "muted small" }, label),
    h("div", { class: "stat-value" }, value),
    extra,
    sub && h("div", { class: "muted small" }, sub));
}

// ---------------------------------------------------------------- Profilim
async function renderStats() {
  const main = $("#app");
  main.replaceChildren(h("p", { class: "muted" }, t("app.loading")));
  const s = await api("/stats/me");

  const weekKind = s.week_remaining_hours <= 0 ? "danger" : s.week_used_hours / s.week_limit_hours >= 0.75 ? "warn" : "ok";
  const dayKind = s.day_used_hours >= s.day_limit_hours ? "danger" : "ok";
  const penaltyKind = s.banned_until ? "danger" : s.penalty_points ? "warn" : "ok";
  const cards = h("div", { class: "grid stats-grid" },
    statCard(t("stats.week"), `${fmtHours(s.week_used_hours)} / ${fmtHours(s.week_limit_hours)}`,
      t("stats.weekRemaining", { n: fmtHours(s.week_remaining_hours) }), meter(s.week_used_hours, s.week_limit_hours, weekKind)),
    statCard(t("stats.today"), `${fmtHours(s.day_used_hours)} / ${fmtHours(s.day_limit_hours)}`,
      null, meter(s.day_used_hours, s.day_limit_hours, dayKind)),
    statCard(t("stats.attendance"), s.attendance_rate == null ? "—" : pct(s.attendance_rate),
      t("stats.attendanceSub", { attended: fmtNum(s.attended), noShow: fmtNum(s.no_show) })),
    statCard(t("stats.studied"), fmtHours(s.attended_hours),
      t("stats.studiedSub", { n: fmtNum(s.attended), cancelled: fmtNum(s.cancelled) })),
    statCard(t("stats.streak"), s.streak_weeks ? `🔥 ${t("stats.weeks", { n: s.streak_weeks })}` : "—", t("stats.streakSub")),
    statCard(t("stats.penalty"), `${s.penalty_points} / ${s.penalty_threshold}`,
      s.banned_until ? t("me.bannedUntil", { date: fmtDateTime(s.banned_until) }) : t("stats.penaltySub", { n: s.penalty_threshold }),
      meter(s.penalty_points, s.penalty_threshold, penaltyKind)),
  );

  const favorites = h("section", { class: "card" },
    h("h2", null, t("stats.habits")),
    s.favorite_room
      ? h("div", { class: "habit-list" },
        habit("🏠", t("stats.favRoom"), s.favorite_room.room_name, t("stats.favRoomSub", { n: fmtHours(s.favorite_room.hours) }),
          `#/rooms/${s.favorite_room.room_id}/${today()}`),
        habit("🕑", t("stats.favHour"), hourRange(s.favorite_hour)),
        habit("📅", t("stats.favDay"), weekdayName(s.favorite_weekday)),
        habit("📌", t("stats.upcoming"), t("stats.upcomingN", { n: fmtNum(s.upcoming) }), null, "#/me"))
      : h("p", { class: "muted" }, t("stats.noHabits")),
  );

  main.replaceChildren(
    h("div", { class: "stack" },
      h("div", null, h("h1", null, t("stats.title")), h("p", { class: "muted" }, t("stats.lead"))),
      cards,
      favorites,
      h("section", { class: "card" }, h("h2", null, t("stats.history")), weeklyChart(s.weekly_history, s.week_limit_hours)),
    ),
  );
}

function habit(icon, label, value, sub = null, href = null) {
  const body = h("div", null, h("div", { class: "muted small" }, label), h("b", null, value), sub && h("div", { class: "muted small" }, sub));
  return h(href ? "a" : "div", { class: "habit", href }, h("span", { class: "habit-icon", "aria-hidden": "true" }, icon), body);
}

function weeklyChart(weeks, limit) {
  const max = Math.max(limit * 1.2, ...weeks.map((w) => w.booked_hours), 1); // limit çizgisi tepeye yapışmasın
  return h("div", { class: "stack" },
    h("div", { class: "week-chart", role: "img", "aria-label": t("stats.historyAria") },
      weeks.map((w) => h("div", { class: "week-col", title: t("stats.weekTip", { booked: fmtHours(w.booked_hours), attended: fmtHours(w.attended_hours) }) },
        h("div", { class: "week-bars" },
          h("i", { class: "booked", style: `height:${(w.booked_hours / max) * 100}%` }),
          h("i", { class: "attended", style: `height:${(w.attended_hours / max) * 100}%` }),
          h("span", { class: "limit-line", style: `bottom:${(limit / max) * 100}%` })),
        h("span", { class: "small muted" }, fmtDay(w.week_start, { day: "numeric", month: "short" }))))),
    h("div", { class: "legend" },
      h("span", null, h("i", { style: "background:var(--accent)" }), t("stats.legendAttended")),
      h("span", null, h("i", { style: "background:var(--surface-2);border:1px solid var(--border)" }), t("stats.legendBooked")),
      h("span", null, h("i", { style: "background:var(--danger)" }), t("stats.legendLimit", { n: fmtHours(limit) }))),
  );
}

// ---------------------------------------------------------------- Oda doluluk tahmini
function roomForecastSection(room, day) {
  const box = h("div", null, h("p", { class: "muted small" }, t("app.loading")));
  api(`/rooms/${room.id}/forecast?day=${day}`)
    .then((f) => box.replaceChildren(forecastView(f)))
    .catch((err) => box.replaceChildren(
      err.code === "forecast_range" ? h("p", { class: "muted small" }, t("fc.outOfRange")) : errorBox(err)));
  return h("div", null, h("h3", null, t("fc.title", { day: weekdayName(weekdayOf(day)) })), box);
}

function forecastView(f) {
  if (!f.hours.length) return h("p", { class: "muted small" }, t("rooms.noSlots"));
  const best = new Set(f.best_hours);
  const bars = h("div", { class: "fc-chart", role: "list" },
    f.hours.map((x) => h("div", {
      role: "listitem",
      class: `fc-col ${x.level}${x.past ? " past" : ""}${best.has(x.hour) ? " best" : ""}`,
      title: t("fc.tip", { hour: hourRange(x.hour), expected: pct(x.expected), booked: pct(x.booked_now),
        predicted: x.predicted == null ? "—" : pct(x.predicted) }),
      "aria-label": `${hourRange(x.hour)}: ${pct(x.expected)} (${t(`fc.level.${x.level}`)})`,
    },
    h("span", { class: "fc-pct small" }, pct(x.expected)),
    h("div", { class: "fc-bar" }, h("i", { style: `height:${Math.max(4, x.expected * 100)}%` }),
      x.booked_now > 0 && h("b", { class: "fc-booked", style: `height:${x.booked_now * 100}%` })),
    h("span", { class: "small muted" }, pad(x.hour)))));
  const chips = h("div", { class: "chips" },
    f.best_hours.length ? f.best_hours.map((hr) => badge(t("fc.best", { hour: hourRange(hr) }), "ok")) : null,
    f.peak_hour != null && badge(t("fc.peak", { hour: hourRange(f.peak_hour) }), "danger"));
  const method = f.weeks_used
    ? t("fc.method", { n: f.weeks_used, day: weekdayName(f.weekday) })
    : t("fc.noHistory");
  return h("div", { class: "stack" }, bars, chips,
    h("div", { class: "legend" },
      h("span", null, h("i", { class: "fc-key low" }), t("fc.level.low")),
      h("span", null, h("i", { class: "fc-key medium" }), t("fc.level.medium")),
      h("span", null, h("i", { class: "fc-key high" }), t("fc.level.high")),
      h("span", null, h("i", { class: "fc-key booked" }), t("fc.bookedNow"))),
    h("div", { class: "muted small" }, method));
}
