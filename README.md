![License](https://img.shields.io/badge/License-MIT-green)
![Python](https://img.shields.io/badge/Python-3.12%2B-3776AB?logo=python&logoColor=white)
![Node](https://img.shields.io/badge/Node.js-18%2B-339933?logo=node.js&logoColor=white)
![FastAPI](https://img.shields.io/badge/FastAPI-API-009485?logo=fastapi&logoColor=white)
![Vite](https://img.shields.io/badge/Vite-Frontend-646CFF?logo=vite&logoColor=white)
![Playwright](https://img.shields.io/badge/Playwright-E2E-45ba4b?logo=playwright&logoColor=white)
![Groq](https://img.shields.io/badge/LLM-Groq-black)

# HunBook – Ingyenes AI‑könyvíró (Groq + Llama3)

HunBook egy modern, ingyenesen futtatható webalkalmazás, amely képes egyetlen témamegadással teljes könyvek vázlatát és fejezeteit legenerálni. A háttérben a Groq OpenAI‑kompatibilis modellek (pl. Llama3 OSS) dolgoznak, a frontenden pedig egy gyors, letisztult Vite alapú UI biztosítja a valós idejű streamelést és letöltést (TXT/PDF).

<p align="center">
  <img src="web/public/hunbook.png" alt="HunBook" width="460" />
</p>

---

## Tartalomjegyzék

- [Mi ez?](#mi-ez)
- [Fő funkciók](#fő-funkciók)
- [Technológiai stack](#technológiai-stack)
- [Architektúra](#architektúra)
- [Helyi futtatás](#helyi-futtatás)
- [Környezeti változók](#környezeti-változók)
- [Használat](#használat)
- [API áttekintés](#api-áttekintés)
- [Tesztelés](#tesztelés)
- [Hibaelhárítás](#hibaelhárítás)
- [Roadmap](#roadmap)
- [Licenc](#licenc)
- [Köszönetnyilvánítás](#köszönetnyilvánítás)

---

## Mi ez?

A HunBook célja, hogy nonprofit módon, lokálisan is könnyen futtathatóan biztosítson könyvgenerálási élményt magyar nyelvű (és egyéb) tartalmakhoz. A rendszer felosztja a feladatot: előbb vázlatot készít (fejezetcímekkel), majd fejezetenként stream-eli az elkészült tartalmat, amelyet a felhasználó a böngészőben követhet és letölthet.

## Fő funkciók

- **[BYOK (Bring Your Own Key)]**: saját Groq API‑kulcs használata kliensoldali tárolással.
- **[Resumable streaming]**: hálózati szakadás esetén automatikus újrapróbálkozás és folytatás.
- **[Üveg (glass) overlay]**: hosszabb műveletek (vázlat/ export) alatt egyértelmű visszajelzés.
- **[Kvóta + TPD]**: napi kvótakezelés és TPD (Tokens per Day) üzenetek magyar nyelven.
- **[Fejezetszám kontroll]**: maximum `MAX_SECTIONS=25`, minimum `MIN_SECTIONS` (pl. 10–15) fallback.
- **[Export]**: TXT/PDF letöltés explicit CORS fejekkel, Windows fallback PDF (fpdf2).
- **[CORS/cold‑start kezelés]**: API warmup (`/healthz`) és preflight‑barát beállítások.
- **[UX]**: progress bar, státuszok, Stop gomb, sablonok, haladó mód.

Források a kódban: `web/src/main.js`, `server/app.py`, `server/routers/generation.py`, `server/services/llm_service.py`.

## Technológiai stack

- **Frontend**: Vite, Tailwind, Vanilla JS
- **Backend**: FastAPI, Uvicorn
- **LLM**: Groq OpenAI‑kompatibilis modellek (pl. `openai/gpt-oss-20b`, `openai/gpt-oss-120b`)
- **E2E tesztek**: Playwright
- **Export**: WeasyPrint (PDF), fallback: `fpdf2`

## Architektúra

```mermaid
flowchart LR
  A[Browser (Vite, web/src/main.js)] -- fetch /config,/quota,/structure,/sections/stream --> B[FastAPI (server/app.py)]
  B -- LLM calls --> C[Groq API]
  B -- Export --> D[TXT/PDF]
  A -- BYOK (Authorization: Bearer) --> B
  A -- Warmup /healthz --> B
  B <---> E[(Quota Manager)]
```

---

## Helyi futtatás

### Előfeltételek

- Python 3.12+
- Node.js 18+
- (Windows PDF export esetén) WeasyPrint/GTK runtime – vagy használd az automatikus `fpdf2` fallbacket

### Backend (FastAPI)

```powershell
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt

# (opcionális) szerveroldali Groq kulcs
$env:GROQ_API_KEY = "gsk_..."

# fejlesztői indítás
uvicorn server.app:app --reload --port 8000
```

### Frontend (Vite)

```powershell
cd web
npm ci

# (opcionális) API bázis
$env:VITE_API_BASE = "http://localhost:8000"

npm run dev  # http://localhost:5173
```

---

## Környezeti változók

### Backend

- `GROQ_API_KEY` – szerveroldali kulcs (ha nincs, BYOK is elég)
- `REQUIRE_BYOK` – ha `true`, a kliens kulcsa kötelező
- `QUOTA_PER_DAY` – napi kvóta (pl. 3)
- `MAX_SECTIONS` – max fejezet (alap: 25)
- `MIN_SECTIONS` – min. fejezet fallback (pl. 10–15)
- `SECTION_PACING_S` – fejezetek közötti késleltetés (rate‑limit védelem)
- `FRONTEND_ORIGIN` – CORS beállítás
- `PORT` – alapértelmezett 8000

### Frontend

- `VITE_API_BASE` – API gyökér (pl. `http://localhost:8000`)

---

## Használat

1. Nyisd meg a frontendet (`npm run dev` → http://localhost:5173).
2. Adj meg egy témát (pl. „AI a mindennapokban”).
3. (BYOK) Kattints az „API‑kulcs (BYOK)” gombra, illeszd be a `gsk_...` kulcsot.
4. Generálás:
   - Vázlatkészítés alatt üveg overlay jelenik meg.
   - Vázlat után fejezetenként streamel a rendszer.
5. Letöltés: TXT vagy PDF.

Tippek:
- Üres/gyenge outline esetén a szerver többfejezetes fallbacket ad.
- Hálózati szakadásnál automatikus újrapróbálkozás történik.

---

## API áttekintés

- `GET /healthz` – readiness
- `GET /config` – `require_byok`, `has_server_key`
- `GET /api/key/validate` – BYOK rapid ellenőrzés (csak 401‑re szigorú)
- `GET /api/quota` – kvóta állapot
- `POST /api/structure` – outline generálás (`StructureRequest` / `StructureResponse`)
- `POST /api/sections/stream` – NDJSON stream: `section_start`, `token`, `stats`, `rate_limit_wait`, `section_end`, `done`, `error`
- `POST /api/export/markdown` és `/api/export/pdf` – letöltés CORS fejekkel

Részletes sémák: `server/schemas.py`.

---

## Tesztelés

### Playwright (E2E)

```powershell
cd web
npx playwright install  # böngészők telepítése a tesztekhez
npm run test:e2e
# UI runner
npm run test:e2e:ui
```

### Pytest

```powershell
pytest -q
```

---

## Hibaelhárítás

- **[Cold‑start/CORS]**: a frontend warmup (`/healthz`) automatikus; frissíts, várj pár másodpercet.
- **[401 BYOK]**: csak valódi 401 esetén kér újra kulcsot; más hibák nem blokkolják a generálást.
- **[429/TPD]**: a UI magyar üzenetet ad és javasolt várakozást.
- **[Export PDF]**: Windows‑on WeasyPrint/GTK szükséges lehet; fallback `fpdf2` mindig működik.

---

## Roadmap

- Párhuzamos fejezetírás (parallelism > 1)
- Gazdagabb export (TOC, stílusok)
- Mélyebb globális kontextus‑összhang

---

## Licenc

MIT License – lásd a LICENSE fájlt.

## Köszönetnyilvánítás

Groq, FastAPI, Vite, Tailwind, Playwright közösségek támogatásáért.
