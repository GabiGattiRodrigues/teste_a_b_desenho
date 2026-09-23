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

import ab_design
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

# O app e aberto: qualquer pessoa entra so com o nome. A senha abaixo serve
# unicamente pra desbloquear o painel de admin ("quem ja entrou").
# Isso NAO e autenticacao de verdade (fica em texto puro aqui no codigo) --
# e so uma trava simples pra separar "uso normal" de "modo admin".
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

st.set_page_config(page_title="DaVinci — Teste A/B · A/B test", page_icon=_page_icon, layout="wide")

# --------------------------------------------------------------------------
# Português e inglês. O texto em inglês mora ao lado do português
# (L("Olá", "Hi")); a língua fica no session_state e espelha na URL
# (?lang=en). As contas não mudam de língua — só os textos e o separador
# de milhar (1.234 · 1,234).
# --------------------------------------------------------------------------

if "idioma" not in st.session_state:
    _pedido = str(st.query_params.get("lang", "pt")).lower()
    st.session_state["idioma"] = "en" if _pedido.startswith("en") else "pt"


def _trocar_idioma() -> None:
    novo = st.session_state.get("_seletor_idioma")
    if novo in ("pt", "en"):          # clicar de novo na língua ativa desmarca: ignora
        st.session_state["idioma"] = novo
        st.query_params["lang"] = novo


EN = st.session_state["idioma"] == "en"
ab_design.definir_idioma(st.session_state["idioma"])


def L(pt: str, en: str) -> str:
    """A frase na língua ativa."""
    return en if EN else pt


def milhar(n) -> str:
    """Inteiro com separador de milhar na língua ativa."""
    s = f"{n:,}"
    return s if EN else s.replace(",", ".")


def seletor_idioma() -> None:
    st.session_state["_seletor_idioma"] = st.session_state["idioma"]
    st.segmented_control(
        "Idioma · Language", options=["pt", "en"],
        format_func=lambda k: {"pt": "🇧🇷 Português", "en": "🇺🇸 English"}[k],
        key="_seletor_idioma", on_change=_trocar_idioma,
        label_visibility="collapsed", selection_mode="single")


# --------------------------------------------------------------------------
# Boas-vindas — na primeira vez que o dash abre nesta sessão, mostra o
# mascote + uma mensagem simpática e pede o nome de quem está usando.
# --------------------------------------------------------------------------

if not st.session_state.get("usuario_nome"):
    st.markdown("<div style='height: 48px;'></div>", unsafe_allow_html=True)
    col_boas_a, col_boas_b, col_boas_c = st.columns([1, 2, 1])
    with col_boas_c:
        seletor_idioma()
    with col_boas_b:
        if LOGO_PATH.exists():
            img_col_a, img_col_b, img_col_c = st.columns([1, 1, 1])
            with img_col_b:
                st.image(str(LOGO_PATH), width=140)
        st.markdown(
            "<h2 style='text-align:center; margin-bottom:4px;'>"
            + L("Oi! Eu sou o DaVinci 🎨", "Hi! I'm DaVinci 🎨") + "</h2>"
            "<p style='text-align:center; color:#5B6B82; font-size:15px; margin-top:0;'>"
            + L("Vou te ajudar a desenhar (dimensionar) o seu próximo teste A/B, todo explicado em "
                "português simples — sem precisar saber estatística de antemão.",
                "I'll help you design (size) your next A/B test, all explained in plain English — "
                "no need to know statistics beforehand.") + "</p>",
            unsafe_allow_html=True,
        )
        nome_input = st.text_input(
            L("Antes da gente começar, qual é o seu nome? *", "Before we start, what's your name? *"),
            key="input_boas_vindas_nome", placeholder=L("Seu nome", "Your name"),
        )
        with st.expander(L("Acesso da criadora (opcional)", "Creator access (optional)")):
            senha_input = st.text_input(
                L("Senha de admin", "Admin password"), key="input_boas_vindas_senha", type="password",
                placeholder=L("Só quem cuida do app precisa disso", "Only whoever runs the app needs this"),
            )
        st.caption(L("Campos com \\* são obrigatórios.", "Fields with \\* are required."))
        if st.button(L("Vamos começar →", "Let's start →"), width="stretch", type="primary"):
            if not nome_input.strip():
                st.warning(L("Preciso do seu nome pra continuar 🙂", "I need your name to continue 🙂"))
            else:
                eh_admin = senha_input == SENHA_ADMIN
                st.session_state.usuario_nome = nome_input.strip()
                st.session_state.is_admin = eh_admin
                _registrar_usuario(nome_input.strip(), eh_admin)
                st.rerun()
    st.stop()

col_logo, col_title, col_usuario = st.columns([1, 6, 2], gap="small")
with col_logo:
    if LOGO_PATH.exists():
        st.image(str(LOGO_PATH), width=76)
with col_title:
    st.title("DaVinci")
    st.caption(L(
        "Seu assistente pra desenhar (dimensionar) um teste A/B direitinho. "
        "Cuida só do desenho do teste — acompanhar o teste rodando e diagnósticos "
        "pós-coleta (SRM, crossover, etc.) ficam fora do escopo desta ferramenta.",
        "Your assistant for designing (sizing) an A/B test properly. "
        "It only handles the test design — monitoring the running test and post-collection "
        "diagnostics (SRM, crossover, etc.) are outside this tool's scope."
    ))
with col_usuario:
    seletor_idioma()
    _selo_admin = (
        " <span style='background:#E3EDFB; color:#1F4E8C; border-radius:999px; padding:2px 9px; "
        "font-size:11px; font-weight:600; margin-left:4px;'>admin</span>"
        if st.session_state.get("is_admin") else ""
    )
    st.markdown(
        f"<div style='text-align:right; padding-top:20px;'>"
        f"<span style='font-size:14px; color:#5B6B82;'>👋 {L('Olá', 'Hi')}, <b>{_esc(st.session_state.usuario_nome)}</b></span>"
        f"{_selo_admin}</div>",
        unsafe_allow_html=True,
    )
    if st.button(L("trocar", "switch"), key="btn_trocar_usuario",
                 help=L("Trocar o nome de quem está usando", "Change the name of who's using it")):
        st.session_state.usuario_nome = None
        st.session_state.is_admin = False
        st.rerun()

with st.expander(L("📖 Tutorial rápido — como usar e o que os números significam",
                   "📖 Quick tutorial — how to use it and what the numbers mean")):
    st.markdown(L(
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
        "resumo em PDF** quando estiver pronto.\n",
        "##### How to use it, step by step\n"
        "1. **Fill in \"About this test\"** — name (required), team and goal. "
        "The ID is generated automatically. The \"Test registration\" is optional, but it helps a "
        "lot when measuring the result later.\n"
        "2. **Pick the metric type**: *Proportion* for something that's yes/no per person "
        "(converted, canceled); *Average/time/quantity* for a number that varies from person "
        "to person (duration, amount in R$, items).\n"
        "3. **Say whether you want the metric to go up or down** (e.g. conversion goes up; churn or "
        "load time goes down).\n"
        "4. **Fill in \"where we are today\"** and **the smallest difference that's worth it** — "
        "it's not how much you expect it to change, it's the minimum it would need to change to be "
        "worth rolling out for good.\n"
        "5. **Adjust alpha and power** if you want to be more or less strict — the defaults "
        "(1% and 80%) are a good start for most tests.\n"
        "6. **Enter the daily traffic** and **how many groups** you'll compare.\n"
        "7. **Define the guardrails** — what must not get worse, with the current value of each.\n"
        "8. **See the result** right there, and **save it to the history** or **export the "
        "summary as PDF** when it's ready.\n"
    ))
    st.markdown(L(
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
        "melhore. Sempre olhe eles junto do resultado, nunca isolados.\n",
        "##### What each number in the result means\n"
        "- **People per group / Experiment total** — how many people you need to gather "
        "in each arm of the test before you can trust the result.\n"
        "- **Run for X days** — how long to keep the test live, already rounded up to full "
        "weeks (cutting mid-week can distort the result, because behavior changes from Monday "
        "to Sunday).\n"
        "- **Smallest visible difference in X days** — if you can only run until that deadline, "
        "this is the smallest change you can still see with confidence.\n"
        "- **Lift** — how much the metric changes in relative terms (%), given the smallest "
        "difference you defined as \"worth it\".\n"
        "- **Chance of error (alpha)** — the chance of thinking it worked when it didn't "
        "really work (a false positive).\n"
        "- **Chance of noticing (power)** — if the change is real, the chance that the test "
        "actually sees it.\n"
        "- **\"What being stricter costs\"** — shows the trade-off between confidence and "
        "speed: asking for less risk of error (lower alpha) calls for more people and, sometimes, "
        "more time.\n"
        "- **Guardrails** — metrics that must not get worse even if the main result "
        "improves. Always look at them together with the result, never in isolation.\n"
    ))
    st.markdown(L(
        "##### E depois que o teste terminar de rodar?\n"
        "Essa ferramenta cuida só do **desenho** (o dimensionamento, antes de começar). "
        "Acompanhar o teste já em andamento e analisar o resultado no fim (SRM, crossover, "
        "novelty etc.) ficam por conta de uma ferramenta de medição separada — o cadastro do "
        "teste preenchido aqui foi pensado justamente pra facilitar esse handoff.",
        "##### And after the test finishes running?\n"
        "This tool only handles the **design** (the sizing, before it starts). "
        "Monitoring the test while it runs and analyzing the result at the end (SRM, crossover, "
        "novelty etc.) are the job of a separate measurement tool — the test registration "
        "filled in here was designed precisely to make that handoff easier."
    ))

if "guardrails" not in st.session_state:
    st.session_state.guardrails = [
        {"nome": L(g.nome, {"custo por cliente": "cost per customer",
                            "tempo medio de cadastro": "average sign-up time"}.get(g.nome, g.nome)),
         "direcao": g.direcao, "valor_atual": g.valor_atual} for g in DEFAULT_GUARDRAILS
    ]

# --------------------------------------------------------------------------
# Identificação do teste
# --------------------------------------------------------------------------

st.subheader(L("Sobre este teste", "About this test"))
st.caption(L("Campos com \\* são obrigatórios.", "Fields with \\* are required."))

if "id_teste" not in st.session_state:
    st.session_state.id_teste = _gerar_id_teste()
if st.session_state.pop("_regenerar_id_teste", False):
    # Precisa mudar o valor ANTES do widget (abaixo) ser criado nesta mesma
    # rodada do script — depois que o widget existe, o Streamlit não deixa
    # mais sobrescrever st.session_state["id_teste"] diretamente (dá
    # StreamlitAPIException / WidgetAlreadyInstantiatedError).
    st.session_state.id_teste = _gerar_id_teste()

c1, c2, c3 = st.columns([2, 2, 2])
with c1:
    nome_teste = st.text_input(
        L("Nome do teste *", "Test name *"), key="nome_teste",
        placeholder=L("Ex.: Novo formulário de cadastro", "E.g.: New sign-up form"),
        help=L("Obrigatório — é o que identifica esse teste no relatório e no histórico.",
               "Required — it's what identifies this test in the report and in the history."),
    )
with c2:
    area_resp = st.text_input(L("Área responsável", "Owning team"), key="area_resp",
                              placeholder=L("Ex.: Produto / Growth", "E.g.: Product / Growth"))
with c3:
    id_col1, id_col2 = st.columns([3, 1])
    with id_col1:
        id_teste = st.text_input(
            L("ID do teste", "Test ID"), key="id_teste",
            help=L("Gerado automaticamente pra identificar esse teste no histórico — pode editar se quiser.",
                   "Generated automatically to identify this test in the history — you can edit it."),
        )
    with id_col2:
        st.markdown("<div style='height: 28px;'></div>", unsafe_allow_html=True)
        if st.button("🔄", key="btn_novo_id", help=L("Gerar um novo ID", "Generate a new ID"), width="stretch"):
            st.session_state._regenerar_id_teste = True
            st.rerun()

objetivo_teste = st.text_area(
    L("Objetivo (o que você quer melhorar, e por quê)", "Goal (what you want to improve, and why)"),
    key="objetivo_teste",
    placeholder=L("Ex.: Diminuir a desistência na tela do cartão de crédito.",
                  "E.g.: Reduce drop-off on the credit card screen."),
)

st.markdown(L("##### 🗂️ Cadastro do teste (aparece no relatório e ajuda na hora de medir depois)",
              "##### 🗂️ Test registration (shows up in the report and helps when measuring later)"))
st.caption(L(
    "Campos opcionais — preenchendo aqui, já vai tudo pronto pro relatório final, sem "
    "precisar repetir na hora de medir o resultado.",
    "Optional fields — filling them in here gets everything ready for the final report, with no "
    "need to repeat it when measuring the result."
))
cc1, cc2 = st.columns(2)
with cc1:
    bu = st.text_input("BU", key="bu", placeholder=L("Ex.: Varejo (e-commerce)", "E.g.: Retail (e-commerce)"))
    experimento = st.text_input(L("Experimento", "Experiment"), key="experimento",
                                placeholder=L("Ex.: Checkout em uma etapa", "E.g.: One-step checkout"))
    campanha = st.text_input(L("Campanha", "Campaign"), key="campanha",
                             placeholder=L("Ex.: Sem campanha (orgânico)", "E.g.: No campaign (organic)"))
    dispositivo = st.text_input(L("Dispositivo", "Device"), key="dispositivo", placeholder=L("Ex.: iOS", "E.g.: iOS"))
with cc2:
    metrica_nome = st.text_input(L("Métrica", "Metric"), key="metrica_nome",
                                 placeholder=L("Ex.: Taxa de conversão do checkout", "E.g.: Checkout conversion rate"))
    regiao = st.text_input(L("Região", "Region"), key="regiao", placeholder=L("Ex.: Nacional", "E.g.: Nationwide"))
    plataforma = st.text_input(L("Plataforma", "Platform"), key="plataforma", placeholder=L("Ex.: App", "E.g.: App"))

st.divider()

# --------------------------------------------------------------------------
# Histórico de testes salvos (persistido em disco, ao lado do app — sempre
# visível aqui em cima, independente do teste que está sendo montado agora)
# --------------------------------------------------------------------------

st.subheader(L("📁 Histórico de testes salvos", "📁 Saved test history"))
_historico_salvo = _carregar_historico()
if not _historico_salvo:
    st.caption(L(
        "Nenhum teste salvo ainda. Depois de montar um teste, use o botão \"Salvar este teste no "
        "histórico\" lá embaixo, no Resumo pra compartilhar.",
        "No saved tests yet. After setting up a test, use the \"Save this test to the history\" "
        "button down below, in the Summary to share."
    ))
else:
    st.caption(L(f"{len(_historico_salvo)} teste(s) salvo(s) neste computador.",
                 f"{len(_historico_salvo)} test(s) saved on this computer."))
    for h in _historico_salvo:
        titulo = f"{h.get('nome') or L('(sem nome)', '(no name)')} · {h.get('salvo_em', '')} · ID {h.get('id', '')}"
        with st.expander(titulo):
            n_braco = h.get("n_por_braco")
            n_tot = h.get("n_total")
            dias = h.get("dias_rodar")
            if n_braco is not None:
                st.write(L(
                    f"**{milhar(n_braco)}** pessoas por grupo · **{milhar(n_tot)}** no total · "
                    f"rodar por **{dias}** dias",
                    f"**{milhar(n_braco)}** people per group · **{milhar(n_tot)}** in total · "
                    f"run for **{dias}** days"))
            hc1, hc2 = st.columns(2)
            with hc1:
                st.download_button(
                    L("⬇️ Baixar resumo (.html)", "⬇️ Download summary (.html)"), h.get("resumo_html", ""),
                    file_name=f"resumo_{h.get('id', 'teste')}.html", mime="text/html",
                    key=f"hist_dl_{h.get('id')}", width="stretch",
                )
            with hc2:
                if st.button(L("🗑️ Remover do histórico", "🗑️ Remove from history"),
                             key=f"hist_del_{h.get('id')}", width="stretch"):
                    restante = [x for x in _carregar_historico() if x.get("id") != h.get("id")]
                    _salvar_historico(restante)
                    st.rerun()

# --------------------------------------------------------------------------
# Painel de admin (só aparece pra quem entrou com a senha da criadora) --
# lista todo mundo que já entrou no DaVinci.
# --------------------------------------------------------------------------

if st.session_state.get("is_admin"):
    st.divider()
    st.subheader(L("👥 Usuários que já entraram no DaVinci", "👥 Users who have entered DaVinci"))
    _usando_planilha = _planilha_usuarios() is not None
    _usuarios = _carregar_usuarios_log()

    if not _usando_planilha:
        if _ERRO_PLANILHA:
            st.caption(L(
                "⚠️ Não consegui usar a planilha Google — caiu pro arquivo local (só desta instância). "
                "Motivo:",
                "⚠️ I couldn't use the Google Sheet — fell back to the local file (this instance only). "
                "Reason:"
            ))
            st.code(_ERRO_PLANILHA, language=None)
        else:
            st.caption(L(
                "Planilha Google não configurada — usando o arquivo local (só desta instância). "
                "Veja o README, seção \"Ver quem usou o DaVinci em qualquer dispositivo\".",
                "Google Sheet not configured — using the local file (this instance only). "
                "See the README, section \"Ver quem usou o DaVinci em qualquer dispositivo\"."
            ))

    if not _usuarios:
        st.caption(L("Ninguém entrou ainda.", "Nobody has entered yet."))
    else:
        if _usando_planilha:
            st.caption(L(
                f"{len(_usuarios)} entrada(s) — vindas da planilha compartilhada "
                "(conta quem entrou em qualquer computador, celular ou instância que usa essa planilha).",
                f"{len(_usuarios)} entry(ies) — from the shared sheet "
                "(counts whoever entered from any computer, phone or instance that uses this sheet)."
            ))
        else:
            st.caption(L(f"{len(_usuarios)} entrada(s) registrada(s) só nesta instância.",
                         f"{len(_usuarios)} entry(ies) recorded on this instance only."))
        _tipos_en = {"Administradora": "Admin", "Usuário": "User"}
        st.table([
            {
                L("Nome", "Name"): u.get("nome", ""),
                L("Quando", "When"): u.get("quando", ""),
                L("Tipo", "Type"): (lambda t: _tipos_en.get(t, t) if EN else t)(
                    u.get("tipo") or ("Administradora" if u.get("admin") else "Usuário")),
            }
            for u in _usuarios
        ])

st.divider()

with st.expander(L("❓ Perguntas que podem aparecer", "❓ Questions that may come up")):
    st.markdown(L(
        "**Mas essa ferramenta não tem \"conceito de negócio\" — como ela conseguiu fazer isso "
        "sozinha?**\n\n"
        "Ela não decide nada de negócio sozinha — só faz a conta depois que **eu** tomo as "
        "decisões que importam: qual é a menor diferença que compensa o esforço de mudar, "
        "quanto risco de errar a empresa aceita correr (alfa/poder), e o que não pode piorar de "
        "jeito nenhum (guardrails). Essas três escolhas são de negócio, e eu que defino olhando "
        "pro contexto — a ferramenta só traduz isso em números.",
        "**But this tool has no \"business sense\" — how did it manage to do this on its own?**\n\n"
        "It doesn't decide anything about the business on its own — it only does the math after "
        "**I** make the decisions that matter: what the smallest difference is that's worth the "
        "effort of changing, how much risk of being wrong the company accepts (alpha/power), and "
        "what must not get worse under any circumstances (guardrails). Those three choices are "
        "business choices, and I make them by looking at the context — the tool just turns them "
        "into numbers."
    ))
    st.markdown(L(
        "**Eu nem preenchi minha população total — como você já me deu um número de amostra?**\n\n"
        "Porque o tamanho da amostra não depende de quantas pessoas existem no total — depende de "
        "três coisas que já estão preenchidas ali em cima: quão comum é o que estou medindo hoje "
        "(baseline), qual a menor diferença que vale a pena enxergar, e quanto risco de errar eu "
        "aceito correr. É como provar uma sopa: o tanto que eu preciso provar pra saber se está boa "
        "não muda muito se a panela tem 10 litros ou 10.000 — o que muda é o quanto a sopa varia de "
        "colher pra colher. A população total só entra como um ajuste fino, e só quando ela é pequena "
        "(a amostra pediria mais de 5% dela) — por isso o campo \"Sei quantas pessoas existem no "
        "total\" é opcional: só marque se sua base for pequena ou se quiser deixar a conta mais "
        "precisa.",
        "**I didn't even fill in my total population — how did you already give me a sample size?**\n\n"
        "Because the sample size doesn't depend on how many people exist in total — it depends on "
        "three things already filled in above: how common what I'm measuring is today (baseline), "
        "the smallest difference worth seeing, and how much risk of being wrong I accept. It's like "
        "tasting soup: how much I need to taste to know whether it's good doesn't change much whether "
        "the pot holds 10 liters or 10,000 — what changes is how much the soup varies from spoonful "
        "to spoonful. The total population only comes in as a fine adjustment, and only when it's "
        "small (the sample would ask for more than 5% of it) — that's why the \"I know how many "
        "people exist in total\" field is optional: only tick it if your base is small or if you "
        "want a more precise calculation."
    ))
    st.markdown(L(
        "**De onde vem esse tal de Z? Por que a conta usa uma \"distribuição normal\"?**\n\n"
        "Quando juntamos muita gente numa amostra, a média dos resultados possíveis se comporta "
        "de um jeito bem previsível: a maioria fica perto da média \"verdadeira\", e vai ficando "
        "cada vez mais raro conforme se afasta dela — isso é o Teorema Central do Limite, e vale "
        "mesmo que o dado de cada pessoa (comprou ou não) não seja \"normal\". Como esse "
        "comportamento é sempre parecido, existe uma tabela pronta (a normal padrão) que traduz "
        "\"quero 95% de confiança\" ou \"quero 80% de poder\" num número — o Z — que entra direto "
        "na fórmula. Na prática, Z é \"quantos desvios-padrão de distância da média eu preciso "
        "ficar pra cobrir X% dos casos possíveis\".",
        "**Where does this Z come from? Why does the math use a \"normal distribution\"?**\n\n"
        "When we gather a lot of people in a sample, the average of the possible results behaves "
        "in a very predictable way: most of it stays close to the \"true\" average, and it gets "
        "rarer and rarer the further you move from it — that's the Central Limit Theorem, and it "
        "holds even when each person's data point (bought or not) isn't \"normal\". Since that "
        "behavior is always similar, there's a ready-made table (the standard normal) that turns "
        "\"I want 95% confidence\" or \"I want 80% power\" into a number — Z — that goes straight "
        "into the formula. In practice, Z is \"how many standard deviations away from the average "
        "I need to go to cover X% of the possible cases\"."
    ))

st.divider()

# --------------------------------------------------------------------------
# Tipo de métrica e direção
# --------------------------------------------------------------------------

with st.sidebar:
    st.header(L("Qual é a métrica?", "What's the metric?"))

    # As opções são chaves fixas; o rótulo muda com a língua (format_func).
    tipo_metrica = st.radio(
        L("Tipo de métrica", "Metric type"),
        ["proporcao", "media"],
        format_func=lambda k: {
            "proporcao": L("Proporção (ex.: % que converte, % de churn)",
                           "Proportion (e.g. % who convert, % churn)"),
            "media": L("Média / tempo / quantidade (ex.: segundos, R$, itens)",
                       "Average / time / quantity (e.g. seconds, R$, items)"),
        }[k],
        key="tipo_metrica_k",
        help=L("Proporção: algo sim/não por pessoa (converteu, cancelou). "
               "Média/tempo: um número que varia de pessoa pra pessoa (duração, quantidade, valor).",
               "Proportion: something yes/no per person (converted, canceled). "
               "Average/time: a number that varies from person to person (duration, quantity, amount)."),
    )

    direcao = st.radio(
        L("O que você quer que aconteça?", "What do you want to happen?"), ["subir", "cair"],
        format_func=lambda k: {"subir": L("Quero que suba", "I want it to go up"),
                               "cair": L("Quero que caia", "I want it to go down")}[k],
        key="direcao_k", horizontal=True,
    )

    st.divider()
    st.header(L("Parâmetros do teste", "Test parameters"))

    if tipo_metrica == "proporcao":
        baseline = st.number_input(
            L("Como estamos indo hoje, antes de mudar nada? (%)", "Where are we today, before changing anything? (%)"),
            min_value=0.01, max_value=99.99,
            value=st.session_state.get("baseline", 32.0), step=0.5, key="baseline",
            help=L("Ex.: hoje, de cada 100 pessoas que chegam nessa etapa, quantas completam (ou cancelam)? "
                   "Conte só quem CHEGA na etapa — não a base inteira do app.",
                   "E.g.: today, out of every 100 people who reach this step, how many complete it (or cancel)? "
                   "Count only who REACHES the step — not the app's whole base."),
        )
        sigma = None
        unidade_metrica = "%"
    else:
        col_m1, col_m2 = st.columns(2)
        with col_m1:
            baseline = st.number_input(
                L("Valor médio hoje", "Average value today"), min_value=0.0001,
                value=st.session_state.get("baseline_media", 30.0), step=1.0,
                key="baseline_media",
                help=L("Ex.: duração média da sessão, tempo até completar, quantidade de itens, R$ por pedido... "
                       "Precisa ser maior que 0.",
                       "E.g.: average session length, time to complete, number of items, R$ per order... "
                       "It must be greater than 0."),
            )
        with col_m2:
            unidade_metrica = st.text_input(
                L("Unidade", "Unit"), value=st.session_state.get("unidade_metrica", L("segundos", "seconds")),
                key="unidade_metrica",
                help=L("Ex.: segundos, R$, itens, sessões.", "E.g.: seconds, R$, items, sessions."),
            )
        sigma = st.number_input(
            L("Desvio padrão estimado (o quanto varia de pessoa pra pessoa hoje)",
              "Estimated standard deviation (how much it varies from person to person today)"),
            min_value=0.0001, value=st.session_state.get("sigma", 12.0), step=1.0, key="sigma",
            help=L("Se não souber o valor exato, uma estimativa grosseira já ajuda: pegue a diferença "
                   "entre os percentis 75 e 25 da métrica e divida por 1,35.",
                   "If you don't know the exact value, a rough estimate already helps: take the difference "
                   "between the metric's 75th and 25th percentiles and divide by 1.35."),
        )

    mde_tipo = st.radio(
        L("Como você prefere definir a menor diferença que já vale a pena?",
          "How do you prefer to define the smallest difference that's worth it?"),
        ["relativo", "absoluto"],
        format_func=lambda k: {"relativo": L("Em % de mudança sobre hoje", "As % change over today"),
                               "absoluto": L("Direto na unidade da métrica", "Directly in the metric's unit")}[k],
        key="mde_tipo_k", horizontal=True,
    )

    if mde_tipo == "relativo":
        _sufixo_mde = L(" (% de mudança sobre hoje)", " (% change over today)")
    else:
        _sufixo_mde = f" ({L('pontos percentuais', 'percentage points') if tipo_metrica == 'proporcao' else unidade_metrica})"
    mde_valor = st.number_input(
        L("Valor da menor diferença", "Smallest difference value") + _sufixo_mde,
        min_value=0.01, value=st.session_state.get("mde_valor", 10.0), step=0.5, key="mde_valor",
        help=L("Não é o quanto você espera mudar — é o mínimo que precisaria mudar "
               "pra valer a pena implementar de vez.",
               "It's not how much you expect it to change — it's the minimum it would need to change "
               "to be worth rolling out for good."),
    )

    col_a, col_b = st.columns(2)
    with col_a:
        alfa = st.number_input(
            L("Chance de a gente se enganar (%)", "Chance of us being wrong (%)"),
            min_value=0.1, max_value=50.0, value=st.session_state.get("alfa", 1.0),
            step=0.5, key="alfa",
            help=L("Alfa — achar que funcionou, sem ter funcionado de verdade.",
                   "Alpha — thinking it worked when it didn't really work."),
        )
    with col_b:
        poder = st.number_input(
            L("Chance de perceber, se funcionar (%)", "Chance of noticing, if it works (%)"),
            min_value=50.0, max_value=99.9, value=st.session_state.get("poder", 80.0),
            step=1.0, key="poder",
            help=L("Poder — se a mudança for real, qual a chance de enxergar?",
                   "Power — if the change is real, what's the chance of seeing it?"),
        )

    trafego = st.number_input(
        L("Quantas pessoas novas chegam nessa etapa por dia?", "How many new people reach this step per day?"),
        min_value=1.0, value=st.session_state.get("trafego", 800.0), step=10.0, key="trafego",
    )

    variantes = st.number_input(
        L("Quantos grupos vamos comparar? (braços, incl. controle)",
          "How many groups will we compare? (arms, incl. control)"),
        min_value=2, max_value=10, value=st.session_state.get("variantes", 2), step=1, key="variantes",
        help=L("Braço = grupo do experimento, não etapa da jornada. Com 2, é "
               "A (controle, versão de hoje) e B (variante, com a mudança). "
               "Mais de 2 braços aplica correção de Bonferroni automaticamente.",
               "Arm = experiment group, not a journey step. With 2, it's "
               "A (control, today's version) and B (variant, with the change). "
               "More than 2 arms applies the Bonferroni correction automatically."),
    )
    st.caption(L(
        "💡 **Braço ≠ etapa do funil.** Cada braço é um grupo que divide o tráfego "
        "(A vê a versão de hoje, B a nova). A etapa da jornada já entra no "
        "\"como estamos indo hoje\" acima — não entra de novo aqui.",
        "💡 **Arm ≠ funnel step.** Each arm is a group that splits the traffic "
        "(A sees today's version, B the new one). The journey step already goes into "
        "\"where we are today\" above — it doesn't go in again here."
    ))

    populacao_ativa = st.checkbox(
        L("Sei quantas pessoas existem no total (afina a conta)",
          "I know how many people exist in total (refines the math)"),
        value=st.session_state.get("populacao_ativa", False), key="populacao_ativa",
    )
    st.caption(L(
        "💡 Opcional — sem isso a conta já funciona normalmente. Só faz diferença quando a base "
        "total é pequena (veja \"Perguntas que podem aparecer\" lá em cima).",
        "💡 Optional — without it the math works normally. It only makes a difference when the "
        "total base is small (see \"Questions that may come up\" above)."
    ))
    populacao = None
    if populacao_ativa:
        populacao = st.number_input(
            L("Total de pessoas elegíveis", "Total eligible people"), min_value=1,
            value=st.session_state.get("populacao", 100000), step=100, key="populacao",
        )

    sazonalidade = st.checkbox(
        L("O período do teste pega feriado ou época fora do normal?",
          "Does the test period include a holiday or an unusual season?"),
        value=st.session_state.get("sazonalidade", False), key="sazonalidade",
    )

    st.divider()
    st.subheader(L("O que NÃO pode piorar (guardrails)", "What must NOT get worse (guardrails)"))
    st.caption(L(
        "Definidos antes do teste — mesmo que o resultado principal melhore, isso aqui não pode "
        "degradar. O valor atual é obrigatório: sem saber o quanto está hoje, não dá pra saber "
        "depois se piorou.",
        "Defined before the test — even if the main result improves, these must not degrade. "
        "The current value is required: without knowing where it is today, you can't tell later "
        "whether it got worse."
    ))

    gh1, gh2, gh3, gh4 = st.columns([3, 2, 2, 1])
    with gh1:
        st.caption(L("Métrica *", "Metric *"))
    with gh2:
        st.caption(L("Valor atual *", "Current value *"))
    with gh3:
        st.caption(L("Direção", "Direction"))
    with gh4:
        st.caption("")

    for i, g in enumerate(st.session_state.guardrails):
        gc1, gc2, gc3, gc4 = st.columns([3, 2, 2, 1])
        with gc1:
            g["nome"] = st.text_input(
                f"{L('Métrica', 'Metric')} {i+1}", value=g["nome"], key=f"g_nome_{i}", label_visibility="collapsed",
                placeholder=L("O que não pode piorar", "What must not get worse"),
            )
        with gc2:
            g["valor_atual"] = st.text_input(
                f"{L('Valor atual', 'Current value')} {i+1}", value=g.get("valor_atual", ""), key=f"g_valor_{i}",
                label_visibility="collapsed", placeholder=L("Valor hoje (ex.: R$ 45)", "Value today (e.g. R$ 45)"),
            )
        with gc3:
            g["direcao"] = st.selectbox(
                L("Direção", "Direction"), ["nao_pode_subir", "nao_pode_cair"],
                index=0 if g["direcao"] == "nao_pode_subir" else 1,
                format_func=lambda d: (L("não pode subir", "must not go up") if d == "nao_pode_subir"
                                       else L("não pode cair", "must not go down")),
                key=f"g_dir_{i}", label_visibility="collapsed",
            )
        with gc4:
            if st.button("🗑️", key=f"g_del_{i}"):
                st.session_state.guardrails.pop(i)
                st.rerun()

    if st.button(L("+ adicionar algo que não pode piorar", "+ add something that must not get worse")):
        st.session_state.guardrails.append({"nome": "", "direcao": "nao_pode_subir", "valor_atual": ""})
        st.rerun()


# --------------------------------------------------------------------------
# Validação do cadastro (nome do teste e valor atual dos guardrails são
# obrigatórios — sem isso, não dá pra rastrear o teste depois nem saber se
# um guardrail realmente piorou)
# --------------------------------------------------------------------------

erros_cadastro = []
if not nome_teste.strip():
    erros_cadastro.append(L("O nome do teste é obrigatório.", "The test name is required."))
for g in st.session_state.guardrails:
    if g["nome"].strip() and not g.get("valor_atual", "").strip():
        erros_cadastro.append(L(f"Guardrail \"{g['nome']}\" precisa do valor atual (o quanto está hoje).",
                                f"Guardrail \"{g['nome']}\" needs its current value (where it is today)."))

if erros_cadastro:
    st.caption(L("👆 Preencha os campos marcados com * acima pra ver o resultado.",
                 "👆 Fill in the fields marked with * above to see the result."))
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
    st.error(L(f"Não deu para desenhar o teste: {erro}", f"Couldn't design the test: {erro}"))
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
    s = f"{valor:,.2f} {plano.unidade_metrica}"
    return s if EN else s.replace(",", "X").replace(".", ",").replace("X", ".")


# --------------------------------------------------------------------------
# Métricas principais
# --------------------------------------------------------------------------

verbo = (L("subir", "go up") if plano.direcao == "subir" else L("cair", "go down"))
st.subheader(L("Quantas pessoas em cada grupo, e por quanto tempo", "How many people in each group, and for how long"))

st.caption(L("Cada grupo (braço) é uma versão sendo testada — não é uma etapa da jornada:",
             "Each group (arm) is a version being tested — not a step in the journey:"))
grupo_cols = st.columns(len(plano.grupos) + 1)
for col, g in zip(grupo_cols[:-1], plano.grupos):
    rotulo = f"{L('Grupo', 'Group')} {g['letra']} ({g['papel']})"
    col.metric(rotulo, milhar(g['n']))
grupo_cols[-1].metric(L("Total do experimento", "Experiment total"), milhar(plano.n_total))

m3, m4 = st.columns(2)
m3.metric(L("Rodar por", "Run for"), f"{plano.dias_rodar} {L('dias', 'days')}",
          f"{plano.dias_rodar // 7} {L('semana(s)', 'week(s)')}")
if plano.mde_realizado_no_prazo is not None:
    unidade_display = L("% (abs.)", "% (abs.)") if plano.tipo_metrica == "proporcao" else plano.unidade_metrica
    valor_display = plano.mde_realizado_no_prazo * 100 if plano.tipo_metrica == "proporcao" else plano.mde_realizado_no_prazo
    m4.metric(
        L(f"Menor diferença visível em {plano.dias_rodar} dias",
          f"Smallest visible difference in {plano.dias_rodar} days"),
        f"{valor_display:.2f} {unidade_display}",
        help=L("Se você só puder rodar por esse prazo, essa é a menor diferença que ainda dá pra enxergar.",
               "If you can only run for this long, this is the smallest difference you can still see."),
    )

st.caption(L(
    f"Queremos que **{verbo}** de **{_fmt_metrica_st(plano.baseline)}** para **{_fmt_metrica_st(plano.alvo)}**.",
    f"We want it to **{verbo}** from **{_fmt_metrica_st(plano.baseline)}** to **{_fmt_metrica_st(plano.alvo)}**."
))
palavra = (L("aumento (lift)", "increase (lift)") if plano.direcao == "subir" else L("redução", "reduction"))
st.success(L(f"📈 Isso é um **{palavra}** de **{abs(plano.lift_relativo)*100:.1f}%** em relação a hoje.",
             f"📈 That's an **{palavra}** of **{abs(plano.lift_relativo)*100:.1f}%** compared to today."))

with st.expander(L("ℹ️ Como eu calculei isso?", "ℹ️ How did I calculate this?")):
    za = z_two_sided(plano.alfa_efetivo)
    zb = z_power(plano.poder)
    if plano.tipo_metrica == "proporcao":
        st.markdown(L(
            "Uso uma fórmula estatística de comparação de duas proporções: quanto **menor** a "
            "diferença que você quer enxergar, ou quanto **mais rigoroso** você quer ser, **mais "
            "gente** o teste precisa — essa relação cresce rápido (reduzir a diferença pela metade "
            "multiplica a amostra por ~4x).",
            "I use a statistical formula comparing two proportions: the **smaller** the difference "
            "you want to see, or the **stricter** you want to be, the **more people** the test needs "
            "— and that relationship grows fast (halving the difference multiplies the sample by ~4x)."
        ))
        st.code(L(
            "n por grupo ≈ [ Z(erro) × √(2·p̄·(1-p̄)) + Z(confiança) × √(p1·(1-p1)+p2·(1-p2)) ]² / (p2 − p1)²",
            "n per group ≈ [ Z(error) × √(2·p̄·(1-p̄)) + Z(confidence) × √(p1·(1-p1)+p2·(1-p2)) ]² / (p2 − p1)²"),
            language=None,
        )
    else:
        st.markdown(L(
            "Pra métrica de média, uso a comparação de duas médias, supondo que o desvio padrão é "
            "parecido nos dois grupos (só a média muda). É uma fórmula fechada — não precisa de "
            "busca numérica como na de proporção.",
            "For an average metric, I use the comparison of two means, assuming the standard deviation "
            "is similar in both groups (only the mean changes). It's a closed formula — it doesn't need "
            "a numerical search like the proportion one."
        ))
        st.code(L("n por grupo ≈ 2 · σ² · [ Z(erro) + Z(confiança) ]² / diferença²",
                  "n per group ≈ 2 · σ² · [ Z(error) + Z(confidence) ]² / difference²"), language=None)
        st.caption(L(f"σ (desvio padrão informado) = {plano.sigma:g} {plano.unidade_metrica}",
                     f"σ (standard deviation entered) = {plano.sigma:g} {plano.unidade_metrica}"))

    st.markdown(L(
        f"**De onde vem o Z?** Quando juntamos muita gente, a média dos resultados possíveis se "
        f"comporta de um jeito previsível (Teorema Central do Limite) — daí dá pra usar a tabela da "
        f"distribuição normal pra traduzir \"{plano.alfa_efetivo*100:.2f}% de chance de erro\" em "
        f"Z(erro) ≈ {za:.2f}, e \"{plano.poder*100:.0f}% de confiança de perceber\" em "
        f"Z(confiança) ≈ {zb:.2f}.",
        f"**Where does Z come from?** When we gather a lot of people, the average of the possible "
        f"results behaves predictably (Central Limit Theorem) — so we can use the normal distribution "
        f"table to turn \"{plano.alfa_efetivo*100:.2f}% chance of error\" into Z(error) ≈ {za:.2f}, "
        f"and \"{plano.poder*100:.0f}% confidence of noticing\" into Z(confidence) ≈ {zb:.2f}."
    ))
    st.markdown(L(f"Com os números atuais → **{milhar(plano.n_por_braco)}** pessoas por grupo.",
                  f"With the current numbers → **{milhar(plano.n_por_braco)}** people per group."))
    st.markdown(L(
        "Pro prazo: calculo em quantos dias junto gente suficiente (amostra ÷ tráfego/dia), "
        "e arredondo pra cima até fechar uma semana cheia — o comportamento muda de segunda a "
        "domingo, e cortar no meio da semana pode distorcer o resultado.",
        "For the duration: I calculate how many days it takes to gather enough people (sample ÷ "
        "traffic/day), and round up to a full week — behavior changes from Monday to Sunday, and "
        "cutting mid-week can distort the result."
    ))
    if plano.bonferroni_aplicada:
        st.markdown(L(
            f"Como você está comparando **{plano.variantes} grupos**, a chance de achar uma "
            f"diferença falsa por acaso aumenta — por isso dividi a chance de erro pelo número de "
            f"comparações: {plano.alfa*100:.1f}% ÷ {plano.variantes - 1} = "
            f"**{plano.alfa_efetivo*100:.2f}%** por comparação (correção de Bonferroni).",
            f"Since you're comparing **{plano.variantes} groups**, the chance of finding a false "
            f"difference by luck goes up — so I divided the chance of error by the number of "
            f"comparisons: {plano.alfa*100:.1f}% ÷ {plano.variantes - 1} = "
            f"**{plano.alfa_efetivo*100:.2f}%** per comparison (Bonferroni correction)."
        ))

# --------------------------------------------------------------------------
# Comparativo de rigor
# --------------------------------------------------------------------------

_atual = L(" (atual)", " (current)")
st.subheader(L("Quanto custa ser mais rigoroso", "What being stricter costs"))
st.caption(L("Mesma diferença, mesma confiança — só muda o quanto a gente aceita se enganar (alfa).",
             "Same difference, same confidence — only how much we accept being wrong (alpha) changes."))
st.table(
    [
        {
            L("Chance de erro", "Chance of error"): f"{c['alfa_pct']}%" + (_atual if c["atual"] else ""),
            L("Pessoas por grupo", "People per group"): milhar(c['n_por_braco']),
            L("Tempo", "Time"): f"~{c['dias']} {L('dias', 'days')}",
        }
        for c in plano.comparativo_alfa
    ]
)

with st.expander(L("ℹ️ Por que esses números mudam de linha pra linha?", "ℹ️ Why do these numbers change from row to row?")):
    z_confianca = z_power(plano.poder)
    if plano.tipo_metrica == "proporcao":
        formula_rigor = L(
            "n por grupo ≈ [ Z(erro) × √(2·p̄·(1-p̄)) + Z(confiança) × √(p1·(1-p1) + p2·(1-p2)) ]² / (p2 − p1)²",
            "n per group ≈ [ Z(error) × √(2·p̄·(1-p̄)) + Z(confidence) × √(p1·(1-p1) + p2·(1-p2)) ]² / (p2 − p1)²")
    else:
        formula_rigor = L("n por grupo ≈ 2 · σ² · [ Z(erro) + Z(confiança) ]² / diferença²",
                          "n per group ≈ 2 · σ² · [ Z(error) + Z(confidence) ]² / difference²")
    st.markdown(L(
        f"Nas três linhas, a diferença mínima que eu quero enxergar e a chance de perceber se "
        f"funcionar não mudam (Z(confiança) fica sempre ≈ {z_confianca:.2f}) — a única coisa que "
        f"muda é o quanto eu aceito me enganar (alfa). E é só o alfa que entra no **Z(erro)** desta "
        f"fórmula:",
        f"In all three rows, the minimum difference I want to see and the chance of noticing if it "
        f"works don't change (Z(confidence) always stays ≈ {z_confianca:.2f}) — the only thing that "
        f"changes is how much I accept being wrong (alpha). And alpha only enters the **Z(error)** "
        f"of this formula:"
    ))
    st.code(formula_rigor, language=None)
    st.markdown(L(
        "Quanto **menor** o alfa (mais rigoroso, mais difícil de errar), **maior** o Z(erro) — e "
        "maior o n. Depois eu transformo n em dias: *total de gente (somando os grupos) ÷ pessoas "
        "novas por dia*, arredondado pra cima até fechar uma semana cheia (o comportamento muda de "
        "segunda a domingo, então corto sempre no fim de uma semana, nunca no meio).",
        "The **lower** the alpha (stricter, harder to be wrong), the **higher** Z(error) — and "
        "the larger n. Then I turn n into days: *total people (adding up the groups) ÷ new people "
        "per day*, rounded up to a full week (behavior changes from Monday to Sunday, so I always "
        "cut at the end of a week, never in the middle)."
    ))
    st.table(
        [
            {
                L("Chance de erro", "Chance of error"): f"{c['alfa_pct']}%" + (_atual if c["atual"] else ""),
                L("Z(erro)", "Z(error)"): f"{z_two_sided(c['alfa_efetivo']):.2f}",
                L("Gente por grupo", "People per group"): milhar(c['n_por_braco']),
                L("Dá pra juntar em", "Can be gathered in"): f"{c['dias_fechar']} {L('dia(s)', 'day(s)')}",
                L("Rodar por", "Run for"): f"{c['dias']} {L('dia(s)', 'day(s)')}",
            }
            for c in plano.comparativo_alfa
        ]
    )
    for anterior, atual in zip(plano.comparativo_alfa, plano.comparativo_alfa[1:]):
        if atual["dias"] == anterior["dias"] and atual["n_por_braco"] != anterior["n_por_braco"]:
            st.markdown(L(
                f"Repare que {anterior['alfa_pct']}% e {atual['alfa_pct']}% de erro deram o mesmo "
                f"prazo ({atual['dias']} dias), mesmo pedindo quantidades de gente diferentes por "
                f"grupo — as duas amostras cabem dentro da mesma semana cheia de tráfego, então o "
                f"prazo não muda.",
                f"Notice that {anterior['alfa_pct']}% and {atual['alfa_pct']}% error gave the same "
                f"duration ({atual['dias']} days), even asking for different numbers of people per "
                f"group — both samples fit within the same full week of traffic, so the duration "
                f"doesn't change."
            ))
        elif atual["dias"] < anterior["dias"]:
            st.markdown(L(
                f"De {anterior['alfa_pct']}% para {atual['alfa_pct']}% de erro, o prazo caiu de "
                f"{anterior['dias']} para {atual['dias']} dias — a amostra ficou pequena o bastante "
                f"pra fechar uma semana inteira a menos.",
                f"From {anterior['alfa_pct']}% to {atual['alfa_pct']}% error, the duration dropped from "
                f"{anterior['dias']} to {atual['dias']} days — the sample got small enough to finish "
                f"one full week sooner."
            ))

# --------------------------------------------------------------------------
# Guardrails
# --------------------------------------------------------------------------

st.subheader(L("O que não pode piorar", "What must not get worse"))
if plano.guardrails:
    for g in plano.guardrails:
        st.write(f"- {g.texto()}")
else:
    st.caption(L("Nenhum guardrail definido.", "No guardrail defined."))

# --------------------------------------------------------------------------
# Relatório completo / exportação
# --------------------------------------------------------------------------

st.subheader(L("Resumo pra compartilhar", "Summary to share"))
resumo_html = build_html_summary(plano)

col_dl, col_save = st.columns(2)
with col_dl:
    st.download_button(
        L("🖨️ Baixar resumo bonito (.html — abra e use Imprimir > Salvar como PDF)",
          "🖨️ Download a nice summary (.html — open it and use Print > Save as PDF)"),
        resumo_html, file_name=f"resumo_teste_ab_{id_teste}.html", mime="text/html",
        width="stretch",
    )
with col_save:
    if st.button(L("💾 Salvar este teste no histórico", "💾 Save this test to the history"), width="stretch"):
        historico = [h for h in _carregar_historico() if h.get("id") != id_teste]
        historico.insert(0, {
            "id": id_teste,
            "nome": nome_teste,
            "salvo_em": datetime.now().strftime(L("%d/%m/%Y %H:%M", "%m/%d/%Y %H:%M")),
            "n_por_braco": plano.n_por_braco,
            "n_total": plano.n_total,
            "dias_rodar": plano.dias_rodar,
            "resumo_html": resumo_html,
        })
        _salvar_historico(historico)
        st.success(L(f"Teste \"{nome_teste}\" salvo no histórico (ID {id_teste}).",
                     f"Test \"{nome_teste}\" saved to the history (ID {id_teste})."))

st.markdown("---")
components.html(resumo_html, height=1300, scrolling=True)
