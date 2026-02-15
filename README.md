# Auto Report: Geração automática de Reports como demonstração de resultados

**Status:** estável e em evolução
**Ferramentas:** Google Slides + Google Sheets. (Entre outras APIs de coleta de métricas)

Este repositório contém uma automação completa para gerar relatórios semanais (ou mensais) de desempenho de clientes em Google Slides, a partir de dados consolidados (planilhas/painéis) e conectores de mídia (Meta Ads, Google Ads, GA4, etc.).  
A aplicação é orquestrada por uma CLI (`report_generator.py`), paraleliza o processamento por cliente via ThreadPool, atualiza status na planilha central, cria/atualiza uma planilha de acompanhamento e preenche/remodela slides com placeholders e elementos de visual.

---

## Sumário

- Automação de Relatórios (Slides + Planilhas) para Marketing Digital
- Arquitetura em alto nível	2
- Fluxo de execução	3
- Estrutura de diretórios	3
- Conceitos principais	5
- Categorias (Handlers)	5
- Placeholders e Templates	5
- Períodos de referência e comparação	6
- Variações e estilização	6
- Logs e observabilidade	6
- Instalação	7
- Configuração	7
- Arquivo config/settings.py	7
- Credenciais e APIs	8
- Como executar	8
- Parâmetros e variáveis de ambiente	8
- Exemplos de uso	9
- Como estender o projeto	9
- Criar uma nova categoria	9
- Adicionar novas métricas/variações	11
- Adicionar pós-processamentos de slides	11
- Tratamento de erros e retry	11
- Boas práticas, padrões e decisões	12
- FAQ / Dúvidas comuns	12
- Roadmap (sugestões)	13
- Licença	13
- Apêndice – Exemplo real (E‑commerce)	13

---

## Arquitetura em alto nível

- Orquestração: `report_generator.py` coordena todo o fluxo, sem conter lógica de negócio.
- Categorias (Handlers): encapsulam coleta, variações e pós‑processamento por tipo de cliente.
- Slides: preenchidos por placeholders; podem ser removidos quando não há dados; barras de meta são redimensionadas.
- Execução paralela: cada cliente é processado em uma thread, com resumo e status ao final.

---

## Fluxo de execução

**Para cada cliente:**

1. Marcar status como `PROCESSANDO` na Planilha Central.
2. Calcular períodos de referência e de comparação (`core.periodo.periodo_referencia`) com base em `FREQ` (`SEMANAL` por padrão).
3. Montar placeholders básicos (cliente + períodos).
4. Selecionar o handler pela categoria do cliente (`core.categorias.get_handler`).
5. Coletar dados com o handler (painel, Meta Ads, Google Ads, GA4, etc.), computar variações e agregar tudo numa `dict` `{ "{{PLACEHOLDER}}": valor_ptbr }`.
6. Criar cópia do template correto para o cliente/período.
7. Preencher placeholders nos slides relevantes.
8. Pós‑processar (redimensionar barras de meta, remover slides vazios, aplicar estilos de variação).
9. Atualizar status para `GERADO ✅` e registrar a data em `ULTIMA VEZ GERADO (AUTO)`.
10. Registrar o relatório na planilha de acompanhamento.
11. Logar o sumário de etapas com tempos.

Se algo falhar, o status do cliente é marcado como `ERRO: <TipoDoErro>` e o stacktrace é logado.

---

## Estrutura de diretórios

.
├── .gitignore  
├── README.md  
├── config  
│   └── settings_example.py  
├── core  
│   ├── __init__.py  
│   ├── basic_placeholders.py  
│   ├── channel_descriptions.json  
│   ├── cred_manager.py  
│   ├── leitura_central.py  
│   ├── periodo.py  
│   ├── progress_bar.py  
│   ├── relatorio_writer.py  
│   ├── slide_filler.py  
│   ├── status.py  
│   ├── template_manager.py  
│   ├── variacao_dados_comparativos.py  
│   ├── variation_styler.py  
│   └── categorias  
│       ├── __init__.py  
│       ├── E-commerce.py  
│       ├── Lead Com Site.py  
│       ├── Lead Sem Site.py  
│       ├── ecommerce/  
│       │   ├── campaign_facebook_gather.py  
│       │   ├── campaign_google_gather.py  
│       │   ├── canais_ga4.py  
│       │   ├── facebook_metrics_gather.py  
│       │   ├── ga4_scraper.py  
│       │   ├── google_metrics_gather.py  
│       │   └── painel_scraper.py  
│       ├── lead_com_site/  
│       │   ├── campaign_facebook_gather.py  
│       │   ├── campaign_google_gather.py  
│       │   ├── canais_ga4.py  
│       │   ├── facebook_metrics_gather.py  
│       │   ├── ga4_scraper.py  
│       │   ├── google_metrics_gather.py  
│       │   └── painel_scraper.py  
│       └── lead_sem_site/  
│           ├── campaign_facebook_gather.py  
│           ├── facebook_metrics_gather.py  
│           └── painel_scraper.py  
├── get_refresh_token.py  
├── report_generator.py  
├── requirements.txt  
└── utils  
    ├── __init__.py  
    ├── formatting.py  
    ├── logger.py  
    └── retry.py

---

## Conceitos principais

### Categorias (Handlers)

Cada categoria descreve como coletar dados, quais slides manipular e quais métricas geram variações. Exemplo simplificado de `core/categorias/E-commerce.py`:

**Atributos públicos:**

- `nome`: string canônica da categoria.
- `template_id`: ID do Google Slides fonte para copiar.
- `_SLIDES`: dataclass com os IDs de página relevantes no template.
- `_VARIATION_KEYS`: conjunto de chaves que terão variações calculadas e estilizadas.

**Funções públicas (contrato):**

- `coletar_dados(cliente, periodo_ref, periodo_comp) -> dict`
- `pos_processar(presentation_id: str, dados: dict) -> None`

**Coletas já previstas (E‑commerce):**

- Painel (`painel_scraper`)
- Meta Ads (`facebook_metrics_gather`)
- Google Ads (`google_metrics_gather`)
- GA4 (`ga4_scraper`)

**Roteamento:** `core.categorias.get_handler(categoria)` retorna o módulo handler correto a partir da categoria do cliente.

### Placeholders e Templates

- Todas as substituições em Slides usam placeholders com chaves `{{...}}`, por ex.: `{{per_meta_fat}}`, `{{fat_face}}`, `{{ses_ga}}`.
- `core.template_manager.criar_copia(...)` duplica o template da categoria e retorna `presentation_id`.
- `core.slide_filler.preencher(presentation_id, dados, slide_id)` substitui placeholders por valores já formatados em PT‑BR (formatação de números/datas está centralizada nos gathers e utilitários).

### Períodos de referência e comparação

- `core.periodo.periodo_referencia(today, frequencia)` gera objetos de período.

Para cada execução:

- `periodo_ref = periodo_referencia(today=today, FREQ)`
- `periodo_comp = periodo_referencia(today=periodo_ref.inicio, FREQ)`  
  Ou seja, compara o período atual com o período anterior de mesma granularidade (semanal/mensal).

### Variações e estilização

- `core.variacao_dados_comparativos.calcular_variacoes(dados, _VARIATION_KEYS)` insere chaves de variação no dict.
- `core.variation_styler.aplicar_vermelho(presentation_id, dados, _VARIATION_KEYS)` aplica realce visual (vermelho) para variações negativas nos elementos do slide.
- `core.progress_bar.redimensionar(...)` ajusta barras de meta (ex.: % da meta de faturamento e investimento).

### Logs e observabilidade

- `utils.logger.get_logger(__name__)` provisiona log padronizado com contexto extra (cliente, doc, tempos).
- `utils.logger.StepLogger` marca início/fim de cada etapa e emite um sumário ao final (por cliente e no pos).
- Níveis e constantes: `OTIMIZACAO` (para medir trechos críticos).
- O orquestrador sempre registra:
  - `set_status(PROCESSANDO | GERADO ✅ | ERRO: ...)`
  - `set_last_generated(date.today())`
  - `relatorio_writer.registrar(...)`
  - Tempos por etapa + resumo final (sucesso/erro por cliente).

---

## Instalação

- Python: 3.10+ (recomendado).
- Clone o repositório.
- Crie um virtualenv e instale dependências:

python -m venv .venv  
source .venv/bin/activate     # Windows: .venv\Scripts\activate  
pip install -r requirements.txt

---

## Configuração

### Arquivo `config/settings.py`

Copie o modelo e preencha:

cp config/settings_example.py config/settings.py

**Campos mínimos (com base no uso direto no código):**

- `CENTRAL_SHEET_URL`: URL da Planilha Central (Google Sheets) com a lista de clientes e colunas de controle.
- `CENTRAL_TAB_NAME`: nome da aba na Planilha Central.

Outros campos podem existir no `settings_example.py` (credenciais, scopes, IDs, etc.) — preencha conforme necessidade dos módulos chamados (Slides/Drive/Sheets, Ads, GA4, etc.).

### Credenciais e APIs

- Google APIs (tipicamente): Slides, Drive, Sheets e possivelmente GA4 Data API.
- Mídia: Meta Marketing API (Facebook/Instagram Ads) e Google Ads API, se utilizados pelos gathers.
- O módulo `core/cred_manager.py` gerencia tokens e refresh.  
  Há um utilitário `get_refresh_token.py` para auxiliar a obter `refresh_token` (fluxo OAuth).

Prática recomendada: usar variáveis de ambiente/secret manager; não versionar credenciais.

Garanta que os IDs de templates de Slides (por categoria) estão válidos e acessíveis pela conta usada no OAuth/Service Account.

---

## Como executar

A CLI está em `report_generator.py`.

### Parâmetros e variáveis de ambiente

- `--cliente` (opcional): processa apenas clientes cujo nome contenha a substring informada (case‑insensitive).
- `FREQ` (env, opcional): `SEMANAL` (padrão) ou outro valor suportado pelos módulos de período (ex.: `MENSAL`, se implementado).
- `THREADS` (env, opcional): número de workers no `ThreadPoolExecutor`.
- Padrão atual no código: `10`. (obs.: um comentário no código menciona “4 por padrão”, mas o valor efetivo é `10`)

### Exemplos de uso

Rodar para todos os clientes marcados na Planilha Central:

FREQ=SEMANAL THREADS=10 python report_generator.py

Rodar mensal (se suportado nos períodos/handlers):

FREQ=MENSAL python report_generator.py

Durante a execução, o sistema cria (caso necessário) e utiliza uma Planilha de Acompanhamento para registrar saídas. Ao final, o log reporta um resumo agregando sucessos/erros.

---

## Como estender o projeto

### Criar uma nova categoria

- Crie um arquivo em `core/categorias/NOME.py` e, opcionalmente, um pacote `core/categorias/nome/` para gathers específicos.
- Implemente o contrato similar às outras categorias.
- Garanta que `core/categorias/__init__.py` exponha o novo handler em `get_handler`.

### Adicionar novas métricas/variações

- Inclua as chaves em `_VARIATION_KEYS` para que `variacao_dados_comparativos` calcule o delta/percentual.
- Preencha os placeholders associados (`{{minha_metrica}}` e `{{minha_metrica_comp}}`).
- Se necessário, atualize o template de Slides para referenciar os novos placeholders.

### Adicionar pós-processamentos de slides

- Use `core.slide_filler.remover_slide` para limpar slides sem dados.
- Use `core.progress_bar.redimensionar` para atualizar barras com base em % de meta.
- Centralize IDs de slides no `_SLIDES` para evitar hardcode disperso.

---

## Tratamento de erros e retry

- O orquestrador captura e marca status de erro por cliente: `ERRO: <TipoDoErro>`.
- Stacktraces são emitidos via logger; o `StepLogger` resume até o ponto de falha.
- `utils.retry` provê utilitários para retentativas (use nos gathers sujeitos a timeouts de API).
- Idempotência: como a automação cria cópias de template, rever comportamento de duplicação ao reprocessar (use `relatorio_writer`/planilha de acompanhamento para referência).

---

## Boas práticas, padrões e decisões

- Separação de responsabilidades: o orquestrador não contém regra de negócio; handlers e gathers sim.
- Formato dos dados: `coletar_dados` retorna strings já formatadas em PT‑BR prontas para injetar no Slides.
- Nomes de placeholders: padronize `snake_case` e sufixos `_comp` para período comparativo.
- Logs: sempre envolver blocos relevantes com `StepLogger.start/end`; use `extra={...}` (cliente, doc, elapsed).
- Threads: dimensione `THREADS` conforme limites de APIs (taxas) e throttling; preferir backoff em retry.
- Tipos: o projeto usa type hints; `# type: ignore` é aplicado quando necessário para manter o main enxuto/testável.
- Segurança: não comitar credenciais; mascarar tokens/IDs sensíveis no log; restringir compartilhamentos de Slides/Sheets.

---

## FAQ / Dúvidas comuns

**Q:** Onde configuro a Planilha Central?  
**A:** Em `config/settings.py`, chaves `CENTRAL_SHEET_URL` e `CENTRAL_TAB_NAME`.

**Q:** Como decido a periodicidade do relatório?  
**A:** Via variável de ambiente `FREQ` (`SEMANAL` por padrão). O cálculo de `periodo_comp` usa o período imediatamente anterior.

**Q:** Qual é o padrão de threads?  
**A:** `THREADS=10` (padrão atual no código). Ajuste conforme limites de API e recursos da máquina.

**Q:** Como os slides são escolhidos para remover?  
**A:** Cada handler define lógica simples, por exemplo: se `{{fat_face}}` ∈ `{"", "0", "-", None}`, remove o slide Meta Ads.

**Q:** Onde vejo o resultado da execução?  
**A:** Nos logs do terminal e na Planilha de Acompanhamento (criada/atualizada por `relatorio_writer`), além do documento de Slides copiado.

---

## Apêndice – Exemplo real (E‑commerce)

**Variações calculadas (trecho):**  
`{"fat_sem", "inv_sem", "vendas", "roas", "taxa_conv", "tck_med", "cps", "meta_fat", "meta_inv", "per_meta_fat", "per_meta_inv", "cpa", "vendas_face", "roas_face", "inv_face", "fat_face", "cpa_face", "vendas_goog", "roas_goog", "inv_goog", "fat_goog", "cpa_goog", "ses_ga", "ses_eng_ga", "taxa_eng_ga", "temp_med_ga"}`

**Slides do template (IDs):**  
`geral="g366e383ee32_0_121", meta_ads="g366e383ee32_0_60", google_ads="g366e383ee32_1_117", ga4="g362be775eb0_0_0".`

**Pós‑processos:**
- Redimensionar barras de meta (usa `{{per_meta_fat}}` e `{{per_meta_inv}}`).
- Remover slides vazios quando não há dados de Meta/Google/GA4.
- Aplicar vermelho para variações negativas.

---

**Dica para IAs/automations que apoiarão o projeto:**
- Respeite o contrato dos handlers (`coletar_dados`, `pos_processar`) e a convenção dos placeholders.
- Antes de alterar placeholders ou slides IDs, valide/atualize o template no Google Slides.
- Preserve a independência da execução (planilha de acompanhamento + `presentation_id`).
- Em scrapers/conectores, centralize credenciais em `cred_manager` e aplique retry/backoff.