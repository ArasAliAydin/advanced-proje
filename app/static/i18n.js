/* StudySpot web arayüzü: Türkçe / İngilizce metinler.
 * Her anahtar [Türkçe, İngilizce] çiftidir; t("anahtar", { param }) seçili dildeki metni döndürür.
 * Metindeki {ad} yer tutucuları parametrelerle doldurulur.
 * Sunucu iş kuralı hatalarını Türkçe "detail" ve dil bağımsız "code" (+ gerekiyorsa "params") ile döndürür;
 * İngilizce arayüz mesajı koddan kendisi kurar (bkz. errorDetail).
 */
"use strict";

const LANGS = ["tr", "en"];

const STRINGS = {
  // --- Genel ---
  "app.loading": ["Yükleniyor…", "Loading…"],
  "app.home": ["StudySpot ana sayfa", "StudySpot home"],
  "app.footer": ["CEN 3001 · StudySpot v3", "CEN 3001 · StudySpot v3"],
  "app.swagger": ["API dokümantasyonu (Swagger)", "API documentation (Swagger)"],
  "nav.rooms": ["Odalar", "Rooms"],
  "nav.me": ["Rezervasyonlarım", "My reservations"],
  "nav.admin": ["Yönetim", "Admin"],
  "nav.logout": ["Çıkış", "Log out"],
  "nav.adminSuffix": [" (admin)", " (admin)"],
  "lang.switch": ["Switch to English", "Türkçeye geç"],
  "lang.other": ["EN", "TR"],
  "theme.toDark": ["Gece moduna geç", "Switch to dark mode"],
  "theme.toLight": ["Gündüz moduna geç", "Switch to light mode"],
  "modal.close": ["Kapat", "Close"],
  "common.cancel": ["Vazgeç", "Cancel"],
  "common.close": ["Kapat", "Close"],
  "common.save": ["Kaydet", "Save"],
  "common.filter": ["Filtrele", "Filter"],
  "common.update": ["Güncelle", "Refresh"],
  "common.all": ["Tümü", "All"],
  "common.none": ["—", "—"],
  "common.yes": ["Evet", "Yes"],
  "common.you": ["siz", "you"],
  "common.more": ["Daha fazla göster", "Show more"],
  "common.from": ["Başlangıç", "From"],
  "common.to": ["Bitiş", "To"],
  "common.room": ["Oda", "Room"],
  "common.user": ["Kullanıcı", "User"],
  "common.status": ["Durum", "Status"],
  "common.time": ["Zaman", "Time"],
  "common.actions": ["İşlemler", "Actions"],
  "common.seat": ["Koltuk {n}", "Seat {n}"],
  "common.roomN": ["Oda #{id}", "Room #{id}"],
  "common.userN": ["Kullanıcı #{id}", "User #{id}"],
  "common.today": ["Bugün", "Today"],
  "common.people": ["{n} kişi", "{n} people"],
  "common.minutesSlot": ["{n} dk dilim", "{n} min slots"],
  "common.hours": ["{n} saat", "{n} h"],
  "common.minutes": ["{n} dk", "{n} min"],

  // --- Hatalar ---
  "err.unexpected": ["Beklenmeyen hata", "Unexpected error"],
  "err.invalidInput": ["Girilen bilgiler geçersiz", "Invalid input"],
  "err.server": ["Sunucu hatası", "Server error"],
  "err.login": ["Giriş başarısız", "Login failed"],
  "err.forbidden": ["Yetkiniz yok", "Not allowed"],
  "err.notFound": ["Bulunamadı", "Not found"],
  "err.failed": ["İşlem yapılamadı", "Action failed"],
  "err.network": ["Sunucuya ulaşılamadı. Bağlantınızı kontrol edin.", "Could not reach the server. Check your connection."],
  "err.sessionExpired": ["Oturumunuzun süresi doldu, lütfen yeniden giriş yapın.", "Your session has expired, please log in again."],

  // --- Giriş / kayıt ---
  "auth.login": ["Giriş yap", "Log in"],
  "auth.register": ["Kayıt ol", "Sign up"],
  "auth.create": ["Hesap oluştur", "Create account"],
  "auth.fullName": ["Ad soyad", "Full name"],
  "auth.email": ["E-posta", "Email"],
  "auth.password": ["Şifre", "Password"],
  "auth.created": ["Hesabınız oluşturuldu.", "Your account has been created."],
  "auth.title": ["Çalışma odanı ayır", "Book your study room"],
  "auth.lead": ["Kütüphane odaları, laboratuvarlar ve çalışma salonları için saat bazlı rezervasyon.",
    "Hourly booking for library rooms, labs and study halls."],
  "auth.hint": ["Demo verisi yüklüyse öğrenci hesapları: ogrenci1@example.com … ogrenci6@example.com (şifre scripts/seed.py içinde). Swagger: /docs",
    "With demo data loaded, student accounts are ogrenci1@example.com … ogrenci6@example.com (password in scripts/seed.py). Swagger: /docs"],

  // --- Oda etiketleri ---
  "type.study_room": ["Grup çalışma odası", "Group study room"],
  "type.lab": ["Laboratuvar", "Lab"],
  "type.hall": ["Salon", "Hall"],
  "mode.exclusive": ["Tüm oda size ayrılır", "Whole room is yours"],
  "mode.shared": ["Koltuk bazlı", "Per seat"],
  "status.confirmed": ["Onaylı", "Confirmed"],
  "status.checked_in": ["Check-in yapıldı", "Checked in"],
  "status.completed": ["Tamamlandı", "Completed"],
  "status.cancelled": ["İptal edildi", "Cancelled"],
  "status.no_show": ["Gelinmedi", "No-show"],
  "wait.waiting": ["Beklemede", "Waiting"],
  "wait.promoted": ["Rezervasyona dönüştü", "Turned into booking"],
  "wait.cancelled": ["Sıradan çıkıldı", "Left the queue"],
  "wait.expired": ["Süresi doldu", "Expired"],
  "source.direct": ["Doğrudan", "Direct"],
  "source.waitlist": ["Bekleme listesinden", "From waitlist"],
  "role.student": ["Öğrenci", "Student"],
  "role.admin": ["Admin", "Admin"],
  "reason.in_past": ["Geçmiş", "Past"],
  "reason.too_far": ["Henüz açılmadı", "Not open yet"],
  "reason.holiday": ["Resmi tatil", "Public holiday"],
  "reason.room_inactive": ["Oda kapalı", "Room closed"],
  "reason.slot_full": ["Dolu", "Full"],

  // --- Odalar sayfası ---
  "rooms.title": ["Odalar", "Rooms"],
  "rooms.lead": ["Bir oda ve gün seçin; boş slota tıklayınca rezervasyon yapılır, dolu slotta alternatif öneriler çıkar.",
    "Pick a room and a day; click a free slot to book it, a full slot shows alternatives."],
  "rooms.empty": ["Henüz rezervasyona açık oda yok.", "No rooms are open for booking yet."],
  "rooms.daySelect": ["Gün seçimi", "Choose a day"],
  "rooms.loadingSlots": ["Slotlar yükleniyor…", "Loading slots…"],
  "rooms.noSlots": ["Bu gün için slot yok.", "No slots on this day."],
  "rooms.legendFree": ["Boş", "Free"],
  "rooms.legendFull": ["Dolu (öneri / bekleme listesi)", "Full (suggestions / waitlist)"],
  "rooms.legendMine": ["Sizin rezervasyonunuz", "Your booking"],
  "rooms.legendOff": ["Kapalı / geçmiş", "Closed / past"],
  "rooms.quietTitle": ["{day} günleri en sakin saatler", "Quietest hours on {day}s"],
  "rooms.quietCell": ["{hour}:00 · doluluk {rate}", "{hour}:00 · {rate} busy"],
  "rooms.quietNone": ["Geçmiş veri yok.", "No history yet."],
  "rooms.quietNote": ["Son 4 haftanın verisine göre.", "Based on the last 4 weeks."],
  "rooms.quietError": ["Sakin saatler alınamadı.", "Could not load quiet hours."],
  "slot.yours": ["Rezervasyonunuz", "Your booking"],
  "slot.free": ["Boş", "Free"],
  "slot.seatsFree": ["{n}/{total} koltuk boş", "{n}/{total} seats free"],
  "slot.full": ["Dolu", "Full"],
  "slot.fullQueued": ["Dolu · sıradasınız", "Full · you are queued"],

  // --- Rezervasyon akışı ---
  "book.title": ["Rezervasyon yap", "Make a booking"],
  "book.duration": ["Süre", "Duration"],
  "book.time": ["Saat", "Time"],
  "book.submit": ["Rezerve et", "Book"],
  "book.checkinNote": ["Başlangıçtan 10 dk önce ile 15 dk sonrası arasında QR kodunuzla check-in yapmanız gerekir; gelmezseniz ceza puanı yazılır.",
    "Check in with your QR code between 10 min before and 15 min after the start; no-shows get penalty points."],
  "book.done": ["Rezervasyon tamam", "Booking complete"],
  "book.confirmed": ["Rezervasyonunuz onaylandı", "Your booking is confirmed"],
  "book.toast": ["{room} rezerve edildi.", "{room} booked."],
  "book.showQr": ["QR kodunu göster", "Show QR code"],
  "book.addCal": ["Takvime ekle (.ics)", "Add to calendar (.ics)"],
  "seat.title": ["Koltuk seçin", "Choose a seat"],
  "seat.front": ["Ön · tahta", "Front · board"],
  "seat.auto": ["Otomatik (ilk boş koltuk)", "Automatic (first free seat)"],
  "seat.chosen": ["Seçilen koltuk: {n}", "Selected seat: {n}"],
  "seat.free": ["Boş", "Free"],
  "seat.taken": ["Dolu", "Taken"],
  "seat.mine": ["Sizin", "Yours"],
  "seat.selected": ["Seçili", "Selected"],
  "seat.remaining": ["Bu aralıkta {n} koltuk boş", "{n} seats free for this time"],
  "seat.label": ["Koltuk {n}: {state}", "Seat {n}: {state}"],
  "seat.loading": ["Koltuk haritası yükleniyor…", "Loading seat map…"],
  "full.title": ["Bu saat dolu", "This slot is full"],
  "full.computing": ["Alternatifler hesaplanıyor…", "Finding alternatives…"],
  "full.suggested": ["Önerilen alternatifler", "Suggested alternatives"],
  "full.orWait": ["Ya da sırada bekleyin", "Or join the queue"],
  "full.waitNote": ["Biri iptal ederse ya da gelmezse slot sıradaki ilk uygun kişiye otomatik verilir.",
    "If someone cancels or does not show up, the slot goes to the first eligible person in line."],
  "full.join": ["Bekleme listesine katıl", "Join the waitlist"],
  "full.queued": ["Sıradasınız: {n}. sıra", "You are number {n} in line"],
  "full.queuedNote": ["Slot boşalırsa rezervasyon otomatik olarak adınıza yapılır ve e-posta gelir.",
    "If the slot frees up, it is booked for you automatically and you get an email."],
  "full.joinedToast": ["Bekleme listesine katıldınız.", "You joined the waitlist."],
  "full.none": ["Kurallara uyan bir alternatif bulunamadı (limitleriniz veya o günkü doluluk nedeniyle). Bekleme listesine katılabilirsiniz.",
    "No alternative fits the rules (because of your limits or that day's demand). You can join the waitlist."],
  "sug.sameRoom": ["Aynı oda", "Same room"],
  "sug.otherRoom": ["Farklı oda", "Other room"],
  "sug.fit": ["Uygunluk {n}", "Score {n}"],
  "sug.scores": ["Uygunluk {score} · yakınlık {prox} · oda uyumu {fit} · sakinlik {quiet}",
    "Score {score} · closeness {prox} · room fit {fit} · quietness {quiet}"],
  "sug.r.same": ["Aynı oda, istenen saatten {delta}", "Same room, {delta}"],
  "sug.r.later": ["{d} sonra", "{d} later"],
  "sug.r.earlier": ["{d} önce", "{d} earlier"],
  "sug.r.sameTime": ["Aynı saat, farklı oda", "Same time, different room"],
  "sug.r.sameType": ["Aynı tipte oda ({type})", "Same room type ({type})"],
  "sug.r.otherType": ["Farklı oda tipi ({type})", "Different room type ({type})"],
  "sug.r.capacity": ["Kapasite {n} (istenen oda: {req})", "Capacity {n} (requested room: {req})"],
  "sug.r.history": ["Geçmişte bu saatlerde doluluk {rate}", "Usually {rate} busy at these hours"],
  "sug.r.seats": ["Kalan koltuk: {n}", "Seats left: {n}"],
  "qr.title": ["Check-in QR kodu", "Check-in QR code"],
  "qr.alt": ["Check-in QR kodu", "Check-in QR code"],
  "qr.note": ["Odaya geldiğinizde bu kodu görevliye okutun. Kod: ", "Show this code to the staff when you arrive. Code: "],

  // --- Rezervasyonlarım ---
  "me.title": ["Rezervasyonlarım", "My reservations"],
  "me.allCal": ["Tümünü takvime ekle (.ics)", "Add all to calendar (.ics)"],
  "me.penalty": ["Ceza puanı: {n}", "Penalty points: {n}"],
  "me.bannedUntil": ["{date} tarihine kadar yasaklı", "Banned until {date}"],
  "me.upcoming": ["Yaklaşan", "Upcoming"],
  "me.waitlist": ["Bekleme listesi", "Waitlist"],
  "me.history": ["Geçmiş ve iptaller", "History and cancellations"],
  "me.noUpcoming": ["Yaklaşan rezervasyonunuz yok. ", "You have no upcoming bookings. "],
  "me.pickRoom": ["Oda seçin", "Pick a room"],
  "me.noWait": ["Bekleme listesi kaydınız yok.", "You are not on any waitlist."],
  "me.noHistory": ["Henüz kayıt yok.", "Nothing here yet."],
  "me.cancel": ["İptal et", "Cancel"],
  "me.cancelTitle": ["Rezervasyonu iptal et", "Cancel booking"],
  "me.cancelLate": ["Başlangıca 30 dakikadan az kaldı; iptal ederseniz 1 ceza puanı yazılır. Yine de iptal edilsin mi?",
    "It starts in less than 30 minutes; cancelling now gives 1 penalty point. Cancel anyway?"],
  "me.cancelAsk": ["{what} rezervasyonu iptal edilsin mi?", "Cancel the booking {what}?"],
  "me.cancelled": ["Rezervasyon iptal edildi. Slot sıradaki kişiye açıldı.", "Booking cancelled. The slot was offered to the next person."],
  "me.leave": ["Sıradan çık", "Leave queue"],
  "me.left": ["Sıradan çıktınız.", "You left the queue."],
  "me.position": ["{n}. sıra", "#{n} in line"],

  // --- Yönetim: genel ---
  "admin.title": ["Yönetim", "Admin"],
  "admin.unauthorized": ["Yetkisiz", "Unauthorized"],
  "admin.onlyAdmins": ["Bu sayfa yalnızca yöneticilere açık.", "This page is for administrators only."],
  "admin.tab.report": ["Rapor", "Report"],
  "admin.tab.rooms": ["Odalar", "Rooms"],
  "admin.tab.users": ["Kullanıcılar", "Users"],
  "admin.tab.reservations": ["Rezervasyonlar", "Reservations"],
  "admin.tab.waitlist": ["Bekleme listesi", "Waitlist"],
  "admin.tab.holidays": ["Tatiller", "Holidays"],
  "admin.sections": ["Yönetim bölümleri", "Admin sections"],

  // --- Yönetim: rapor ---
  "report.runJobs": ["Görevleri şimdi çalıştır", "Run jobs now"],
  "report.jobsRan": ["Görevler çalıştı", "Jobs finished"],
  "report.jobsResult": ["No-show: {no_shows} · tamamlanan: {completed} · hatırlatma: {reminders} · süresi dolan sıra: {waitlist_expired}",
    "No-shows: {no_shows} · completed: {completed} · reminders: {reminders} · expired queue entries: {waitlist_expired}"],
  "report.heatRoom": ["Isı haritası odası", "Heatmap room"],
  "report.allRooms": ["Tüm odalar", "All rooms"],
  "report.preparing": ["Rapor hazırlanıyor…", "Preparing report…"],
  "report.heatTitle": ["Doluluk ısı haritası (gün × saat)", "Occupancy heatmap (day × hour)"],
  "report.summary": ["Özet rapor · {from} – {to}", "Summary · {from} – {to}"],
  "report.avgOcc": ["Ortalama doluluk", "Average occupancy"],
  "report.usedHours": ["Kullanılan saat", "Hours used"],
  "report.noShowRate": ["Gelmeme oranı", "No-show rate"],
  "report.busiestHour": ["En yoğun saat", "Busiest hour"],
  "report.busiestDay": ["En yoğun gün", "Busiest day"],
  "report.users": ["Kullanıcı", "Users"],
  "report.activeRooms": ["Aktif oda", "Active rooms"],
  "report.penaltyGiven": ["Verilen ceza puanı", "Penalty points given"],
  "report.banned": ["Yasaklı kullanıcı", "Banned users"],
  "report.resStatuses": ["Rezervasyon durumları", "Reservation statuses"],
  "report.waitlist": ["Bekleme listesi", "Waitlist"],
  "report.noData": ["Bu aralıkta veri yok.", "No data in this range."],
  "report.heatCell": ["{day} {hour}:00 · doluluk {rate} ({used}/{cap} saat)", "{day} {hour}:00 · {rate} busy ({used}/{cap} h)"],
  "report.heatAria": ["Doluluk yüzdesi, satırlar gün, sütunlar saat", "Occupancy percent, rows are days, columns are hours"],
  "report.roomStats": ["Oda istatistikleri", "Room statistics"],
  "report.col.room": ["Oda", "Room"],
  "report.col.res": ["Rezervasyon", "Bookings"],
  "report.col.hours": ["Kullanılan saat", "Hours used"],
  "report.col.occ": ["Doluluk", "Occupancy"],
  "report.col.cancel": ["İptal", "Cancelled"],
  "report.col.noShow": ["Gelmeme", "No-shows"],
  "report.col.noShowRate": ["Gelmeme oranı", "No-show rate"],
  "report.emails": ["E-posta günlüğü", "Email log"],
  "report.emailsNote": ["Son 25 bildirim. Varsayılan console modunda e-postalar gönderilmez, burada kayıt altına alınır.",
    "Last 25 notifications. In the default console mode emails are not sent, only logged here."],
  "report.col.to": ["Alıcı", "To"],
  "report.col.subject": ["Konu / içerik", "Subject / body"],
  "report.col.kind": ["Tür", "Kind"],
  "report.noEmails": ["Henüz e-posta yok.", "No emails yet."],

  // --- Yönetim: odalar ---
  "ar.new": ["Yeni oda", "New room"],
  "ar.lead": ["Kapatılan oda silinmez: rezervasyona kapanır, geçmiş kayıtlar ve raporlar korunur. İstediğiniz zaman geri açabilirsiniz.",
    "Closing a room does not delete it: it stops taking bookings and its history stays in reports. You can reopen it any time."],
  "ar.active": ["Açık", "Open"],
  "ar.inactive": ["Kapalı", "Closed"],
  "ar.edit": ["Düzenle", "Edit"],
  "ar.close": ["Kapat", "Close"],
  "ar.reopen": ["Geri aç", "Reopen"],
  "ar.empty": ["Henüz oda yok. “Yeni oda” ile ekleyin.", "No rooms yet. Add one with “New room”."],
  "ar.createTitle": ["Yeni oda", "New room"],
  "ar.editTitle": ["Odayı düzenle: {name}", "Edit room: {name}"],
  "ar.f.name": ["Oda adı", "Room name"],
  "ar.f.location": ["Konum", "Location"],
  "ar.f.description": ["Açıklama", "Description"],
  "ar.f.room_type": ["Oda tipi", "Room type"],
  "ar.f.booking_mode": ["Rezervasyon modu", "Booking mode"],
  "ar.f.capacity": ["Kapasite", "Capacity"],
  "ar.f.capacityShared": ["Koltuk sayısı", "Number of seats"],
  "ar.f.seats_per_row": ["Bir sıradaki koltuk", "Seats per row"],
  "ar.f.open_time": ["Açılış", "Opens"],
  "ar.f.close_time": ["Kapanış", "Closes"],
  "ar.f.slot_minutes": ["Slot uzunluğu (dk)", "Slot length (min)"],
  "ar.f.is_active": ["Durum", "Status"],
  "ar.modeHelp": ["Tüm oda: oda tek rezervasyona ayrılır. Koltuk bazlı: aynı anda koltuk sayısı kadar kişi, koltuk haritasından seçer.",
    "Whole room: one booking takes the room. Per seat: up to the seat count at once, each picks a seat on the map."],
  "ar.slotHelp": ["15–240 dakika. Rezervasyonlar bu dilimlere hizalanır.", "15–240 minutes. Bookings align to these slots."],
  "ar.hoursError": ["Kapanış saati açılıştan sonra olmalı.", "Closing time must be after opening time."],
  "ar.nameTaken": ["Bu isimde bir oda zaten var; başka bir ad seçin.", "A room with this name already exists; choose another name."],
  "ar.created": ["{name} eklendi.", "{name} added."],
  "ar.saved": ["{name} kaydedildi.", "{name} saved."],
  "ar.noChanges": ["Değişiklik yok.", "Nothing changed."],
  "ar.closeTitle": ["Odayı kapat", "Close room"],
  "ar.closeAsk": ["{name} rezervasyona kapatılsın mı?", "Close {name} for bookings?"],
  "ar.closeUpcoming": ["Henüz başlamamış {n} onaylı rezervasyon cezasız iptal edilecek ve sahiplerine e-posta gidecek; bekleyenler sıradan çıkarılacak.",
    "{n} upcoming confirmed bookings will be cancelled without penalty and their owners emailed; waitlist entries will be removed."],
  "ar.closeNone": ["Yaklaşan rezervasyon yok.", "There are no upcoming bookings."],
  "ar.closed": ["{name} kapatıldı.", "{name} closed."],
  "ar.reopened": ["{name} yeniden rezervasyona açıldı.", "{name} is open for bookings again."],
  "ar.hours": ["{open}–{close}", "{open}–{close}"],
  "ar.col.kind": ["Tip / mod", "Type / mode"],
  "ar.col.hours": ["Saatler · slot", "Hours · slot"],

  // --- Yönetim: kullanıcılar ---
  "au.search": ["Ad veya e-posta ara", "Search name or email"],
  "au.role": ["Rol", "Role"],
  "au.active": ["Aktif", "Active"],
  "au.inactive": ["Pasif", "Inactive"],
  "au.points": ["Ceza puanı", "Penalty points"],
  "au.bannedUntil": ["Yasak bitişi", "Ban ends"],
  "au.notBanned": ["Yasak yok", "Not banned"],
  "au.makeAdmin": ["Admin yap", "Make admin"],
  "au.makeStudent": ["Öğrenci yap", "Make student"],
  "au.deactivate": ["Pasif yap", "Deactivate"],
  "au.activate": ["Aktif yap", "Activate"],
  "au.resetPenalty": ["Cezayı sıfırla", "Reset penalty"],
  "au.penaltyLog": ["Ceza kayıtları", "Penalty log"],
  "au.self": ["Kendi hesabınızın rolünü ve durumunu değiştiremezsiniz.", "You cannot change your own role or status."],
  "au.roleTitle": ["Rolü değiştir", "Change role"],
  "au.roleAsk": ["{name} kullanıcısının rolü “{role}” yapılsın mı?", "Change {name}'s role to “{role}”?"],
  "au.roleAdminNote": ["Admin tüm odaları, kullanıcıları ve rezervasyonları yönetebilir.", "Admins can manage all rooms, users and bookings."],
  "au.statusTitle": ["Hesap durumunu değiştir", "Change account status"],
  "au.deactivateAsk": ["{name} pasif yapılsın mı? Giriş yapamaz ve rezervasyon oluşturamaz.", "Deactivate {name}? They will not be able to log in or book."],
  "au.activateAsk": ["{name} yeniden aktif yapılsın mı?", "Reactivate {name}?"],
  "au.resetTitle": ["Cezayı sıfırla", "Reset penalty"],
  "au.resetAsk": ["{name} kullanıcısının cezası sıfırlansın mı? Ceza puanı: {n} → 0{ban}.", "Reset {name}'s penalty? Points: {n} → 0{ban}."],
  "au.resetBan": ["; {date} tarihine kadar süren rezervasyon yasağı kaldırılır", "; the booking ban until {date} is lifted"],
  "au.updated": ["{name} güncellendi.", "{name} updated."],
  "au.reset": ["{name} kullanıcısının cezası sıfırlandı.", "{name}'s penalty was reset."],
  "au.empty": ["Eşleşen kullanıcı yok.", "No matching users."],
  "au.logTitle": ["Ceza kayıtları", "Penalty log"],
  "au.logUserTitle": ["Ceza kayıtları: {name}", "Penalty log: {name}"],
  "au.logEmpty": ["Ceza kaydı yok.", "No penalty records."],
  "au.col.points": ["Puan", "Points"],
  "au.col.reason": ["Neden", "Reason"],
  "au.col.reservation": ["Rezervasyon", "Booking"],
  "au.count": ["{n} kullanıcı", "{n} users"],

  // --- Yönetim: rezervasyonlar ---
  "ares.allRooms": ["Tüm odalar", "All rooms"],
  "ares.allUsers": ["Tüm kullanıcılar", "All users"],
  "ares.allStatuses": ["Tüm durumlar", "All statuses"],
  "ares.csv": ["CSV indir", "Download CSV"],
  "ares.csvNeedsDates": ["CSV için başlangıç ve bitiş tarihi seçin.", "Pick a start and end date for the CSV."],
  "ares.csvNote": ["CSV, seçilen tarih aralığındaki tüm rezervasyonları içerir (diğer filtreler uygulanmaz).",
    "The CSV contains all bookings in the selected date range (other filters are not applied)."],
  "ares.datesInvalid": ["Bitiş tarihi başlangıçtan önce olamaz.", "End date cannot be before start date."],
  "ares.count": ["{n} kayıt gösteriliyor", "Showing {n} records"],
  "ares.empty": ["Filtreye uyan rezervasyon yok.", "No bookings match the filter."],
  "ares.col.id": ["#", "#"],
  "ares.col.source": ["Kaynak", "Source"],
  "ares.cancel": ["İptal et", "Cancel"],
  "ares.cancelTitle": ["Rezervasyonu iptal et (admin)", "Cancel booking (admin)"],
  "ares.cancelAsk": ["#{id} · {user} · {what} iptal edilsin mi? Kullanıcıya e-posta gider, ceza yazılmaz, slot bekleme listesine açılır.",
    "Cancel #{id} · {user} · {what}? The user is emailed, no penalty is given and the slot goes to the waitlist."],
  "ares.reason": ["İptal nedeni (isteğe bağlı)", "Reason (optional)"],
  "ares.reasonPh": ["Ör. Oda bakımda", "E.g. Room under maintenance"],
  "ares.cancelled": ["#{id} iptal edildi.", "#{id} cancelled."],

  // --- Yönetim: bekleme listesi ---
  "aw.allStatuses": ["Tüm durumlar", "All statuses"],
  "aw.col.position": ["Sıra", "Position"],
  "aw.col.created": ["Katılma", "Joined"],
  "aw.empty": ["Bekleme listesi kaydı yok.", "No waitlist entries."],
  "aw.remove": ["Sıradan çıkar", "Remove"],
  "aw.removeTitle": ["Sıradan çıkar", "Remove from queue"],
  "aw.removeAsk": ["{user} · {room} · {what} bekleme kaydı silinsin mi?", "Remove {user}'s waitlist entry for {room} · {what}?"],
  "aw.removed": ["Bekleme kaydı kaldırıldı.", "Waitlist entry removed."],

  // --- Yönetim: tatiller ---
  "ah.year": ["Yıl", "Year"],
  "ah.lead": ["Resmi tatiller harici API'den (date.nager.at) çekilip önbelleğe alınır; bu günlerde rezervasyon yapılamaz.",
    "Public holidays are fetched from an external API (date.nager.at) and cached; bookings are blocked on these days."],
  "ah.empty": ["Bu yıl için tatil bulunamadı (harici API kapalı olabilir: HOLIDAY_CHECK_ENABLED).",
    "No holidays found for this year (the external API may be disabled: HOLIDAY_CHECK_ENABLED)."],
  "ah.col.day": ["Tarih", "Date"],
  "ah.col.name": ["Tatil", "Holiday"],
  "ah.past": ["Geçti", "Past"],
  "ah.upcoming": ["Yaklaşan", "Upcoming"],
  "ah.count": ["{n} tatil günü", "{n} holidays"],
};

// İş kuralı hataları: kısa başlık, kullanıcıya ne yapabileceğini söyleyen ipucu ve İngilizce ayrıntı.
// Türkçe ayrıntı sunucudan gelir ("detail"); İngilizcede params ile buradan kurulur.
const ERROR_TEXTS = {
  slot_full: [["Bu saat dolu", "Aşağıdaki alternatiflerden birini seçebilir ya da bekleme listesine katılabilirsiniz."],
    ["This slot is full", "Pick one of the alternatives below or join the waitlist."], "This time slot is full. You can join the waitlist."],
  seat_taken: [["Koltuk dolu", "Haritadan boş bir koltuk seçin ya da otomatik seçimi kullanın."],
    ["Seat taken", "Pick a free seat on the map or use automatic choice."], "Seat {seat} is taken for this time, choose another seat."],
  invalid_seat: [["Geçersiz koltuk", ""], ["Invalid seat", ""], "Seat number must be between 1 and {max}."],
  seat_not_applicable: [["Koltuk seçilmez", ""], ["No seat selection", ""], "This room is booked as a whole; seats are not selected."],
  user_conflict: [["Saat çakışması", "Aynı saatte başka bir rezervasyonunuz var; Rezervasyonlarım sayfasından bakabilirsiniz."],
    ["Time conflict", "You already have a booking at this time; see My reservations."], "You already have another booking in this time range."],
  daily_limit: [["Günlük limit doldu", "Başka bir gün deneyin ya da daha kısa bir süre seçin."],
    ["Daily limit reached", "Try another day or a shorter duration."], "Your daily limit is {limit} hours (used: {used} hours)."],
  weekly_limit: [["Haftalık limit doldu", "Haftalık hakkınız yenilenince (Pazartesi) tekrar deneyin."],
    ["Weekly limit reached", "Try again when your weekly quota resets (Monday)."], "Your weekly limit is {limit} hours (used: {used} hours)."],
  too_long: [["Süre çok uzun", "Daha kısa bir süre seçin."], ["Too long", "Choose a shorter duration."], "A single booking can be at most {hours} hours."],
  outside_hours: [["Çalışma saatleri dışında", "Odanın açık olduğu saatlerden birini seçin."],
    ["Outside opening hours", "Choose a time when the room is open."], "The room is only open {open}–{close}."],
  slot_misaligned: [["Saat dilimine uymuyor", "Slot tablosundaki saatlerden birini seçin."],
    ["Not aligned to slots", "Choose one of the times in the slot table."], "Times must align to {minutes}-minute slots."],
  in_past: [["Geçmiş zaman", "İleri bir saat seçin."], ["In the past", "Choose a later time."], "You cannot book a time in the past."],
  too_far: [["Çok ileri bir tarih", "En fazla {days} gün sonrasına rezervasyon yapılabilir."],
    ["Too far ahead", "You can book at most {days} days ahead."], "You can book at most {days} days ahead."],
  holiday: [["Resmi tatil", "Bu gün kampüs kapalı; başka bir gün seçin."], ["Public holiday", "Campus is closed that day; pick another day."],
    "{date} is a public holiday ({name}); bookings are not possible."],
  user_banned: [["Rezervasyon yasağı", "Ceza süreniz bitince tekrar rezervasyon yapabilirsiniz."],
    ["Booking ban", "You can book again when your penalty ends."], "Because of penalties you cannot book until {until}."],
  user_inactive: [["Hesap pasif", "Yönetici ile iletişime geçin."], ["Account inactive", "Contact an administrator."], "Your account is not active."],
  room_inactive: [["Oda kapalı", "Başka bir oda seçin."], ["Room closed", "Choose another room."], "This room is currently closed for bookings."],
  room_not_found: [["Oda bulunamadı", ""], ["Room not found", ""], "Room not found."],
  already_waiting: [["Zaten sıradasınız", "Sıra durumunuzu Rezervasyonlarım sayfasında görebilirsiniz."],
    ["Already queued", "See your position on My reservations."], "You are already on the waitlist for this time."],
  slot_available: [["Slot boşaldı", "Bekleme listesine gerek yok, doğrudan rezervasyon yapabilirsiniz."],
    ["Slot is free", "No need to queue, you can book it directly."], "This time is free, you can book it directly."],
  already_started: [["Rezervasyon başladı", "Başlamış rezervasyon iptal edilemez."], ["Already started", "A started booking cannot be cancelled."],
    "A booking that has started cannot be cancelled."],
  not_cancellable: [["İptal edilemez", "Yalnızca onaylı rezervasyonlar iptal edilebilir."],
    ["Cannot cancel", "Only confirmed bookings can be cancelled."], "Only confirmed bookings can be cancelled."],
  invalid_interval: [["Geçersiz saat aralığı", ""], ["Invalid time range", ""], "The time range is not valid."],
  not_waiting: [["Beklemede değil", ""], ["Not waiting", ""], "This entry is no longer waiting."],
  forbidden: [["Yetkiniz yok", ""], ["Not allowed", ""], "This item does not belong to you."],
  invalid_code: [["Geçersiz kod", ""], ["Invalid code", ""], "Invalid check-in code."],
  already_checked_in: [["Check-in yapılmış", ""], ["Already checked in", ""], "This booking is already checked in."],
  not_active: [["Check-in yapılamaz", ""], ["Cannot check in", ""], "This booking's status does not allow check-in."],
  too_early: [["Çok erken", ""], ["Too early", ""], "Check-in opens at {time}."],
  too_late: [["Süre doldu", ""], ["Too late", ""], "The check-in window has closed."],
};

// Kodsuz HTTP hataları (HTTPException) için Türkçe -> İngilizce
const DETAIL_EN = {
  "E-posta veya şifre hatalı": "Wrong email or password",
  "Hesabınız devre dışı bırakılmış": "Your account has been deactivated",
  "Bu e-posta adresi zaten kayıtlı": "This email address is already registered",
  "Geçersiz veya süresi dolmuş token": "Invalid or expired token",
  "Bu işlem için admin yetkisi gerekli": "Admin rights are required for this action",
  "Kullanıcı bulunamadı": "User not found",
  "Kendi rolünüzü veya durumunuzu değiştiremezsiniz": "You cannot change your own role or status",
  "Geçersiz tarih aralığı (en fazla 1 yıl)": "Invalid date range (at most 1 year)",
  "Rezervasyon bulunamadı": "Booking not found",
  "Bu rezervasyon size ait değil": "This booking does not belong to you",
  "Oda bulunamadı": "Room not found",
  "Bu isimde bir oda zaten var": "A room with this name already exists",
  "close_time, open_time'dan sonra olmalı": "Closing time must be after opening time",
  "Bekleme listesi kaydı bulunamadı": "Waitlist entry not found",
  // Ceza ve iptal nedenleri (veritabanında Türkçe saklanır)
  "Geç iptal": "Late cancellation",
  "Rezervasyona gelmeme (no-show)": "No-show",
  "Admin tarafından iptal": "Cancelled by admin",
  "Kullanıcı iptali": "Cancelled by user",
  "Oda rezervasyona kapatıldı": "Room closed for bookings",
};

// Sunucudan gelen sabit Türkçe metin (ceza/iptal nedeni vb.) için seçili dildeki karşılık
const serverText = (s) => (i18n.lang === "en" && s && DETAIL_EN[s]) || s;

const WEEKDAY_NAMES = {
  tr: ["Pazartesi", "Salı", "Çarşamba", "Perşembe", "Cuma", "Cumartesi", "Pazar"],
  en: ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"],
};
const WEEKDAY_SHORT = {
  tr: ["Pzt", "Sal", "Çar", "Per", "Cum", "Cmt", "Paz"],
  en: ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"],
};

// ---------------------------------------------------------------- Dil seçimi
const i18n = {
  lang: (() => {
    try {
      const saved = localStorage.getItem("studyspot_lang");
      if (LANGS.includes(saved)) return saved;
    } catch { /* gizli pencere vb. */ }
    return (navigator.language || "tr").toLowerCase().startsWith("tr") ? "tr" : "en";
  })(),
  get locale() { return this.lang === "en" ? "en-GB" : "tr-TR"; },
  set(lang) {
    this.lang = lang;
    try { localStorage.setItem("studyspot_lang", lang); } catch { /* yok say */ }
    document.documentElement.lang = lang;
  },
};
document.documentElement.lang = i18n.lang;

function fill(text, params) {
  return params ? text.replace(/\{(\w+)\}/g, (m, key) => (params[key] != null ? params[key] : m)) : text;
}

function t(key, params) {
  const entry = STRINGS[key];
  if (!entry) return key;
  return fill(entry[i18n.lang === "en" ? 1 : 0], params);
}

// Hata kodu için [başlık, ipucu]; bilinmeyen kodda null
function errorTexts(code, params) {
  const entry = ERROR_TEXTS[code];
  if (!entry) return null;
  const [title, hint] = entry[i18n.lang === "en" ? 1 : 0];
  return [fill(title, params), fill(hint, params)];
}

// Sunucu mesajının seçili dildeki hâli
function errorDetail(code, detail, params) {
  if (i18n.lang !== "en") return detail;
  const entry = ERROR_TEXTS[code];
  if (entry) {
    const p = { ...(params || {}) };
    if (p.until) p.until = p.until.replace("T", " ").slice(0, 16);
    return fill(entry[2], p);
  }
  if (typeof detail === "string") {
    const plain = detail.replace(/^Value error, /, "");
    return DETAIL_EN[plain] || detail;
  }
  return detail;
}

// FastAPI/Pydantic doğrulama hatası (422) için okunur mesaj. Pydantic mesajları İngilizcedir;
// Türkçe arayüzde sık görülen türler çevrilir, bilinmeyenler olduğu gibi gösterilir.
const VALIDATION_TR = {
  missing: () => "Bu alan zorunlu",
  greater_than_equal: (c) => `En az ${c.ge} olmalı`,
  greater_than: (c) => `${c.gt} değerinden büyük olmalı`,
  less_than_equal: (c) => `En fazla ${c.le} olmalı`,
  less_than: (c) => `${c.lt} değerinden küçük olmalı`,
  string_too_short: (c) => `En az ${c.min_length} karakter olmalı`,
  string_too_long: (c) => `En fazla ${c.max_length} karakter olabilir`,
  int_parsing: () => "Tam sayı girin",
  int_from_float: () => "Tam sayı girin",
  time_parsing: () => "Geçerli bir saat girin (SS:DD)",
  time_type: () => "Geçerli bir saat girin (SS:DD)",
  enum: () => "Geçersiz seçim",
  bool_parsing: () => "Evet/hayır değeri girin",
};
function validationMessage(d) {
  const msg = String(d.msg || "").replace(/^Value error, /, "");
  if (i18n.lang === "en") return DETAIL_EN[msg] || msg;
  if (d.type === "value_error" && /email/i.test(msg)) return "Geçerli bir e-posta adresi girin";
  const make = VALIDATION_TR[d.type];
  return make ? make(d.ctx || {}) : msg;
}

// index.html'deki sabit metinler: data-i18n (metin), data-i18n-aria (aria-label)
function applyStaticTexts(root = document) {
  root.querySelectorAll("[data-i18n]").forEach((el) => { el.textContent = t(el.dataset.i18n); });
  root.querySelectorAll("[data-i18n-aria]").forEach((el) => el.setAttribute("aria-label", t(el.dataset.i18nAria)));
}
