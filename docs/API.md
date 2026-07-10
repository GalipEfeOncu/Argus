# Argus — API Referansı

## Base URL

Geliştirme: `http://127.0.0.1:8000`  
WebSocket: `ws://127.0.0.1:8000`

---

## REST Endpoint'leri

### Sağlık

```
GET /health
→ { "status": "ok", "version": "0.1.0" }
```

---

### Sessions

#### Session Oluştur
```
POST /sessions
Content-Type: application/json

{
  "name": "Bug Fix Session",
  "project_path": "/home/user/my-project",
  "task": "Şu endpoint'teki 500 hatasını düzelt",
  "role_configs": [
    {
      "role": "planner",
      "enabled": true,
      "provider_type": "anthropic",
      "model_id": "claude-opus-4-5",
      "api_key": "sk-ant-...",
      "base_url": null
    },
    {
      "role": "builder",
      "enabled": true,
      "provider_type": "openai_compat",
      "model_id": "gpt-4o",
      "api_key": "sk-...",
      "base_url": null
    }
  ]
}

→ { "session_id": "uuid", "status": "created" }
```

#### Session Listesi
```
GET /sessions
→ [{ "id", "name", "status", "created_at", "project_path" }, ...]
```

#### Session Başlat
```
POST /sessions/{session_id}/start
→ { "status": "running" }
```

---

### Providers

#### Provider Ekle
```
POST /providers
{
  "name": "OpenRouter",
  "type": "openai_compat",
  "api_key": "sk-or-...",
  "base_url": "https://openrouter.ai/api/v1"
}
→ { "id": "uuid", "name": "OpenRouter" }
```

#### Provider Listesi
```
GET /providers
→ [{ "id", "name", "type", "base_url" }, ...]
(api_key asla döndürülmez)
```

#### Provider Sil
```
DELETE /providers/{provider_id}
→ 204 No Content
```

---

### Models

#### Provider'ın Model Listesi
```
GET /models/{provider_id}
→ [{ "id": "gpt-4o", "name": "GPT-4o", "context_length": 128000 }, ...]
```

---

## WebSocket Protokolü

### Bağlantı
```
WS ws://127.0.0.1:8000/ws/session/{session_id}
```

### Server → Client Event'leri

#### `agent_start`
```json
{
  "type": "agent_start",
  "agent_role": "planner",
  "timestamp": 1720601234.123
}
```

#### `token`
```json
{
  "type": "token",
  "agent_role": "builder",
  "content": " fonk",
  "timestamp": 1720601234.456
}
```

#### `agent_done`
```json
{
  "type": "agent_done",
  "agent_role": "planner",
  "timestamp": 1720601235.0
}
```

#### `tool_call_start`
```json
{
  "type": "tool_call_start",
  "agent_role": "builder",
  "tool_call": {
    "id": "tc_123",
    "tool_name": "write_file",
    "args": { "path": "src/utils.py", "content": "..." }
  },
  "timestamp": 1720601236.0
}
```

#### `tool_call_end`
```json
{
  "type": "tool_call_end",
  "tool_call_id": "tc_123",
  "result": { "success": true, "output": "File written." },
  "timestamp": 1720601236.5
}
```

#### `interrupt`
```json
{
  "type": "interrupt",
  "reason": "Reviewer approval required",
  "message": "Builder 47 satır kod yazdı. Devam etmemi onaylıyor musunuz?",
  "timestamp": 1720601240.0
}
```

#### `error`
```json
{
  "type": "error",
  "message": "API rate limit exceeded",
  "timestamp": 1720601241.0
}
```

#### `session_done`
```json
{
  "type": "session_done",
  "timestamp": 1720601300.0
}
```

---

### Client → Server Mesajları

#### Kullanıcı Mesajı
```json
{ "type": "user_message", "content": "Testi geçirmek için şunu dene..." }
```

#### Onay (Interrupt Sonrası)
```json
{ "type": "human_response", "approved": true, "feedback": null }
```

#### Ret (Interrupt Sonrası)
```json
{ "type": "human_response", "approved": false, "feedback": "Önce şu dosyayı incele" }
```

#### Acil Durdurma
```json
{ "type": "interrupt" }
```

---

## Provider Tipleri

| `provider_type` | API URL | Notlar |
|---|---|---|
| `openai_compat` | Herhangi bir OpenAI-uyumlu URL | OpenRouter, LM Studio, Together AI vb. |
| `anthropic` | `https://api.anthropic.com` (otomatik) | Claude modelleri |
| `google` | `https://generativelanguage.googleapis.com` (otomatik) | Gemini modelleri |

## LangGraph Agent Rolleri

| `role` | Açıklama |
|--------|----------|
| `planner` | Görevi analiz eder, adımlara böler |
| `builder` | Kodu yazar ve düzenler |
| `reviewer` | Kodu denetler, onaylar ya da geri gönderir |
| `tester` | Testleri çalıştırır ve raporlar |
| `ui_agent` | UI/frontend odaklı görevler |
