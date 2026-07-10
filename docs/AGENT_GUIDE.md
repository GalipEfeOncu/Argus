# Argus — Agent Kılavuzu

Bu dosya, Argus projesinde çalışan AI coding agent'lar için yazılmıştır.
Projeye bağlanmadan önce bu belgeyi okuyun.

---

## Proje Kimliği

**Argus**, şeffaf bir multi-agent orchestration masaüstü uygulamasıdır.  
Kullanıcı kendi API key'lerini girerek birden fazla LLM'i farklı rollere atar ve bu agent'ların bir görevi birlikte çözmesini gerçek zamanlı izler.

## Teknoloji Stack'i

| Katman | Teknoloji |
|--------|-----------|
| Desktop | Tauri v2 (Rust) |
| Frontend | React 18 + TypeScript + Vite 6 |
| State | Zustand |
| Backend | FastAPI + LangGraph 1.2 |
| LLM | langchain-openai / anthropic / google-genai |
| Araçlar | file, shell, git, ripgrep |
| Stil | Vanilla CSS + CSS custom properties |

## Kritik Dosyalar

Bunları her zaman bağlam olarak oku:

- [`docs/ARCHITECTURE.md`](ARCHITECTURE.md) — Tam teknik mimari
- [`docs/PHASES.md`](PHASES.md) — Öncelikli görevler
- [`src/types/agent.ts`](../src/types/agent.ts) — Tip tanımları
- [`src/types/session.ts`](../src/types/session.ts) — Session tipleri
- [`backend/app/agents/state.py`](../backend/app/agents/state.py) — LangGraph state

## Geliştirme Kuralları

### Frontend (React/TypeScript)

1. **Tip güvenliği önce gelir** — `any` kullanma, `unknown` tercih et
2. **CSS token'larını kullan** — `tokens.css`'deki değişkenleri kullan, hardcode renk yazma
3. **Store'lar sadece state içerir** — iş mantığı servis katmanında
4. **Bileşenler küçük tutulur** — 150 satırı geçen bileşen bölünmeli
5. **`tsc --noEmit`** — Her değişiklikten sonra TypeScript kontrolü yap

### Backend (Python/FastAPI)

1. **Async önce** — Tüm I/O operasyonları `async/await` ile
2. **Pydantic modeller** — Tüm request/response tipleri Pydantic ile
3. **LangGraph state immutable** — State'i doğrudan mutate etme, yeni dict döndür
4. **Tool'lar LangChain tool formatında** — `@tool` decorator kullan
5. **Importları kontrol et** — `backend/.venv/bin/python3 -c "import app.main"` çalıştır

### Rust/Tauri

1. Sadece `src-tauri/src/` altında değişiklik yap
2. Her değişikten sonra `cargo check` çalıştır
3. Yeni permission ekleyince `capabilities/default.json`'ı güncelle

## Komutlar

```bash
# TypeScript kontrol
npx tsc --noEmit

# Backend import kontrolü
cd backend && .venv/bin/python3 -c "import app.main; print('OK')"

# Rust derleme kontrolü
source $HOME/.cargo/env && cd src-tauri && cargo check

# Geliştirme başlat
export PATH="$HOME/.cargo/bin:$PATH" && npm run tauri dev

# Backend ayrı başlat (geliştirme)
cd backend && .venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
```

## Şu An Eksik Olanlar (Faz 1)

Bu üçü tamamlanmadan uygulama işe yaramaz. Önce bunlara bak:

1. **Backend otomatik başlatma** → `src-tauri/src/sidecar.rs`
2. **Session→WS bağlantısı** → `src/components/pages/SessionSetup.tsx` + `src/services/api.ts`
3. **WebSocket event handler** → `backend/app/api/websocket.py`

Detaylar için: [`docs/PHASES.md` Faz 1](PHASES.md#-faz-1--kritik-ilk-çalışan-döngü)

## Dizin Yapısı Özeti

```
src/
  components/ui/        ← Atomic bileşenler (Button, Card, Input…)
  components/chat/      ← Agent mesaj UI'ı
  components/layout/    ← Sidebar, Header, StatusBar
  components/workflow/  ← Agent akış grafiği
  components/pages/     ← Tam sayfalar (Dashboard, SessionView…)
  stores/               ← Zustand store'lar
  services/             ← WebSocket, API istemcisi
  hooks/                ← useTauri, useSession, useWebSocket
  types/                ← TypeScript tip tanımları
  styles/               ← Design token'lar, global CSS

backend/app/
  agents/               ← LangGraph node'ları (planner, builder…)
  api/                  ← FastAPI router'lar + WebSocket
  tools/                ← Dosya/shell/git/arama araçları
  schemas/              ← Pydantic modeller
  core/                 ← LLM factory, ayarlar
  db/                   ← SQLite veritabanı

src-tauri/src/
  main.rs               ← Binary entry
  lib.rs                ← Plugin kurulumu
  commands.rs           ← IPC komutları
  sidecar.rs            ← Python process yönetimi
```
