# Bet Trends

Lista diária de jogos de futebol com **tendências claras** para apostas esportivas.
Para cada partida: mercado recomendado, score de confiança (0–100), odd, leitura de
valor (EV), posição na tabela, fase recente (últimos 5) e as tendências que sustentam
a sugestão ("invicto há X", "não vence há Y", over/under, ambos marcam, etc.).

Site estático + build diário no GitHub Actions. Custo zero, sem servidor.

## Como funciona

```
GitHub Actions (cron 08:00 BRT / botão manual)
  └─ python -m app.build --days 3
       ├─ 365scores      → jogos, tabela, últimos 5 de cada time (sem chave)
       └─ the-odds-api    → odds 1X2 / over-under / ambos marcam (chave grátis)
  └─ commita docs/data/*.json
GitHub Pages serve /docs → página estática lê data/latest.json
```

- **Modelo** (`app/model.py`): Poisson de força de time. Ataque/defesa de cada lado =
  mistura de temporada atual, últimos 5 jogos e (quando a temporada tem poucos jogos)
  a temporada anterior. Gols esperados → matriz de placares → probabilidades por mercado.
- **Tendências** (`app/trends.py`): sequências e padrões dos últimos jogos + gap na tabela.
- **Recomendação** (`app/recommend.py`): entre 1X2, dupla chance, over/under 2.5 e ambos
  marcam, escolhe o de melhor combinação probabilidade × clareza de tendência.
  Confiança = `0.65·prob + 0.35·tendências`, penalizada por amostra pequena.
  Valor: `EV% = prob_modelo × odd − 1`; stake sugerido = ¼ de Kelly (teto 2% da banca).

## Rodar local

```bash
pip install -r requirements-dev.txt

# sem odds (não precisa de chave)
python -m app.build --date 2026-09-13 --days 3 --no-odds

# com odds
export ODDS_API_KEY=xxxxxxxx
python -m app.build --days 3

# ver o site
python -m http.server -d docs 8000   # abre http://localhost:8000

# testes
pytest
```

## Configuração

Tudo em `app/config.py`:

- **`LEAGUES`** — ligas cobertas. Para adicionar uma:
  ```bash
  python -m app.discover "nome da liga"     # acha o competitionId do 365scores
  ```
  e acrescente uma linha em `LEAGUES` (o `odds_key` pode ser `None`).
- **`MODEL`** — pesos do modelo (mando de campo, temporada vs. recente, compressão de
  forças extremas, limites de gols esperados).
- **`SCORING`** — pisos de probabilidade por mercado, peso prob. × tendência, limiar de
  valor, fração de Kelly, confiança mínima para um jogo entrar na lista.
- **`BANKROLL`** — se preenchido, o stake aparece em R$ em vez de %.

## Deploy (uma vez)

1. Conta no GitHub + `gh auth login`.
2. `gh repo create bet-trends --public --source . --push`
3. `gh secret set ODDS_API_KEY` (chave grátis em <https://the-odds-api.com>).
4. Settings → Pages → Source: branch `main`, pasta `/docs`.
5. Actions → *Gerar sugestões diárias* → *Run workflow* para a primeira carga.

## Compartilhar

O site é uma URL pública do GitHub Pages (`https://<usuário>.github.io/bet-trends`).
Basta mandar o link — não tem login, cadastro nem nada. No celular, o amigo abre e
usa "Adicionar à tela de início" (funciona como app, PWA).

## Continuar funcionando sozinho

- O **GitHub Actions roda 2x/dia** (08h e 17h BRT) e faz commit dos dados novos.
- Cada commit conta como atividade, então o cron **não é desativado** pela regra dos
  60 dias de inatividade — a menos que a build falhe por 60 dias seguidos.
- Se a fonte (365scores) mudar e a build parar de gerar jogos, o passo *Sanidade*
  **falha de propósito** e o GitHub **te manda um e-mail** (notificação padrão de
  workflow que falha).
- O site também mostra um **aviso amarelo no topo** se os dados estiverem com mais de
  ~40h — assim você (e os amigos) percebem na hora.
- Para forçar uma atualização: aba **Actions → Gerar sugestões diárias → Run workflow**.

## Aviso

Sugestões geradas por um modelo estatístico simples, **sem garantia de acerto**.
Não é recomendação financeira. Aposte com responsabilidade e apenas o que puder perder.
