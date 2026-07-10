# Argus 🔭

> **Transparent Multi-Agent Orchestration Platform**
>
> Cursor, Codex ve Antigravity gibi araçlar arka planda agent kullanır — ama bu tamamen kapalı bir kutu.  
> Argus bunun tersini yapar: hangi agent hangi rolü üstlendi, hangi modeli kullandı, aralarında nasıl konuştu — hepsini **canlı olarak** görebilir ve kontrol edebilirsiniz.

<p align="center">
  <img src="docs/assets/banner.png" alt="Argus Banner" width="800" />
</p>

## Özellikler

| Özellik | Açıklama |
|---------|----------|
| 🎭 **5 Özelleştirilebilir Agent Rolü** | Planner · Builder · Reviewer · Tester · UI Agent |
| 🔑 **Kendi API Key'ini Getir** | OpenAI, Anthropic, Google Gemini, OpenRouter — ya da herhangi bir OpenAI-uyumlu API |
| 🔴 **Canlı İzleme** | Agent'ların birbirine mesaj paslayışını, araç kullanımını ve kodu gerçek zamanlı görün |
| 🛑 **Human-in-the-Loop** | İstediğiniz an müdahale edin, onaylayın ya da yönlendirin |
| 🛠️ **Tam Dosya Sistemi Erişimi** | Okuma, yazma, düzenleme, ripgrep arama, shell, git — Claude Code gibi |
| 🖥️ **Native Desktop Uygulama** | Tauri v2 ile paketlenmiş — macOS, Linux, Windows |

## Mimari

```
┌─────────────────────────────────────────────┐
│              Tauri Desktop App              │
│  ┌─────────────────────────────────────┐   │
│  │         React + Vite Frontend       │   │
│  │  Dashboard · SessionView · Settings  │   │
│  │         Zustand State Stores        │   │
│  └────────────────┬────────────────────┘   │
│                   │ WebSocket              │
│  ┌────────────────▼────────────────────┐   │
│  │        FastAPI Python Backend       │   │
│  │   LangGraph StateGraph Orchestrator  │   │
│  │  Planner→Builder→Reviewer→Tester   │   │
│  │     File/Shell/Git/Search Tools     │   │
│  └─────────────────────────────────────┘   │
└─────────────────────────────────────────────┘
```

## Hızlı Başlangıç

### Gereksinimler

- [Node.js](https://nodejs.org/) ≥ 18
- [Rust](https://rustup.rs/) (stable)
- [uv](https://docs.astral.sh/uv/) (Python paket yöneticisi)
- Python ≥ 3.12

### Kurulum

```bash
# 1. Repo'yu klonla
git clone https://github.com/GalipEfeOncu/Argus.git
cd Argus

# 2. Frontend bağımlılıklarını kur
npm install

# 3. Backend bağımlılıklarını kur
cd backend && uv sync && cd ..

# 4. Geliştirme modunda başlat
npm run tauri dev
```

### Backend'i ayrıca çalıştır (opsiyonel)

```bash
cd backend
uv run uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
```

## Proje Yapısı

```
Argus/
├── src/                        # React + TypeScript Frontend
│   ├── components/
│   │   ├── ui/                 # Atomic UI (Button, Card, Modal…)
│   │   ├── chat/               # Agent mesaj arayüzü
│   │   ├── layout/             # Sidebar, Header, StatusBar
│   │   ├── workflow/           # WorkflowMini agent akış görseli
│   │   └── pages/              # Dashboard, SessionSetup, SessionView, Settings
│   ├── stores/                 # Zustand state yönetimi
│   ├── services/               # WebSocket & API katmanı
│   ├── hooks/                  # Custom React hook'ları
│   ├── types/                  # TypeScript tip tanımları
│   └── styles/                 # Design token'ları ve global CSS
│
├── backend/                    # FastAPI + LangGraph Backend
│   └── app/
│       ├── agents/             # LangGraph düğümleri (planner, builder…)
│       ├── api/                # REST + WebSocket endpoint'leri
│       ├── tools/              # Dosya, shell, git, arama araçları
│       ├── schemas/            # Pydantic modeller
│       └── db/                 # SQLite veritabanı
│
├── src-tauri/                  # Rust / Tauri Native Layer
│   └── src/
│       ├── main.rs             # Binary giriş noktası
│       ├── lib.rs              # Plugin kurulumu
│       ├── commands.rs         # IPC komutları
│       └── sidecar.rs          # Python sidecar yönetimi
│
└── docs/                       # Proje dokümantasyonu
```

## Dokümantasyon

- [📐 Mimari](docs/ARCHITECTURE.md)
- [🗺️ Geliştirme Fazları](docs/PHASES.md)
- [🔌 API Referansı](docs/API.md)
- [🤝 Katkı Rehberi](CONTRIBUTING.md)

## Lisans

MIT © Galip Efe Oncu