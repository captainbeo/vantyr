# Vantyr API

Acceso premium a Claude y Codex por una fracción de las tarifas oficiales — una sola clave, un solo panel, con pago por uso o ilimitado.

## Empieza en 5 minutos

1. **Crea una cuenta** — [Regístrate](/register) y luego [inicia sesión](/login). Después vincula tu **Telegram** en Seguridad → Vinculaciones de cuenta para recibir **$5 de crédito gratis** — suficiente para probar todos los modelos como es debido, sin necesidad de tarjeta.
2. **Añade crédito** — abre la página del [Monedero](/wallet), elige un importe de recarga y paga con tarjeta (Stripe).
   Se aplican tarifas de pago por uso (PAYG) en cada solicitud; consulta la página de [Modelos y precios](/pricing).
3. **Crea una clave de API** — ve a [Claves](/keys), haz clic en **Crear**, dale un nombre y copia la clave.
   > **Consejo:** deja marcada la **Cuota ilimitada**. El campo de cuota limita el gasto total de esta clave; con la cuota ilimitada es el saldo de tu monedero el que controla el gasto.
4. **Apunta tu herramienta a Vantyr** — URL base `https://vantyr.example.com/v1` (marcador de posición; consulta el dominio de lanzamiento), cabecera de autenticación `Authorization: Bearer sk-...`.

## Usar Codex CLI

Añade esto a `~/.codex/config.toml` (crea el archivo si no existe):

```toml
model = "gpt-6-astra"
model_provider = "vantyr"

[model_providers.vantyr]
name = "Vantyr"
base_url = "https://vantyr.example.com/v1"
wire_api = "responses"
env_key = "VANTYR_API_KEY"
```

Luego exporta tu clave y ejecuta:

```bash
export VANTYR_API_KEY="sk-..."
codex
```

**Modelos recomendados:** `gpt-6-astra` (insignia), `gpt-5-6-luna` (económico). Los modelos de Claude funcionan en cualquier herramienta compatible con OpenAI.

## Usar cualquier cliente compatible con OpenAI

```bash
curl https://vantyr.example.com/v1/chat/completions \
  -H "Authorization: Bearer sk-..." \
  -H "Content-Type: application/json" \
  -d '{"model": "claude-sonnet-5", "messages": [{"role": "user", "content": "Hello!"}]}'
```

Usuarios de Claude Code y del SDK de Anthropic: configura `ANTHROPIC_BASE_URL` con `https://vantyr.example.com` y `ANTHROPIC_API_KEY` con tu clave de Vantyr.

## Ilimitado mensual — $180

Un solo pago, 30 días, uso **ilimitado** de Claude + Codex. Sin facturación por token ni facturas sorpresa.

- Precio fijo de $180/mes, cancela cuando quieras (el acceso simplemente caduca; vuelve a comprar para renovar)
- Todos los modelos incluidos, con la misma API
- Se aplican límites de solicitudes de uso razonable

[Suscríbete en la página de Precios](/pricing)

## Preguntas

- **¿Error de "insufficient quota"?** Tu monedero está vacío — recárgalo en la página del [Monedero](/wallet).
- **¿Error de "429 rate limit"?** Has alcanzado el tope de solicitudes por minuto. Espera un minuto o contáctanos para aumentar tu límite.
- Historial de uso: la página de [Registros](/logs) muestra cada solicitud, sus tokens y su coste.
