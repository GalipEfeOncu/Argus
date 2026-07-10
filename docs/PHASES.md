# Argus — Geliştirme Fazları & Görev Öncelikleri

Bu belge, Argus projesinin mevcut durumunu, tamamlanan işleri ve önceliklendirilmiş sonraki adımları tanımlar.
**AI agent'lar ve geliştiriciler bu belgeyi referans alarak görevleri ele almalıdır.**

---

## Mevcut Durum (v0.1.0-dev)

### ✅ Tamamlanan

| Alan | Detay |
|------|-------|
| Proje iskeleti | Tauri v2 + React + Vite + TypeScript |
| Design system | Dark futuristic token'lar, glassmorphism, animasyonlar |
| UI bileşenleri | Button, Card, Input, Select, Modal, Badge, Tabs, Tooltip, ScrollArea, StatusIndicator |
| Chat bileşenleri | AgentMessage, AgentAvatar, ToolCallBlock, ChatPanel, MessageList, MessageInput, ApprovalBar |
| Layout | Sidebar, Header, StatusBar, WorkflowMini |
| Sayfalar | Dashboard, SessionSetup, SessionView, Settings |
| State | Zustand (settingsStore, sessionStore, agentStore, uiStore) |
| Servisler | WebSocket client, API client |
| Backend altyapı | FastAPI, LangGraph StateGraph, 5 agent node, araçlar (file/shell/git/search) |
| Rust/Tauri | main.rs, lib.rs, commands.rs, sidecar.rs |
| Derleme | TypeScript 0 hata, Cargo check başarılı, Backend import OK |

---

## 🔴 Faz 1 — Kritik: İlk Çalışan Döngü
**Öncelik: EN YÜKSEK — Bu olmadan uygulama kullanılamaz.**

### 1.1 Backend Otomatik Başlatma

**Problem:** Backend FastAPI süreci Tauri uygulama açıldığında otomatik başlamıyor.  
**Dosyalar:** `src-tauri/src/sidecar.rs`, `src-tauri/src/lib.rs`, `src/hooks/useTauri.ts`

**Yapılacaklar:**
- [ ] `sidecar.rs`'te backend'i `tauri-plugin-shell` ile başlatan kodu tamamla
- [ ] `lib.rs`'te uygulama başlarken `start_backend` komutunu çağır
- [ ] `useTauri.ts` hook'una gerçek `invoke('start_backend')` çağrısı ekle
- [ ] Backend port çakışmasını handle et (port zaten kullanımdaysa skip et)
- [ ] Uygulama kapanırken backend'i durdur (`on_window_event`)

**Referans:** [Tauri Sidecar Docs](https://v2.tauri.app/plugin/shell/#sidecar)

---

### 1.2 Session Başlatma → WebSocket Bağlantısı

**Problem:** SessionSetup formu doldurulunca backend'e POST atılıp WS bağlantısı kurulmuyor.  
**Dosyalar:** `src/components/pages/SessionSetup.tsx`, `src/services/websocket.ts`, `src/services/api.ts`

**Yapılacaklar:**
- [ ] `SessionSetup.tsx`'te form submit edilince `api.createSession()` çağır
- [ ] Backend session_id alındıktan sonra `wsManager.connect(sessionId)` çağır
- [ ] `SessionView.tsx`'te WebSocket bağlantısını başlat (mount'ta)
- [ ] Bağlantı durumunu StatusBar'da göster
- [ ] `POST /sessions/{id}/start` endpoint'ini test et

---

### 1.3 Backend WebSocket Handler

**Problem:** `app/api/websocket.py` LangGraph event'lerini doğru parse edip client'a göndermiyor.  
**Dosya:** `backend/app/api/websocket.py`

**Yapılacaklar:**
- [ ] `graph.astream_events()` döngüsünü doğru event type'larla yaz
- [ ] `on_chat_model_stream` → `token` event'i olarak gönder
- [ ] `on_tool_start` / `on_tool_end` → `tool_call_start/end` olarak gönder
- [ ] `on_chain_start` (agent node başlıyor) → `agent_start` olarak gönder
- [ ] Interrupt signal'ını handle et (asyncio.Queue ile frontend mesajları dinle)
- [ ] Bağlantı kopması durumunda graph'ı temizle

---

## 🟠 Faz 2 — Yüksek Öncelik: UX Tamamlama

### 2.1 Settings Sayfası — API Key Doğrulama

**Dosyalar:** `src/components/pages/Settings.tsx`, `backend/app/api/providers.py`

**Yapılacaklar:**
- [ ] Provider eklendikten sonra `GET /models/{provider_id}` çağırarak key'i doğrula
- [ ] Doğrulama sonucunu Badge ile göster (✅ / ❌)
- [ ] Rol → Model eşleme bölümünü Settings'e ekle
- [ ] Model listesini provider'dan çekerek Select'i doldur

---

### 2.2 Dashboard — Gerçek Veri

**Dosya:** `src/components/pages/Dashboard.tsx`

**Yapılacaklar:**
- [ ] Dashboard'u mock data yerine `useSessionStore`'dan gerçek session'ları gösterecek şekilde bağla
- [ ] "Resume" butonu → aktif session'a git
- [ ] "Delete" butonu → session sil + backend'e DELETE /sessions/{id}
- [ ] Boş durum (hiç session yok) tasarımı

---

### 2.3 WorkflowMini — Canlı Güncelleme

**Dosya:** `src/components/workflow/WorkflowMini.tsx`

**Yapılacaklar:**
- [ ] `useAgentStore` ile bağla → aktif agent'ı highlight et
- [ ] Agent durumu değişince animasyonlu geçiş yap
- [ ] Tamamlanan node'lara ✓ işareti ekle

---

### 2.4 AgentPanel — Sağ Kenar Çubuğu

**Yapılacaklar:**
- [ ] Sağ panelde her agent'ın anlık durumunu göster (AgentCard bileşeni var)
- [ ] Token sayacı, son eylem bilgisi
- [ ] SessionView layout'una AgentPanel'i ekle

---

## 🟡 Faz 3 — Orta Öncelik: Güvenilirlik & Kalite

### 3.1 Hata Yönetimi

- [ ] Backend bağlantısı kurulamazsa kullanıcıya anlamlı hata göster
- [ ] LLM API hatası (rate limit, geçersiz key) → kullanıcı dostu mesaj
- [ ] WebSocket bağlantısı kesilirse otomatik yeniden bağlan (websocket.ts'te iskelet var)
- [ ] Graph yürütme timeout'u

### 3.2 Tool Güvenliği

**Dosya:** `backend/app/tools/shell_tools.py`

- [ ] Shell komutlarını sandbox'la (proje dizini dışına çıkamasın)
- [ ] Tehlikeli komut listesi (rm -rf /, format vb.) → reddet
- [ ] Kullanıcıya shell komutlarını onay için göster (interrupt)

### 3.3 Veri Kalıcılığı

**Dosya:** `backend/app/agents/graph.py`

- [ ] `MemorySaver`'ı `AsyncSqliteSaver` ile değiştir
- [ ] `langgraph-checkpoint-sqlite` paketini pyproject.toml'a ekle ve `uv sync` çalıştır
- [ ] Session'lar uygulama yeniden açıldığında geri yüklenmeli

---

## 🟢 Faz 4 — Düşük Öncelik: Gelişmiş Özellikler

### 4.1 Ek Agent Rolleri

- [ ] **Architect Agent** — Büyük projeler için üst düzey tasarım
- [ ] **DocWriter Agent** — Otomatik dokümantasyon yazımı
- [ ] **SecurityAuditor Agent** — Güvenlik açığı taraması

### 4.2 Proje Bağlamı (Context Window)

- [ ] Session başlarken proje dizinini indexle (ripgrep ile)
- [ ] Dosya ağacını sistem prompt'una ekle
- [ ] `.argusignore` desteği (`.gitignore` gibi)

### 4.3 Diff Viewer

- [ ] Builder agent dosya değiştirince inline diff göster
- [ ] Kullanıcı değişikliği kabul/ret edebilsin
- [ ] Git commit önerisi

### 4.4 Built-in Ücretsiz Modeller

- [ ] Groq API ile Llama 3 ücretsiz entegrasyonu
- [ ] Google Gemini Flash ücretsiz tier
- [ ] Uygulama içi "free tier" badge'i

### 4.5 Session Şablonları

- [ ] Önceden tanımlı görev şablonları (bug fix, feature add, refactor)
- [ ] Başarılı session'ları şablon olarak kaydet

### 4.6 Dışa Aktarma

- [ ] Session logunu Markdown olarak dışa aktar
- [ ] Agent'ların ürettiği kodu ZIP olarak indir

---

## 🔵 Faz 5 — Production Hazırlığı

### 5.1 Dağıtım

- [ ] PyInstaller ile backend'i binary'ye paketle
- [ ] `tauri.conf.json`'a `sidecar` binary'sini ekle
- [ ] macOS / Linux / Windows build pipeline (GitHub Actions)
- [ ] Uygulama ikonları (gerçek, 1x1 placeholder değil)

### 5.2 Güvenlik

- [ ] API key'leri OS Keychain'e kaydet (plaintext localStorage yerine)
- [ ] Tauri CSP politikalarını sıkılaştır
- [ ] Shell command injection önleme

### 5.3 Test

- [ ] Backend: `pytest` ile agent node unit testleri
- [ ] Backend: FastAPI TestClient ile integration testleri
- [ ] Frontend: Vitest + Testing Library bileşen testleri
- [ ] E2E: Tauri WebDriver ile UI testleri

---

## Öncelik Özeti

```
🔴 Faz 1  →  Önce bunlar (uygulama çalışmıyor)
🟠 Faz 2  →  Sonra bunlar (UX eksik)
🟡 Faz 3  →  Güvenlik ve güvenilirlik
🟢 Faz 4  →  Değer katan özellikler
🔵 Faz 5  →  Production release
```

---

## Bilinen Sorunlar

| Sorun | Etki | Faz |
|-------|------|-----|
| Backend otomatik başlamıyor | Uygulama kullanılamaz | 1.1 |
| Session→WS bağlantısı kurulmuyor | Agent akışı çalışmaz | 1.2 |
| WebSocket event parse'ı eksik | Token stream gelmiyor | 1.3 |
| MemorySaver kullanılıyor | Session'lar kalıcı değil | 3.3 |
| Shell tool sandbox yok | Güvenlik riski | 3.2 |
| API key localStorage'da düz metin | Güvenlik riski | 5.2 |
