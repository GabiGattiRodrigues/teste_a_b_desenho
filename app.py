"""
DaVinci — assistente de desenho de teste A/B (v2)

Rodar com:
    pip install -r requirements.txt
    streamlit run app.py
"""

import json
import random
import string
from datetime import datetime
from html import escape as _esc
from pathlib import Path

import streamlit as st
import streamlit.components.v1 as components

from ab_design import (
    montar_plano,
    build_html_summary,
    Guardrail,
    DEFAULT_GUARDRAILS,
    z_two_sided,
    z_power,
)

ASSETS_DIR = Path(__file__).parent / "assets"
LOGO_PATH = ASSETS_DIR / "davinci_mascote.jpg"
_page_icon = str(LOGO_PATH) if LOGO_PATH.exists() else "🧑‍🎨"

HISTORICO_PATH = Path(__file__).parent / "historico_testes.json"
USUARIOS_LOG_PATH = Path(__file__).parent / "usuarios_log.json"

# Senha compartilhada pra quem usa o app no dia a dia, e uma senha à parte
# pra criadora (Gabi) -- so pra desbloquear o painel de "quem ja entrou".
# Isso NAO e autenticacao de verdade (as senhas ficam em texto puro aqui no
# codigo) -- e so uma trava simples pra separar "uso normal" de "modo admin"
# num prototipo local.
SENHA_PADRAO = "teste_a_b_produto"
SENHA_ADMIN = "teste_a_b_gabi"


def _gerar_id_teste() -> str:
    sufixo = "".join(random.choices(string.ascii_uppercase + string.digits, k=4))
    return f"DV-{datetime.now():%Y%m%d}-{sufixo}"


def _carregar_historico() -> list:
    if HISTORICO_PATH.exists():
        try:
            return json.loads(HISTORICO_PATH.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return []
    return []


def _salvar_historico(lista: list) -> None:
    HISTORICO_PATH.write_text(json.dumps(lista, ensure_ascii=False, indent=2), encoding="utf-8")


# --------------------------------------------------------------------------
# Log de "quem já entrou" — por padrão fica só num arquivo local (não
# aparece pra quem acessa de outro computador/celular/instância). Se uma
# planilha Google for configurada nos secrets (veja o README), o log passa
# a ser escrito e lido dali, e aí sim fica igual pra todo mundo, em
# qualquer device. Se a planilha não estiver configurada ou der erro, o
# app volta sozinho a usar o arquivo local — nunca quebra por causa disso.
# --------------------------------------------------------------------------

_SHEETS_SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]

# Guarda o motivo da última tentativa de conectar na planilha, pra mostrar
# pra admin no painel quando não estiver usando a planilha (em vez de só
# "não configurado" — ajuda a descobrir o que corrigir). Como a conexão é
# cacheada por processo (@st.cache_resource), essa variável também precisa
# ser global — não dá pra guardar em st.session_state, porque só a sessão
# que "ganhou" a primeira tentativa executaria a função de novo.
_ERRO_PLANILHA = None


@st.cache_resource(show_spinner=False)
def _planilha_usuarios():
    global _ERRO_PLANILHA
    try:
        import gspread
        from google.oauth2.service_account import Credentials
    except ImportError as e:
        _ERRO_PLANILHA = f"biblioteca não instalada ({e}) — rode 'pip install -r requirements.txt' de novo."
        return None
    try:
        if "gcp_service_account" not in st.secrets or "gsheets_log_url" not in st.secrets:
            _ERRO_PLANILHA = "secrets não configurados (faltando gcp_service_account e/ou gsheets_log_url)."
            return None
        creds = Credentials.from_service_account_info(
            dict(st.secrets["gcp_service_account"]), scopes=_SHEETS_SCOPES
        )
        cliente = gspread.authorize(creds)
        aba = cliente.open_by_url(st.secrets["gsheets_log_url"]).sheet1
        _ERRO_PLANILHA = None
        return aba
    except Exception as e:
        _ERRO_PLANILHA = f"{type(e).__name__}: {e}"
        return None


def _carregar_usuarios_log_local() -> list:
    if USUARIOS_LOG_PATH.exists():
        try:
            return json.loads(USUARIOS_LOG_PATH.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return []
    return []


def _carregar_usuarios_log() -> list:
    aba = _planilha_usuarios()
    if aba is not None:
        try:
            return aba.get_all_records()
        except Exception:
            pass
    return _carregar_usuarios_log_local()


def _registrar_usuario(nome: str, admin: bool) -> None:
    quando = datetime.now().strftime("%d/%m/%Y %H:%M")
    tipo = "Administradora" if admin else "Usuário"
    aba = _planilha_usuarios()
    if aba is not None:
        try:
            aba.append_row([nome, quando, tipo])
            return
        except Exception:
            pass
    log = _carregar_usuarios_log_local()
    log.insert(0, {"nome": nome, "quando": quando, "tipo": tipo})
    USUARIOS_LOG_PATH.write_text(json.dumps(log, ensure_ascii=False, indent=2), encoding="utf-8")

st.set_page_config(page_title="DaVinci — Teste A/B", page_icon=_page_icon, layout="wide")

# --------------------------------------------------------------------------
# Boas-vindas — na primeira vez que o dash abre nesta sessão, mostra o
# mascote + uma mensagem simpática e pede o nome de quem está usando.
# --------------------------------------------------------------------------

if not st.session_state.get("usuario_nome"):
    st.markdown("<div style='height: 48px;'></div>", unsafe_allow_html=True)
    col_boas_a, col_boas_b, col_boas_c = st.columns([1, 2, 1])
    with col_boas_b:
        if LOGO_PATH.exists():
            img_col_a, img_col_b, img_col_c = st.columns([1, 1, 1])
            with img_col_b:
                st.image(str(LOGO_PATH), width=140)
        st.markdown(
            "<h2 style='text-align:center; margin-bottom:4px;'>Oi! Eu sou o DaVinci 🎨</h2>"
            "<p style='text-align:center; color:#7A6752; font-size:15px; margin-top:0;'>"
            "Vou te ajudar a desenhar (dimensionar) o seu próximo teste A/B, todo explicado em "
            "português simples — sem precisar saber estatística de antemão.</p>",
            unsafe_allow_html=True,
        )
        nome_input = st.text_input(
            "Antes da gente começar, qual é o seu nome? *",
            key="input_boas_vindas_nome", placeholder="Seu nome",
        )
        senha_input = st.text_input(
            "Senha de acesso *", key="input_boas_vindas_senha", type="password", placeholder="Senha",
        )
        st.caption("Campos com \\* são obrigatórios.")
        if st.button("Vamos começar →", use_container_width=True, type="primary"):
            if not nome_input.strip():
                st.warning("Preciso do seu nome pra continuar 🙂")
            elif senha_input == SENHA_ADMIN:
                st.session_state.usuario_nome = nome_input.strip()
                st.session_state.is_admin = True
                _registrar_usuario(nome_input.strip(), True)
                st.rerun()
            elif senha_input == SENHA_PADRAO:
                st.session_state.usuario_nome = nome_input.strip()
                st.session_state.is_admin = False
                _registrar_usuario(nome_input.strip(), False)
                st.rerun()
            else:
                st.error("Senha incorreta — confere com quem te passou o acesso.")
    st.stop()

col_logo, col_title, col_usuario = st.columns([1, 6, 2], gap="small")
with col_logo:
    if LOGO_PATH.exists():
        st.image(str(LOGO_PATH), width=76)
with col_title:
    st.title("DaVinci")
    st.caption(
        "Seu assistente pra desenhar (dimensionar) um teste A/B direitinho. "
        "Cuida só do desenho do teste — acompanhar o teste rodando e diagnósticos "
        "pós-coleta (SRM, crossover, etc.) ficam fora do escopo desta ferramenta."
    )
with col_usuario:
    _selo_admin = (
        " <span style='background:#FBF0D2; color:#6B4E00; border-radius:999px; padding:2px 9px; "
        "font-size:11px; font-weight:600; margin-left:4px;'>admin</span>"
        if st.session_state.get("is_admin") else ""
    )
    st.markdown(
        f"<div style='text-align:right; padding-top:20px;'>"
        f"<span style='font-size:14px; color:#7A6752;'>👋 Olá, <b>{_esc(st.session_state.usuario_nome)}</b></span>"
        f"{_selo_admin}</div>",
        unsafe_allow_html=True,
    )
    if st.button("trocar", key="btn_trocar_usuario", help="Trocar o nome de quem está usando"):
        st.session_state.usuario_nome = None
        st.session_state.is_admin = False
        st.rerun()

with st.expander("📖 Tutorial rápido — como usar e o que os números significam"):
    st.markdown(
        "##### Como usar, passo a passo\n"
        "1. **Preencha o \"Sobre este teste\"** — nome (obrigatório), área e objetivo. "
        "O ID é gerado sozinho. O \"Cadastro do teste\" é opcional, mas ajuda bastante na "
        "hora de medir o resultado depois.\n"
        "2. **Escolha o tipo de métrica**: *Proporção* pra algo que é sim/não por pessoa "
        "(converteu, cancelou); *Média/tempo/quantidade* pra um número que varia de pessoa "
        "pra pessoa (duração, valor em R$, itens).\n"
        "3. **Diga se você quer que a métrica suba ou caia** (ex.: conversão sobe; churn ou "
        "tempo de carregamento cai).\n"
        "4. **Preencha \"como estamos indo hoje\"** e **a menor diferença que já vale a pena** — "
        "não é o quanto você espera que mude, é o mínimo que precisaria mudar pra valer a "
        "pena implementar de vez.\n"
        "5. **Ajuste alfa e poder** se quiser ser mais ou menos rigoroso — os valores padrão "
        "(1% e 80%) já são um bom começo pra maioria dos testes.\n"
        "6. **Informe o tráfego diário** e **quantos grupos** você vai comparar.\n"
        "7. **Defina os guardrails** — o que não pode piorar, com o valor atual de cada um.\n"
        "8. **Veja o resultado** logo ali do lado, e **salve no histórico** ou **exporte o "
        "resumo em PDF** quando estiver pronto.\n"
    )
    st.markdown(
        "##### O que cada número do resultado quer dizer\n"
        "- **Pessoas por grupo / Total do experimento** — quantas pessoas você precisa juntar "
        "em cada braço do teste antes de poder confiar no resultado.\n"
        "- **Rodar por X dias** — quanto tempo deixar o teste no ar, já arredondado pra fechar "
        "semanas completas (cortar no meio da semana pode distorcer o resultado, porque o "
        "comportamento muda de segunda a domingo).\n"
        "- **Menor diferença visível em X dias** — se você só puder rodar até esse prazo, essa "
        "é a menor mudança que ainda dá pra enxergar com confiança.\n"
        "- **Lift** — o quanto a métrica muda em termos relativos (%), considerando a menor "
        "diferença que você definiu como \"já vale a pena\".\n"
        "- **Chance de erro (alfa)** — a chance de achar que funcionou, sem ter funcionado de "
        "verdade (um falso positivo).\n"
        "- **Chance de perceber (poder)** — se a mudança for real, qual a chance do teste "
        "realmente enxergar isso.\n"
        "- **\"Quanto custa ser mais rigoroso\"** — mostra a troca entre confiança e "
        "velocidade: pedir menos risco de erro (alfa menor) pede mais gente e, às vezes, "
        "mais tempo.\n"
        "- **Guardrails** — métricas que não podem piorar mesmo que o resultado principal "
        "melhore. Sempre olhe eles junto do resultado, nunca isolados.\n"
    )
    st.markdown(
        "##### E depois que o teste terminar de rodar?\n"
        "Essa ferramenta cuida só do **desenho** (o dimensionamento, antes de começar). "
        "Acompanhar o teste já em andamento e analisar o resultado no fim (SRM, crossover, "
        "novelty etc.) ficam por conta de uma ferramenta de medição separada — o cadastro do "
        "teste preenchido aqui foi pensado justamente pra facilitar esse handoff."
    )

if "guardrails" not in st.session_state:
    st.session_state.guardrails = [
        {"nome": g.nome, "direcao": g.direcao, "valor_atual": g.valor_atual} for g in DEFAULT_GUARDRAILS
    ]

# --------------------------------------------------------------------------
# Identificação do teste
# --------------------------------------------------------------------------

st.subheader("Sobre este teste")
st.caption("Campos com \\* são obrigatórios.")

if "id_teste" not in st.session_state:
    st.session_state.id_teste = _gerar_id_teste()

c1, c2, c3 = st.columns([2, 2, 2])
with c1:
    nome_teste = st.text_input(
        "Nome do teste *", key="nome_teste", placeholder="Ex.: Novo formulário de cadastro",
        help="Obrigatório — é o que identifica esse teste no relatório e no histórico.",
    )
with c2:
    area_resp = st.text_input("Área responsável", key="area_resp", placeholder="Ex.: Produto / Growth")
with c3:
    id_col1, id_col2 = st.columns([3, 1])
    with id_col1:
        id_teste = st.text_input(
            "ID do teste", key="id_teste",
            help="Gerado automaticamente pra identificar esse teste no histórico — pode editar se quiser.",
        )
    with id_col2:
        st.markdown("<div style='height: 28px;'></div>", unsafe_allow_html=True)
        if st.button("🔄", key="btn_novo_id", help="Gerar um novo ID", use_container_width=True):
            st.session_state.id_teste = _gerar_id_teste()
            st.rerun()

objetivo_teste = st.text_area(
    "Objetivo (o que você quer melhorar, e por quê)", key="objetivo_teste",
    placeholder="Ex.: Diminuir a desistência na tela do cartão de crédito.",
)

st.markdown("##### 🗂️ Cadastro do teste (aparece no relatório e ajuda na hora de medir depois)")
st.caption(
    "Campos opcionais — preenchendo aqui, já vai tudo pronto pro relatório final, sem "
    "precisar repetir na hora de medir o resultado."
)
cc1, cc2 = st.columns(2)
with cc1:
    bu = st.text_input("BU", key="bu", placeholder="Ex.: Varejo (e-commerce)")
    experimento = st.text_input("Experimento", key="experimento", placeholder="Ex.: Checkout em uma etapa")
    campanha = st.text_input("Campanha", key="campanha", placeholder="Ex.: Sem campanha (orgânico)")
    dispositivo = st.text_input("Dispositivo", key="dispositivo", placeholder="Ex.: iOS")
with cc2:
    metrica_nome = st.text_input("Métrica", key="metrica_nome", placeholder="Ex.: Taxa de conversão do checkout")
    regiao = st.text_input("Região", key="regiao", placeholder="Ex.: Nacional")
    plataforma = st.text_input("Plataforma", key="plataforma", placeholder="Ex.: App")

st.divider()

# --------------------------------------------------------------------------
# Histórico de testes salvos (persistido em disco, ao lado do app — sempre
# visível aqui em cima, independente do teste que está sendo montado agora)
# --------------------------------------------------------------------------

st.subheader("📁 Histórico de testes salvos")
_historico_salvo = _carregar_historico()
if not _historico_salvo:
    st.caption(
        "Nenhum teste salvo ainda. Depois de montar um teste, use o botão \"Salvar este teste no "
        "histórico\" lá embaixo, no Resumo pra compartilhar."
    )
else:
    st.caption(f"{len(_historico_salvo)} teste(s) salvo(s) neste computador.")
    for h in _historico_salvo:
        titulo = f"{h.get('nome') or '(sem nome)'} · {h.get('salvo_em', '')} · ID {h.get('id', '')}"
        with st.expander(titulo):
            n_braco = h.get("n_por_braco")
            n_tot = h.get("n_total")
            dias = h.get("dias_rodar")
            if n_braco is not None:
                st.write(
                    f"**{n_braco:,}** pessoas por grupo · **{n_tot:,}** no total · "
                    f"rodar por **{dias}** dias".replace(",", ".")
                )
            hc1, hc2 = st.columns(2)
            with hc1:
                st.download_button(
                    "⬇️ Baixar resumo (.html)", h.get("resumo_html", ""),
                    file_name=f"resumo_{h.get('id', 'teste')}.html", mime="text/html",
                    key=f"hist_dl_{h.get('id')}", use_container_width=True,
                )
            with hc2:
                if st.button("🗑️ Remover do histórico", key=f"hist_del_{h.get('id')}", use_container_width=True):
                    restante = [x for x in _carregar_historico() if x.get("id") != h.get("id")]
                    _salvar_historico(restante)
                    st.rerun()

# --------------------------------------------------------------------------
# Painel de admin (só aparece pra quem entrou com a senha da criadora) --
# lista todo mundo que já entrou no DaVinci.
# --------------------------------------------------------------------------

if st.session_state.get("is_admin"):
    st.divider()
    st.subheader("👥 Usuários que já entraram no DaVinci")
    _usando_planilha = _planilha_usuarios() is not None
    _usuarios = _carregar_usuarios_log()

    if not _usando_planilha:
        if _ERRO_PLANILHA:
            st.caption(
                "⚠️ Não consegui usar a planilha Google — caiu pro arquivo local (só desta instância). "
                "Motivo:"
            )
            st.code(_ERRO_PLANILHA, language=None)
        else:
            st.caption(
                "Planilha Google não configurada — usando o arquivo local (só desta instância). "
                "Veja o README, seção \"Ver quem usou o DaVinci em qualquer dispositivo\"."
            )

    if not _usuarios:
        st.caption("Ninguém entrou ainda.")
    else:
        if _usando_planilha:
            st.caption(
                f"{len(_usuarios)} entrada(s) — vindas da planilha compartilhada "
                "(conta quem entrou em qualquer computador, celular ou instância que usa essa planilha)."
            )
        else:
            st.caption(f"{len(_usuarios)} entrada(s) registrada(s) só nesta instância.")
        st.table([
            {
                "Nome": u.get("nome", ""),
                "Quando": u.get("quando", ""),
                "Tipo": u.get("tipo") or ("Administradora" if u.get("admin") else "Usuário"),
            }
            for u in _usuarios
        ])

st.divider()

with st.expander("❓ Perguntas que podem aparecer"):
    st.markdown(
        "**Mas essa ferramenta não tem \"conceito de negócio\" — como ela conseguiu fazer isso "
        "sozinha?**\n\n"
        "Ela não decide nada de negócio sozinha — só faz a conta depois que **eu** tomo as "
        "decisões que importam: qual é a menor diferença que compensa o esforço de mudar, "
        "quanto risco de errar a empresa aceita correr (alfa/poder), e o que não pode piorar de "
        "jeito nenhum (guardrails). Essas três escolhas são de negócio, e eu que defino olhando "
        "pro contexto — a ferramenta só traduz isso em números."
    )
    st.markdown(
        "**Eu nem preenchi minha população total — como você já me deu um número de amostra?**\n\n"
        "Porque o tamanho da amostra não depende de quantas pessoas existem no total — depende de "
        "três coisas que já estão preenchidas ali em cima: quão comum é o que estou medindo hoje "
        "(baseline), qual a menor diferença que vale a pena enxergar, e quanto risco de errar eu "
        "aceito correr. É como provar uma sopa: o tanto que eu preciso provar pra saber se está boa "
        "não muda muito se a panela tem 10 litros ou 10.000 — o que muda é o quanto a sopa varia de "
        "colher pra colher. A população total só entra como um ajuste fino, e só quando ela é pequena "
        "(a amostra pediria mais de 5% dela) — por isso o campo \"Sei quantas pessoas existem no "
        "total\" é opcional: só marque se sua base for pequena ou se quiser deixar a conta mais "
        "precisa."
    )
    st.markdown(
        "**De onde vem esse tal de Z? Por que a conta usa uma \"distribuição normal\"?**\n\n"
        "Quando juntamos muita gente numa amostra, a média dos resultados possíveis se comporta "
        "de um jeito bem previsível: a maioria fica perto da média \"verdadeira\", e vai ficando "
        "cada vez mais raro conforme se afasta dela — isso é o Teorema Central do Limite, e vale "
        "mesmo que o dado de cada pessoa (comprou ou não) não seja \"normal\". Como esse "
        "comportamento é sempre parecido, existe uma tabela pronta (a normal padrão) que traduz "
        "\"quero 95% de confiança\" ou \"quero 80% de poder\" num número — o Z — que entra direto "
        "na fórmula. Na prática, Z é \"quantos desvios-padrão de distância da média eu preciso "
        "ficar pra cobrir X% dos casos possíveis\"."
    )

st.divider()

# --------------------------------------------------------------------------
# Tipo de métrica e direção
# --------------------------------------------------------------------------

with st.sidebar:
    st.header("Qual é a métrica?")

    tipo_metrica_label = st.radio(
        "Tipo de métrica",
        ["Proporção (ex.: % que converte, % de churn)", "Média / tempo / quantidade (ex.: segundos, R$, itens)"],
        index=0,  # ignorado por streamlit se "tipo_metrica_label" ja existir no session_state
        key="tipo_metrica_label",
        help="Proporção: algo sim/não por pessoa (converteu, cancelou). "
             "Média/tempo: um número que varia de pessoa pra pessoa (duração, quantidade, valor).",
    )
    tipo_metrica = "proporcao" if tipo_metrica_label.startswith("Proporção") else "media"

    direcao_label = st.radio(
        "O que você quer que aconteça?", ["Quero que suba", "Quero que caia"],
        index=0 if st.session_state.get("direcao_label", "Quero que suba") == "Quero que suba" else 1,
        key="direcao_label", horizontal=True,
    )
    direcao = "subir" if direcao_label == "Quero que suba" else "cair"

    st.divider()
    st.header("Parâmetros do teste")

    if tipo_metrica == "proporcao":
        baseline = st.number_input(
            "Como estamos indo hoje, antes de mudar nada? (%)", min_value=0.01, max_value=99.99,
            value=st.session_state.get("baseline", 32.0), step=0.5, key="baseline",
            help="Ex.: hoje, de cada 100 pessoas que chegam nessa etapa, quantas completam (ou cancelam)? "
                 "Conte só quem CHEGA na etapa — não a base inteira do app.",
        )
        sigma = None
        unidade_metrica = "%"
    else:
        col_m1, col_m2 = st.columns(2)
        with col_m1:
            baseline = st.number_input(
                "Valor médio hoje", min_value=0.0001,
                value=st.session_state.get("baseline_media", 30.0), step=1.0,
                key="baseline_media",
                help="Ex.: duração média da sessão, tempo até completar, quantidade de itens, R$ por pedido... "
                     "Precisa ser maior que 0.",
            )
        with col_m2:
            unidade_metrica = st.text_input(
                "Unidade", value=st.session_state.get("unidade_metrica", "segundos"), key="unidade_metrica",
                help="Ex.: segundos, R$, itens, sessões.",
            )
        sigma = st.number_input(
            "Desvio padrão estimado (o quanto varia de pessoa pra pessoa hoje)",
            min_value=0.0001, value=st.session_state.get("sigma", 12.0), step=1.0, key="sigma",
            help="Se não souber o valor exato, uma estimativa grosseira já ajuda: pegue a diferença "
                 "entre os percentis 75 e 25 da métrica e divida por 1,35.",
        )

    mde_tipo_label = st.radio(
        "Como você prefere definir a menor diferença que já vale a pena?",
        ["Em % de mudança sobre hoje", "Direto na unidade da métrica"],
        index=0 if st.session_state.get("mde_tipo", "Em % de mudança sobre hoje") == "Em % de mudança sobre hoje" else 1,
        key="mde_tipo", horizontal=True,
    )
    mde_tipo = "relativo" if mde_tipo_label.startswith("Em %") else "absoluto"

    mde_valor = st.number_input(
        "Valor da menor diferença"
        + (" (% de mudança sobre hoje)" if mde_tipo == "relativo"
           else f" ({'pontos percentuais' if tipo_metrica == 'proporcao' else unidade_metrica})"),
        min_value=0.01, value=st.session_state.get("mde_valor", 10.0), step=0.5, key="mde_valor",
        help="Não é o quanto você espera mudar — é o mínimo que precisaria mudar "
             "pra valer a pena implementar de vez.",
    )

    col_a, col_b = st.columns(2)
    with col_a:
        alfa = st.number_input(
            "Chance de a gente se enganar (%)",
            min_value=0.1, max_value=50.0, value=st.session_state.get("alfa", 1.0),
            step=0.5, key="alfa", help="Alfa — achar que funcionou, sem ter funcionado de verdade.",
        )
    with col_b:
        poder = st.number_input(
            "Chance de perceber, se funcionar (%)",
            min_value=50.0, max_value=99.9, value=st.session_state.get("poder", 80.0),
            step=1.0, key="poder", help="Poder — se a mudança for real, qual a chance de enxergar?",
        )

    trafego = st.number_input(
        "Quantas pessoas novas chegam nessa etapa por dia?", min_value=1.0,
        value=st.session_state.get("trafego", 800.0), step=10.0, key="trafego",
    )

    variantes = st.number_input(
        "Quantos grupos vamos comparar? (braços, incl. controle)", min_value=2, max_value=10,
        value=st.session_state.get("variantes", 2), step=1, key="variantes",
        help="Braço = grupo do experimento, não etapa da jornada. Com 2, é "
             "A (controle, versão de hoje) e B (variante, com a mudança). "
             "Mais de 2 braços aplica correção de Bonferroni automaticamente.",
    )
    st.caption(
        "💡 **Braço ≠ etapa do funil.** Cada braço é um grupo que divide o tráfego "
        "(A vê a versão de hoje, B a nova). A etapa da jornada já entra no "
        "\"como estamos indo hoje\" acima — não entra de novo aqui."
    )

    populacao_ativa = st.checkbox(
        "Sei quantas pessoas existem no total (afina a conta)",
        value=st.session_state.get("populacao_ativa", False), key="populacao_ativa",
    )
    st.caption(
        "💡 Opcional — sem isso a conta já funciona normalmente. Só faz diferença quando a base "
        "total é pequena (veja \"Perguntas que podem aparecer\" lá em cima)."
    )
    populacao = None
    if populacao_ativa:
        populacao = st.number_input(
            "Total de pessoas elegíveis", min_value=1, value=st.session_state.get("populacao", 100000),
            step=100, key="populacao",
        )

    sazonalidade = st.checkbox(
        "O período do teste pega feriado ou época fora do normal?",
        value=st.session_state.get("sazonalidade", False), key="sazonalidade",
    )

    st.divider()
    st.subheader("O que NÃO pode piorar (guardrails)")
    st.caption(
        "Definidos antes do teste — mesmo que o resultado principal melhore, isso aqui não pode "
        "degradar. O valor atual é obrigatório: sem saber o quanto está hoje, não dá pra saber "
        "depois se piorou."
    )

    gh1, gh2, gh3, gh4 = st.columns([3, 2, 2, 1])
    with gh1:
        st.caption("Métrica *")
    with gh2:
        st.caption("Valor atual *")
    with gh3:
        st.caption("Direção")
    with gh4:
        st.caption("")

    for i, g in enumerate(st.session_state.guardrails):
        gc1, gc2, gc3, gc4 = st.columns([3, 2, 2, 1])
        with gc1:
            g["nome"] = st.text_input(
                f"Métrica {i+1}", value=g["nome"], key=f"g_nome_{i}", label_visibility="collapsed",
                placeholder="O que não pode piorar",
            )
        with gc2:
            g["valor_atual"] = st.text_input(
                f"Valor atual {i+1}", value=g.get("valor_atual", ""), key=f"g_valor_{i}",
                label_visibility="collapsed", placeholder="Valor hoje (ex.: R$ 45)",
            )
        with gc3:
            g["direcao"] = st.selectbox(
                "Direção", ["nao_pode_subir", "nao_pode_cair"],
                index=0 if g["direcao"] == "nao_pode_subir" else 1,
                format_func=lambda d: "não pode subir" if d == "nao_pode_subir" else "não pode cair",
                key=f"g_dir_{i}", label_visibility="collapsed",
            )
        with gc4:
            if st.button("🗑️", key=f"g_del_{i}"):
                st.session_state.guardrails.pop(i)
                st.rerun()

    if st.button("+ adicionar algo que não pode piorar"):
        st.session_state.guardrails.append({"nome": "", "direcao": "nao_pode_subir", "valor_atual": ""})
        st.rerun()


# --------------------------------------------------------------------------
# Validação do cadastro (nome do teste e valor atual dos guardrails são
# obrigatórios — sem isso, não dá pra rastrear o teste depois nem saber se
# um guardrail realmente piorou)
# --------------------------------------------------------------------------

erros_cadastro = []
if not nome_teste.strip():
    erros_cadastro.append("O nome do teste é obrigatório.")
for g in st.session_state.guardrails:
    if g["nome"].strip() and not g.get("valor_atual", "").strip():
        erros_cadastro.append(f"Guardrail \"{g['nome']}\" precisa do valor atual (o quanto está hoje).")

if erros_cadastro:
    st.caption("👆 Preencha os campos marcados com * acima pra ver o resultado.")
    st.stop()

# --------------------------------------------------------------------------
# Cálculo
# --------------------------------------------------------------------------

erro = None
plano = None
try:
    guardrails_obj = [
        Guardrail(nome=g["nome"], direcao=g["direcao"], valor_atual=g.get("valor_atual", ""))
        for g in st.session_state.guardrails if g["nome"].strip()
    ]
    plano = montar_plano(
        tipo_metrica=tipo_metrica,
        direcao=direcao,
        baseline_valor=baseline,
        sigma=sigma,
        unidade_metrica=unidade_metrica,
        mde_valor=mde_valor,
        mde_tipo=mde_tipo,
        alfa_pct=alfa,
        poder_pct=poder,
        trafego_dia=trafego,
        variantes=int(variantes),
        populacao=int(populacao) if populacao else None,
        janela_tem_sazonalidade=sazonalidade,
        guardrails=guardrails_obj,
        id_teste=id_teste,
        nome=nome_teste, area=area_resp, objetivo=objetivo_teste,
        bu=bu, metrica_nome=metrica_nome, experimento=experimento,
        regiao=regiao, campanha=campanha, plataforma=plataforma, dispositivo=dispositivo,
    )
except ValueError as e:
    erro = str(e)

if erro:
    st.error(f"Não deu para desenhar o teste: {erro}")
    st.stop()

# --------------------------------------------------------------------------
# Avisos
# --------------------------------------------------------------------------

icone = {"erro": "🔴", "aviso": "🟡", "info": "🔵", "ok": "🟢"}
for a in plano.alertas:
    texto = f"{icone.get(a.nivel, '•')} {a.texto}"
    if a.nivel == "erro":
        st.error(texto)
    elif a.nivel == "aviso":
        st.warning(texto)
    elif a.nivel == "info":
        st.info(texto)
    else:
        st.success(texto)


def _fmt_metrica_st(valor: float) -> str:
    if plano.tipo_metrica == "proporcao":
        return f"{valor*100:.2f}%"
    return f"{valor:,.2f} {plano.unidade_metrica}".replace(",", "X").replace(".", ",").replace("X", ".")


# --------------------------------------------------------------------------
# Métricas principais
# --------------------------------------------------------------------------

verbo = "subir" if plano.direcao == "subir" else "cair"
st.subheader("Quantas pessoas em cada grupo, e por quanto tempo")

st.caption("Cada grupo (braço) é uma versão sendo testada — não é uma etapa da jornada:")
grupo_cols = st.columns(len(plano.grupos) + 1)
for col, g in zip(grupo_cols[:-1], plano.grupos):
    rotulo = f"Grupo {g['letra']} ({g['papel']})"
    col.metric(rotulo, f"{g['n']:,}".replace(",", "."))
grupo_cols[-1].metric("Total do experimento", f"{plano.n_total:,}".replace(",", "."))

m3, m4 = st.columns(2)
m3.metric("Rodar por", f"{plano.dias_rodar} dias", f"{plano.dias_rodar // 7} semana(s)")
if plano.mde_realizado_no_prazo is not None:
    unidade_display = "% (abs.)" if plano.tipo_metrica == "proporcao" else plano.unidade_metrica
    valor_display = plano.mde_realizado_no_prazo * 100 if plano.tipo_metrica == "proporcao" else plano.mde_realizado_no_prazo
    m4.metric(
        f"Menor diferença visível em {plano.dias_rodar} dias",
        f"{valor_display:.2f} {unidade_display}",
        help="Se você só puder rodar por esse prazo, essa é a menor diferença que ainda dá pra enxergar.",
    )

st.caption(
    f"Queremos que **{verbo}** de **{_fmt_metrica_st(plano.baseline)}** para **{_fmt_metrica_st(plano.alvo)}**."
)
palavra = "aumento (lift)" if plano.direcao == "subir" else "redução"
st.success(f"📈 Isso é um **{palavra}** de **{abs(plano.lift_relativo)*100:.1f}%** em relação a hoje.")

with st.expander("ℹ️ Como eu calculei isso?"):
    za = z_two_sided(plano.alfa_efetivo)
    zb = z_power(plano.poder)
    if plano.tipo_metrica == "proporcao":
        st.markdown(
            "Uso uma fórmula estatística de comparação de duas proporções: quanto **menor** a "
            "diferença que você quer enxergar, ou quanto **mais rigoroso** você quer ser, **mais "
            "gente** o teste precisa — essa relação cresce rápido (reduzir a diferença pela metade "
            "multiplica a amostra por ~4x)."
        )
        st.code(
            "n por grupo ≈ [ Z(erro) × √(2·p̄·(1-p̄)) + Z(confiança) × √(p1·(1-p1)+p2·(1-p2)) ]² / (p2 − p1)²",
            language=None,
        )
    else:
        st.markdown(
            "Pra métrica de média, uso a comparação de duas médias, supondo que o desvio padrão é "
            "parecido nos dois grupos (só a média muda). É uma fórmula fechada — não precisa de "
            "busca numérica como na de proporção."
        )
        st.code("n por grupo ≈ 2 · σ² · [ Z(erro) + Z(confiança) ]² / diferença²", language=None)
        st.caption(f"σ (desvio padrão informado) = {plano.sigma:g} {plano.unidade_metrica}")

    st.markdown(
        f"**De onde vem o Z?** Quando juntamos muita gente, a média dos resultados possíveis se "
        f"comporta de um jeito previsível (Teorema Central do Limite) — daí dá pra usar a tabela da "
        f"distribuição normal pra traduzir \"{plano.alfa_efetivo*100:.2f}% de chance de erro\" em "
        f"Z(erro) ≈ {za:.2f}, e \"{plano.poder*100:.0f}% de confiança de perceber\" em "
        f"Z(confiança) ≈ {zb:.2f}."
    )
    st.markdown(
        f"Com os números atuais → **{plano.n_por_braco:,}** pessoas por grupo.".replace(",", ".")
    )
    st.markdown(
        "Pro prazo: calculo em quantos dias junto gente suficiente (amostra ÷ tráfego/dia), "
        "e arredondo pra cima até fechar uma semana cheia — o comportamento muda de segunda a "
        "domingo, e cortar no meio da semana pode distorcer o resultado."
    )
    if plano.bonferroni_aplicada:
        st.markdown(
            f"Como você está comparando **{plano.variantes} grupos**, a chance de achar uma "
            f"diferença falsa por acaso aumenta — por isso dividi a chance de erro pelo número de "
            f"comparações: {plano.alfa*100:.1f}% ÷ {plano.variantes - 1} = "
            f"**{plano.alfa_efetivo*100:.2f}%** por comparação (correção de Bonferroni)."
        )

# --------------------------------------------------------------------------
# Comparativo de rigor
# --------------------------------------------------------------------------

st.subheader("Quanto custa ser mais rigoroso")
st.caption("Mesma diferença, mesma confiança — só muda o quanto a gente aceita se enganar (alfa).")
st.table(
    [
        {
            "Chance de erro": f"{c['alfa_pct']}%" + (" (atual)" if c["atual"] else ""),
            "Pessoas por grupo": f"{c['n_por_braco']:,}".replace(",", "."),
            "Tempo": f"~{c['dias']} dias",
        }
        for c in plano.comparativo_alfa
    ]
)

with st.expander("ℹ️ Por que esses números mudam de linha pra linha?"):
    z_confianca = z_power(plano.poder)
    if plano.tipo_metrica == "proporcao":
        formula_rigor = "n por grupo ≈ [ Z(erro) × √(2·p̄·(1-p̄)) + Z(confiança) × √(p1·(1-p1) + p2·(1-p2)) ]² / (p2 − p1)²"
    else:
        formula_rigor = "n por grupo ≈ 2 · σ² · [ Z(erro) + Z(confiança) ]² / diferença²"
    st.markdown(
        f"Nas três linhas, a diferença mínima que eu quero enxergar e a chance de perceber se "
        f"funcionar não mudam (Z(confiança) fica sempre ≈ {z_confianca:.2f}) — a única coisa que "
        f"muda é o quanto eu aceito me enganar (alfa). E é só o alfa que entra no **Z(erro)** desta "
        f"fórmula:"
    )
    st.code(formula_rigor, language=None)
    st.markdown(
        "Quanto **menor** o alfa (mais rigoroso, mais difícil de errar), **maior** o Z(erro) — e "
        "maior o n. Depois eu transformo n em dias: *total de gente (somando os grupos) ÷ pessoas "
        "novas por dia*, arredondado pra cima até fechar uma semana cheia (o comportamento muda de "
        "segunda a domingo, então corto sempre no fim de uma semana, nunca no meio)."
    )
    st.table(
        [
            {
                "Chance de erro": f"{c['alfa_pct']}%" + (" (atual)" if c["atual"] else ""),
                "Z(erro)": f"{z_two_sided(c['alfa_efetivo']):.2f}",
                "Gente por grupo": f"{c['n_por_braco']:,}".replace(",", "."),
                "Dá pra juntar em": f"{c['dias_fechar']} dia(s)",
                "Rodar por": f"{c['dias']} dia(s)",
            }
            for c in plano.comparativo_alfa
        ]
    )
    for anterior, atual in zip(plano.comparativo_alfa, plano.comparativo_alfa[1:]):
        if atual["dias"] == anterior["dias"] and atual["n_por_braco"] != anterior["n_por_braco"]:
            st.markdown(
                f"Repare que {anterior['alfa_pct']}% e {atual['alfa_pct']}% de erro deram o mesmo "
                f"prazo ({atual['dias']} dias), mesmo pedindo quantidades de gente diferentes por "
                f"grupo — as duas amostras cabem dentro da mesma semana cheia de tráfego, então o "
                f"prazo não muda."
            )
        elif atual["dias"] < anterior["dias"]:
            st.markdown(
                f"De {anterior['alfa_pct']}% para {atual['alfa_pct']}% de erro, o prazo caiu de "
                f"{anterior['dias']} para {atual['dias']} dias — a amostra ficou pequena o bastante "
                f"pra fechar uma semana inteira a menos."
            )

# --------------------------------------------------------------------------
# Guardrails
# --------------------------------------------------------------------------

st.subheader("O que não pode piorar")
if plano.guardrails:
    for g in plano.guardrails:
        st.write(f"- {g.texto()}")
else:
    st.caption("Nenhum guardrail definido.")

# --------------------------------------------------------------------------
# Relatório completo / exportação
# --------------------------------------------------------------------------

st.subheader("Resumo pra compartilhar")
resumo_html = build_html_summary(plano)

col_dl, col_save = st.columns(2)
with col_dl:
    st.download_button(
        "🖨️ Baixar resumo bonito (.html — abra e use Imprimir > Salvar como PDF)",
        resumo_html, file_name=f"resumo_teste_ab_{id_teste}.html", mime="text/html",
        use_container_width=True,
    )
with col_save:
    if st.button("💾 Salvar este teste no histórico", use_container_width=True):
        historico = [h for h in _carregar_historico() if h.get("id") != id_teste]
        historico.insert(0, {
            "id": id_teste,
            "nome": nome_teste,
            "salvo_em": datetime.now().strftime("%d/%m/%Y %H:%M"),
            "n_por_braco": plano.n_por_braco,
            "n_total": plano.n_total,
            "dias_rodar": plano.dias_rodar,
            "resumo_html": resumo_html,
        })
        _salvar_historico(historico)
        st.success(f"Teste \"{nome_teste}\" salvo no histórico (ID {id_teste}).")

st.markdown("---")
components.html(resumo_html, height=1300, scrolling=True)
