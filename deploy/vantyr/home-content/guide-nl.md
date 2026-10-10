# Vantyr API

Premium-toegang tot Claude & Codex voor een fractie van de officiële prijzen — één sleutel, één dashboard, pay-as-you-go of onbeperkt.

## In 5 minuten aan de slag

1. **Account aanmaken** — [registreer je](/register) en [log in](/login). Koppel vervolgens je **Telegram** onder Beveiliging → Accountkoppelingen om **$5 gratis tegoed** te ontvangen — genoeg om elk model grondig uit te proberen, geen kaart nodig.
2. **Tegoed toevoegen** — open de pagina [Portemonnee](/wallet), kies een opwaardeerbedrag en betaal met kaart (Stripe).
   Er gelden PAYG-tarieven per aanvraag; bekijk de pagina [Modellen & prijzen](/pricing).
3. **API-sleutel aanmaken** — ga naar [Sleutels](/keys), klik op **Aanmaken**, geef de sleutel een naam en kopieer hem.
   > **Tip:** laat **Onbeperkt quotum** aangevinkt. Het quotumveld begrenst de totale uitgaven van deze sleutel; bij onbeperkt bepaalt je portemonneesaldo de uitgaven.
4. **Richt je tool op Vantyr** — basis-URL `https://vantyr.example.com/v1` (placeholder; zie het domein bij de lancering), autorisatieheader `Authorization: Bearer sk-...`.

## Codex CLI gebruiken

Voeg dit toe aan `~/.codex/config.toml` (maak het bestand aan als het nog niet bestaat):

```toml
model = "gpt-6-astra"
model_provider = "vantyr"

[model_providers.vantyr]
name = "Vantyr"
base_url = "https://vantyr.example.com/v1"
wire_api = "responses"
env_key = "VANTYR_API_KEY"
```

Exporteer vervolgens je sleutel en voer dit uit:

```bash
export VANTYR_API_KEY="sk-..."
codex
```

**Aanbevolen modellen:** `gpt-6-astra` (vlaggenschip), `gpt-5-6-luna` (budget). Claude-modellen werken in elke OpenAI-compatibele tool.

## Elke OpenAI-compatibele client gebruiken

```bash
curl https://vantyr.example.com/v1/chat/completions \
  -H "Authorization: Bearer sk-..." \
  -H "Content-Type: application/json" \
  -d '{"model": "claude-sonnet-5", "messages": [{"role": "user", "content": "Hello!"}]}'
```

Gebruikers van Claude Code en de Anthropic SDK: stel `ANTHROPIC_BASE_URL` in op `https://vantyr.example.com` en `ANTHROPIC_API_KEY` op je Vantyr-sleutel.

## Onbeperkt maandelijks — $180

Eén betaling, 30 dagen, **onbeperkt** gebruik van Claude + Codex. Geen facturering per token, geen verrassende facturen.

- Vast bedrag van $180 per maand, altijd opzegbaar (de toegang loopt gewoon af; koop opnieuw om te verlengen)
- Alle modellen inbegrepen, dezelfde API
- Er gelden ratelimieten voor redelijk gebruik

[Abonneer je op de pagina Prijzen](/pricing)

## Vragen

- **Foutmelding "insufficient quota"?** Je portemonnee is leeg — waardeer je saldo op via de [Portemonnee](/wallet)-pagina.
- **Foutmelding "429 rate limit"?** Je hebt de limiet van aanvragen per minuut bereikt. Wacht een minuut, of neem contact met ons op om je limiet te verhogen.
- Gebruiksgeschiedenis: de pagina [Logs](/logs) toont elke aanvraag, de tokens en de kosten.
