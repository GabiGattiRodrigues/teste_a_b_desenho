# DaVinci — assistente de desenho de teste A/B

O DaVinci ajuda a dimensionar (desenhar) um teste A/B em português simples: você
conta o que quer testar, e ele calcula quantas pessoas precisa em cada grupo e
quanto tempo esperar — sem precisar saber estatística de antemão.

Cuida só do **desenho do teste** (o dimensionamento, antes de rodar). Acompanhar
o teste já em andamento e diagnósticos pós-coleta (SRM, crossover, novelty etc.)
ficam fora do escopo — isso é assunto de uma ferramenta de medição separada.

## O que tem aqui

- `app.py` — o app em Streamlit (a versão que roda em Python).
- `ab_design.py` — a biblioteca com toda a lógica de cálculo (só usa a biblioteca
  padrão do Python, sem dependências externas).
- `test_ab_design.py` — os testes automatizados da lógica de cálculo.
- `assets/davinci_mascote.jpg` — o mascote usado no ícone da aba e no topo do app.
- `requirements.txt` — dependências do projeto (só o Streamlit).
- `.streamlit/config.toml` — tema visual do app (cores, fundo claro).
- `rodar_davinci.bat` — atalho pra rodar o app com dois cliques no Windows.

## Rodando localmente

**Windows:** descompacte tudo numa pasta e dê dois cliques em `rodar_davinci.bat`.
Ele confere se o Python está instalado, instala as dependências automaticamente
na primeira vez e já abre o app no navegador.

**Manual (qualquer sistema), com Python 3.10+ já instalado:**

```bash
pip install -r requirements.txt
streamlit run app.py
```

O app abre em `http://localhost:8501`.

### Acesso

Na primeira tela, o app pede um nome e uma senha:

- Senha padrão (uso normal): `teste_a_b_produto`
- Senha da administradora: `teste_a_b_gabi` — libera um painel extra mostrando
  todos os usuários que já entraram no DaVinci.

*(Isso não é autenticação de verdade — são duas senhas fixas no código, só pra
separar "uso normal" de "modo admin" num protótipo local. Não usar pra proteger
dado sensível.)*

### Onde ficam os dados salvos

O histórico de testes salvos (`historico_testes.json`) e o registro de quem já
entrou (`usuarios_log.json`) são criados automaticamente na mesma pasta do
`app.py`, na primeira vez que são usados. Eles não vêm no repositório — cada
instalação acumula o próprio histórico.

## Testando a lógica de cálculo

```bash
python test_ab_design.py
```

## Publicando no Streamlit Community Cloud

1. Suba este repositório pro GitHub (ele já está pronto: `app.py` na raiz,
   `requirements.txt` e `.streamlit/config.toml` inclusos).
2. Entre em [share.streamlit.io](https://share.streamlit.io) com sua conta do
   GitHub.
3. Clique em **New app**, escolha este repositório e a branch, e aponte
   **Main file path** para `app.py`.
4. Clique em **Deploy**. O Streamlit lê o `requirements.txt` e o
   `.streamlit/config.toml` automaticamente.

Atenção: no Streamlit Community Cloud o armazenamento não é permanente — o
histórico de testes e o log de usuários salvos em disco (`.json`) podem ser
perdidos quando o app reinicia ou dorme por inatividade. Pra uso local (via
`rodar_davinci.bat`) isso não é um problema, já que os arquivos ficam na sua
própria máquina.

## Versão web

Existe também uma versão em HTML/JavaScript autocontida (sem precisar de
Python), publicada como artifact — a mesma lógica de cálculo, com curva normal
desenhada e histórico salvo no navegador.
