# Vantyr API

Resmi fiyatların çok küçük bir bölümü karşılığında premium Claude ve Codex erişimi — tek anahtar, tek panel; kullandıkça öde ya da sınırsız.

## 5 dakikada başla

1. **Hesap oluştur** — [Kaydol](/register), ardından [oturum aç](/login). Sonra **5 $ ücretsiz kredi** almak için **Telegram** hesabını Güvenlik → Hesap Bağlamaları altından bağla — her modeli gerektiği gibi denemeye yeter, kart gerekmez.
2. **Kredi ekle** — [Cüzdan](/wallet) sayfasını aç, bir yükleme tutarı seç ve kartla öde (Stripe).
   İstek başına kullandıkça öde (PAYG) fiyatları uygulanır; [Modeller ve Fiyatlandırma](/pricing) sayfasına bak.
3. **API anahtarı oluştur** — [API Anahtarları](/keys) sayfasına git, **Oluştur**'a tıkla, bir ad ver ve anahtarı kopyala.
   > **İpucu:** **Sınırsız kota** işaretli kalsın. Kota alanı bu anahtarın toplam harcamasını sınırlar; sınırsız bırakırsan harcamayı cüzdan bakiyen kontrol eder.
4. **Aracını Vantyr'a yönlendir** — temel URL `https://vantyr.xyz/v1` (yer tutucu; lansman alan adına bak), kimlik doğrulama başlığı `Authorization: Bearer sk-...`.

## Codex CLI kullanımı

Aşağıdakileri `~/.codex/config.toml` dosyasına ekle (dosya yoksa oluştur):

```toml
model = "gpt-6-astra"
model_provider = "vantyr"

[model_providers.vantyr]
name = "Vantyr"
base_url = "https://vantyr.xyz/v1"
wire_api = "responses"
env_key = "VANTYR_API_KEY"
```

Sonra anahtarını export et ve şunları çalıştır:

```bash
export VANTYR_API_KEY="sk-..."
codex
```

**Önerilen modeller:** `gpt-6-astra` (en üst düzey), `gpt-5-6-luna` (ekonomik). Claude modelleri OpenAI uyumlu her araçta çalışır.

## OpenAI uyumlu herhangi bir istemciyle kullanım

```bash
curl https://vantyr.xyz/v1/chat/completions \
  -H "Authorization: Bearer sk-..." \
  -H "Content-Type: application/json" \
  -d '{"model": "claude-sonnet-5", "messages": [{"role": "user", "content": "Hello!"}]}'
```

Claude Code ve Anthropic SDK kullanıcıları: `ANTHROPIC_BASE_URL` değerini `https://vantyr.xyz`, `ANTHROPIC_API_KEY` değerini Vantyr anahtarın olarak ayarla.

## Sınırsız Aylık — $180

Tek ödeme, 30 gün, **sınırsız** Claude + Codex kullanımı. Token başına faturalama yok, sürpriz faturalar yok.

- Sabit aylık 180 $, istediğin zaman iptal et (erişim yalnızca sona erer; yenilemek için tekrar satın al)
- Tüm modeller dahil, aynı API yüzeyi
- Adil kullanım kapsamında istek limitleri uygulanır

[Fiyatlandırma sayfasından abone ol](/pricing)

## Sorular

- **"insufficient quota" hatası mı?** Cüzdanın boş — [Cüzdan](/wallet) sayfasından bakiye yükle.
- **"429 rate limit" hatası mı?** Dakika başına istek üst sınırına ulaştın. Bir dakika bekle ya da limitini yükseltmemiz için bizimle iletişime geç.
- Kullanım geçmişi: [Günlükler](/logs) sayfası her isteği, token'larını ve maliyetini gösterir.
