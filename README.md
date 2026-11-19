# StudySpot — Çalışma Salonu / Oda Rezervasyon Sistemi

Haliç Üniversitesi · CEN 3001 Advanced Computer Programming · Grup Projesi

Kütüphane odaları, laboratuvarlar ve çalışma salonları için saat bazlı rezervasyon platformu: REST API ve aynı API'yi kullanan web arayüzü.

> **v2 — geliştirme sürümü** (`v2` dalı). Sunum demosu `main` dalında sabit kalır; yeni özellikler burada geliştirilir.
> Docker'da **8001** portunda çalışır: <http://localhost:8001>, böylece demo sürümüyle (8000) aynı anda açık kalabilir.
> v2'de yeni: **web arayüzü** ve **akıllı slot önerisi**.

| Ortak altyapı gereksinimi | Bu projede |
|---|---|
| FastAPI + SQLModel + SQLite, Python 3.12 | `app/` — 41 endpoint, 7 tablo |
| JWT auth + rol bazlı yetkilendirme | `student` / `admin` rolleri, OAuth2 password flow |
| Pytest | `tests/` — 76 test |
| Docker | `Dockerfile`, `docker-compose.yml` |
| **Gerçek bir algoritma** | Sweep-line ile çakışma/kapasite tespiti, FIFO bekleme listesi ve otomatik atama, çok kriterli skorla akıllı slot önerisi |
| Web arayüzü | `app/static/` — HTML/CSS/vanilla JS, derleme adımı yok, FastAPI'den sunulur |
| **Harici API** | Resmi tatiller ([date.nager.at](https://date.nager.at)), DB'de önbellekli, fail-open |
| **Arka plan görevi** | Dakikada bir: no-show iptali + ceza, hatırlatma e-postası, tamamlama, sıra temizliği |

## Özellikler

- **Odalar:** iki rezervasyon modu — `exclusive` (oda tek rezervasyona kapanır) ve `shared` (koltuk bazlı, aynı anda `capacity` kadar kişi). Açılış/kapanış saati ve slot uzunluğu oda bazında. Oda kapatılınca (pasife alınınca) henüz başlamamış rezervasyonları cezasız iptal edilir ve sahiplerine e-posta gider.
- **Rezervasyon:** çakışma kontrolü, slot hizalama, çalışma saatleri, tek seferde en fazla 3 saat, en fazla 14 gün ileri, resmi tatilde kapalı.
- **Müsaitlik:** müsaitlik sorguları rezervasyon kurallarıyla tutarlıdır; tatil günleri, geçmiş ve 14 gün ötesi müsait görünmez, slotun `reason` alanı nedenini söyler (`holiday`, `in_past`, `too_far`, `slot_full`, `room_inactive`).
- **Limitler:** öğrenci başına günlük 4, haftalık 12 saat (admin muaf).
- **Bekleme listesi:** dolu slot için sıraya girilir; iptal veya no-show olunca sıradaki *uygun* kişiye rezervasyon otomatik açılır ve e-posta gider.
- **Akıllı slot önerisi:** istenen slot doluysa aynı odada aynı gün en yakın boş aralıklar (aynı süre) ve aynı saatte uygun diğer odalar önerilir. Her öneri gerçek rezervasyon kurallarından geçmiştir (saat, limit, çakışma, kalan koltuk); skor zaman yakınlığı + oda tipi/kapasite uyumu + geçmiş doluluğa (sakinlik) göredir. `409 slot_full` yanıtı önerileri `suggestions` alanında taşır. Odanın en sakin saatleri ayrıca sorgulanabilir.
- **Web arayüzü:** giriş/kayıt, oda ve gün seçerek slot tablosu, boş slota tıklayıp rezervasyon, dolu slotta öneriler (tek tıkla rezervasyon) ve bekleme listesi; Rezervasyonlarım (iptal, QR, `.ics`, sıra numaraları); admin için özet rapor, gün × saat ısı haritası, oda istatistikleri, e-posta günlüğü ve "görevleri şimdi çalıştır". İş kuralı hataları kodlarına göre başlık ve ipucuyla gösterilir; telefon genişliğinde de kullanılır.
- **QR check-in:** her rezervasyonun QR kodu (PNG) vardır. Başlangıçtan 10 dk önce açılır, 15 dk sonra kapanır (slotun bitişini aşamaz).
- **Ceza sistemi:** no-show 2 puan, geç iptal (son 30 dk) 1 puan; 6 puanda 7 gün rezervasyon yasağı. Başlangıca 30 dk veya daha az kala (ya da slot başladıktan sonra) bekleme listesinden atanan rezervasyon ceza doğurmaz: kişinin cezasız iptal etme fırsatı hiç olmamıştır.
- **Analitik:** gün × saat doluluk ısı haritası, saatlik/günlük yoğunluk, oda istatistikleri, özet rapor, CSV dışa aktarma.
- **Takvim:** tek rezervasyon veya tüm yaklaşanlar için `.ics` (Google Calendar / Outlook).
- **E-posta:** onay, hatırlatma, iptal, sıradan atama, yasak bildirimleri. Varsayılan `console` modunda gönderilmez, `EmailLog` tablosuna yazılır (`GET /admin/emails`); SMTP ayarlanırsa gerçekten gönderilir.

Tüm kural değerleri `.env` ile değiştirilebilir (bkz. `.env.example`).

## Çalıştırma

### Yerel

```bash
python -m venv .venv
.venv\Scripts\activate            # Linux/macOS: source .venv/bin/activate
pip install -r requirements-dev.txt
copy .env.example .env            # SECRET_KEY'i değiştirin (varsayılan anahtarla açılışta uyarı loglanır)
python -m scripts.seed            # isteğe bağlı: demo verisi
uvicorn app.main:app --reload
```

Web arayüzü: <http://127.0.0.1:8000/> · Swagger arayüzü: <http://127.0.0.1:8000/docs>

İlk açılışta `.env` içindeki `ADMIN_EMAIL` / `ADMIN_PASSWORD` ile bir admin hesabı oluşturulur (varsayılanlar `.env.example` içinde). Web arayüzünde bu bilgilerle giriş yapınca **Yönetim** sekmesi açılır; Swagger'da **Authorize** düğmesine e-posta ve şifreyi yazmak yeterli.

### Docker

```bash
docker compose up --build
```

Web arayüzü <http://localhost:8001>, Swagger <http://localhost:8001/docs> adresinde açılır. Veritabanı `studyspot-v2_studyspot-data` volume'ünde kalıcıdır. Demo verisi için: `docker compose exec api python -m scripts.seed` (sıfırdan: `--reset`)

### Testler

```bash
pytest
```

Testler bellek içi SQLite kullanır, zamanı sabitler (`clock.freeze`) ve harici API'yi taklit eder; internet gerektirmez.

## Mimari

```
app/
├── main.py                  # uygulama, lifespan (tablolar, admin, zamanlayıcı), hata handler'ı
├── models.py                # SQLModel tabloları
├── schemas.py               # istek/yanıt şemaları
├── core/
│   ├── config.py            # ayarlar (.env)
│   ├── database.py          # engine, oturum
│   ├── security.py          # bcrypt, JWT
│   ├── deps.py              # CurrentUser, AdminUser bağımlılıkları
│   └── clock.py             # tek zaman kaynağı (testte dondurulabilir)
├── static/                  # WEB ARAYÜZÜ: index.html, style.css, app.js (derleme yok)
├── routers/                 # ince HTTP katmanı: auth, rooms, reservations, waitlist, suggestions, analytics, admin
└── services/                # iş mantığı
    ├── scheduling.py        # ALGORİTMA: overlaps, peak_concurrency (sweep-line), hour_buckets
    ├── reservation_service.py  # kurallar, limitler, iptal, check-in
    ├── waitlist_service.py  # ALGORİTMA: FIFO sıra + otomatik atama
    ├── suggestions.py       # ALGORİTMA: akıllı slot önerisi (aday üret, kurallarla ele, skorla), sakin saatler
    ├── penalties.py         # ceza puanı, yasak
    ├── jobs.py              # ARKA PLAN GÖREVLERİ
    ├── holidays.py          # HARİCİ API + önbellek
    ├── notifications.py     # e-posta
    ├── exports.py           # .ics, QR
    └── analytics.py         # doluluk hesapları
```

### Algoritmalar

**Çakışma / kapasite tespiti** (`services/scheduling.py`). Aralıklar yarı açıktır `[başlangıç, bitiş)`. Koltuk bazlı salonlarda yalnızca çakışan rezervasyonları saymak yanlış sonuç verir: 10–11 ve 11–12 rezervasyonları 10–12 isteğiyle çakışır ama aynı koltuğu art arda kullanır. Bu yüzden istenen pencere içindeki **en yüksek eşzamanlı doluluk** sweep-line ile bulunur (olayları sırala, +1/−1 topla; O(n log n)). `kalan = kapasite − tepe`.

**Bekleme listesi ataması** (`services/waitlist_service.py`). Slot boşalınca o aralıkla kesişen bekleyenler kayıt sırasına göre gezilir; her aday için tüm rezervasyon kuralları yeniden doğrulanır. Uymayan (limiti dolmuş, cezalı, o saate başka yer bulmuş) atlanır ve sırada kalır. Böylece boşalan 2 saatlik slot, 1'er saat bekleyen iki kişiye de dağıtılabilir.

**Akıllı slot önerisi** (`services/suggestions.py`). Üç adım:

1. *Aday üret:* aynı odada aynı gün, odanın slot ızgarasına hizalı ve istenenle aynı süredeki tüm başlangıçlar + aynı saat aralığında diğer aktif odalar.
2. *Kurallarla ele:* her aday rezervasyonda kullanılan fonksiyonlardan geçer (`validate_time_rules`, `ensure_no_user_conflict`, `ensure_within_limits`, `remaining_seats`). Yani önerilen her slot o an gerçekten alınabilir; limiti dolmuş öğrenciye o gün için öneri çıkmaz.
3. *Skorla ve sırala* (her bileşen 0..1):

| Bileşen | Formül | Varsayılan ağırlık |
|---|---|---|
| Yakınlık | `max(0, 1 − \|Δt\| / 6 saat)` | 0.5 |
| Oda uyumu | `½·tip + ½·min(c₁,c₂)/max(c₁,c₂)` — tip: aynı `room_type` 1, yalnızca aynı `booking_mode` 0.5; aynı oda 1 | 0.3 |
| Sakinlik | `1 − geçmiş doluluk` — son 28 gün, haftanın aynı günü ve saatleri (analitikle aynı hesap) | 0.2 |

`skor = Σ wᵢ·bileşenᵢ / Σ wᵢ`. Eşit skorda istenen saate yakın olan, sonra aynı oda önce gelir. Ağırlıklar, ufuk ve geçmiş penceresi `.env` ile değişir (`SUGGEST_WEIGHT_PROXIMITY`, `SUGGEST_WEIGHT_FIT`, `SUGGEST_WEIGHT_QUIET`, `SUGGEST_HORIZON_HOURS`, `SUGGEST_HISTORY_DAYS`, `SUGGEST_LIMIT`). Yakınlık en ağır basar çünkü öğrenci büyük olasılıkla o saate göre plan yapmıştır; oda uyumu ikinci gelir çünkü 6 kişilik bir grup için tek koltuk işe yaramaz; sakinlik eşitlik bozucu gibi çalışıp kalabalık saatlerden uzaklaştırır. Her önerinin yanıtında bileşen puanları ve Türkçe gerekçeler (`reasons`) bulunur.

**Eşzamanlılık.** "Kontrol et → kaydet" adımı `booking_lock` altında çalışır; iki istek aynı anda son koltuğu alamaz (tek süreçli SQLite kurulumu için yeterli).

### Veritabanı şeması

| Tablo | Önemli alanlar |
|---|---|
| `user` | email (unique), hashed_password, role, is_active, penalty_points, banned_until |
| `room` | name (unique), room_type, booking_mode, capacity, open_time, close_time, slot_minutes, is_active |
| `reservation` | user_id → user, room_id → room, start_time, end_time, status, source, checkin_code (unique), checked_in_at, reminder_sent |
| `waitlistentry` | user_id, room_id, start_time, end_time, status, promoted_reservation_id → reservation |
| `penaltylog` | user_id, reservation_id, points, reason |
| `emaillog` | user_id, to_email, subject, body, kind, status |
| `holiday` | day (unique), year, name |

Rezervasyon durumları: `confirmed → checked_in → completed`, `confirmed → cancelled`, `confirmed → no_show`.
Zamanlar kampüs yerel saatinde (`TIMEZONE`) tz'siz saklanır; tz'li girişler otomatik çevrilir.

## Endpoint listesi

Tümü `/api/v1` altında. 🔒 = giriş gerekli, 👑 = yalnızca admin.

| Metot | Yol | Açıklama |
|---|---|---|
| POST | `/auth/register` | Öğrenci kaydı |
| POST | `/auth/login` | JWT al (form: username = e-posta) |
| GET | `/auth/me` 🔒 | Profil, ceza puanı |
| GET | `/auth/me/penalties` 🔒 | Ceza geçmişim |
| GET | `/rooms` 🔒 | Oda listesi (tip, kapasite filtresi) |
| GET | `/rooms/available` 🔒 | Verilen aralıkta müsait odalar |
| GET | `/rooms/{id}` 🔒 | Oda detayı |
| GET | `/rooms/{id}/availability?day=` 🔒 | Günün slotları, kalan yer, müsait değilse nedeni |
| GET | `/rooms/{id}/quiet-hours?weekday=&limit=` 🔒 | Geçmiş doluluğa göre odanın en sakin saatleri |
| GET | `/suggestions?room_id=&start_time=&end_time=&limit=` 🔒 | Dolu slot yerine kurallara uyan alternatifler (skorlu) |
| POST / PATCH / DELETE | `/rooms`, `/rooms/{id}` 👑 | Oda yönetimi (silme = pasife alma + yaklaşan rezervasyonların iptali) |
| POST | `/reservations` 🔒 | Rezervasyon yap (dolu slotta 409 + `suggestions`) |
| GET | `/reservations/me` 🔒 | Rezervasyonlarım |
| GET | `/reservations/me/calendar.ics` 🔒 | Yaklaşanlar, takvim dosyası |
| GET | `/reservations/{id}` 🔒 | Detay (sahibi veya admin) |
| DELETE | `/reservations/{id}` 🔒 | İptal + sıradakine atama |
| GET | `/reservations/{id}/qr` 🔒 | Check-in QR kodu (PNG) |
| GET | `/reservations/{id}/ics` 🔒 | Takvim dosyası |
| GET | `/reservations` 👑 | Tüm rezervasyonlar (filtreli) |
| POST | `/checkin` 🔒 | QR koduyla check-in |
| POST | `/waitlist` 🔒 | Dolu slot için sıraya gir |
| GET | `/waitlist/me` 🔒 | Sıra kayıtlarım (pozisyonla) |
| DELETE | `/waitlist/{id}` 🔒 | Sıradan çık |
| GET | `/waitlist` 👑 | Tüm sıra kayıtları |
| GET | `/analytics/occupancy/heatmap` 🔒 | Gün × saat doluluk |
| GET | `/analytics/occupancy/hourly` 🔒 | Saatlik yoğunluk |
| GET | `/analytics/occupancy/daily` 🔒 | Günlük yoğunluk |
| GET | `/analytics/rooms` 👑 | Oda istatistikleri |
| GET | `/analytics/summary` 👑 | Özet rapor |
| GET | `/admin/users` 👑 | Kullanıcılar |
| PATCH | `/admin/users/{id}` 👑 | Rol / aktiflik |
| POST | `/admin/users/{id}/reset-penalty` 👑 | Ceza ve yasağı kaldır |
| GET | `/admin/penalties` 👑 | Ceza kayıtları |
| GET | `/admin/emails` 👑 | Bildirim günlüğü |
| POST | `/admin/jobs/run` 👑 | Zamanlanmış görevleri hemen çalıştır |
| GET | `/admin/holidays/{year}` 👑 | Önbellekteki resmi tatiller |
| GET | `/admin/reports/reservations.csv` 👑 | CSV rapor |

Bunlara ek olarak `/` web arayüzünü, `/docs` Swagger'ı, `/health` sağlık kontrolünü döndürür.

İş kuralı hataları `{"detail": "...", "code": "slot_full"}` biçiminde döner (`slot_full` yanıtında ayrıca `suggestions` listesi bulunur). Kodlar: `slot_full`, `user_conflict`, `daily_limit`, `weekly_limit`, `outside_hours`, `slot_misaligned`, `too_long`, `in_past`, `too_far`, `holiday`, `user_banned`, `room_inactive`, `too_early`, `too_late`, `already_started` …

## Sunum için demo senaryosu

`python -m scripts.seed --reset` sonrası web arayüzünden (<http://localhost:8001>). Öğrenci hesapları `ogrenci1..6@example.com` (şifre `scripts/seed.py` içinde), admin bilgileri `.env.example` içinde. İki öğrenciyi aynı anda göstermek için ikinci bir tarayıcı penceresi (gizli pencere) kullanılabilir.

1. **Admin** ile giriş → **Yönetim**: özet rapor, gün × saat **ısı haritası** (3 haftalık geçmiş veri; öğlen saatleri koyu), oda istatistikleri.
2. **ogrenci1** ile giriş → **Odalar** → *Grup Odası 1* → yarın → boş 10:00 slotuna tıkla → süre 2 saat → **Rezerve et** → **QR kodunu göster** / **Takvime ekle (.ics)**. Slot tablosunda mor "Rezervasyonunuz" olarak görünür; altta günün **en sakin saatleri** listelenir.
3. **ogrenci2** ile aynı odada aynı güne gir → kırmızı **Dolu** 10:00 slotuna tıkla → **akıllı öneriler**: aynı odada en yakın boş saatler ve aynı saatte uygun diğer odalar, uygunluk yüzdesi ve gerekçeleriyle → birinde **Rezerve et** (tek tık).
4. ogrenci2 dolu 11:00 slotunda **Bekleme listesine katıl** → *Rezervasyonlarım*'da "1. sıra".
5. ogrenci1 → *Rezervasyonlarım* → 10–12 rezervasyonunu **İptal et** → ogrenci2'ye 11–12 slotu **otomatik atanır** (`Bekleme listesinden` rozeti); admin **E-posta günlüğü**'nde bildirimi gösterir.
6. No-show: 15 dakikadan önce başlamış, check-in yapılmamış bir rezervasyon varken admin **Görevleri şimdi çalıştır** → durum `no_show`, kullanıcıya +2 ceza puanı. (Sunumda beklememek için `.env` içinde `CHECKIN_GRACE_MINUTES=1` yapılabilir.)
7. Swagger'da (`/docs`): `GET /suggestions` yanıtındaki skor bileşenleri, aynı slota `POST /reservations` → **409 `slot_full`** + `suggestions`; `GET /admin/holidays/2026` → harici API'den gelen tatiller, bir tatil gününe rezervasyon → **400 `holiday`**.

## İş bölümü (4 kişi)

| Kişi | Sorumluluk | Dosyalar |
|---|---|---|
| 1 | Auth, roller, güvenlik, kullanıcı yönetimi, web arayüzü | `core/security.py`, `core/deps.py`, `routers/auth.py`, `routers/admin.py` (kullanıcı kısmı), `static/`, `tests/test_auth_rooms.py`, `tests/test_web.py` |
| 2 | Oda ve rezervasyon mantığı, çakışma algoritması, akıllı slot önerisi | `services/scheduling.py`, `services/reservation_service.py`, `services/suggestions.py`, `routers/rooms.py`, `routers/reservations.py`, `routers/suggestions.py`, `tests/test_reservations.py`, `tests/test_suggestions.py` |
| 3 | Bekleme listesi, QR check-in, ceza, arka plan görevleri | `services/waitlist_service.py`, `services/penalties.py`, `services/jobs.py`, `routers/waitlist.py`, `tests/test_waitlist_checkin_jobs.py` |
| 4 | Analitik, .ics / e-posta / tatil API'si, Docker, CI, README, slayt | `services/analytics.py`, `services/exports.py`, `services/notifications.py`, `services/holidays.py`, `Dockerfile`, `.github/`, `tests/test_exports_analytics.py` |

## Git akışı

`main` korumalı dal; her özellik için `feature/<konu>` dalı açılıp pull request ile birleştirilir. `.github/workflows/ci.yml` her PR'da testleri ve Docker build'ini çalıştırır.

## Bilinen sınırlar

- Tek süreç varsayılır (`booking_lock` ve zamanlayıcı süreç içi). Birden fazla worker ile çalıştırılacaksa PostgreSQL + satır kilidi ve ayrı bir görev çalıştırıcı gerekir.
- Şema değişiklikleri için migration aracı (Alembic) yok; geliştirmede `python -m scripts.seed --reset` ile sıfırlanır.
- Refresh token yok; access token süresi dolunca yeniden giriş yapılır.
- Check-in fiziksel varlığı kanıtlamaz: kod rezervasyon sahibine API yanıtında da döner, yani öğrenci odaya gelmeden `POST /checkin` çağırabilir. Gerçek kullanımda QR odadaki görevli tarafından okutulmalı (endpoint'i yalnızca admin'e açmak) ya da kod odaya ait olmalıdır.
- Pasife alınma tarihi tutulmaz; analitikte pasif bir odanın kapasitesi, rezervasyonu bulunan tarih aralığının tamamında sayılır.
- Bağımlılık sürümleri `requirements.txt` içinde sabittir; güncellerken testleri Python 3.12 ile (Docker imajı) yeniden koşun.
