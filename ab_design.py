"""
ab_design.py
============

Ferramenta de dimensionamento de teste A/B -- DaVinci v2.

Escopo:
  - duas familias de metrica:
      * "proporcao" -- metrica binaria por pessoa (converteu ou nao,
        cancelou ou nao). z-test de duas proporcoes, variancia pooled
        sob H0 e variancias separadas sob H1.
      * "media" -- metrica continua (duracao, quantidade, valor em R$...).
        z-test de duas medias assumindo variancia igual nos dois grupos
        (o usuario informa o desvio padrao hoje). Formula fechada, sem
        precisar de busca binaria pro calculo inverso.
  - direcao do objetivo: "subir" (ex.: conversao) ou "cair" (ex.: churn,
    tempo de carregamento) -- o sinal da diferenca muda, o resto da conta
    nao.
  - duracao arredondada para multiplo de 7 dias, com minimo de uma semana;
  - calculo inverso (dado um prazo, qual o menor efeito detectavel);
  - correcao de Bonferroni automatica quando ha mais de dois bracos;
  - correcao de populacao finita quando a amostra e fatia relevante do
    universo (> 5%);
  - relatorio em linguagem de produto, com alertas e comparativo de
    custo entre niveis de rigor (alfa).

Fora de escopo por decisao: acompanhamento de teste ja em andamento e
diagnostico pos-coleta (SRM, crossover, novelty, etc.) -- essa ferramenta
cuida so do desenho/dimensionamento do teste, nao da medicao depois que
ele ja esta rodando. Tambem fora de escopo, para versoes seguintes: teste
sequencial e peeking, CUPED, metricas de razao via delta method.

Depende apenas da biblioteca padrao do Python (math, dataclasses).
"""

from __future__ import annotations

import math
import threading
from dataclasses import dataclass, field


# ---------------------------------------------------------------------------
# Lingua dos textos (alertas, guardrails, relatorios)
# ---------------------------------------------------------------------------
# Portugues por padrao. O app chama definir_idioma("en") no comeco de cada
# execucao; a lingua fica por thread, entao duas pessoas usando o app ao
# mesmo tempo em linguas diferentes nao se atrapalham. As contas nao mudam.

_LINGUA = threading.local()


def definir_idioma(idioma: str) -> None:
    _LINGUA.valor = "en" if str(idioma).lower().startswith("en") else "pt"


def idioma() -> str:
    return getattr(_LINGUA, "valor", "pt")


def _L(pt: str, en: str) -> str:
    """A frase na lingua ativa."""
    return en if idioma() == "en" else pt


# ---------------------------------------------------------------------------
# 0. Normal inversa / CDF (sem scipy) -- aproximacao de Peter Acklam
# ---------------------------------------------------------------------------

def norm_pdf(x: float) -> float:
    """Densidade da normal padrao -- usada so pra desenhar a curva (ilustrativo)."""
    return math.exp(-0.5 * x * x) / math.sqrt(2 * math.pi)


def norm_cdf(x: float) -> float:
    """CDF da normal padrao, via erf (biblioteca padrao)."""
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def norm_ppf(p: float) -> float:
    """
    Inversa da CDF da normal padrao (funcao quantil).
    Aproximacao racional de Peter Acklam - erro absoluto < 1.15e-9.
    """
    if not (0.0 < p < 1.0):
        raise ValueError("p precisa estar em (0, 1)")

    # Coeficientes do algoritmo de Acklam
    a = [-3.969683028665376e+01, 2.209460984245205e+02,
         -2.759285104469687e+02, 1.383577518672690e+02,
         -3.066479806614716e+01, 2.506628277459239e+00]
    b = [-5.447609879822406e+01, 1.615858368580409e+02,
         -1.556989798598866e+02, 6.680131188771972e+01,
         -1.328068155288572e+01]
    c = [-7.784894002430293e-03, -3.223964580411365e-01,
         -2.400758277161838e+00, -2.549732539343734e+00,
         4.374664141464968e+00, 2.938163982698783e+00]
    d = [7.784695709041462e-03, 3.224671290700398e-01,
         2.445134137142996e+00, 3.754408661907416e+00]

    p_low = 0.02425
    p_high = 1 - p_low

    if p < p_low:
        q = math.sqrt(-2 * math.log(p))
        return (((((c[0]*q+c[1])*q+c[2])*q+c[3])*q+c[4])*q+c[5]) / \
               ((((d[0]*q+d[1])*q+d[2])*q+d[3])*q+1)
    elif p <= p_high:
        q = p - 0.5
        r = q * q
        return (((((a[0]*r+a[1])*r+a[2])*r+a[3])*r+a[4])*r+a[5])*q / \
               (((((b[0]*r+b[1])*r+b[2])*r+b[3])*r+b[4])*r+1)
    else:
        q = math.sqrt(-2 * math.log(1 - p))
        return -(((((c[0]*q+c[1])*q+c[2])*q+c[3])*q+c[4])*q+c[5]) / \
                ((((d[0]*q+d[1])*q+d[2])*q+d[3])*q+1)


def z_two_sided(alpha: float) -> float:
    """z critico para teste bicaudal com nivel de significancia alpha."""
    return norm_ppf(1 - alpha / 2)


def z_power(power: float) -> float:
    """z critico associado ao poder desejado (1 - beta)."""
    return norm_ppf(power)


# ---------------------------------------------------------------------------
# 1a. Tamanho de amostra -- metrica de PROPORCAO (z-test de duas proporcoes)
# ---------------------------------------------------------------------------

def sample_size_two_proportions(p1: float, p2: float, alpha: float,
                                 power: float) -> int:
    """
    n por braco para detectar a diferenca (p2 - p1), bicaudal.
    Variancia pooled sob H0 (o termo de alfa) e variancias separadas
    sob H1 (o termo de poder) -- formula classica de dimensionamento.
    """
    if p1 <= 0 or p1 >= 1 or p2 <= 0 or p2 >= 1:
        raise ValueError("p1 e p2 precisam estar em (0, 1)")
    if p1 == p2:
        raise ValueError("a diferenca minima nao pode ser zero")

    delta = abs(p2 - p1)
    p_bar = (p1 + p2) / 2

    z_a = z_two_sided(alpha)
    z_b = z_power(power)

    term_h0 = z_a * math.sqrt(2 * p_bar * (1 - p_bar))
    term_h1 = z_b * math.sqrt(p1 * (1 - p1) + p2 * (1 - p2))

    n = ((term_h0 + term_h1) ** 2) / (delta ** 2)
    return math.ceil(n)


def min_detectable_effect_proporcao(n_per_arm: int, p1: float, alpha: float,
                                     power: float, sinal: float = 1.0,
                                     tol: float = 1e-6) -> float:
    """
    Inverso de sample_size_two_proportions: dado n por braco, qual o
    menor efeito absoluto detectavel? Busca binaria (a formula fechada
    exige resolver uma equacao nao-linear em delta, pois p_bar e a
    variancia sob H1 dependem do proprio delta).

    `sinal` = +1 procura p2 > p1 (metrica que deve SUBIR); -1 procura
    p2 < p1 (metrica que deve CAIR). Como p_bar e p2(1-p2) nao sao
    simetricos em torno de p1 (a nao ser que p1 = 50%), o efeito minimo
    detectavel pode ser levemente diferente pra cada lado.
    """
    if n_per_arm <= 0:
        raise ValueError("n_per_arm precisa ser positivo")

    teto = (1 - p1) if sinal > 0 else p1
    lo, hi = 1e-6, teto - 1e-6
    if hi <= lo:
        hi = 1e-3

    def p2_de(mid):
        return min(max(p1 + sinal * mid, 1e-6), 1 - 1e-6)

    while sample_size_two_proportions(p1, p2_de(hi), alpha, power) > n_per_arm:
        hi *= 1.5
        if hi > teto:
            hi = teto - 1e-9
            break

    for _ in range(200):
        mid = (lo + hi) / 2
        n_needed = sample_size_two_proportions(p1, p2_de(mid), alpha, power)
        if n_needed > n_per_arm:
            lo = mid
        else:
            hi = mid
        if hi - lo < tol:
            break

    return hi


# kept as an alias -- nome antigo usado em versoes anteriores do app
min_detectable_effect = min_detectable_effect_proporcao


# ---------------------------------------------------------------------------
# 1b. Tamanho de amostra -- metrica de MEDIA (duracao, quantidade, R$...)
# ---------------------------------------------------------------------------

def sample_size_two_means(sigma: float, delta: float, alpha: float, power: float) -> int:
    """
    n por braco para detectar uma diferenca `delta` entre as medias de
    dois grupos, assumindo o MESMO desvio padrao `sigma` nos dois
    (simplificacao razoavel quando a mudanca testada nao deveria alterar
    muito a dispersao dos dados -- so a media). Formula fechada, sem
    depender do proprio delta como no caso de proporcoes.
    """
    if sigma <= 0:
        raise ValueError("o desvio padrao precisa ser maior que zero")
    if delta == 0:
        raise ValueError("a diferenca minima nao pode ser zero")

    z_a = z_two_sided(alpha)
    z_b = z_power(power)

    n = 2 * (sigma ** 2) * ((z_a + z_b) ** 2) / (delta ** 2)
    return math.ceil(n)


def min_detectable_effect_media(n_per_arm: int, sigma: float, alpha: float, power: float) -> float:
    """Inverso fechado de sample_size_two_means: menor delta detectavel dado n."""
    if n_per_arm <= 0:
        raise ValueError("n_per_arm precisa ser positivo")
    if sigma <= 0:
        raise ValueError("o desvio padrao precisa ser maior que zero")

    z_a = z_two_sided(alpha)
    z_b = z_power(power)
    return (z_a + z_b) * sigma * math.sqrt(2 / n_per_arm)


# ---------------------------------------------------------------------------
# 2. Correcoes -- Bonferroni e populacao finita
# ---------------------------------------------------------------------------

def bonferroni_alpha(alpha: float, num_variantes: int) -> float:
    """
    Alfa efetivo por comparacao quando ha mais de 2 bracos (1 controle +
    N-1 variantes testadas contra o controle).
    """
    num_comparacoes = max(1, num_variantes - 1)
    return alpha / num_comparacoes


def finite_population_correction(n: int, populacao: int | None, variantes: int = 2) -> tuple[int, bool]:
    """
    Aplica correcao de populacao finita quando a amostra requerida
    (n * numero de grupos) passa de ~5% da populacao total.
    Retorna (n_ajustado, foi_aplicada).
    """
    if not populacao or populacao <= 0:
        return n, False

    amostra_total = n * variantes
    if amostra_total / populacao <= 0.05:
        return n, False

    n_ajustado = math.ceil(n / (1 + (n - 1) / populacao))
    return n_ajustado, True


# ---------------------------------------------------------------------------
# 3. Duracao
# ---------------------------------------------------------------------------

def duracao_em_dias(amostra_total: int, trafego_dia: float) -> tuple[int, int]:
    """
    Retorna (dias_para_fechar_amostra, dias_para_rodar).
    dias_para_rodar e arredondado para o proximo multiplo de 7,
    com minimo de 7 dias (uma semana completa).
    """
    if trafego_dia <= 0:
        raise ValueError("trafego_dia precisa ser positivo")

    dias_fechar = math.ceil(amostra_total / trafego_dia)
    dias_rodar = max(7, math.ceil(dias_fechar / 7) * 7)
    return dias_fechar, dias_rodar


# ---------------------------------------------------------------------------
# 4. Guardrails
# ---------------------------------------------------------------------------

@dataclass
class Guardrail:
    nome: str
    direcao: str  # "nao_pode_subir" ou "nao_pode_cair"
    valor_atual: str = ""  # o quanto esta hoje (texto livre: "R$ 45", "3 min", "12%"...)

    def texto(self) -> str:
        if self.direcao == "nao_pode_subir":
            rotulo = _L("nao pode subir", "must not go up")
        else:
            rotulo = _L("nao pode cair", "must not go down")
        valor = f" ({_L('hoje', 'today')}: {self.valor_atual})" if self.valor_atual.strip() else ""
        return f"{self.nome}{valor} {rotulo}"


DEFAULT_GUARDRAILS = [
    Guardrail("custo por cliente", "nao_pode_subir"),
    Guardrail("tempo medio de cadastro", "nao_pode_subir"),
]


# ---------------------------------------------------------------------------
# 5. Plano completo (o que a UI consome)
# ---------------------------------------------------------------------------

@dataclass
class Alerta:
    nivel: str  # "erro" | "aviso" | "info"
    texto: str


@dataclass
class PlanoTeste:
    tipo_metrica: str          # "proporcao" | "media"
    direcao: str                # "subir" | "cair"
    unidade_metrica: str        # "%" para proporcao; texto livre para media
    baseline: float              # proporcao: fracao 0-1 | media: valor bruto
    sigma: float | None          # so pra "media"
    delta: float                 # diferenca COM SINAL (negativa se direcao="cair")
    lift_relativo: float         # delta / baseline, com sinal
    alvo: float                  # baseline + delta
    alfa: float
    poder: float
    trafego_dia: float
    variantes: int
    populacao: int | None
    janela_tem_sazonalidade: bool
    guardrails: list

    n_por_braco: int
    n_total: int
    grupos: list
    dias_fechar: int
    dias_rodar: int
    fpc_aplicada: bool
    alfa_efetivo: float
    bonferroni_aplicada: bool
    mde_realizado_no_prazo: float | None

    # cadastro do teste -- so metadados textuais, nao entram em nenhuma conta;
    # existem pra ficar registrados no relatorio final e servir de handoff pra
    # quem for medir o resultado depois (BU, metrica, experimento etc. batem
    # com os filtros de segmentacao que a ferramenta de mensuracao usa).
    id_teste: str = ""
    nome: str = ""
    area: str = ""
    objetivo: str = ""
    bu: str = ""
    metrica_nome: str = ""
    experimento: str = ""
    regiao: str = ""
    campanha: str = ""
    plataforma: str = ""
    dispositivo: str = ""

    alertas: list = field(default_factory=list)
    comparativo_alfa: list = field(default_factory=list)


def _n_para_delta(tipo_metrica: str, baseline: float, sigma: float | None,
                   delta: float, alfa: float, poder: float) -> int:
    """
    Tamanho de amostra por braco, despachando pro tipo de metrica certo.
    `delta` e COM SINAL (positivo se a metrica deve subir, negativo se
    deve cair) -- pra proporcao isso importa de verdade, porque p_bar e
    a variancia sob H1 nao sao simetricas em torno de p1.
    """
    if tipo_metrica == "proporcao":
        p1 = baseline
        p2 = p1 + delta
        return sample_size_two_proportions(p1, p2, alfa, poder)
    elif tipo_metrica == "media":
        return sample_size_two_means(sigma, delta, alfa, poder)
    raise ValueError(f"tipo_metrica desconhecido: {tipo_metrica!r}")


def montar_plano(tipo_metrica: str, direcao: str, baseline_valor: float,
                  sigma: float | None, unidade_metrica: str,
                  mde_valor: float, mde_tipo: str,
                  alfa_pct: float, poder_pct: float, trafego_dia: float,
                  variantes: int, populacao: int | None,
                  janela_tem_sazonalidade: bool,
                  guardrails: list,
                  id_teste: str = "",
                  nome: str = "", area: str = "", objetivo: str = "",
                  bu: str = "", metrica_nome: str = "", experimento: str = "",
                  regiao: str = "", campanha: str = "", plataforma: str = "",
                  dispositivo: str = "") -> PlanoTeste:
    """
    tipo_metrica: "proporcao" (ex.: taxa de conversao, churn, em %) ou
                  "media" (ex.: duracao, quantidade, R$ -- precisa de `sigma`)
    direcao: "subir" (ex.: conversao) ou "cair" (ex.: churn, tempo)
    mde_tipo: "relativo" (% sobre o baseline) ou "absoluto" (unidade da propria metrica)

    nome..dispositivo: cadastro do teste -- texto livre, nao entra em nenhuma
    conta, so fica registrado no plano pra aparecer no relatorio final e
    servir de handoff pra quem for medir o resultado depois.
    """
    if tipo_metrica not in ("proporcao", "media"):
        raise ValueError("tipo_metrica precisa ser 'proporcao' ou 'media'")
    if direcao not in ("subir", "cair"):
        raise ValueError("direcao precisa ser 'subir' ou 'cair'")

    sinal = 1.0 if direcao == "subir" else -1.0

    if tipo_metrica == "proporcao":
        baseline = baseline_valor / 100
        if not (0 < baseline < 1):
            raise ValueError("o valor de hoje precisa ficar entre 0% e 100%")
        mde_abs_magnitude = baseline * (mde_valor / 100) if mde_tipo == "relativo" else mde_valor / 100
        unidade = "%"
    else:
        baseline = baseline_valor
        if not (baseline > 0):
            raise ValueError("o valor medio hoje precisa ser maior que zero")
        if sigma is None or sigma <= 0:
            raise ValueError("informe um desvio padrao maior que zero pra metrica de media")
        mde_abs_magnitude = abs(baseline) * (mde_valor / 100) if mde_tipo == "relativo" else mde_valor
        unidade = unidade_metrica or "unidades"

    if mde_abs_magnitude <= 0:
        raise ValueError("a diferenca minima que vale a pena precisa ser maior que zero")

    delta = sinal * mde_abs_magnitude
    alvo = baseline + delta

    if tipo_metrica == "proporcao" and not (0 < alvo < 1):
        raise ValueError("o valor de hoje + a diferenca minima precisa ficar entre 0% e 100%")

    alfa = alfa_pct / 100
    poder = poder_pct / 100

    bonferroni_aplicada = variantes > 2
    alfa_efetivo = bonferroni_alpha(alfa, variantes) if bonferroni_aplicada else alfa

    n = _n_para_delta(tipo_metrica, baseline, sigma, delta, alfa_efetivo, poder)
    n_fpc, fpc_aplicada = finite_population_correction(n, populacao, variantes)
    n_final = n_fpc

    n_total = n_final * variantes
    dias_fechar, dias_rodar = duracao_em_dias(n_total, trafego_dia)

    grupos = []
    for idx in range(variantes):
        letra = chr(ord("A") + idx)
        if idx == 0:
            papel = _L("controle", "control")
        else:
            papel = _L("variante", "variant") if variantes == 2 else f"{_L('variante', 'variant')} {idx}"
        grupos.append({"letra": letra, "papel": papel, "n": n_final})

    trafego_no_prazo = trafego_dia * dias_rodar
    n_por_braco_no_prazo = math.floor(trafego_no_prazo / variantes)
    mde_realizado = None
    if n_por_braco_no_prazo > 0:
        try:
            if tipo_metrica == "proporcao":
                mde_realizado = min_detectable_effect_proporcao(
                    n_por_braco_no_prazo, baseline, alfa_efetivo, poder, sinal=sinal)
            else:
                mde_realizado = min_detectable_effect_media(n_por_braco_no_prazo, sigma, alfa_efetivo, poder)
        except Exception:
            mde_realizado = None

    comparativo_alfa = []
    for alfa_ref_pct in (1, 5, 10):
        alfa_ref = alfa_ref_pct / 100
        alfa_ref_efetivo = bonferroni_alpha(alfa_ref, variantes) if bonferroni_aplicada else alfa_ref
        n_ref = _n_para_delta(tipo_metrica, baseline, sigma, delta, alfa_ref_efetivo, poder)
        n_ref_fpc, _ = finite_population_correction(n_ref, populacao, variantes)
        dias_fechar_ref, dias_ref = duracao_em_dias(n_ref_fpc * variantes, trafego_dia)
        comparativo_alfa.append({
            "alfa_pct": alfa_ref_pct,
            "alfa_efetivo": alfa_ref_efetivo,
            "n_por_braco": n_ref_fpc,
            "dias_fechar": dias_fechar_ref,
            "dias": dias_ref,
            "atual": alfa_ref_pct == alfa_pct,
        })

    # --------------------- alertas ---------------------
    alertas = []

    if dias_rodar < 7:
        alertas.append(Alerta("erro", _L(
            "Duracao abaixo de 7 dias -- nao cobre um ciclo semanal completo.",
            "Duration under 7 days -- it doesn't cover a full weekly cycle.")))

    if dias_rodar > 42:
        alertas.append(Alerta(
            "erro",
            _L(f"Duracao de {dias_rodar} dias (> 6 semanas) -- risco de cookie churn e contaminacao. "
               "Considere aumentar a diferenca minima aceita, o trafego ou afrouxar poder/alfa.",
               f"Duration of {dias_rodar} days (> 6 weeks) -- risk of cookie churn and contamination. "
               "Consider raising the minimum accepted difference, the traffic, or loosening power/alpha.")
        ))
    elif dias_rodar > 28:
        alertas.append(Alerta(
            "aviso",
            _L(f"Duracao de {dias_rodar} dias (4-6 semanas) -- ainda aceitavel, mas fique de olho em cookie churn.",
               f"Duration of {dias_rodar} days (4-6 weeks) -- still acceptable, but keep an eye on cookie churn.")
        ))

    if janela_tem_sazonalidade:
        alertas.append(Alerta(
            "aviso",
            _L("A janela do teste foi marcada como sobrepondo feriado ou pico sazonal -- "
               "considere deslocar o periodo ou tratar o efeito de sazonalidade na analise.",
               "The test window was flagged as overlapping a holiday or seasonal peak -- "
               "consider shifting the period or handling the seasonality effect in the analysis.")
        ))

    if dias_rodar > 56:
        alertas.append(Alerta(
            "erro",
            _L("A diferenca minima pedida e otimista demais para o trafego disponivel -- no ritmo atual "
               "o teste passaria de 8 semanas. Revise a diferenca minima, alfa, poder ou trafego.",
               "The minimum difference requested is too optimistic for the available traffic -- at the current "
               "pace the test would go past 8 weeks. Review the minimum difference, alpha, power or traffic.")
        ))

    if bonferroni_aplicada:
        alertas.append(Alerta(
            "info",
            _L(f"{variantes} variantes -- correcao de Bonferroni aplicada automaticamente "
               f"(alfa efetivo por comparacao: {alfa_efetivo*100:.2f}%, em vez de {alfa*100:.2f}%).",
               f"{variantes} variants -- Bonferroni correction applied automatically "
               f"(effective alpha per comparison: {alfa_efetivo*100:.2f}%, instead of {alfa*100:.2f}%).")
        ))

    if fpc_aplicada:
        alertas.append(Alerta(
            "info",
            _L(f"A amostra requerida passa de 5% da populacao informada -- correcao de populacao "
               f"finita aplicada (n ajustado de {n} para {n_final} por braco).",
               f"The required sample exceeds 5% of the population entered -- finite population "
               f"correction applied (n adjusted from {n} to {n_final} per arm).")
        ))

    if not alertas:
        alertas.append(Alerta("ok", _L("Nenhum alerta -- desenho dentro dos parametros esperados.",
                                       "No alerts -- design within the expected parameters.")))

    lift_relativo = (delta / baseline) if baseline != 0 else 0.0

    return PlanoTeste(
        tipo_metrica=tipo_metrica, direcao=direcao, unidade_metrica=unidade,
        baseline=baseline, sigma=sigma, delta=delta, lift_relativo=lift_relativo, alvo=alvo,
        alfa=alfa, poder=poder,
        trafego_dia=trafego_dia, variantes=variantes, populacao=populacao,
        janela_tem_sazonalidade=janela_tem_sazonalidade, guardrails=guardrails,
        n_por_braco=n_final, n_total=n_total, grupos=grupos, dias_fechar=dias_fechar,
        dias_rodar=dias_rodar, fpc_aplicada=fpc_aplicada, alfa_efetivo=alfa_efetivo,
        bonferroni_aplicada=bonferroni_aplicada, mde_realizado_no_prazo=mde_realizado,
        id_teste=id_teste, nome=nome, area=area, objetivo=objetivo,
        bu=bu, metrica_nome=metrica_nome, experimento=experimento,
        regiao=regiao, campanha=campanha, plataforma=plataforma, dispositivo=dispositivo,
        alertas=alertas, comparativo_alfa=comparativo_alfa,
    )


# ---------------------------------------------------------------------------
# 6. Relatorio em texto (linguagem de produto)
# ---------------------------------------------------------------------------

def _fmt_pct(x: float, casas: int = 2) -> str:
    return f"{x*100:.{casas}f}%"


def _fmt_int(n: int) -> str:
    """Inteiro com separador de milhar: ponto em portugues, virgula em ingles."""
    s = f"{n:,}"
    return s if idioma() == "en" else s.replace(",", ".")


def _fmt_metrica(plano: PlanoTeste, valor: float, casas: int = 2) -> str:
    if plano.tipo_metrica == "proporcao":
        return _fmt_pct(valor, casas)
    s = f"{valor:,.{casas}f} {plano.unidade_metrica}"
    if idioma() == "en":
        return s
    return s.replace(",", "X").replace(".", ",").replace("X", ".")


_CADASTRO_CAMPOS = [
    ("id_teste", "ID do teste", "Test ID"),
    ("nome", "Nome do teste", "Test name"),
    ("area", "Área responsável", "Owning team"),
    ("objetivo", "Objetivo", "Goal"),
    ("bu", "BU", "BU"),
    ("metrica_nome", "Métrica", "Metric"),
    ("experimento", "Experimento", "Experiment"),
    ("regiao", "Região", "Region"),
    ("campanha", "Campanha", "Campaign"),
    ("plataforma", "Plataforma", "Platform"),
    ("dispositivo", "Dispositivo", "Device"),
]


def _cadastro_preenchido(plano: PlanoTeste) -> list[tuple[str, str]]:
    """Campos de cadastro do teste que foram preenchidos (rotulo, valor)."""
    return [(_L(pt, en), getattr(plano, campo)) for campo, pt, en in _CADASTRO_CAMPOS
            if getattr(plano, campo, "").strip()]


def build_report(plano: PlanoTeste) -> str:
    L = _L
    prop = plano.tipo_metrica == "proporcao"
    linhas = []
    linhas.append("=" * 66)
    linhas.append(L("DESENHO DO TESTE A/B", "A/B TEST DESIGN"))
    linhas.append("=" * 66)
    linhas.append("")

    cadastro = _cadastro_preenchido(plano)
    if cadastro:
        linhas.append(L("CADASTRO DO TESTE", "TEST REGISTRATION"))
        for rotulo, valor in cadastro:
            linhas.append(f"  {rotulo + ' ':.<36} {valor}")
        linhas.append("")

    sobe = plano.direcao == "subir"
    verbo = L("subir", "go up") if sobe else L("cair", "go down")
    linhas.append(L("O QUE ESTAMOS TESTANDO", "WHAT WE ARE TESTING"))
    linhas.append(f"  {L('Como estamos hoje ................. ', 'Where we are today ................ ')}"
                   f"{_fmt_metrica(plano, plano.baseline)}")
    sinal = "+" if plano.delta >= 0 else "-"
    efeito = "lift" if sobe else L("reducao", "reduction")
    linhas.append(f"  {L(f'Queremos que {verbo} para .............. ', f'We want it to {verbo} to ............. ')}"
                   f"{_fmt_metrica(plano, plano.alvo)} "
                   f"({sinal}{abs(plano.delta)*100 if prop else abs(plano.delta):.2f} "
                   f"{'p.p.' if prop else plano.unidade_metrica}, "
                   f"{sinal}{abs(plano.lift_relativo)*100:.1f}% {L('de', 'of')} {efeito})")
    linhas.append(f"  {L('Grupos ............................. ', 'Groups ............................. ')}"
                   f"{plano.variantes} {L('(divisao igual entre eles)', '(split equally)')}")
    linhas.append("")
    linhas.append(L("RISCOS QUE ESTAMOS ACEITANDO", "RISKS WE ARE ACCEPTING"))
    linhas.append(f"  {L('Chance de achar que funcionou sem funcionar ..... ', 'Chance of thinking it worked when it did not .... ')}"
                   f"{_fmt_pct(plano.alfa_efetivo, 1)}"
                   + (f"  ({L('nominal', 'nominal')} {_fmt_pct(plano.alfa, 1)}, {L('com', 'with')} Bonferroni)"
                      if plano.bonferroni_aplicada else ""))
    linhas.append(f"  {L('Chance de perceber, se funcionar ................ ', 'Chance of noticing, if it works ................. ')}"
                   f"{_fmt_pct(plano.poder, 0)}")
    linhas.append("")
    linhas.append(L("AMOSTRA E PRAZO", "SAMPLE AND DURATION"))
    linhas.append(L("  Cada grupo (braco) e uma versao sendo testada, nao uma etapa da jornada:",
                    "  Each group (arm) is a version being tested, not a step in the journey:"))
    for g in plano.grupos:
        rotulo = f"{L('Grupo', 'Group')} {g['letra']} ({g['papel']})"
        linhas.append(f"    {rotulo:<28} {_fmt_int(g['n'])} {L('pessoas', 'people')}")
    linhas.append(f"  {L('Total do experimento (todos os grupos) .... ', 'Experiment total (all groups) ............. ')}"
                   f"{_fmt_int(plano.n_total)}")
    linhas.append(f"  {L('Amostra fecha em .................... ', 'Sample fills in ..................... ')}"
                   f"{plano.dias_fechar} {L('dias', 'days')}")
    semanas = plano.dias_rodar // 7
    linhas.append(f"  {L('Rodar por ........................... ', 'Run for ............................. ')}"
                   f"{plano.dias_rodar} {L('dias', 'days')} "
                   f"({semanas} {L('semana(s) completa(s)', 'full week(s)')})")
    if plano.mde_realizado_no_prazo is not None:
        valor = plano.mde_realizado_no_prazo * 100 if prop else plano.mde_realizado_no_prazo
        unid = L('% (pontos absolutos)', '% (absolute points)') if prop else ' ' + plano.unidade_metrica
        linhas.append(L(f"  Se rodar so {plano.dias_rodar} dias, a menor diferenca que da pra ver e de ",
                        f"  If it runs only {plano.dias_rodar} days, the smallest visible difference is ")
                      + f"{valor:.2f}{unid}")
    linhas.append("")
    linhas.append(L("CUSTO DO NIVEL DE RIGOR", "COST OF THE RIGOR LEVEL"))
    for c in plano.comparativo_alfa:
        marcador = L("  <- atual", "  <- current") if c["atual"] else ""
        linhas.append(f"  {L('erro', 'error')} {c['alfa_pct']:>2}%: {_fmt_int(c['n_por_braco'])} "
                       f"{L('por grupo', 'per group')}, ~{c['dias']} {L('dias', 'days')}{marcador}")
    linhas.append("")

    if plano.guardrails:
        linhas.append(L("O QUE NAO PODE PIORAR", "WHAT MUST NOT GET WORSE"))
        for g in plano.guardrails:
            linhas.append(f"  - {g.texto()}")
        linhas.append("")

    linhas.append("=" * 66)

    return "\n".join(linhas)


def build_html_summary(plano: PlanoTeste) -> str:
    """
    Resumo em HTML autocontido, com uma cara mais amigavel (tipo um PDF).
    Abra o arquivo no navegador e use "Imprimir > Salvar como PDF" para exportar.

    Nome, area e objetivo, junto com o restante do cadastro do teste (BU,
    metrica, experimento, regiao, campanha, plataforma, dispositivo), vem do
    proprio `plano` -- foram preenchidos na hora de montar o plano.

    Sai na lingua ativa (definir_idioma).
    """
    import html as _html
    from datetime import datetime

    L = _L
    en = idioma() == "en"
    esc = _html.escape
    _meses_pt = ["janeiro", "fevereiro", "março", "abril", "maio", "junho",
                 "julho", "agosto", "setembro", "outubro", "novembro", "dezembro"]
    _meses_en = ["January", "February", "March", "April", "May", "June",
                 "July", "August", "September", "October", "November", "December"]
    _agora = datetime.now()
    if en:
        hoje = f"{_meses_en[_agora.month - 1]} {_agora.day}, {_agora.year}"
    else:
        hoje = f"{_agora.day:02d} de {_meses_pt[_agora.month - 1]} de {_agora.year}"
    semanas = plano.dias_rodar // 7
    palavra_efeito = "Lift" if plano.direcao == "subir" else L("Redução", "Reduction")
    nome, area, objetivo = plano.nome, plano.area, plano.objetivo
    prop = plano.tipo_metrica == "proporcao"

    grupos_html = "".join(
        f'<div class="m"><div class="l">{L("Grupo", "Group")} {g["letra"]} · {esc(g["papel"])}</div>'
        f'<div class="v">{_fmt_int(g["n"])} {L("pessoas", "people")}</div></div>'
        for g in plano.grupos
    )
    guardrails_html = "".join(
        f'<span class="chip">{esc(g.nome)}'
        f'{" (" + L("hoje", "today") + ": " + esc(g.valor_atual) + ")" if g.valor_atual.strip() else ""} '
        f'{L("não sobe", "must not go up") if g.direcao == "nao_pode_subir" else L("não cai", "must not go down")}</span>'
        for g in plano.guardrails
    ) or f'<span class="muted">{L("nenhum definido", "none defined")}</span>'

    contexto_campos = [
        ("BU", plano.bu), (L("Métrica", "Metric"), plano.metrica_nome),
        (L("Experimento", "Experiment"), plano.experimento),
        (L("Região", "Region"), plano.regiao), (L("Campanha", "Campaign"), plano.campanha),
        (L("Plataforma", "Platform"), plano.plataforma), (L("Dispositivo", "Device"), plano.dispositivo),
    ]
    contexto_html = "".join(
        f'<span class="chip">{esc(rotulo)}: {esc(valor)}</span>' for rotulo, valor in contexto_campos if valor.strip()
    )
    titulo_padrao = L("Desenho de teste A/B", "A/B test design")
    diferenca = abs(plano.delta) * 100 if prop else abs(plano.delta)
    diferenca_txt = f"{'+' if plano.delta >= 0 else '-'}{diferenca:.2f}{'p.p.' if prop else ' ' + plano.unidade_metrica}"
    verbo = L("subir", "go up") if plano.direcao == "subir" else L("cair", "go down")

    return f"""<!doctype html>
<html lang="{'en' if en else 'pt-BR'}"><head><meta charset="utf-8">
<title>{esc(nome) or titulo_padrao} — DaVinci</title>
<style>
  body {{ font-family: -apple-system, "Segoe UI", Arial, sans-serif; background:#F6F9FD; color:#0F1E36;
         margin:0; padding:24px; }}
  .sheet {{ max-width: 720px; margin: 0 auto; background:#fff; border:1px solid #D6E2F2; border-radius:10px;
            padding:28px; }}
  h4 {{ font-size:12px; text-transform:uppercase; letter-spacing:.06em; color:#5B6B82; margin:20px 0 8px; }}
  h4:first-of-type {{ margin-top:0; }}
  .head {{ display:flex; justify-content:space-between; gap:14px; border-bottom:2px solid #2A78D6; padding-bottom:14px; }}
  .title {{ font-size:20px; font-weight:700; }}
  .sub {{ font-size:12.5px; color:#5B6B82; margin-top:3px; }}
  .date {{ font-size:11.5px; color:#5B6B82; text-align:right; white-space:nowrap; }}
  .grid {{ display:grid; grid-template-columns:repeat(auto-fit, minmax(140px,1fr)); gap:10px; margin-top:6px; }}
  .m {{ background:#EEF4FC; border-radius:8px; padding:10px; }}
  .m .l {{ font-size:11px; text-transform:uppercase; color:#7A8BA5; font-weight:600; }}
  .m .v {{ font-family: "SFMono-Regular", Menlo, monospace; font-size:17px; font-weight:600; margin-top:3px; }}
  .big .v {{ color:#1B5DB0; }}
  .chip {{ display:inline-block; background:#E3EDFB; color:#1F4E8C; border-radius:999px; padding:5px 11px;
           font-size:12.5px; margin:3px 6px 0 0; }}
  .muted {{ color:#7A8BA5; font-style:italic; font-size:13px; }}
  ol {{ margin:0; padding-left:18px; font-size:13px; line-height:1.7; }}
  .foot {{ margin-top:18px; padding-top:12px; border-top:1px solid #D6E2F2; font-size:11px; color:#7A8BA5; }}
  @media print {{ body {{ background:#fff; padding:0; }} .sheet {{ border:none; box-shadow:none; }} }}
</style></head>
<body>
  <div class="sheet">
    <div class="head">
      <div>
        <div class="title">{esc(nome) or titulo_padrao}</div>
        <div class="sub">{(esc(area) + ' · ') if area else ''}{esc(objetivo) or L('Objetivo não preenchido', 'Goal not filled in')}</div>
      </div>
      <div class="date">{('ID ' + esc(plano.id_teste) + '<br>') if plano.id_teste.strip() else ''}{L('Gerado em', 'Generated on')}<br>{hoje}</div>
    </div>

    <h4>{L('O que estamos testando', 'What we are testing')}</h4>
    <div class="grid">
      <div class="m"><div class="l">{L('Hoje', 'Today')}</div><div class="v">{_fmt_metrica(plano, plano.baseline)}</div></div>
      <div class="m"><div class="l">{L(f'Queremos {verbo} para', f'We want it to {verbo} to')}</div><div class="v">{_fmt_metrica(plano, plano.alvo)}</div></div>
      <div class="m"><div class="l">{L('Diferença', 'Difference')}</div><div class="v">{diferenca_txt}</div></div>
      <div class="m"><div class="l">{palavra_efeito}</div><div class="v">{abs(plano.lift_relativo)*100:.1f}%</div></div>
    </div>

    <h4>{L('Riscos aceitos', 'Accepted risks')}</h4>
    <div class="grid">
      <div class="m"><div class="l">{L('Chance de erro', 'Chance of error')}</div><div class="v">{_fmt_pct(plano.alfa_efetivo, 1)}</div></div>
      <div class="m"><div class="l">{L('Chance de perceber', 'Chance of noticing')}</div><div class="v">{_fmt_pct(plano.poder, 0)}</div></div>
    </div>

    <h4>{L('Gente e prazo', 'People and duration')}</h4>
    <div class="grid big">
      {grupos_html}
      <div class="m big"><div class="l">Total</div><div class="v">{_fmt_int(plano.n_total)}</div></div>
      <div class="m big"><div class="l">{L('Rodar por', 'Run for')}</div><div class="v">{plano.dias_rodar}d</div></div>
    </div>

    <h4>{L('Não pode piorar', 'Must not get worse')}</h4>
    <div>{guardrails_html}</div>

    {f'<h4>{L("Contexto do experimento", "Experiment context")}</h4><div>{contexto_html}</div>' if contexto_html else ''}

    <div class="foot">DaVinci · {L('desenho de teste A/B', 'A/B test design')} · {semanas} {L('semana(s) completa(s)', 'full week(s)')}</div>
  </div>
</body></html>"""
