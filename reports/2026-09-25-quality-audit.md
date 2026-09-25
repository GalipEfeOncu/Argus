# Argus yayın öncesi kalite denetimi

- **Denetim tarihi:** 25 Eylül 2026
- **Kaynak durumu:** `main`, `ff1da0f` (`1.0.0-alpha.2` kod tabanı)
- **Sınıflandırma:** Salt okunur denetim; uygulama, yapılandırma ve sürüm değişikliği yapılmadı.
- **Yayın kararı:** Bu kaynak durumu için yayını bekletin.

## Denetim özeti

Argus; React 19/Tauri arayüzü, yerel FastAPI sidecar'ı, SQLite olay günlüğü ve deterministik ajan kontrol düzlemi olan bir masaüstü çalışma alanı. Yaklaşık 178 uygulama kaynak dosyası ve 26,7 bin satır kod içeriyor. Mimari, işlevsel akışlar, güvenlik, kalıcılık/kurtarma, API, arayüz/erişilebilirlik, bağımlılıklar ve yayın hazırlığı incelendi. Ödeme, çok kiracılı SaaS ve SEO bu ürün için ilgili olmadığından kapsam dışı bırakıldı.

**Bulgu sayısı:** 0 Kritik, 6 Yüksek, 2 Orta, 0 Düşük.

Depo yönergeleri ve `argus-development` becerisi, kaynak/test incelemesi, yerel tarayıcı gözlemi, `npm audit`, `pip-audit` ve `cargo audit` kullanıldı. `.agents/skills/argus-development/scripts/verify.sh all` geçti: doküman ve sürüm kontrolü, TypeScript, 103 frontend testi, üretim derlemesi, backend importu, 351 backend testi ve `cargo check`. Üretilmiş sözleşme, yerel erişilebilirlik ve platform kontrolleri de geçti. `cargo clippy` ve dört Rust testi ayrı çalıştırıldığında geçti; `cargo fmt --check` geçmedi.

Tarayıcı kontrolü, backend kapalıyken Vite arayüzünün ilk kullanım ekranıyla sınırlıydı. Paketlenmiş Tauri uygulaması, gerçek model sağlayıcısı, temiz Windows/macOS/Linux istemcileri, yerel ekran okuyucuları ve referans donanım performansı bu denetimde çalıştırılmadı. Rust bağımlılık taraması bir güvenlik kaydı döndürdü; kayıt deposundaki bazı `yanked` sorguları ağ zaman aşımına uğradığından taramanın o bölümü tam doğrulanmadı. Bu rapor mevcut `main` kaynağını değerlendirir; belirli bir imzalı/yayımlanacak artefaktı sertifikalandırmaz.

## En yüksek öncelikli konular

1. `SEC-01`: Gizli dosyaların model araçlarıyla sağlayıcıya aktarılabilmesi.
2. `FLOW-02` ve `FLOW-03`: İnsan mesajları ile açık `@agent` yönlendirmelerinin güvenilir biçimde işlenmemesi.
3. `AUTH-04`: `ask_each_time` onayının ilgili işlemi açamaması.
4. `REC-05`: Yeniden başlatma sonrasında kuyruklanan atamanın ilerlememesi.
5. `REL-06`: Kilitli bağımlılıkların yayın tedarik zinciri kapısını geçmemesi.

## Bulgular

### [SEC-01] Gizli proje dosyaları modele aktarılabiliyor

- **Önem:** Yüksek
- **Konum:** `backend/app/services/workspace_service.py:525-595`, `backend/app/services/assignment_worker.py:215-219,274-293`
- **Doğrulama:** Çalışma zamanı; sahte içerikli geçici `.env` dosyası kullanıldı.

**Sorun:** `read_file` ve `search_files` gizli dosyaları filtrelemiyor. Araç sonucu takip eden sağlayıcı mesajına ekleniyor. Sentetik `.env` dosyası hem doğrudan okunabildi hem aramada bulundu. Bu yol, `docs/SECURITY.md` içindeki bilinen sır çıkarma sınırıyla çelişiyor.

**Etkisi:** Seçilen proje gerçek sır dosyaları içeriyorsa modelin talep ettiği içerik yapılandırılmış sağlayıcıya gidebilir. Bu denetim gerçek bir sırın sızdığını göstermedi.

**Düzeltme:** Sağlayıcıya teslimden önce hassas dosya yolları ve içerikleri için zorunlu koruma uygulayın; gerekirse açık, dar kapsamlı kullanıcı izni tasarlayın. Gizli ve iç içe dosyaları kapsayan sahte sır testleriyle sağlayıcıya teslimi doğrulayın.

### [FLOW-02] Yeni insan mesajı güvenilir biçimde yeni tur başlatmıyor

- **Önem:** Yüksek
- **Konum:** `backend/app/api/websocket.py:115-123`, `backend/app/services/command_processor.py:99-106,156-161`, `backend/app/services/session_runtime_manager.py:50-58`
- **Doğrulama:** Statik kod akışı.

**Sorun:** `message.send` sonrasında çalışma zamanı yalnızca doğrudan sohbet için başlatılıyor. Çalışan proje oturumunda takip mesajı kalıcı olarak kaydedilip aktif Coordinator turunu geçersiz kılabiliyor, fakat yerine yeni tur planlanmıyor. Doğrudan sohbette yanıt akarken gelen ikinci mesaj için `start()` aktif görev nedeniyle `false` döndürüyor; sonraya bırakılmış bir başlatma görünmüyor.

**Etkisi:** Kabul edilmiş bir kullanıcı müdahalesi yanıtsız kalabilir.

**Düzeltme:** Kalıcı bekleyen mesajlardan tekil ve sıralı tur planlayın. Çalışan proje turuna müdahale, akış sırasında ikinci sohbet mesajı ve tur tamamlandıktan sonraki kuyruk boşaltma yollarını test edin.

### [FLOW-03] Açık `@agent` mesajları hedefe teslim edilmiyor

- **Önem:** Yüksek
- **Konum:** `backend/app/services/participant_instruction_service.py:33-65`, `backend/app/api/websocket.py:119-123`
- **Doğrulama:** Statik kod akışı ve üretim çağrı yerleri taraması.

**Sorun:** Açık mention, hedef katılımcı için `pending` talimat satırı yazıyor. Üretim akışında `pending_for()` sonucunu tüketip uzmanı uyandıran bir çağrı bulunmuyor.

**Etkisi:** Kullanıcı mesajı ortak zaman çizelgesinde görünse de hedef uzmana ulaşmıyor; görünür müdahale beklentisi karşılanmıyor.

**Düzeltme:** Bekleyen talimatları scheduler'a bağlayın. Teslim, tekrar bağlanma, yinelenen komut ve iptal durumları için olay/sözleşme testleri ekleyin.

### [AUTH-04] `ask_each_time` onayı ilgili işlemi açamıyor

- **Önem:** Yüksek
- **Konum:** `backend/app/services/approval_grant_service.py:117-123`, `backend/app/services/acceptance_service.py:187-201`, `src/services/websocket.ts:126-134`
- **Doğrulama:** Statik kod akışı.

**Sorun:** Yetki değerlendirmesi `ask_each_time` için kayıtlı tek kullanımlık hibeyi incelemeden her seferinde `ask` döndürüyor. Arayüz kullanıcı onayını `grantScope: 'once'` olarak gönderiyor. Böylece diff uygulama akışında onay sonrası tekrar deneme yeniden onay istiyor.

**Etkisi:** Seçilen izin davranışında onay gerektiren işlem tamamlanamayabilir.

**Düzeltme:** Her isteğe bağlı onayı yalnızca ilişkili tek işlem için tüketin. İlk isteğin onayla ilerlediğini, ikinci bağımsız isteğin yeniden onay gerektirdiğini test edin.

### [REC-05] Yeniden başlatmada kuyruklanan uzman işi ilerlemiyor

- **Önem:** Yüksek
- **Konum:** `backend/app/services/assignment_scheduler.py:519-524`, `backend/app/main.py:30-34`, `backend/app/services/session_runtime_manager.py:94-113`
- **Doğrulama:** Statik başlangıç/kurtarma akışı.

**Sorun:** Kurtarma kesilmiş uygun atamayı `created` durumuna getirip scheduler yönetimli tekrar deneme kuyruğuna alındığını bildiriyor. Başlangıç akışı bu atamayı dispatch etmiyor; runtime kurtarması yalnızca sonucu belirsiz Coordinator/doğrudan sohbet sağlayıcı işlemlerini ele alıyor.

**Etkisi:** Oturum çalışıyor görünürken uzman işi ilerlemeyebilir.

**Düzeltme:** Başlangıçta güvenle tekrar başlatılabilecek atamaları scheduler üzerinden uyandırın; sonucu belirsiz mutasyonları otomatik oynatmayın. Uzman çalışırken süreç kesme ve yeniden başlatma testi ekleyin.

### [REL-06] Kilitli bağımlılıklar tedarik zinciri kapısını geçmiyor

- **Önem:** Yüksek — yayın kapısı; Argus içinde sömürülebilirlik ayrıca doğrulanmadı.
- **Konum:** `package-lock.json:2613-2615`, `backend/uv.lock:61-62`, `src-tauri/Cargo.lock:3240-3241`, `.github/workflows/supply-chain.yml:49-52`
- **Doğrulama:** Güncel bağımlılık taramaları.

**Sorun:** `npm audit` dört yüksek bulgu bildirdi; üretim zincirindeki `fast-uri` 3.1.5 için [3.1.6 düzeltmesi](https://github.com/advisories/GHSA-f65p-4m7j-42xc) mevcut. `pip-audit`, `anyio` 4.14.1 üzerinde üç kayıt buldu; [4.14.2 düzeltmesi](https://github.com/agronholm/anyio/security/advisories/GHSA-82r6-8w77-94w6) mevcut. `cargo audit`, `rustls` 0.23.42 için [RUSTSEC-2026-0285](https://rustsec.org/advisories/RUSTSEC-2026-0285.html) bildirdi; düzeltme 0.23.45 ve sonrası.

**Etkisi:** Kaynak etiketi üzerindeki tedarik zinciri iş akışı bu kilitlerle geçmez. Danışmanlık kayıtlarının her biri Argus'ta kullanılabilir bir saldırı yolunun kanıtı değildir.

**Düzeltme:** Kilit dosyalarını hedefli güncelleyin; npm/Python/Rust taramalarını, sözleşmeleri, testleri ve yerel paketleme kontrollerini yeniden çalıştırın. Rust taramasının ağ zaman aşımına uğrayan bölümünü de tamamlayın.

### [CI-07] Rust biçim kontrolü CI'da hata veriyor

- **Önem:** Orta
- **Konum:** `src-tauri/src/sidecar.rs:152`, `.github/workflows/ci.yml:91-95`
- **Doğrulama:** `cargo fmt --check` komutu hata verdi.

**Sorun:** `ensure` işlevinin imzası `rustfmt` biçimine uymuyor. CI Rust işi biçim kontrolünde durur; ayrı çalıştırılan `cargo clippy` ve dört Rust testi geçti.

**Düzeltme:** İmzayı biçimlendirin ve Rust CI işini baştan sona tekrar çalıştırın.

### [UX-08] İlk oturum ekranı yanlış yönlendiriyor

- **Önem:** Orta
- **Konum:** `src/components/pages/Dashboard.tsx:49-59`
- **Doğrulama:** Backend kapalıyken tarayıcıda görüldü ve düğmeye tıklandı.

**Sorun:** Katalog yüklenemediğinde ekran aynı anda “Local catalogue unavailable” ve “No sessions yet” gösteriyor. “Start your first session” düğmesi, yanındaki Coordinator + uzman proje oturumu vaadine rağmen proje/uzman içermeyen “Direct chat” ekranına gidiyor.

**Etkisi:** Kullanıcı mevcut oturumlarının olmadığını sanabilir ve beklediğinden farklı bir akışa girer.

**Düzeltme:** Yükleme hatasında boş durum iddiasını gizleyin. Düğmeyi proje oturumu kurulumuna yönlendirin veya metni gerçek hedefe göre değiştirin; hata ve boş durumları ayrı arayüz testleriyle doğrulayın.

## Önerilen düzeltme sırası

1. `SEC-01` için model araçlarının dosya/içerik sınırını kapatın.
2. `FLOW-02`, `FLOW-03` ve `REC-05` için kalıcı talimat kuyruğu ile tekil scheduler uyandırmasını birlikte ele alın; sıralama ve yeniden başlatma testleri ekleyin.
3. `AUTH-04` için işlem başına tek kullanımlık onay semantiğini düzeltin.
4. `REL-06` ve `CI-07` yayın kapılarını temizleyin.
5. `UX-08` ilk kullanım akışını düzeltin ve gerçek ekranlarda tekrar kontrol edin.
6. Aynı kaynak etiketinden paketlenmiş artefaktlarla `docs/PUBLISH_CHECKLIST.md` içindeki temiz istemci, erişilebilirlik, yaşam döngüsü, yedekleme ve referans donanım kapılarını tamamlayın.

## Son değerlendirme

Katman ayrımı ve otomatik doğrulama altyapısı makul; temel kod kalitesi kabul edilebilir. Ancak insan müdahalesi, izin ve kurtarma akışları için test koruması yetersiz. Otomatik erişilebilirlik kontrolleri geçti, ciddi bir performans gerilemesi bu denetimde saptanmadı; paketli performans ve yerel ekran okuyucu davranışı bilinmiyor. `README.md` bu Alpha'nın mutasyon, test ve shell uzman yürütmesini henüz sunmadığını açıkça belirtiyor; tam yazılım geliştirme MVP'si için bu planlı sınır da ayrıca geçerli.

**Yayın sonucu:** `SEC-01`, `FLOW-02/03`, `AUTH-04`, `REC-05` ve yayın kapıları çözülüp aynı artefaktlar üzerinde zorunlu yayın kanıtları tamamlanmadan yayın onayı verilmemeli.
