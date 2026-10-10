# Vantyr API

Premium-Zugriff auf Claude & Codex für einen Bruchteil der offiziellen Preise — ein Schlüssel, ein Dashboard, bezahle pro Nutzung oder unbegrenzt.

## In 5 Minuten loslegen

1. **Konto erstellen** — [Registriere dich](/register) und [melde dich an](/login). Verknüpfe dann dein **Telegram** unter Sicherheit → Kontoverknüpfungen, um **5 $ Guthaben gratis** zu erhalten — genug, um jedes Modell ausgiebig auszuprobieren, ganz ohne Karte.
2. **Guthaben aufladen** — öffne die [Wallet](/wallet), wähle einen Aufladebetrag und bezahle mit Karte (Stripe).
   PAYG-Tarife gelten pro Anfrage; sieh dir die Seite [Modelle & Preise](/pricing) an.
3. **API-Schlüssel erstellen** — gehe zu [Schlüssel](/keys), klicke auf **Erstellen**, gib ihm einen Namen und kopiere den Schlüssel.
   > **Tipp:** Lasse **Unbegrenztes Kontingent** aktiviert. Das Kontingentfeld begrenzt die Gesamtausgaben dieses Schlüssels; unbegrenzt heißt, dein Wallet-Guthaben steuert die Ausgaben.
4. **Richte dein Tool auf Vantyr** — Basis-URL `https://vantyr.xyz/v1` (Platzhalter; siehe Launch-Domain), Auth-Header `Authorization: Bearer sk-...`.

## Codex CLI verwenden

Füge dies zu `~/.codex/config.toml` hinzu (erstelle die Datei, falls sie nicht existiert):

```toml
model = "gpt-6-astra"
model_provider = "vantyr"

[model_providers.vantyr]
name = "Vantyr"
base_url = "https://vantyr.xyz/v1"
wire_api = "responses"
env_key = "VANTYR_API_KEY"
```

Exportiere dann deinen Schlüssel und starte:

```bash
export VANTYR_API_KEY="sk-..."
codex
```

**Empfohlene Modelle:** `gpt-6-astra` (Flaggschiff), `gpt-5-6-luna` (Budget). Claude-Modelle funktionieren in jedem OpenAI-kompatiblen Tool.

## Beliebigen OpenAI-kompatiblen Client verwenden

```bash
curl https://vantyr.xyz/v1/chat/completions \
  -H "Authorization: Bearer sk-..." \
  -H "Content-Type: application/json" \
  -d '{"model": "claude-sonnet-5", "messages": [{"role": "user", "content": "Hello!"}]}'
```

Claude-Code- und Anthropic-SDK-Nutzer: Setze `ANTHROPIC_BASE_URL` auf `https://vantyr.xyz` und `ANTHROPIC_API_KEY` auf deinen Vantyr-Schlüssel.

## Unbegrenzt im Monat — 180 $

Eine Zahlung, 30 Tage, **unbegrenzte** Claude- + Codex-Nutzung. Keine Abrechnung pro Token, keine überraschenden Rechnungen.

- Pauschal 180 $/Monat, jederzeit kündbar (der Zugang läuft einfach ab; zum Verlängern erneut kaufen)
- Alle Modelle inklusive, gleiche API-Oberfläche
- Faire Nutzungs-Rate-Limits gelten

[Abo auf der Preisseite abschließen](/pricing)

## Fragen

- **Fehler „insufficient quota"?** Deine Wallet ist leer — lade Guthaben auf der [Wallet](/wallet)-Seite auf.
- **Fehler „429 rate limit"?** Du hast das Anfragelimit pro Minute erreicht. Warte eine Minute oder kontaktiere uns, um dein Limit zu erhöhen.
- Nutzungsverlauf: Die Seite [Protokolle](/logs) zeigt jede Anfrage mit ihren Tokens und Kosten.

