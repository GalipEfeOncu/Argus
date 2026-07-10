# Argus — Mimari Referans

Bu belge, Argus'un teknik mimarisini anlamak isteyen geliştiriciler ve AI agent'lar için kapsamlı bir referans sunar.

## Genel Bakış

Argus iki ana katmandan oluşur:

1. **Frontend** — Tauri v2 içinde çalışan React + Vite uygulaması
2. **Backend** — Tauri sidecar olarak başlatılan FastAPI + LangGraph süreci

İkisi arasındaki iletişim **WebSocket** üzerinden gerçekleşir. Frontend olayları dinler, backend LangGraph graph'ını çalıştırır ve token/araç olaylarını stream'ler.

---

## Frontend Katmanı

### Teknolojiler
- **Framework:** React 18 + TypeScript 5
- **Build:** Vite 6
- **State:** Zustand (persist middleware ile localStorage'a kayıt)
- **UI Primitives:** Radix UI (Dialog, Select, Tabs, ScrollArea, Tooltip)
- **Stil:** Vanilla CSS — design token'lar (`src/styles/tokens.css`), glassmorphism yardımcıları
- **Tauri Bridge:** `@tauri-apps/api/core` (invoke), `@tauri-apps/plugin-dialog` (dosya seç)

### State Mimarisi (Zustand)

```
useSettingsStore   — API provider'lar, rol→model eşlemeleri (localStorage'a persist)
useSessionStore    — Session meta verileri (localStorage'a persist)
useAgentStore      — Aktif session'daki mesajlar, agent durumları (persist değil)
useUIStore         — Aktif sayfa, sidebar açık/kapalı (persist değil)
```

### WebSocket Event Akışı

```
Backend → Frontend olayları:
  agent_start      → AgentStore: yeni mesaj balonu aç, durumu "thinking"
  token            → AgentStore: stream token'ı ekle
  agent_done       → AgentStore: mesajı finalize et
  tool_call_start  → AgentStore: ToolCallBlock aç
  tool_call_end    → AgentStore: ToolCallBlock'u sonuçla kapat
  interrupt        → AgentStore: isInterrupted=true, ApprovalBar göster
  error            → Hata mesajı

Frontend → Backend olayları:
  user_message     → Kullanıcı chat girdisi
  human_response   → Onay/ret (interrupt sonrası)
  interrupt        → Acil durdurma
```

### Sayfa Akışı

```
Dashboard (/)
  → "New Session" butonu
SessionSetup (/setup)
  → Proje klasörü seç
  → Görev yaz
  → Agent roller aktif/pasif
  → "Initialize Agents" → backend'e POST /sessions
SessionView (/session)
  → ChatPanel (canlı mesajlar)
  → WorkflowMini (agent akış grafiği)
  → AgentPanel (sağda her agent'ın durumu)
  → ApprovalBar (interrupt geldiğinde)
Settings (/settings)
  → Provider yönetimi (API key ekle/sil)
  → Rol→Model eşleme
```

---

## Backend Katmanı

### Teknolojiler
- **Framework:** FastAPI 0.115+
- **Orchestration:** LangGraph 1.2+ (StateGraph)
- **LLM Desteği:** langchain-openai, langchain-anthropic, langchain-google-genai
- **Checkpointing:** MemorySaver (MVP) → AsyncSqliteSaver (production)
- **DB:** aiosqlite (session meta verileri)
- **Server:** uvicorn[standard]

### LangGraph Graph Yapısı

```
START
  │
  ▼
[planner]     ← Görevi analiz et, adımlara böl, plan yaz
  │
  ▼
[builder]     ← Kodu yaz/düzenle (file_tools + shell_tools kullanır)
  │
  ▼
[reviewer]    ← Kodu incele → APPROVE veya REVISE
  │
  ├─ REVISE → [builder] (geri döngü)
  │
  ▼
[tester]      ← Test çalıştır, sonuçları raporla
  │
  ▼
END
```

`ui_agent` — İsteğe bağlı; builder yerine ya da builder sonrası UI odaklı görevler için.

### Agent Node Anatomisi

Her agent node şu yapıyı izler:
```python
async def create_X_node(provider_type, model_id, api_key, base_url, tools):
    llm = create_llm(provider_type, model_id, api_key, base_url)
    llm_with_tools = llm.bind_tools(tools) if tools else llm
    
    async def node(state: AgentState) -> AgentState:
        messages = state["messages"]
        response = await llm_with_tools.ainvoke(messages)
        return {"messages": [response], "current_agent": "X"}
    
    return node
```

### LLM Factory

`app/core/llm_factory.py` → `create_llm(provider_type, model_id, api_key, base_url)` fonksiyonu:

| `provider_type` | Kullanılan Kütüphane | Notlar |
|---|---|---|
| `openai_compat` | `ChatOpenAI` | `base_url` ile OpenRouter, LM Studio vb. |
| `anthropic` | `ChatAnthropic` | Claude modelleri |
| `google` | `ChatGoogleGenerativeAI` | Gemini modelleri |

### Araçlar (Tools)

```
app/tools/
  file_tools.py    — read_file, write_file, edit_file, list_directory
  shell_tools.py   — run_shell_command (güvenlik sınırlı)
  search_tools.py  — ripgrep_search, find_files
  git_tools.py     — git_status, git_diff, git_commit, git_log
```

### API Endpoint'leri

```
GET  /health                     — Backend sağlık kontrolü
POST /sessions                   — Yeni session oluştur
GET  /sessions                   — Session listesi
GET  /sessions/{id}              — Session detayı
POST /sessions/{id}/start        — Agent graph'ını başlat
POST /providers                  — Provider ekle (API key kaydet)
GET  /providers                  — Provider listesi
DELETE /providers/{id}           — Provider sil
GET  /models/{provider_id}       — Provider'ın model listesi
WS   /ws/session/{id}            — Canlı event stream
```

---

## Tauri / Rust Katmanı

### Dosyalar

```
src-tauri/src/
  main.rs        — Binary entry point (argus_lib::run() çağırır)
  lib.rs         — Plugin'leri kaydeder (dialog, shell, opener, fs)
  commands.rs    — #[tauri::command] fonksiyonları (IPC)
  sidecar.rs     — Python backend process lifecycle (MVP: ayrı başlatılır)
```

### IPC Komutları (commands.rs)

Frontend → Rust arası:
- `greet` — Test komutu
- İleride: `start_backend`, `stop_backend`, `get_app_config`

### İzin Modeli (capabilities/default.json)

```json
{
  "permissions": [
    "core:default",
    "shell:allow-execute",
    "dialog:allow-open",
    "fs:allow-read-all",
    "fs:allow-write-all",
    "opener:allow-open-url"
  ]
}
```

---

## Veri Akışı — Tam Senaryo

```
1. Kullanıcı SessionSetup'ta "Initialize Agents" tıklar
2. Frontend → POST /sessions (role_configs + task + project_path)
3. Backend session kaydeder → session_id döner
4. Frontend → WS /ws/session/{id} bağlanır
5. Backend WS handler → compile_graph() çağırır
6. LangGraph graph.astream() başlar
7. Her LangGraph event → JSON WebSocket frame olarak frontend'e
8. Frontend AgentStore'u günceller → UI reaktif render
9. Reviewer INTERRUPT gönderirse → Frontend ApprovalBar gösterir
10. Kullanıcı onaylarsa → Frontend WS'e human_response gönderir
11. Backend interrupt'tan devam eder
12. Tüm agent'lar bitince → agent_done + session completed
```
