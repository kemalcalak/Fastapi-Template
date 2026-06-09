# REVIEW.md — Fastapi-Template Code Review Rehberi

`/review` slash komutunun PR audit'inde referans aldığı repo-spesifik konvansiyonlar. Her madde gerçek bir dosyaya `path:line` ile bağlıdır. Generic best-practice yoktur.

---

## 1. Stack

| Katman | Seçim |
|---|---|
| Framework | FastAPI 0.129 (`fastapi[standard]`) |
| Runtime | Python 3.12+ (`requires-python = ">=3.12"`) |
| Package mgr | **uv** (pip yasak) |
| Tip kontrolü | Pyright `strict` mode + `reportAny=error` |
| Lint/Format | Ruff (E,W,F,I,B,C4,UP,ARG001,TID252,ANN401) |
| ORM | SQLAlchemy 2.0 async + asyncpg |
| Validation | Pydantic v2 + pydantic-settings (`@t3-oss/env`-vari) |
| Auth | PyJWT (HS256) + bcrypt + HttpOnly cookie / Bearer fallback |
| Cache / Rate limit / Token blacklist | Redis 7 |
| Rate limit | slowapi (memory in local, async-redis in prod) |
| Background jobs | arq (Redis-backed) |
| Migrations | Alembic |
| Observability | OpenTelemetry (opt-in via env), Prometheus (gated `/metrics`), Sentry |
| Test | pytest + pytest-asyncio + httpx ASGI + aiosqlite + fakeredis |
| Pre-commit / Pre-push | pre-commit (ruff) / pytest |
| CI | GitHub Actions (ruff + pytest) |

Kanıt: [pyproject.toml](pyproject.toml), [.pre-commit-config.yaml](.pre-commit-config.yaml), [.github/workflows/test.yml](.github/workflows/test.yml).

---

## 2. Klasör Yapısı (katmanlı: `api → services → repositories → models`)

```
app/
├── main.py                  # 37 satır — sadece composition (init_sentry, register_*, init_*)
├── api/
│   ├── deps.py              # SessionDep, CurrentUser/ActiveUser/AdminUser/SuperAdmin, require_permission(s), ensure_permission, user_has_permission
│   ├── decorators.py        # audit_unexpected_failure
│   ├── exception_handlers.py# register_exception_handlers + slowapi limiter wiring
│   ├── main.py              # api_router (health, auth, users, support, admin)
│   └── routes/{auth,users,support,health}.py + admin/{users,admins,files,support,activities,stats}
├── services/                # async fonksiyonlar — class YASAK
│   ├── auth_service.py
│   ├── user_service.py
│   └── admin/
├── repositories/            # async DB queries — class YASAK
│   ├── user.py
│   ├── user_activity.py
│   ├── token_blacklist.py
│   └── admin/
├── use_cases/               # cross-cutting (log_activity) — birden fazla servisten çağrılan
├── models/                  # SQLAlchemy DeclarativeBase — sadece ORM, mantık yok
├── schemas/                 # Pydantic DTO'lar (Create/Update/Response ayrı)
├── core/
│   ├── config.py            # pydantic-settings — boot-time validate
│   ├── db.py                # async engine + AsyncSessionLocal
│   ├── security.py          # JWT + bcrypt
│   ├── messages/{error,success}_message.py  # ⚠️ Tüm hata/başarı string'leri
│   ├── lifespan.py          # init/close redis + ensure_first_superadmin
│   ├── realtime.py          # generic Redis pub/sub ↔ WebSocket bus (support + account topics)
│   ├── bootstrap.py         # ensure_first_superadmin (startup superadmin seed)
│   ├── middleware.py        # origin_check + CORS
│   ├── exception_handlers içinde (api/) ama register middleware/metrics/telemetry/sentry/openapi
│   ├── rate_limit.py        # slowapi limiter + decorator factory'ler
│   ├── redis.py
│   ├── metrics.py           # Prometheus instrumentator + gated /metrics
│   ├── telemetry.py         # OTel — OTEL_EXPORTER_OTLP_ENDPOINT set ise
│   ├── sentry.py
│   ├── openapi.py           # custom_generate_unique_id
│   └── email.py
├── worker/                  # arq jobs (delete_expired_accounts vs.)
├── utils/                   # pure helpers (datetime_utils, email_templates)
├── alembic/                 # migration scripts
└── tests/                   # pytest — sqlite+aiosqlite + fakeredis
```

Yeni domain: model → schema → repository → service → route (her katman sırayla). Model değiştiyse **Alembic migration zorunlu**.

---

## 3. Konvansiyonlar (kanıtlı)

### 3.1 Katman akışı (tek yönlü)
- **`api → services → repositories → models`** — bu sıra bozulamaz.
- `api/routes/` repository çağırmaz, **her zaman service üzerinden** geçer ([CLAUDE.md:84](CLAUDE.md)).
- Services başka service çağırmaz — paylaşılan repo fonksiyonu veya `use_cases/` ile çözülür.
- `Depends()` **sadece route handler'larda** ([deps.py:107-111](app/api/deps.py)). Service/repository fonksiyonları parametre olarak `session: AsyncSession` alır.
- Route'tan ham ORM objesi değil, Pydantic schema response döner ([users.py:25-28](app/api/routes/users.py): `response_model=UserPublic`).

### 3.2 Async-only
- **Sync DB call yasak.** Tüm queries `async/await`. SQLAlchemy 2.0 `select(...)` + `await session.execute(...)` paterni ([repositories/user.py:17-21](app/repositories/user.py)).
- Engine [core/db.py:11-19](app/core/db.py): `create_async_engine` + `async_sessionmaker(expire_on_commit=False)`. `pool_pre_ping=True`.

### 3.3 No classes (services/repositories)
- **Services ve repositories saf async fonksiyonlardır** ([CLAUDE.md:98](CLAUDE.md)). Class wrapper ekleme.
- Repository fonksiyonu: `async def <verb>_<entity>(session: AsyncSession, ...)` ([repositories/user.py:12-43](app/repositories/user.py)).

### 3.4 Pydantic schemas
- Domain başına `Create`/`Update`/`UpdateMe`/`Public`/`UpdateResponse` ayrı sınıflar ([schemas/user.py:34-79](app/schemas/user.py)).
- `model_config = ConfigDict(from_attributes=True)` ORM → Pydantic mapping için zorunlu ([schemas/user.py:22](app/schemas/user.py)).
- Validator hata mesajları **`ErrorMessages.X`**'tan gelir, hardcode yasak ([schemas/user.py:43](app/schemas/user.py)).
- `field_validator` + `@classmethod` paterni ([schemas/user.py:39-44](app/schemas/user.py)).

### 3.5 Error/Success messages — single source of truth
- **Tüm hata mesajları [app/core/messages/error_message.py](app/core/messages/error_message.py)** — `ErrorMessages.X` class attribute olarak.
- **Tüm başarı mesajları [app/core/messages/success_message.py](app/core/messages/success_message.py)**.
- Inline string kesinlikle yasak (`detail="User not found"` ❌; `detail=ErrorMessages.USER_NOT_FOUND` ✅) ([CLAUDE.md:107, 123-126](CLAUDE.md)).
- i18n key'leri `error.<domain>.<reason>` veya `error.account.<state>` formatında — frontend bu key'i çevirir.
- Sistem hataları (validation, 401, 403, 404, 409, 429, 500) için yukarı seviye sabitler [error_message.py:1-9](app/core/messages/error_message.py).

### 3.6 Auth & güvenlik
- JWT logic **sadece [app/core/security.py](app/core/security.py)** — başka yerde `jwt.encode/decode` yasak. HS256.
- Token tipleri: `access`, `refresh`, `password_reset`, `new_account` — `type` claim ile ayrılır ([security.py:88-90](app/core/security.py)). Yanlış tip → `None`.
- Password hashing **bcrypt** ([security.py:107-140](app/core/security.py)) — plain-text password log/return yasak.
- Auth flow: cookie `access_token` (HttpOnly) öncelikli, fallback `Authorization: Bearer` ([deps.py:42](app/api/deps.py)).
- `is_token_blacklisted` Redis kontrolü her `get_current_user` çağrısında ([deps.py:51-56](app/api/deps.py)).
- `CurrentUser` deletion grace window'undakileri kabul eder; `CurrentActiveUser` red eder ([deps.py](app/api/deps.py)). Admin paneli için `CurrentAdminUser` (admin **veya** superadmin), superadmin-özel uçlar için `CurrentSuperAdmin`; ince taneli yetki için **`require_permission(Permission.X)`** tek `Depends` — bkz. [3.18 RBAC](#318-rbac-roller--izinler).
- Logout/deactivate token blacklist'e eklenir ([user_service.py:74-80](app/services/user_service.py)).
- Cookie path: `access_token` "/", `refresh_token` `f"{API_V1_STR}/auth/refresh"` ([users.py:82-85](app/api/routes/users.py)).

### 3.7 Rate limiting
- `slowapi` ile [core/rate_limit.py](app/core/rate_limit.py). Local'de in-memory, prod'da `async+redis://...` (replica'lar arası paylaşım).
- Üç decorator factory: `rate_limit_public` (10/min default), `rate_limit_authenticated` (100/min), `rate_limit_strict` (3/min — şifre reset/hesap silme gibi).
- Decorator route'ta kullanılır ve **route signature'ında `request: Request` zorunlu** (slowapi limiter scope'tan okur).
- Limiter `app.state.limiter` üzerinden register edilir ([exception_handlers.py:91](app/api/exception_handlers.py)).

### 3.8 Audit logging
- `@audit_unexpected_failure(activity_type, resource_type, endpoint)` decorator'u ([api/decorators.py:31-71](app/api/decorators.py)) — beklenmeyen exception'da `log_activity` ile kayıt + re-raise.
- Service'lerde manuel `log_activity` çağrısı login fail / deactivate fail gibi domain-spesifik durumlarda ([user_service.py:55-64](app/services/user_service.py)).
- `log_activity` use case [use_cases/log_activity.py](app/use_cases/log_activity.py) — request'ten IP + user-agent extract eder.
- IP/user-agent **sadece** `log_activity` üzerinden alınır; route içinde manuel `request.client.host` yazılmaz.

### 3.9 Migrations
- Model değişti → **Alembic migration zorunlu** ([CLAUDE.md:108](CLAUDE.md)). `uv run alembic revision --autogenerate -m "..."`.
- Partial/GIN index gibi özel index'ler model'in `__table_args__`'ında deklare edilir ([models/user.py:17-46](app/models/user.py)) — autogenerate aksi takdirde drop önerir.
- `passive_deletes=True` + FK `ON DELETE CASCADE` paterni ([models/user.py:78-83](app/models/user.py)).

### 3.10 Config & env
- **`os.getenv`/`os.environ` doğrudan kullanılmaz** — `from app.core.config import settings`.
- `pydantic-settings` boot-time validate eder ([core/config.py:24-29](app/core/config.py)). `extra="ignore"`, `env_ignore_empty=True`.
- `_check_default_secret` `"changethis"` değerlerini local dışında **fail** eder ([core/config.py:112-121](app/core/config.py)). `SECRET_KEY` non-local'de explicit env zorunlu ([core/config.py:135-139](app/core/config.py)).
- Yeni env: `Settings` field'ı + `.env.example` güncelleme.

### 3.11 main.py composition
[app/main.py](app/main.py) sadece kompozisyon — 37 satır, mantık yok:
1. `init_sentry()` (lifespan başlamadan)
2. `FastAPI(...)` instance + `lifespan` + `custom_generate_unique_id`
3. `register_exception_handlers(app)` (slowapi limiter `app.state`'e burada bağlanır)
4. `register_middleware(app)` (origin_check + CORS)
5. `app.include_router(api_router, prefix=settings.API_V1_STR)`
6. `init_telemetry(app)` (OTel — `OTEL_EXPORTER_OTLP_ENDPOINT` set değilse no-op)
7. `init_metrics(app)` (Prometheus + gated `/metrics`)

Yeni global concern → kendi modülüne `register_X(app)` / `init_X(app)` ile eklenir, `main.py` şişmez.

### 3.12 Origin check + CORS
- [core/middleware.py](app/core/middleware.py): yabancı origin'e **404** döner (`ErrorMessages.RESOURCE_NOT_FOUND`) — hangi origin'lerin trusted olduğunu sızdırmaz.
- `allow_credentials=True` + `"*"` wildcard kombinasyonu **runtime'da reddedilir** ([middleware.py:57-63](app/core/middleware.py)) — explicit origin gerekir.
- Same-origin request'lere izin verilir ([middleware.py:32-39](app/core/middleware.py)).

### 3.13 Metrics endpoint
- [core/metrics.py](app/core/metrics.py): `/metrics` non-local'de `Authorization: Bearer <METRICS_TOKEN>` ister; aksi halde **404** (origin check ile aynı şekil — endpoint varlığını sızdırmaz).
- `/health/.*` ve `/metrics` instrumentation'dan exclude edilir.

### 3.14 OpenTelemetry (opt-in)
- [core/telemetry.py](app/core/telemetry.py): `OTEL_EXPORTER_OTLP_ENDPOINT` set değilse **no-op return**, sıfır overhead.
- Auto-instrument: `FastAPIInstrumentor` + `SQLAlchemyInstrumentor` + `RedisInstrumentor` + `HTTPXClientInstrumentor`.
- `/metrics` ve `/health` excluded.

### 3.15 Test
- `app/tests/` altında `test_*.py`. **In-memory SQLite + aiosqlite** ([conftest.py:14-24](app/tests/conftest.py)).
- Her test fresh DB (autouse fixture); `fake_redis` autouse fixture ile gerçek Redis swap'lanır.
- `httpx.AsyncClient` + `ASGITransport` ile FastAPI app'e direkt vurulur ([conftest.py:60-68](app/tests/conftest.py)).
- `mock_email_send` ve `mock_email_validation` autouse — gerçek SMTP/MX lookup test'lerden bypass edilir.
- `pytest-asyncio` `asyncio_mode = "auto"` ([pyproject.toml:46-49](pyproject.toml)).

### 3.16 Naming & docstring
- Modül adı snake_case; class adı PascalCase; fonksiyon snake_case.
- **Her fonksiyonun docstring'i olmalı** — minimum bir satır, İngilizce ([CLAUDE.md:111](CLAUDE.md)).
- Repository: `<verb>_<entity>` (`get_user_by_id`, `create_user`, `deactivate_user`).
- Service: `<verb>_<resource>_service` (`update_user_service`, `deactivate_own_account_service`).
- Schema: `<Entity><Action>` (`UserCreate`, `UserUpdate`, `UserUpdateMe`, `UserPublic`).

### 3.17 Commit / hooks
- Conventional Commits zorunlu (`feat:`, `fix:`, `refactor:`, `chore:`, `docs:`).
- Pre-commit: ruff check (--fix) + ruff format. Pre-push: `uv run pytest` ([.pre-commit-config.yaml:22-31](.pre-commit-config.yaml)).
- `uv.lock` dependency değişikliği ile birlikte commit edilir ([CLAUDE.md:109](CLAUDE.md)). `pip install` yasak.

### 3.18 RBAC (roller + izinler)

- Üç rol: `user` / `admin` / `superadmin` ([schemas/user.py](app/schemas/user.py) `SystemRole`). Superadmin tüm izin kontrolünü bypass eder ve admin'leri **oluşturur/siler** + izin atar. **Root superadmin** (`is_root_superadmin` kolonu, [models/user.py](app/models/user.py)) ek olarak **superadmin katmanını** yönetir: admin→superadmin terfi, superadmin→admin düşürme, root devri. İlk seed edilen superadmin root'tur ([core/bootstrap.py](app/core/bootstrap.py)).
- İzinler `resource:action` key'leri (12 adet) ([schemas/admin_permission.py](app/schemas/admin_permission.py) `Permission` enum; `users:role` **yok**). Plain admin'in grant'ları `admin_permission` tablosunda ([models/admin_permission.py](app/models/admin_permission.py)); superadmin hepsine implicit sahip.
- **Her admin endpoint tek `Depends(require_permission(Permission.X))` ile korunur** ([deps.py](app/api/deps.py)). `require_permission`/`require_permissions` → `ensure_permission` zincirine iner (auth → active → admin rolü → grant; superadmin short-circuit). **Payload-koşullu** izinler `require_permissions(base, conditional={...})` ile raw body alanına göre ek izin ister (ticket atama → `support:update`).
- Admin-yönetim uçları ([routes/admin/admins.py](app/api/routes/admin/admins.py)) **`CurrentSuperAdmin`** ile korunur: list / katalog / **create** (`POST`) / izin-set (`PATCH`) / **delete account** (`DELETE /{id}`) / **promote→superadmin** (`POST /{id}/promote`) / **demote→admin** (`POST /{id}/demote`) / **root devri** (`POST /transfer-root` + `/confirm`). Son üçü serviste ayrıca **root** kontrolü ister (`ONLY_ROOT_SUPERADMIN`).
- **Rol/katman invariant'ları serviste** ([services/admin/admin_service.py](app/services/admin/admin_service.py), [user_service.py](app/services/admin/user_service.py)): users yüzeyinde **user↔admin rol geçişi yok** (admin'ler hesap olarak oluşturulur/silinir; `AdminUserUpdate`'te `role` alanı yok); **superadmin katmanı root-only** (root değilse `ONLY_ROOT_SUPERADMIN`); root'un kendi rolü değişmez (self-demote `SUPERADMIN_ROLE_IMMUTABLE`, yalnızca OTP devriyle aktarılır); plain admin superadmin hedefe dokunamaz (`_guard_superadmin_target`); son superadmin korunur (`is_last_active_superadmin`).
- **Root devri email-OTP ile** ([services/admin/admin_service.py](app/services/admin/admin_service.py) + [repositories/root_transfer.py](app/repositories/root_transfer.py)): root `/transfer-root` ile mevcut bir superadmin hedef seçer → 6 haneli OTP root'un **kendi** mailine gider, Redis'te **hash'li + TTL (3 dk)**; `/transfer-root/confirm` kodu doğrular, root bayrağını taşır, iki tarafa `permissions_updated` basar.
- `/users/me` admin'e `permissions` döndürür (superadmin/user'a alanı hiç göndermez) + her kullanıcıya `is_root_superadmin` — FE gating birebir bunu yansıtır.
- İzin/katman değişince hedef hesab(lar)a `permissions_updated` realtime event'i basılır ([core/realtime.py](app/core/realtime.py) `account:{id}` topic) — FE re-fetch eder.

---

## 4. Anti-Pattern'ler (kaçınılır)

1. **Class-based service/repository.** Sadece async fonksiyonlar. ([CLAUDE.md:98](CLAUDE.md))
2. **Service/repository içinde `Depends()`.** Sadece route handler'da; aşağıya parametre olarak geçilir.
3. **Route'tan repository'ye doğrudan çağrı** — service katmanı atlanmamalı.
4. **Service başka service çağırma** — `use_cases/` veya repository.
5. **Sync DB call.** Hepsi `async/await`.
6. **Inline error/success string** (`detail="User not found"`) — `ErrorMessages.X` zorunlu.
7. **JWT işlemini `core/security.py` dışında yapma** (`jwt.encode/decode` başka modülde).
8. **`os.getenv`/`os.environ` doğrudan** — `settings`.
9. **Plain-text password log/return.**
10. **`Authorization: Bearer` header'ı doğrulamadan kullanma** (cookie öncelikli, blacklist kontrolü zorunlu).
11. **Model değişimini Alembic migration'sız bırakma.**
12. **Ham ORM objesi response** — Pydantic schema mapping zorunlu.
13. **`pip install`** — `uv add`.
14. **`uv.lock` commit etmeden dependency değişimi.**
15. **`request.client.host`/`request.headers["user-agent"]` route içinde manuel okuma** — `log_activity` use case kullanılır.
16. **Yeni `slowapi` limiter instance yaratma** — tek `limiter` [core/rate_limit.py](app/core/rate_limit.py) üzerinden gider.
17. **`@router.<verb>` üzerinde `request: Request` parametresi olmadan rate-limit decorator** — slowapi scope alamaz, runtime exception.
18. **`allow_credentials=True` + `"*"` CORS wildcard** — middleware bunu zaten reddeder, ama PR'da gelirse blocker.

---

## 5. Review'da KESİNLİKLE Flag'lenecekler

### 5.1 Katman ihlali
- **Route → repository doğrudan çağrı** (service atlanmış).
- **Service → service çağrısı** (use_case veya repository olmalı).
- **Service/repository signature'ında `Depends()`.**
- **Route handler'da business logic** (validation/transform/policy) — service'e taşınmalı.
- Repository fonksiyonunda HTTPException raise (repository persistence katmanıdır; HTTP servis/route işi).

### 5.2 Async / DB
- **Sync DB call** (`session.query(...)` SQLAlchemy 1.x stili, `session.execute` await edilmemiş).
- `await` unutulmuş async çağrı → coroutine return ediliyor.
- `expire_on_commit=False` override'ı (session config kırılır).
- N+1 query: list endpoint'inde her item için ek `await session.execute(...)`.
- **`with_for_update()` lock'u kaldırma** ([repositories/user.py:63-65](app/repositories/user.py)) — concurrent deactivate/reactivate race condition.

### 5.3 Mesaj/i18n
- **Inline `detail="..."` string** — `ErrorMessages.X` zorunlu.
- `ErrorMessages`'a yeni eklenmeden kullanılmış sabit (NameError).
- Backend i18n key formatı dışında kalan ham mesaj (`detail="Bir hata oluştu"`).
- Success mesajının `SuccessMessages` dışından gelmesi.

### 5.4 Auth & güvenlik
- **`jwt.encode/decode` `core/security.py` dışında** — token logic single source of truth.
- **`get_password_hash`/`verify_password` bypass'i** — bcrypt kullanılmamış.
- **Password log'lama / response'a koyma** (`return {"password": ...}`).
- **`get_current_user` bypass eden route** (`Depends(get_current_user)` olmadan korumalı route).
- **`is_token_blacklisted` kontrolünü atlama.**
- Token'ı URL query/path/log/error'a sızdırma.
- **Cookie path/domain ayarını değiştirme** (`access_token` "/", `refresh_token` `f"{API_V1_STR}/auth/refresh"`) — diğer parça kırılır.
- HttpOnly/SameSite/Secure flag'larını kaldırma.
- **`@router.delete("/users/me")` veya silme/şifre değişimi gibi endpoint'lerde rate limit decorator yok**.
- `verify_token` `expected_type` parametresini değiştirme/kaldırma — yanlış tip token kabul edilebilir.
- **Admin endpoint'i `require_permission(...)` / `CurrentAdminUser` olmadan** açık — RBAC yetki kapısı yok.
- **Admin-yönetim ucu (`/admin/admins/*`) `CurrentSuperAdmin` olmadan** — superadmin-özel kapı atlanmış.
- **Koşullu izni (ticket atama → `support:update`) enforce etmeyen** mutation — raw payload izni atlanırsa yanlış işlem 403 yerine geçer.
- **Superadmin/root koruma invariant'larını gevşetme** (`_guard_superadmin_target`, `is_last_active_superadmin`, `SUPERADMIN_ROLE_IMMUTABLE`) veya **superadmin-katman aksiyonlarının (promote / demote / transfer-root) `ONLY_ROOT_SUPERADMIN` kontrolünü kaldırma**.
- **`/users/me` payload'ına superadmin/user için `permissions` ekleme** (yalnızca plain admin'e dönmeli).

### 5.5 Pydantic / Schemas
- **ORM modeli response'ta** — `response_model` Pydantic schema olmalı.
- `from_attributes=True` eksik schema (ORM mapping çalışmaz).
- `field_validator` hata mesajının inline string olması.
- `UserPublic`'e password/hashed_password sızması.
- `model_dump()` yerine `dict()` (Pydantic v2'de deprecated).

### 5.6 Migrations / models
- **Model değişikliği var ama `app/alembic/versions/` altında migration yok.**
- Migration file'ında `op.execute(...)` raw SQL — gerekçe yoksa flag (idempotent değil olabilir).
- `__table_args__`'tan partial/GIN index silinmesi ([models/user.py:17-46](app/models/user.py)) — autogenerate sürekli drop önerir.
- `passive_deletes=True` ile birlikte FK'da `ondelete="CASCADE"` eksikliği.
- Yeni `unique` constraint migration'ında index drop/create sıralaması yanlış.

### 5.7 Config / env
- **`os.getenv("X")` / `os.environ["X"]` doğrudan kullanım** — `settings.X`.
- Yeni env değeri `Settings`'e eklenmemiş — runtime `AttributeError`.
- `.env.example` güncellenmemiş yeni env.
- `SECRET_KEY` veya benzer secret'ı default literal'la fallback (`os.getenv("SECRET_KEY", "default")`).

### 5.8 Rate limit / audit
- Hassas endpoint (`/auth/login`, `/auth/forgot-password`, `/users/me` DELETE, `/users/me/reactivate`) decorator'sız.
- Rate limit decorator var ama `request: Request` parametresi route signature'ında yok.
- **Yeni `Limiter(...)` instance** [core/rate_limit.py](app/core/rate_limit.py) dışında.
- Beklenmeyen failure'lı route'ta `@audit_unexpected_failure` eksik (kritik domain mutation'larında).
- `log_activity` parametre olmadan IP/user-agent manuel toplanmış (`request.client.host` route içinde).

### 5.9 Tests
- Yeni endpoint için test yok (auth/security/payment-impacting'se major).
- Test'te gerçek SMTP/Redis'e vurma (autouse fixture'ları override etmiş).
- `get_db` override edilmemiş test (production DB'ye bağlanır).
- `pytest-asyncio` decorator'ları olmadan async test (`@pytest.mark.asyncio` veya autouse mode olmazsa skip).
- DB değiştiren test fixture'ı temizlemiyor (test isolation kırılır).

### 5.10 Type / lint
- **`Any` kullanımı** — Pyright `reportAny=error`. `unknown` veya generic narrow olmalı.
- `# type: ignore` gerekçesiz ekleme ([config.py:45, 97](app/core/config.py) gibi yorum açıklayıcı olmalı).
- Function return type annotation eksik (Ruff ANN).
- Ruff `E,W,F,I,B,C4,UP,ARG001,TID252` ihlali.
- Relative import (`from ..foo import bar`) — Ruff TID252 yasak.
- Unused function argument (Ruff ARG001).

### 5.11 Docstring & file size
- **Yeni fonksiyonun docstring'i yok** ([CLAUDE.md:111](CLAUDE.md)).
- Türkçe docstring (İngilizce zorunlu).

### 5.12 Observability
- [core/sentry.py](app/core/sentry.py)/[core/telemetry.py](app/core/telemetry.py) içine ek `Sentry.init(...)` / `TracerProvider(...)` çağrısı (duplicate init).
- `/metrics` veya `/health` instrumentation exclude listesinden çıkarılması.
- `METRICS_TOKEN` Bearer kontrolünün gevşetilmesi/kaldırılması ([metrics.py](app/core/metrics.py)).
- OTel `init_telemetry`'nin opt-in (`OTEL_EXPORTER_OTLP_ENDPOINT` env) kontrolünü kaldırma.

---

## 6. Görmezden Gelinecekler (false-positive)

Bu maddeleri **flag etme**:

1. **Ruff/Pyright zaten yakalıyorsa** (unused import, unused arg, missing return type) — pre-commit/CI fail eder.
2. **PR diff'inde olmayan satır** — pre-existing kabul.
3. **Mevcut `# type: ignore` yorumlu/gerekçeli** ([config.py:45, 97](app/core/config.py) `[prop-decorator]` gibi).
4. **Formatting** (line-length, quote style) — ruff format halleder.
5. **Eski dosyada `Any`/inline string PR'da değişmediyse**. Yeni eklenen flag.
6. **TODO** ticket/sahip referansı varsa kabul; sahipsizse minor.
7. **Test eksikliği** non-critical endpoint için minor öneri, blocking değil. Auth/payment/silme'de major.
8. **`response_model` opsiyonel return tip annotation** (FastAPI zaten serialize eder).
9. **Generic best-practice** önerileri (clean code, hexagonal, DDD) — bu repo idiomatic FastAPI; mimari öneri review skopu dışı.
10. **`B904`** (raise from) — pyproject'te ignored, gerekçe orada.
11. **`B008`** (Depends() default) — pyproject'te ignored, FastAPI paterni.
12. **`E501`** line too long — formatter halleder.
13. **`async def` içinde `await` yok** uyarısı — bilinçli olabilir (FastAPI dependency uyumluluğu).
14. **`HTTPException` raise hem service hem route'ta** — repo bilinçli ([CLAUDE.md:117](CLAUDE.md)). Sadece repository'de raise flag.
15. **Print/console** — ruff yakalar, low-noise.

---

## 7. Review Yazma Stili

- Türkçe, kısa, doğrudan.
- "Bu değişiklik X kuralını ihlal ediyor: <REVIEW.md alıntısı>" — soyut kural değil somut kanıt.
- Her bulgu: **dosya + satır + kural + öneri** (tek satırda anlaşılır düzeltme).
- Confidence < 80 ise yorumlama (slash komutu zaten filtreliyor).
- "Görmezden gelinecekler" listesindeki şeyleri yorumlama.

---

Son güncelleme: 2026-06-09.
