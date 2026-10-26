const fs = require('fs')
const path = require('path')

// Per-language replacement for the crypto-networks line: from the 8-network
// list to 11 networks + GRAM note. Keys: 'old' fragment must exist in the
// payments <li>; new text per language.
const updates = {
  index: {
    old: 'USDT / USDC at 1:1 against the dollar, on 8 networks: TRON (TRC20), Solana, Ethereum, BNB Chain, Polygon, Plasma, TON, Aptos.',
    network: 'USDT / USDC at 1:1 against the dollar, on 11 networks: TRON (TRC20), Solana, Ethereum, BNB Chain, Polygon, Plasma, TON, Aptos, Arbitrum One, X Layer, Base.',
    note: 'On Base only USDC is supported; on TON you can also pay with native GRAM.',
  },
  de: {
    old: 'USDT / USDC im Verhältnis 1:1 zum Dollar, auf 8 Netzwerken: TRON (TRC20), Solana, Ethereum, BNB Chain, Polygon, Plasma, TON, Aptos.',
    network: 'USDT / USDC im Verhältnis 1:1 zum Dollar, auf 11 Netzwerken: TRON (TRC20), Solana, Ethereum, BNB Chain, Polygon, Plasma, TON, Aptos, Arbitrum One, X Layer, Base.',
    note: 'Auf Base wird nur USDC unterstützt; auf TON kannst du auch mit nativem GRAM zahlen.',
  },
  nl: {
    old: 'USDT / USDC 1:1 tegen de dollar, op 8 netwerken: TRON (TRC20), Solana, Ethereum, BNB Chain, Polygon, Plasma, TON, Aptos.',
    network: 'USDT / USDC 1:1 tegen de dollar, op 11 netwerken: TRON (TRC20), Solana, Ethereum, BNB Chain, Polygon, Plasma, TON, Aptos, Arbitrum One, X Layer, Base.',
    note: 'Op Base wordt alleen USDC ondersteund; op TON kun je ook met native GRAM betalen.',
  },
  tr: {
    old: 'USDT / USDC, dolara karşı 1:1 oranla, 8 ağda: TRON (TRC20), Solana, Ethereum, BNB Chain, Polygon, Plasma, TON, Aptos.',
    network: 'USDT / USDC, dolara karşı 1:1 oranla, 11 ağda: TRON (TRC20), Solana, Ethereum, BNB Chain, Polygon, Plasma, TON, Aptos, Arbitrum One, X Layer, Base.',
    note: 'Base ağında yalnızca USDC desteklenir; TON’da yerel GRAM ile de ödeyebilirsin.',
  },
  es: {
    old: 'USDT / USDC a 1:1 contra el dólar, en 8 redes: TRON (TRC20), Solana, Ethereum, BNB Chain, Polygon, Plasma, TON, Aptos.',
    network: 'USDT / USDC a 1:1 contra el dólar, en 11 redes: TRON (TRC20), Solana, Ethereum, BNB Chain, Polygon, Plasma, TON, Aptos, Arbitrum One, X Layer, Base.',
    note: 'En Base solo se admite USDC; en TON también puedes pagar con GRAM nativo.',
  },
  ar: {
    old: 'USDT / USDC بنسبة 1:1 مقابل الدولار، عبر 8 شبكات: TRON (TRC20) وSolana وEthereum وBNB Chain وPolygon وPlasma وTON وAptos.',
    network: 'USDT / USDC بنسبة 1:1 مقابل الدولار، عبر 11 شبكة: TRON (TRC20) وSolana وEthereum وBNB Chain وPolygon وPlasma وTON وAptos وArbitrum One وX Layer وBase.',
    note: 'على شبكة Base يُدعم USDC فقط؛ وعلى TON يمكنك الدفع أيضًا بعملة GRAM الأصلية.',
  },
  fr: {
    old: 'USDT / USDC à 1:1 contre le dollar, sur 8 réseaux : TRON (TRC20), Solana, Ethereum, BNB Chain, Polygon, Plasma, TON, Aptos.',
    network: 'USDT / USDC à 1:1 contre le dollar, sur 11 réseaux : TRON (TRC20), Solana, Ethereum, BNB Chain, Polygon, Plasma, TON, Aptos, Arbitrum One, X Layer, Base.',
    note: 'Sur Base, seul l’USDC est pris en charge ; sur TON vous pouvez aussi payer en GRAM natif.',
  },
  ru: {
    old: 'USDT / USDC 1:1 к доллару, в 8 сетях: TRON (TRC20), Solana, Ethereum, BNB Chain, Polygon, Plasma, TON, Aptos.',
    network: 'USDT / USDC 1:1 к доллару, в 11 сетях: TRON (TRC20), Solana, Ethereum, BNB Chain, Polygon, Plasma, TON, Aptos, Arbitrum One, X Layer, Base.',
    note: 'В сети Base поддерживается только USDC; в TON можно платить также нативным GRAM.',
  },
  ja: {
    old: 'USDT / USDC は米ドルに対して 1:1、8 ネットワークに対応：TRON (TRC20)、Solana、Ethereum、BNB Chain、Polygon、Plasma、TON、Aptos。',
    network: 'USDT / USDC は米ドルに対して 1:1、11 ネットワークに対応：TRON (TRC20)、Solana、Ethereum、BNB Chain、Polygon、Plasma、TON、Aptos、Arbitrum One、X Layer、Base。',
    note: 'Base では USDC のみ対応。TON ではネイティブの GRAM でも支払えます。',
  },
  vi: {
    old: 'USDT / USDC tỷ lệ 1:1 với đô la, trên 8 mạng: TRON (TRC20), Solana, Ethereum, BNB Chain, Polygon, Plasma, TON, Aptos.',
    network: 'USDT / USDC tỷ lệ 1:1 với đô la, trên 11 mạng: TRON (TRC20), Solana, Ethereum, BNB Chain, Polygon, Plasma, TON, Aptos, Arbitrum One, X Layer, Base.',
    note: 'Trên Base chỉ hỗ trợ USDC; trên TON bạn cũng có thể trả bằng GRAM native.',
  },
  'zh-CN': {
    old: 'USDT / USDC 与美元 1:1，支持 8 个网络：TRON (TRC20)、Solana、Ethereum、BNB Chain、Polygon、Plasma、TON、Aptos。',
    network: 'USDT / USDC 与美元 1:1，支持 11 个网络：TRON (TRC20)、Solana、Ethereum、BNB Chain、Polygon、Plasma、TON、Aptos、Arbitrum One、X Layer、Base。',
    note: 'Base 网络仅支持 USDC；TON 网络还支持原生 GRAM 支付。',
  },
  'zh-TW': {
    old: 'USDT / USDC 與美元 1:1，支援 8 個網路：TRON (TRC20)、Solana、Ethereum、BNB Chain、Polygon、Plasma、TON、Aptos。',
    network: 'USDT / USDC 與美元 1:1，支援 11 個網路：TRON (TRC20)、Solana、Ethereum、BNB Chain、Polygon、Plasma、TON、Aptos、Arbitrum One、X Layer、Base。',
    note: 'Base 網路僅支援 USDC；TON 網路還支援原生 GRAM 支付。',
  },
}

const dir = 'deploy/vantyr/static/docs'
let failures = 0
for (const [name, u] of Object.entries(updates)) {
  const file = path.join(dir, name === 'index' ? 'index.html' : name + '.html')
  let text = fs.readFileSync(file, 'utf8')
  if (!text.includes(u.old)) {
    console.error('anchor not found in ' + name)
    failures++
    continue
  }
  text = text.replace(u.old, u.network)
  fs.writeFileSync(file, text)
  console.log('updated network line in', name)
}
if (failures) process.exitCode = 1
