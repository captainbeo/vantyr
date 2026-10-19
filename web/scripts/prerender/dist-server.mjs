// Throwaway static server over web/dist for local prerender verification.
// Mimics the gateway: directory -> index.html, else SPA fallback to /index.html.
import http from 'node:http'
import fs from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..', '..', 'dist')
const CT = {
  '.html': 'text/html; charset=utf-8',
  '.xml': 'text/xml; charset=utf-8',
  '.png': 'image/png',
  '.txt': 'text/plain',
  '.js': 'text/javascript',
  '.css': 'text/css',
  '.woff2': 'font/woff2',
  '.svg': 'image/svg+xml',
  '.mp4': 'video/mp4',
}

function handler(req, res) {
  let p = decodeURIComponent(req.url.split('?')[0])
  let fp = path.join(root, p)
  if (fs.existsSync(fp) && fs.statSync(fp).isDirectory()) fp = path.join(fp, 'index.html')
  if (fs.existsSync(fp) && fs.statSync(fp).isFile()) {
    res.writeHead(200, { 'Content-Type': CT[path.extname(fp)] || 'application/octet-stream' })
    return res.end(fs.readFileSync(fp))
  }
  res.writeHead(200, { 'Content-Type': 'text/html; charset=utf-8' })
  res.end(fs.readFileSync(path.join(root, 'index.html')))
}

const port = Number(process.env.PORT) || 8123
http.createServer(handler).listen(port, () => console.log(`dist server on http://localhost:${port}`))
