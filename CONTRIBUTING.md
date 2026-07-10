# Argus — Katkı Rehberi

## Dallar (Branches)

| Dal | Amaç |
|-----|------|
| `main` | Stabil, her zaman çalışan kod |
| `dev` | Aktif geliştirme |
| `feat/xxx` | Yeni özellik |
| `fix/xxx` | Bug düzeltmesi |
| `docs/xxx` | Yalnızca dokümantasyon |

## Commit Formatı

[Conventional Commits](https://www.conventionalcommits.org/) standardını takip ediyoruz:

```
<type>(<scope>): <kısa açıklama>

[isteğe bağlı detay]
```

### Tipler

| Tip | Kullanım |
|-----|----------|
| `feat` | Yeni özellik |
| `fix` | Bug düzeltmesi |
| `chore` | Build, bağımlılık, config değişiklikleri |
| `docs` | Yalnızca dokümantasyon |
| `style` | Kod formatı (logic değişimi yok) |
| `refactor` | Yeniden yapılandırma (özellik/fix yok) |
| `test` | Test ekleme/düzeltme |
| `perf` | Performans iyileştirmesi |

### Scope'lar

| Scope | Alan |
|-------|------|
| `frontend` | React bileşenleri, store'lar, servisler |
| `backend` | FastAPI, LangGraph, araçlar |
| `tauri` | Rust, sidecar, IPC komutları |
| `styles` | CSS, design tokens |
| `deps` | Bağımlılık güncellemeleri |
| `docs` | Dokümantasyon dosyaları |

### Örnekler

```
feat(backend): add WebSocket streaming for LangGraph events
fix(frontend): correct agent avatar color for reviewer role
chore(deps): add langgraph-checkpoint-sqlite for persistence
docs(api): add WebSocket protocol reference
refactor(tauri): extract sidecar lifecycle to separate module
```

## Geliştirme Akışı

```bash
# 1. Feature dalı aç
git checkout -b feat/ws-backend-streaming

# 2. Değişiklikleri yap
# ...

# 3. Kontroller
npx tsc --noEmit
cd backend && .venv/bin/python3 -c "import app.main; print('OK')"
source $HOME/.cargo/env && cd src-tauri && cargo check

# 4. Commit
git add -p  # değişiklikleri gözden geçirerek ekle
git commit -m "feat(backend): stream LangGraph events via WebSocket"

# 5. Push & PR
git push origin feat/ws-backend-streaming
```

## PR Kontrol Listesi

- [ ] TypeScript derleniyor (`tsc --noEmit`)
- [ ] Backend import hatasız
- [ ] Rust `cargo check` başarılı
- [ ] Commit mesajları Conventional Commits formatında
- [ ] İlgili `.md` dokümantasyonu güncellendi
- [ ] Yeni API endpoint'leri `docs/API.md`'de belgelendi
