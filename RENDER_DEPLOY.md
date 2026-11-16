# Mark-LVII Dashboard on Render — Deploy Guide

Render-e shudhu **dashboard + API** host hobe. Desktop HUD (PyQt window +
Gemini Live voice) PC-tei thakbe — Render-e screen/mic/Qt nei, tai HUD
kokhono Render-e cholbe na. PC holo brain, Render holo dashboard-er public
dorja.

## Deploy steps

### 1. Repo GitHub-e push koro

```bash
git add render.yaml dashboard/render_entry.py RENDER_DEPLOY.md
git commit -m "Add Render hosting for dashboard"
git push
```

### 2. Render-e Web Service banao

- [dashboard.render.com](https://dashboard.render.com) → **New → Web Service**
- Repo-ta select koro. Render `render.yaml` Blueprint-ta nijei dhore felbe
  (na dhorele: **New → Blueprint**, repo select koro).
- Service name: `mark-lvii-dashboard`, Environment: Python.
- Build Command: `pip install -r requirements.txt`
- Start Command: `python -m dashboard.render_entry`

### 3. Deploy

**Deploy** chap dao. Prothom build-e ektu time lagbe — `requirements.txt`-e
PyQt6 / OpenCV-r moto desktop package-o ache, jegulo dashboard-er dorkar
nei kintu pip Linux-e install kore nebe.

### 4. Public URL Mark-e boshao

Deploy sesh hole Render ekta URL debe, jemon:

```
https://mark-lvii-dashboard.onrender.com
```

Ei URL-ta copy kore Mark-er **Plugin Settings → 📱 JARVIS LINK → Render
URL** field-e paste koro. Tarpor theke phone / browser / Chrome extension
oi URL diye dashboard-e pouchabe — PC-r LAN IP-r dorkar nei.

### 5. (Optional) Fixed BROWSER_TOKEN set koro

Render dashboard → service → **Environment** → Add:

| Key | Value |
|---|---|
| `BROWSER_TOKEN` | ekta lomba random string (nije banao) |

Eta Chrome extension-er fixed token-er jonno — restart-er poreo token
ek-i thakbe. Note: `dashboard/server.py` ekhono `BROWSER_TOKEN` pore na —
eta extension-er kaaj-er jonno reserve kora naam; ekhon set kore rakhle
kono khoti nei. Dashboard-er nijer login token memory-te thake (12h TTL),
restart hole pairing key diye abar login korte hoy.

## Honest limits — age jene rakho

- **Free tier ghumay.** Kichukkhon keu na ele service sleep kore jay;
  prothom load-e **~30–60 second** lagte pare. Eta Render free tier-er
  niyom, bug na.
- **HUD PC-tei.** Voice session, PyQt window, screen control — sob PC-te
  cholbe. Render-e shudhu dashboard page + `/api/*` routes.
- **Dashboard-e PC-r kaaj queue hoy.** `/api/command` PC-r Mark-ke pathay —
  PC bondho thakle ba Mark na cholle command pouchabe na. Dashboard chollei
  PC cholche, emon na.
- **LAN IP / port lekha cosmetic.** Dashboard page-er bhetore kothao
  `192.168.x.x:8000` dekhale ghabraben na — ota PC-r local address; public
  URL diyei kaj hobe.
- **TLS Render kore.** Render nije HTTPS dey, tai ei service plain HTTP-te
  chole — kono certificate banate hoy na.
