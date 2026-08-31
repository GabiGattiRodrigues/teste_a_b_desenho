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

## Ver quem usou o DaVinci em qualquer dispositivo

Por padrão, o registro de "quem já entrou" (`usuarios_log.json`) fica só na
máquina/processo que está rodando o app naquele momento — não é
compartilhado entre instâncias. Isso significa:

- Se você roda o app localmente (`.bat`) e também testa pelo app publicado
  no Streamlit Cloud, são dois registros separados.
- No Streamlit Community Cloud o app "dorme" e reinicia sozinho por
  inatividade — e cada reinício apaga esse arquivo, então o painel de admin
  só mostra quem entrou depois do último reinício.

Pra ter uma lista única, igual pra qualquer computador/celular que acessar o
app, dá pra ligar o log numa planilha Google compartilhada. É opcional — sem
configurar nada, o app continua funcionando normalmente com o arquivo local.

**1. Crie a planilha:** no Google Sheets, crie uma planilha nova (ex:
"DaVinci — Log de usuários") com uma aba cuja primeira linha tenha
exatamente as colunas: `nome`, `quando`, `tipo`.

**2. Crie uma conta de serviço no Google Cloud** (gratuito):
   - Entre em [console.cloud.google.com](https://console.cloud.google.com),
     crie um projeto (ou use um existente).
   - Em "APIs e serviços" → "Biblioteca", ative a **Google Sheets API** e a
     **Google Drive API**.
   - Em "APIs e serviços" → "Credenciais" → "Criar credenciais" → "Conta de
     serviço". Dê um nome (ex: `davinci-log`) e crie.
   - Na conta de serviço criada, aba "Chaves" → "Adicionar chave" → "Criar
     nova chave" → formato **JSON**. Isso baixa um arquivo `.json` — guarde
     ele, é a credencial.

**3. Compartilhe a planilha com a conta de serviço:** abra o arquivo `.json`
baixado, copie o valor de `client_email` (algo como
`davinci-log@seu-projeto.iam.gserviceaccount.com`), e compartilhe a
planilha do passo 1 com esse e-mail, dando permissão de **Editor**.

**4. Preencha os secrets:** copie `.streamlit/secrets.toml.example` para
`.streamlit/secrets.toml` e preencha com o link da planilha (`gsheets_log_url`)
e os dados do arquivo `.json` baixado (cada campo do JSON vira uma linha em
`[gcp_service_account]`). Esse arquivo `secrets.toml` **não vai pro git**
(já está no `.gitignore`) — é só local.

**5. No Streamlit Community Cloud:** o app publicado não lê o
`secrets.toml` da sua máquina. Entre nas configurações do app lá no portal
(⋮ → Settings → Secrets) e cole lá o mesmo conteúdo do seu
`secrets.toml` já preenchido.

Depois disso, o painel de admin passa a mostrar "vindas da planilha
compartilhada" e lista todo mundo que entrou, de qualquer dispositivo. Se a
planilha não estiver configurada (ou dado algum erro de acesso), o app
volta sozinho a usar o arquivo local, sem quebrar.

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
