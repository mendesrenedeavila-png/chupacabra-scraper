# Chupacabra Scraper 🦎

> **C**onfluence **H**arvester for **U**pdated **P**ages **A**nd **C**opilot **A**gent **B**ase **R**epository **A**rchive

Async Python scraper that crawls any Confluence-based (or HTML) documentation site and mirrors it into clean files in your choice of format: **Markdown, plain text, HTML, CSV, or PDF** — ready to be used as a knowledge base for RAG pipelines, AI agents, or any system that consumes structured text.

---

*[Versão em Português abaixo / Portuguese version below](#português)*

---

---

# English

## Why Chupacabra Scraper instead of a generic scraper?

Most scrapers blast through a site, produce one giant file per page, never skip unchanged content, and leave you with a mess of unattributed text.  Chupacabra Scraper was designed specifically for **RAG (Retrieval-Augmented Generation)** knowledge bases and addresses four concrete pain points:

### 1. Multiple output formats

Choose the format that fits your pipeline with `--format`:

| Format | Flag | Best for |
|--------|------|----------|
| Markdown | `--format md` *(default)* | AI knowledge bases, documentation portals |
| Plain text | `--format txt` | Full-text search, simple ingestion |
| HTML | `--format html` | Web publishing, in-browser preview |
| CSV | `--format csv` | Databases, embedding pipelines, spreadsheets |
| PDF | `--format pdf` | Archiving, sharing, offline reading |

**CSV mode** is especially powerful for RAG: every page (or chunk) becomes a single row with columns `title`, `source_url`, `scraped_at`, `breadcrumb`, `chunk`, `section`, `content` — ready to pipe into a vector database or embedding API.

### 2. Incremental scraping — only process what changed

A persistent content-hash state file (`output/.scraper-state.json`) records a SHA-256 fingerprint of every scraped page.  On re-runs, pages whose body has not changed are skipped entirely — **no network request, no disk write**.

```
First run   →  Saved: 312  |  Unchanged: 0    (full crawl)
Second run  →  Saved: 4    |  Unchanged: 308  (only 4 pages updated)
```

This makes it safe to schedule Chupacabra Scraper as a daily CI job without hammering the target servers or re-uploading hundreds of identical files to your AI platform.  Use `--force` to bypass the state and re-scrape everything.

> **Format changes are handled automatically:** switching from `--format md` to `--format html` on the next run invalidates the cache for all pages, so files are re-written in the new format even if content is unchanged.

### 3. RAG-optimised semantic chunking

Any vector/RAG pipeline retrieves the **closest matching chunk**, not the full document.  A 10 000-word page will score poorly against specific questions because irrelevant sections dilute the relevance signal.

With `--chunk`, Chupacabra Scraper splits each page at heading boundaries (`##`, `###`) into self-contained, topic-scoped chunks:

```
documentation/
  overview.md                     ← short page, kept whole
  installation.chunk-01.md        ←  "Requirements" section
  installation.chunk-02.md        ←  "Setup" section (with overlap)
  installation.chunk-03.md        ←  "Configuration" section (with overlap)
```

Each chunk:
- Inherits the parent page's YAML front-matter (`title`, `source_url`, `breadcrumb`).
- Adds `section:` and `chunk: "2/3"` metadata for attribution.
- Repeats the last `CHUNK_OVERLAP_WORDS` words from the previous chunk as context.

### 4. Hierarchical breadcrumb metadata

Every output file carries a `breadcrumb` field in its YAML front-matter (or as a column in CSV) that records the full ancestor path in the site tree:

```yaml
---
title: "Installation Guide"
source_url: "https://docs.example.com/pages/viewpage.action?pageId=12345"
scraped_at: "2026-04-16T11:09:46Z"
breadcrumb: ["Getting Started"]
---
```

This field lets an AI agent answer "**In which section of the documentation is this?**" with precision, reducing hallucinations and improving citations.

---

## Quick start

### Requirements

- Python **3.10 or later**
- Git

#### Python libraries (installed automatically by `setup.sh` or `pip install`)

| Library | Version | Purpose |
|---------|---------|----------|
| `aiohttp` | 3.9.5 | Async HTTP client for parallel page downloads |
| `aiofiles` | 23.2.1 | Async file I/O for writing output files without blocking |
| `beautifulsoup4` | 4.12.3 | HTML parsing and content extraction |
| `lxml` | 5.2.1 | Fast HTML/XML parser backend for BeautifulSoup |
| `markdownify` | 0.12.1 | Converts cleaned HTML to Markdown |
| `markdown` | 3.6 | Converts Markdown to HTML (used by HTML/TXT/PDF output formats) |
| `fpdf2` | 2.7.9 | Generates PDF files from page content |
| `python-slugify` | 8.0.4 | Generates safe, ASCII file and folder names from page titles |
| `tqdm` | 4.66.2 | Progress bar in the terminal |

> **PDF note:** For full Unicode support (accented characters, non-Latin scripts) install DejaVu fonts:
> ```bash
> sudo apt install fonts-dejavu-core   # Ubuntu/Debian
> sudo dnf install dejavu-sans-fonts   # Fedora/RHEL
> ```
> If no TrueType font is found, Chupacabra falls back to Helvetica (Latin-1 only) and logs a warning.

---

### Installation — Linux / macOS

```bash
# 1. Clone the repository
git clone https://github.com/your-org/chupacabra-scraper.git
cd chupacabra-scraper

# 2. Create a virtual environment and install dependencies
bash setup.sh

# 3. Activate the environment
source scraper/.venv/bin/activate

# 4. Run
cd scraper
python scrape.py
```

> **macOS note:** If `lxml` fails to compile, install the Xcode CLI tools first:
> ```bash
> xcode-select --install
> ```

---

### Installation — Windows (via WSL2 — recommended)

WSL2 (Windows Subsystem for Linux) provides a native Linux shell, which is the easiest path on Windows.

```powershell
# 1. Install WSL2 if you haven't already (run in PowerShell as Administrator)
wsl --install

# 2. Open an Ubuntu terminal, then follow the Linux steps above
```

Inside the WSL2 Ubuntu shell:

```bash
git clone https://github.com/your-org/chupacabra-scraper.git
cd chupacabra-scraper
bash setup.sh
source scraper/.venv/bin/activate
cd scraper
python scrape.py
```

#### Windows — native Python (without WSL2)

If you prefer to run directly in Windows:

```powershell
# 1. Clone the repository
git clone https://github.com/your-org/chupacabra-scraper.git
cd chupacabra-scraper

# 2. Create a virtual environment
python -m venv scraper\.venv

# 3. Activate the environment
scraper\.venv\Scripts\Activate.ps1

# 4. Install dependencies
pip install -r scraper\requirements.txt

# 5. Run
cd scraper
python scrape.py
```

> **Note:** If `Activate.ps1` is blocked by the execution policy, run:
> ```powershell
> Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser
> ```

---

### 2 — Configure URLs

Edit `CONTEXT/documentacao.md` — one URL per line, lines starting with `#` are treated as comments:

```
# Minha documentação
https://tdn.totvs.com.br/display/public/LRM/Educacional
https://tdn.totvs.com.br/pages/releaseview.action?pageId=638413280
https://tdn.totvs.com/display/public/LRM/Educacional
```

> **No manual domain configuration needed.** `ALLOWED_DOMAINS` and `PREFERRED_DOMAIN` in `config.py` are derived automatically from the hostnames in this file at startup. Just add your URLs — no code changes required.

Rules:
- One URL per line
- Lines starting with `#` are ignored (comments)
- Blank lines are ignored
- The first hostname found becomes the canonical (`PREFERRED_DOMAIN`) used to normalise URLs
- All unique hostnames are automatically added to `ALLOWED_DOMAINS`

### 3 — Run

```bash
cd scraper
python scrape.py
```

Output files are written to `output/`.

---

## Usage

```
python scrape.py [OPTIONS]
```

### Parameters

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `--depth` | `INT` | `5` | **Maximum recursion depth.** Controls how many levels of child pages are followed from each root URL. `--depth 1` scrapes only the root pages themselves (no children). `--depth 2` scrapes the root pages plus their immediate children. Increase this value to crawl deeply nested documentation trees. Beware: very large values on deep sites can yield hundreds of pages. |
| `--workers` | `INT` | `5` | **Number of concurrent HTTP workers.** Controls how many pages are downloaded in parallel. Higher values speed up the crawl but increase load on the target servers. Keep between `3`–`10` for normal use; drop to `1`–`2` if you see `429 Too Many Requests` errors. |
| `--chunk` | flag | off | **Enable RAG-optimised semantic chunking.** When active, pages longer than `MAX_CHUNK_WORDS` (default 1 500 words) are split at heading boundaries (`##`, `###`) into multiple self-contained files. Each chunk inherits the parent page’s front-matter and adds `section:` and `chunk: "N/T"` metadata. Highly recommended before uploading to any AI knowledge base. |
| `--format` | `md\|txt\|html\|csv\|pdf` | `md` | **Output file format.** `md` — Markdown with YAML front-matter; `txt` — clean plain text; `html` — standalone HTML page with embedded CSS; `csv` — all pages appended as rows to a single `output/_pages.csv` (ideal for embedding pipelines); `pdf` — one PDF per page. Switching format between runs automatically invalidates the incremental cache. |
| `--flat` | flag | off | **Flat output layout.** By default files are organised into sub-folders by root section (e.g. `output/educacional/page.md`). With `--flat`, all Markdown files are saved directly in `output/` with no sub-folders — useful when uploading to a system that does not support directories. |
| `--force` | flag | off | **Force full re-scrape, ignoring the incremental state.** Chupacabra normally skips pages whose content hash has not changed since the last run (incremental mode). Pass `--force` to bypass this check and re-download every page regardless of whether it changed. Use this when: you suspect the state file (`.scraper-state.json`) is corrupted; you changed something in `extractor.py` or `config.py` that affects the output format but the page body itself did not change; you want a guaranteed fresh copy of everything. **Warning:** `--force` deletes and rewrites every file in the output directory for the crawled sections. |
| `--urls` | `URL...` | _(from docs file)_ | **Override root URLs inline.** Provide one or more space-separated URLs directly on the command line instead of reading from `CONTEXT/documentacao.md`. Useful for quick one-off tests or CI jobs targeting a single section. |
| `--docs-file` | `PATH` | `CONTEXT/documentacao.md` | **Path to a custom URL list file.** Points Chupacabra at a different input file instead of the default one. Each line in the file should contain one URL; lines starting with `#` are treated as comments. |

### Examples

```bash
# Standard full crawl — default Markdown output
python scrape.py

# Full crawl with RAG chunking
python scrape.py --chunk

# Output as plain text
python scrape.py --format txt

# Output as standalone HTML pages
python scrape.py --format html

# Output as CSV (one row per page — ideal for embedding pipelines)
python scrape.py --format csv --flat

# Output as PDF
python scrape.py --format pdf

# Quick smoke test — root pages only, no children
python scrape.py --depth 1 --workers 3

# Force re-scrape of a single section (skip incremental cache)
python scrape.py --force --urls https://docs.example.com/display/SPACE/PageName

# Flat output — no sub-folders
python scrape.py --flat

# Deep crawl with RAG chunking, flat CSV output
python scrape.py --depth 5 --workers 5 --chunk --flat --format csv
```

---

## Output format

By default (`--format md`), each page is saved as a Markdown file with YAML front-matter:

```yaml
---
title: "Page Title"
source_url: "https://docs.example.com/..."
scraped_at: "2026-04-16T11:00:00Z"
breadcrumb: ["Parent Section", "Grandparent Section"]  # depth ≥ 2 only
chunk: "2/5"      # only when --chunk splits the page
section: "Setup"  # only when --chunk splits the page
---

Page body in clean Markdown ...
```

### Per-format output

| Format | Output |
|--------|--------|
| `md` | `output/<folder>/page-title.md` (or flat with `--flat`) |
| `txt` | Same structure, `.txt`; front-matter stripped, plain text body |
| `html` | Same structure, `.html`; standalone page with embedded CSS |
| `csv` | Single file `output/_pages.csv`; one row per page/chunk |
| `pdf` | Same structure, `.pdf`; one PDF per page |

**CSV columns:** `title`, `source_url`, `scraped_at`, `breadcrumb`, `chunk`, `section`, `content`

### Directory structure

```
output/
├── _index.md               ← master index (md/txt/html/pdf modes)
├── _pages.csv              ← all pages as rows (csv mode only)
├── .scraper-state.json     ← incremental state (do not delete)
├── scraper.log             ← full log of the last run
├── section-a/
│   ├── page-one.md           ← or .txt / .html / .pdf
│   └── page-two.chunk-01.md  ← only when --chunk is active
└── ...
```

---

## Uploading to a knowledge base / Copilot Studio

1. Open your agent in [Copilot Studio](https://copilotstudio.microsoft.com/)
2. Go to **Knowledge** → **Add Knowledge** → **Files**
3. Upload the files from `output/` (by section folder or all at once)
4. For Markdown/HTML/TXT: include `output/_index.md` as a navigation reference
5. For CSV: upload `output/_pages.csv` directly as a structured knowledge source

> **Tip:** Use `--chunk --format csv` for the best retrieval precision in vector-based RAG pipelines.

---

## Configuration reference

All settings are in `scraper/config.py`:

| Variable | Default | Description |
|---|---|---|
| `OUTPUT_FORMAT` | `md` | Default output format (`md`, `txt`, `html`, `csv`, `pdf`) |
| `FLAT_OUTPUT` | `False` | Save all files flat without sub-folders |
| `MAX_DEPTH` | `5` | Recursion depth limit |
| `MAX_WORKERS` | `5` | Concurrent HTTP workers |
| `DELAY_SECONDS` | `0.5` | Delay between requests per worker |
| `REQUEST_TIMEOUT` | `30` | HTTP timeout in seconds |
| `INCREMENTAL` | `True` | Enable change-detection on re-runs |
| `CHUNK_PAGES` | `False` | Enable RAG chunking by default |
| `MAX_CHUNK_WORDS` | `1500` | Maximum words per chunk |
| `CHUNK_OVERLAP_WORDS` | `100` | Word overlap between consecutive chunks |
| `ALLOWED_DOMAINS` | _(derived from `CONTEXT/documentacao.md`)_ | Domains to follow links on — **set automatically, no manual edit needed** |
| `PREFERRED_DOMAIN` | _(first hostname in `CONTEXT/documentacao.md`)_ | Canonical domain for URL normalisation — **set automatically** |

---

## Architecture

```
scraper/
├── scrape.py      # Entry point — async BFS orchestrator
├── extractor.py   # Confluence REST API + HTML scraping + Markdown conversion
├── formatter.py   # Output format converters (md / txt / html / csv / pdf)
├── chunker.py     # Semantic chunking at heading boundaries
├── state.py       # Incremental state (content hashing)
├── utils.py       # URL normalisation, slug generation, link filtering
├── config.py      # All configurable settings
└── requirements.txt
```

**Extraction strategy:**
1. If the URL contains a `pageId`, try the **Confluence REST API** (`/rest/api/content/{pageId}`) for clean JSON — includes child page IDs for reliable crawling.
2. Fall back to **HTML scraping** with BeautifulSoup for standard `/display/SPACE/PageTitle` style URLs or any other HTML page.
3. Convert extracted HTML to Markdown with `markdownify`, strip navigation noise, add YAML front-matter.
4. Convert the Markdown to the target output format via `formatter.py`.

**Crawl strategy:** async BFS with a `asyncio.Semaphore` limiting concurrent workers.  A `visited` set prevents cycles.  The `parent_map` tracks child→parent relationships for breadcrumb generation.

---

## Caveats

- **Authentication-required pages**: Content behind login is not accessible. The scraper skips pages returning HTTP 401/403.
- **Rate limiting**: The default 0.5 s delay per worker is conservative. If you see 429 errors, increase `DELAY_SECONDS` in `config.py`.
- **Images and attachments**: Not downloaded. Image links in the output point to the original source URLs.
- **Dynamic content**: Pages that load content via JavaScript may be incomplete. Chupacabra Scraper processes server-rendered HTML only, so JS-only sections may be missing.
- **PDF Unicode**: Full Unicode in PDFs requires a TrueType font on the system (e.g. DejaVu). See the PDF note in the Requirements section.

---

## License

MIT — see [LICENSE](LICENSE).

---

*Chupacabra Scraper is an independent open-source tool.  
Always respect the terms of service of the websites you scrape.*

---

---

# Português

## Por que o Chupacabra Scraper e não um scraper genérico?

A maioria dos scrapers varre um site, gera um arquivo gigante por página, nunca pula conteúdo não alterado e deixa um caos de texto sem atribuição. O Chupacabra Scraper foi criado especificamente para bases de conhecimento **RAG (Retrieval-Augmented Generation)** e resolve quatro problemas concretos:

### 1. Múltiplos formatos de saída

Escolha o formato adequado ao seu pipeline com `--format`:

| Formato | Flag | Ideal para |
|---------|------|------------|
| Markdown | `--format md` *(padrão)* | Bases de conhecimento de IA, portais de documentação |
| Texto puro | `--format txt` | Busca full-text, ingestão simples |
| HTML | `--format html` | Publicação web, visualização no navegador |
| CSV | `--format csv` | Bancos de dados, pipelines de embedding, planilhas |
| PDF | `--format pdf` | Arquivamento, compartilhamento, leitura offline |

**O modo CSV** é especialmente poderoso para RAG: cada página (ou chunk) vira uma linha com as colunas `title`, `source_url`, `scraped_at`, `breadcrumb`, `chunk`, `section`, `content` — pronto para alimentar um banco vetorial ou API de embedding.

### 2. Scraping incremental — processa apenas o que mudou

Um arquivo de estado persistente (`output/.scraper-state.json`) armazena um fingerprint SHA-256 de cada página raspada. Em execuções subsequentes, páginas cujo conteúdo não mudou são ignoradas completamente — **sem requisição de rede, sem escrita em disco**.

```
Primeira execução  →  Salvas: 312  |  Inalteradas: 0    (crawl completo)
Segunda execução   →  Salvas: 4    |  Inalteradas: 308  (apenas 4 páginas atualizadas)
```

Isso permite agendar o Chupacabra Scraper como um job diário de CI sem sobrecarregar os servidores alvo nem fazer re-upload de centenas de arquivos idênticos para a sua plataforma de IA. Use `--force` para ignorar o estado e refazer tudo.

> **Mudanças de formato são tratadas automaticamente:** trocar de `--format md` para `--format html` na próxima execução invalida o cache de todas as páginas, fazendo com que os arquivos sejam reescritos no novo formato mesmo que o conteúdo não tenha mudado.

### 3. Chunking semântico otimizado para RAG

Qualquer pipeline de vetor/RAG recupera o **chunk mais relevante**, não o documento inteiro. Uma página de 10 000 palavras terá pontuação baixa para perguntas específicas porque seções irrelevantes diluem o sinal de relevância.

Com `--chunk`, o Chupacabra Scraper divide cada página nos limites de cabeçalho (`##`, `###`) em chunks independentes com escopo temático:

```
output/
  visao-geral.md                    ← página curta, mantida inteira
  instalacao.chunk-01.md            ← seção "Requisitos"
  instalacao.chunk-02.md            ← seção "Configuração" (com overlap)
  instalacao.chunk-03.md            ← seção "Execução" (com overlap)
```

Cada chunk:
- Herda o front-matter YAML da página pai (`title`, `source_url`, `breadcrumb`).
- Adiciona metadados `section:` e `chunk: "2/3"` para rastreabilidade.
- Repete as últimas `CHUNK_OVERLAP_WORDS` palavras do chunk anterior como contexto.

### 4. Metadados de breadcrumb hierárquico

Cada arquivo de saída carrega um campo `breadcrumb` no seu front-matter YAML (ou como coluna no CSV) que registra o caminho completo de ancestrais na árvore do site:

```yaml
---
title: "Guia de Instalação"
source_url: "https://tdn.totvs.com.br/pages/viewpage.action?pageId=12345"
scraped_at: "2026-04-16T11:09:46Z"
breadcrumb: ["Primeiros Passos"]
---
```

Esse campo permite que um agente de IA responda "**Em qual seção da documentação está isso?**" com precisão, reduzindo alucinações e melhorando as citações.

---

## Início rápido

### Requisitos

- Python **3.10 ou superior**
- Git

#### Bibliotecas Python (instaladas automaticamente pelo `setup.sh` ou `pip install`)

| Biblioteca | Versão | Finalidade |
|------------|--------|------------|
| `aiohttp` | 3.9.5 | Cliente HTTP assíncrono para downloads paralelos |
| `aiofiles` | 23.2.1 | I/O de arquivo assíncrono sem bloquear o loop |
| `beautifulsoup4` | 4.12.3 | Parsing e extração de conteúdo HTML |
| `lxml` | 5.2.1 | Parser HTML/XML rápido para o BeautifulSoup |
| `markdownify` | 0.12.1 | Converte HTML limpo em Markdown |
| `markdown` | 3.6 | Converte Markdown em HTML (usado pelos formatos HTML/TXT/PDF) |
| `fpdf2` | 2.7.9 | Gera arquivos PDF a partir do conteúdo |
| `python-slugify` | 8.0.4 | Gera nomes de arquivo seguros em ASCII a partir dos títulos |
| `tqdm` | 4.66.2 | Barra de progresso no terminal |

> **Nota sobre PDF:** Para suporte completo a Unicode (acentos, alfabetos não-latinos) instale as fontes DejaVu:
> ```bash
> sudo apt install fonts-dejavu-core   # Ubuntu/Debian
> sudo dnf install dejavu-sans-fonts   # Fedora/RHEL
> ```
> Se nenhuma fonte TrueType for encontrada, o Chupacabra usa Helvetica (apenas Latin-1) e registra um aviso.

---

### Instalação — Linux / macOS

```bash
# 1. Clone o repositório
git clone https://github.com/mendesrenedeavila-png/chupacabra-scraper.git
cd chupacabra-scraper

# 2. Crie o ambiente virtual e instale as dependências
bash setup.sh

# 3. Ative o ambiente
source scraper/.venv/bin/activate

# 4. Execute
cd scraper
python scrape.py
```

> **macOS:** Se o `lxml` falhar na compilação, instale o Xcode CLI tools primeiro:
> ```bash
> xcode-select --install
> ```

---

### Instalação — Windows (via WSL2 — recomendado)

O WSL2 (Windows Subsystem for Linux) fornece um shell Linux nativo, que é o caminho mais simples no Windows.

```powershell
# 1. Instale o WSL2 se ainda não tiver (execute no PowerShell como Administrador)
wsl --install

# 2. Abra um terminal Ubuntu e siga os passos do Linux acima
```

Dentro do shell Ubuntu no WSL2:

```bash
git clone https://github.com/mendesrenedeavila-png/chupacabra-scraper.git
cd chupacabra-scraper
bash setup.sh
source scraper/.venv/bin/activate
cd scraper
python scrape.py
```

#### Windows — Python nativo (sem WSL2)

Se preferir executar diretamente no Windows:

```powershell
# 1. Clone o repositório
git clone https://github.com/mendesrenedeavila-png/chupacabra-scraper.git
cd chupacabra-scraper

# 2. Crie o ambiente virtual
python -m venv scraper\.venv

# 3. Ative o ambiente
scraper\.venv\Scripts\Activate.ps1

# 4. Instale as dependências
pip install -r scraper\requirements.txt

# 5. Execute
cd scraper
python scrape.py
```

> **Nota:** Se o `Activate.ps1` for bloqueado pela política de execução, rode:
> ```powershell
> Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser
> ```

---

### 2 — Configure as URLs

Edite `CONTEXT/documentacao.md` — uma URL por linha, linhas começando com `#` são comentários:

```
# Minha documentação
https://tdn.totvs.com.br/display/public/LRM/Educacional
https://tdn.totvs.com.br/pages/releaseview.action?pageId=638413280
https://tdn.totvs.com/display/public/LRM/Educacional
```

> **Nenhuma configuração de domínio necessária.** `ALLOWED_DOMAINS` e `PREFERRED_DOMAIN` em `config.py` são derivados automaticamente dos hostnames presentes neste arquivo na inicialização. Basta adicionar suas URLs — nenhuma alteração no código é necessária.

Regras:
- Uma URL por linha
- Linhas começando com `#` são ignoradas (comentários)
- Linhas em branco são ignoradas
- O primeiro hostname encontrado se torna o domínio canônico (`PREFERRED_DOMAIN`) usado para normalizar URLs
- Todos os hostnames únicos são adicionados automaticamente a `ALLOWED_DOMAINS`

### 3 — Execute

```bash
cd scraper
python scrape.py
```

Os arquivos de saída são gravados em `output/`.

---

## Uso

```
python scrape.py [OPÇÕES]
```

### Parâmetros

| Parâmetro | Tipo | Padrão | Descrição |
|-----------|------|--------|-----------|
| `--depth` | `INT` | `5` | **Profundidade máxima de recursão.** Controla quantos níveis de páginas filhas são seguidos a partir de cada URL raiz. `--depth 1` raspa apenas as páginas raiz (sem filhos). `--depth 2` raspa as raízes mais seus filhos imediatos. |
| `--workers` | `INT` | `5` | **Número de workers HTTP concorrentes.** Controla quantas páginas são baixadas em paralelo. Valores maiores aceleram o crawl mas aumentam a carga nos servidores. Mantenha entre `3`–`10`; reduza para `1`–`2` se receber erros `429 Too Many Requests`. |
| `--chunk` | flag | desligado | **Ativa o chunking semântico otimizado para RAG.** Quando ativo, páginas maiores que `MAX_CHUNK_WORDS` (padrão 1 500 palavras) são divididas nos limites de cabeçalho em vários arquivos independentes. |
| `--format` | `md\|txt\|html\|csv\|pdf` | `md` | **Formato do arquivo de saída.** `md` — Markdown com front-matter YAML; `txt` — texto puro; `html` — página HTML standalone; `csv` — todas as páginas como linhas em `output/_pages.csv`; `pdf` — um PDF por página. |
| `--flat` | flag | desligado | **Layout de saída plano.** Por padrão os arquivos são organizados em subpastas por seção raiz. Com `--flat`, todos os arquivos são salvos diretamente em `output/` sem subpastas. |
| `--force` | flag | desligado | **Força o re-scraping completo, ignorando o estado incremental.** O Chupacabra normalmente pula páginas cujo hash de conteúdo não mudou. Use `--force` para baixar tudo novamente independentemente de mudanças. |
| `--urls` | `URL...` | _(do arquivo)_ | **Substitui as URLs raiz inline.** Informe uma ou mais URLs separadas por espaço diretamente na linha de comando em vez de ler de `CONTEXT/documentacao.md`. |
| `--docs-file` | `PATH` | `CONTEXT/documentacao.md` | **Caminho para um arquivo de lista de URLs customizado.** Cada linha deve conter uma URL; linhas começando com `#` são comentários. |

### Exemplos

```bash
# Crawl completo padrão — saída em Markdown
python scrape.py

# Crawl completo com chunking RAG
python scrape.py --chunk

# Saída em texto puro
python scrape.py --format txt

# Saída em HTML standalone
python scrape.py --format html

# Saída em CSV (uma linha por página — ideal para pipelines de embedding)
python scrape.py --format csv --flat

# Saída em PDF
python scrape.py --format pdf

# Teste rápido — apenas páginas raiz, sem filhos
python scrape.py --depth 1 --workers 3

# Forçar re-scraping de uma seção específica
python scrape.py --force --urls https://tdn.totvs.com.br/display/public/LRM/Educacional

# Saída plana — sem subpastas
python scrape.py --flat

# Crawl profundo com chunking RAG e saída CSV plana
python scrape.py --depth 5 --workers 5 --chunk --flat --format csv
```

---

## Formato de saída

Por padrão (`--format md`), cada página é salva como um arquivo Markdown com front-matter YAML:

```yaml
---
title: "Título da Página"
source_url: "https://tdn.totvs.com.br/..."
scraped_at: "2026-04-16T11:00:00Z"
breadcrumb: ["Seção Pai", "Seção Avô"]  # apenas quando profundidade ≥ 2
chunk: "2/5"      # apenas quando --chunk divide a página
section: "Configuração"  # apenas quando --chunk divide a página
---

Corpo da página em Markdown limpo ...
```

### Saída por formato

| Formato | Saída |
|---------|-------|
| `md` | `output/<pasta>/titulo-da-pagina.md` (ou plano com `--flat`) |
| `txt` | Mesma estrutura, `.txt`; front-matter removido, corpo em texto puro |
| `html` | Mesma estrutura, `.html`; página standalone com CSS embutido |
| `csv` | Arquivo único `output/_pages.csv`; uma linha por página/chunk |
| `pdf` | Mesma estrutura, `.pdf`; um PDF por página |

**Colunas do CSV:** `title`, `source_url`, `scraped_at`, `breadcrumb`, `chunk`, `section`, `content`

### Estrutura de diretórios

```
output/
├── _index.md               ← índice mestre (modos md/txt/html/pdf)
├── _pages.csv              ← todas as páginas como linhas (modo csv)
├── .scraper-state.json     ← estado incremental (não deletar)
├── scraper.log             ← log completo da última execução
├── secao-a/
│   ├── pagina-um.md
│   └── pagina-dois.chunk-01.md  ← apenas quando --chunk está ativo
└── ...
```

---

## Upload para base de conhecimento / Copilot Studio

1. Abra seu agente no [Copilot Studio](https://copilotstudio.microsoft.com/)
2. Vá em **Knowledge** → **Add Knowledge** → **Files**
3. Faça upload dos arquivos de `output/` (por pasta de seção ou todos de uma vez)
4. Para Markdown/HTML/TXT: inclua `output/_index.md` como referência de navegação
5. Para CSV: faça upload de `output/_pages.csv` diretamente como fonte de conhecimento estruturada

> **Dica:** Use `--chunk --format csv` para a melhor precisão de recuperação em pipelines RAG baseados em vetor.

---

## Referência de configuração

Todas as configurações estão em `scraper/config.py`:

| Variável | Padrão | Descrição |
|---|---|---|
| `OUTPUT_FORMAT` | `md` | Formato de saída padrão (`md`, `txt`, `html`, `csv`, `pdf`) |
| `FLAT_OUTPUT` | `False` | Salvar todos os arquivos sem subpastas |
| `MAX_DEPTH` | `5` | Limite de profundidade de recursão |
| `MAX_WORKERS` | `5` | Workers HTTP concorrentes |
| `DELAY_SECONDS` | `0.5` | Intervalo entre requisições por worker |
| `REQUEST_TIMEOUT` | `30` | Timeout HTTP em segundos |
| `INCREMENTAL` | `True` | Habilitar detecção de mudanças para re-execuções |
| `CHUNK_PAGES` | `False` | Habilitar chunking RAG por padrão |
| `MAX_CHUNK_WORDS` | `1500` | Máximo de palavras por chunk |
| `CHUNK_OVERLAP_WORDS` | `100` | Sobreposição de palavras entre chunks consecutivos |
| `ALLOWED_DOMAINS` | _(derivado de `CONTEXT/documentacao.md`)_ | Domínios para seguir links — **definido automaticamente** |
| `PREFERRED_DOMAIN` | _(primeiro hostname em `CONTEXT/documentacao.md`)_ | Domínio canônico para normalização de URLs — **definido automaticamente** |

---

## Arquitetura

```
scraper/
├── scrape.py      # Ponto de entrada — orquestrador BFS assíncrono
├── extractor.py   # API REST do Confluence + scraping HTML + conversão para Markdown
├── formatter.py   # Conversores de formato de saída (md / txt / html / csv / pdf)
├── chunker.py     # Chunking semântico nos limites de cabeçalho
├── state.py       # Estado incremental (hash de conteúdo)
├── utils.py       # Normalização de URL, geração de slug, filtragem de links
├── config.py      # Todas as configurações ajustáveis
└── requirements.txt
```

**Estratégia de extração:**
1. Se a URL contém um `pageId`, tenta a **API REST do Confluence** (`/rest/api/content/{pageId}`) para JSON limpo — inclui IDs de páginas filhas para crawling confiável.
2. Fallback para **scraping HTML** com BeautifulSoup para URLs no estilo `/display/SPACE/TituloDaPagina` ou qualquer outra página HTML.
3. Converte o HTML extraído para Markdown com `markdownify`, remove ruído de navegação, adiciona front-matter YAML.
4. Converte o Markdown para o formato de saída alvo via `formatter.py`.

**Estratégia de crawl:** BFS assíncrono com `asyncio.Semaphore` limitando workers concorrentes. Um conjunto `visited` previne ciclos. O `parent_map` rastreia relacionamentos filho→pai para geração de breadcrumbs.

---

## Limitações

- **Páginas com autenticação**: Conteúdo protegido por login não é acessível. O scraper pula páginas que retornam HTTP 401/403.
- **Rate limiting**: O delay padrão de 0,5 s por worker é conservador. Se receber erros 429, aumente `DELAY_SECONDS` em `config.py`.
- **Imagens e anexos**: Não são baixados. Links de imagens no output apontam para as URLs originais.
- **Conteúdo dinâmico**: Páginas que carregam conteúdo via JavaScript podem estar incompletas. O Chupacabra processa apenas HTML renderizado no servidor.
- **Unicode em PDF**: Suporte completo requer uma fonte TrueType no sistema (ex: DejaVu). Veja a nota sobre PDF na seção de Requisitos.

---

## Licença

MIT — veja [LICENSE](LICENSE).

---

*Chupacabra Scraper é uma ferramenta open-source independente.  
Sempre respeite os termos de serviço dos sites que você raspa.*
