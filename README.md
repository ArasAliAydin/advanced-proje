# StudySpot — Çalışma Salonu / Oda Rezervasyon Sistemi

Haliç Üniversitesi · CEN 3001 Advanced Computer Programming · Grup Projesi

Kütüphane odaları, laboratuvarlar ve çalışma salonları için saat bazlı rezervasyon platformu (REST API).

| Ortak altyapı gereksinimi | Bu projede |
|---|---|
| FastAPI + SQLModel + SQLite, Python 3.12 | `app/` — 39 endpoint, 7 tablo |
| JWT auth + rol bazlı yetkilendirme | `student` / `admin` rolleri, OAuth2 password flow |
| Pytest | `tests/` — 56 test |
| Docker | `Dockerfile`, `docker-compose.yml` |
| **Gerçek bir algoritma** | Sweep-line ile çakışma/kapasite tespiti + FIFO bekleme listesi ve otomatik atama |
| **Harici API** | Resmi tatiller ([date.nager.at](https://date.nager.at)), DB'de önbellekli, fail-open |
| **Arka plan görevi** | Dakikada bir: no-show iptali + ceza, hatırlatma e-postası, tamamlama, sıra temizliği |

## Özellikler

- **Odalar:** iki rezervasyon modu — `exclusive` (oda tek rezervasyona kapanır) ve `shared` (koltuk bazlı, aynı anda `capacity` kadar kişi). Açılış/kapanış saati ve slot uzunluğu oda bazında. Oda kapatılınca (pasife alınınca) henüz başlamamış rezervasyonları cezasız iptal edilir ve sahiplerine e-posta gider.
- **Rezervasyon:** çakışma kontrolü, slot hizalama, çalışma saatleri, tek seferde en fazla 3 saat, en fazla 14 gün ileri, resmi tatilde kapalı.
- **Müsaitlik:** müsaitlik sorguları rezervasyon kurallarıyla tutarlıdır; tatil günleri, geçmiş ve 14 gün ötesi müsait görünmez, slotun `reason` alanı nedenini söyler (`holiday`, `in_past`, `too_far`, `slot_full`, `room_inactive`).
- **Limitler:** öğrenci başına günlük 4, haftalık 12 saat (admin muaf).
- **Bekleme listesi:** dolu slot için sıraya girilir; iptal veya no-show olunca sıradaki *uygun* kişiye rezervasyon otomatik açılır ve e-posta gider.
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

Swagger arayüzü: <http://127.0.0.1:8000/docs>

İlk açılışta `.env` içindeki `ADMIN_EMAIL` / `ADMIN_PASSWORD` ile bir admin hesabı oluşturulur (varsayılanlar `.env.example` içinde). Swagger'da **Authorize** düğmesine e-posta ve şifreyi yazmak yeterli.

### Docker

```bash
docker compose up --build
```

Uygulama <http://localhost:8000> adresinde açılır; Docker Desktop'ta `studyspot-v1` adıyla görünür. Veritabanı `studyspot-v1_studyspot-data` volume'ünde kalıcıdır. Demo verisi için: `docker compose exec api python -m scripts.seed`

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
├── routers/                 # ince HTTP katmanı: auth, rooms, reservations, waitlist, analytics, admin
└── services/                # iş mantığı
    ├── scheduling.py        # ALGORİTMA: overlaps, peak_concurrency (sweep-line), hour_buckets
    ├── reservation_service.py  # kurallar, limitler, iptal, check-in
    ├── waitlist_service.py  # ALGORİTMA: FIFO sıra + otomatik atama
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
| POST / PATCH / DELETE | `/rooms`, `/rooms/{id}` 👑 | Oda yönetimi (silme = pasife alma + yaklaşan rezervasyonların iptali) |
| POST | `/reservations` 🔒 | Rezervasyon yap |
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

İş kuralı hataları `{"detail": "...", "code": "slot_full"}` biçiminde döner. Kodlar: `slot_full`, `user_conflict`, `daily_limit`, `weekly_limit`, `outside_hours`, `slot_misaligned`, `too_long`, `in_past`, `too_far`, `holiday`, `user_banned`, `room_inactive`, `too_early`, `too_late`, `already_started` …

## Sunum için demo senaryosu

`python -m scripts.seed` sonrası Swagger üzerinden:

1. Admin ile giriş → `GET /analytics/occupancy/heatmap` ve `/analytics/summary` (3 haftalık geçmiş veri).
2. `ogrenci1` ile giriş → `GET /rooms/1/availability?day=<yarın>` → boş bir slota `POST /reservations`.
3. `ogrenci2` ile aynı slota `POST /reservations` → **409 `slot_full`** → `POST /waitlist` (position: 1).
4. `ogrenci1` → `DELETE /reservations/{id}` → `ogrenci2`'nin `GET /reservations/me` listesinde rezervasyon **otomatik oluşmuş** (`source: waitlist`); admin `GET /admin/emails` ile bildirimi gösterir.
5. `GET /reservations/{id}/qr` → QR görseli; `GET /reservations/{id}/ics` → takvime ekle.
6. No-show: 15 dakikadan önce başlamış, check-in yapılmamış bir rezervasyon varken admin `POST /admin/jobs/run` → durum `no_show`, kullanıcıya +2 ceza puanı. (Sunumda beklememek için `.env` içinde `CHECKIN_GRACE_MINUTES=1` yapılabilir.)
7. `GET /admin/holidays/2026` → harici API'den gelen tatiller; bir tatil gününe rezervasyon → **400 `holiday`**.

## İş bölümü (4 kişi)

| Kişi | Sorumluluk | Dosyalar |
|---|---|---|
| 1 | Auth, roller, güvenlik, kullanıcı yönetimi | `core/security.py`, `core/deps.py`, `routers/auth.py`, `routers/admin.py` (kullanıcı kısmı), `tests/test_auth_rooms.py` |
| 2 | Oda ve rezervasyon mantığı, çakışma algoritması | `services/scheduling.py`, `services/reservation_service.py`, `routers/rooms.py`, `routers/reservations.py`, `tests/test_reservations.py` |
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
