# Vantyr API

公式料金の数分の一でプレミアムな Claude & Codex を利用できます — 1つのキー、1つのダッシュボードで、従量課金か無制限かを選べます。

## 5分で始める

1. **アカウントを作成** — [新規登録](/register)して[ログイン](/login)してください。続いて、セキュリティ → アカウント連携 で **Telegram** を連携すると、**$5分の無料クレジット**を受け取れます — すべてのモデルをじっくり試せる十分な金額で、カードの登録は不要です。
2. **残高をチャージ** — [ウォレット](/wallet)ページを開き、チャージ金額を選択して、カード（Stripe）でお支払いください。
   PAYG（従量課金）の料金はリクエストごとに適用されます。詳しくは[モデルと料金](/pricing)ページをご覧ください。
3. **APIキーを作成** — [キー](/keys)ページに移動して**作成**をクリックし、名前を付けてからキーをコピーします。
   > **ヒント：** **無制限のクォータ**はチェックしたままにしてください。クォータの欄はこのキーの合計利用額の上限です。無制限にしておくと、支出はウォレット残高で管理されます。
4. **ツールの接続先をVantyrに設定** — ベースURLは `https://vantyr.example.com/v1`（プレースホルダー。ローンチ時のドメインをご確認ください）、認証ヘッダーは `Authorization: Bearer sk-...` です。

## Codex CLI を使う

以下を `~/.codex/config.toml` に追加してください（ファイルが存在しない場合は作成してください）：

```toml
model = "gpt-6-astra"
model_provider = "vantyr"

[model_providers.vantyr]
name = "Vantyr"
base_url = "https://vantyr.example.com/v1"
wire_api = "responses"
env_key = "VANTYR_API_KEY"
```

次に、キーをエクスポートして起動します：

```bash
export VANTYR_API_KEY="sk-..."
codex
```

**おすすめのモデル：** `gpt-6-astra`（フラッグシップ）、`gpt-5-6-luna`（低価格）。Claudeのモデルは、OpenAI互換のどのツールでも動作します。

## 任意のOpenAI互換クライアントを使う

```bash
curl https://vantyr.example.com/v1/chat/completions \
  -H "Authorization: Bearer sk-..." \
  -H "Content-Type: application/json" \
  -d '{"model": "claude-sonnet-5", "messages": [{"role": "user", "content": "Hello!"}]}'
```

Claude Code と Anthropic SDK をお使いの方は、`ANTHROPIC_BASE_URL` を `https://vantyr.example.com` に、`ANTHROPIC_API_KEY` を Vantyr のキーに設定してください。

## 無制限月額プラン — $180

1回のお支払いで、30日間 Claude + Codex を**無制限**に利用できます。トークン単位の課金も、想定外の請求書もありません。

- 月額固定 $180、いつでも解約できます（解約するとアクセスは期限で終了します。更新は再購入で行えます）
- すべてのモデルが含まれ、APIインターフェースも同一です
- フェアユースに基づくレート制限が適用されます

[料金ページで購読する](/pricing)

## よくある質問

- **「insufficient quota」エラー？** ウォレット残高が尽きています — [ウォレット](/wallet)ページでチャージしてください。
- **「429 rate limit」エラー？** 1分あたりのリクエスト上限に達しました。しばらくお待ちいただくか、制限の引き上げについてはお問い合わせください。
- 利用履歴：[ログ](/logs)ページで、各リクエストとそのトークン数・費用をすべて確認できます。

