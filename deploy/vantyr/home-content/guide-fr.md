# Vantyr API

Un accès premium à Claude et Codex pour une fraction des tarifs officiels — une seule clé, un seul tableau de bord, paiement à l'usage ou illimité.

## Commencez en 5 minutes

1. **Créez un compte** — [Inscrivez-vous](/register), puis [connectez-vous](/login). Liez ensuite votre compte **Telegram** dans Sécurité → Associations de compte pour recevoir **$5 de crédit gratuit** — de quoi tester correctement tous les modèles, sans carte bancaire.
2. **Ajoutez du crédit** — ouvrez la page [Portefeuille](/wallet), choisissez un montant de recharge et payez par carte (Stripe).
   Les tarifs PAYG s'appliquent par requête ; consultez la page [Modèles et tarifs](/pricing).
3. **Créez une clé API** — rendez-vous sur [Clés API](/keys), cliquez sur **Créer**, donnez-lui un nom, puis copiez la clé.
   > **Astuce :** laissez **Quota illimité** coché. Le champ quota limite la dépense totale de cette clé ; en illimité, c'est le solde de votre portefeuille qui contrôle les dépenses.
4. **Dirigez votre outil vers Vantyr** — URL de base `https://vantyr.example.com/v1` (provisoire ; voir le domaine de lancement), en-tête d'authentification `Authorization: Bearer sk-...`.

## Utiliser Codex CLI

Ajoutez ceci à `~/.codex/config.toml` (créez le fichier s'il n'existe pas) :

```toml
model = "gpt-6-astra"
model_provider = "vantyr"

[model_providers.vantyr]
name = "Vantyr"
base_url = "https://vantyr.example.com/v1"
wire_api = "responses"
env_key = "VANTYR_API_KEY"
```

Exportez ensuite votre clé et lancez :

```bash
export VANTYR_API_KEY="sk-..."
codex
```

**Modèles recommandés :** `gpt-6-astra` (modèle phare), `gpt-5-6-luna` (économique). Les modèles Claude fonctionnent dans n'importe quel outil compatible OpenAI.

## Utiliser n'importe quel client compatible OpenAI

```bash
curl https://vantyr.example.com/v1/chat/completions \
  -H "Authorization: Bearer sk-..." \
  -H "Content-Type: application/json" \
  -d '{"model": "claude-sonnet-5", "messages": [{"role": "user", "content": "Hello!"}]}'
```

Utilisateurs de Claude Code et du SDK Anthropic : définissez `ANTHROPIC_BASE_URL` sur `https://vantyr.example.com` et `ANTHROPIC_API_KEY` avec votre clé Vantyr.

## Forfait mensuel illimité — $180

Un seul paiement, 30 jours, **illimité** pour Claude + Codex. Pas de facturation au token, pas de facture surprise.

- $180/mois à prix fixe, résiliable à tout moment (l'accès expire simplement ; rachetez le forfait pour renouveler)
- Tous les modèles inclus, la même API
- Des limites de débit en usage raisonnable s'appliquent

[Abonnez-vous sur la page Tarifs](/pricing)

## Questions

- **Erreur « insufficient quota » ?** Votre portefeuille est vide — rechargez-le sur la page [Portefeuille](/wallet).
- **Erreur « 429 rate limit » ?** Vous avez atteint le plafond de requêtes par minute. Attendez une minute, ou contactez-nous pour faire augmenter votre limite.
- Historique d'utilisation : la page [Journaux](/logs) affiche chaque requête, ses tokens et son coût.
