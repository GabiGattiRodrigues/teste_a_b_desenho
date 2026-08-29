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
from dataclasses import dataclass, field


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
        rotulo = "nao pode subir" if self.direcao == "nao_pode_subir" else "nao pode cair"
        valor = f" (hoje: {self.valor_atual})" if self.valor_atual.strip() else ""
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
        papel = "controle" if idx == 0 else ("variante" if variantes == 2 else f"variante {idx}")
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
        alertas.append(Alerta("erro", "Duracao abaixo de 7 dias -- nao cobre um ciclo semanal completo."))

    if dias_rodar > 42:
        alertas.append(Alerta(
            "erro",
            f"Duracao de {dias_rodar} dias (> 6 semanas) -- risco de cookie churn e contaminacao. "
            "Considere aumentar a diferenca minima aceita, o trafego ou afrouxar poder/alfa."
        ))
    elif dias_rodar > 28:
        alertas.append(Alerta(
            "aviso",
            f"Duracao de {dias_rodar} dias (4-6 semanas) -- ainda aceitavel, mas fique de olho em cookie churn."
        ))

    if janela_tem_sazonalidade:
        alertas.append(Alerta(
            "aviso",
            "A janela do teste foi marcada como sobrepondo feriado ou pico sazonal -- "
            "considere deslocar o periodo ou tratar o efeito de sazonalidade na analise."
        ))

    if dias_rodar > 56:
        alertas.append(Alerta(
            "erro",
            "A diferenca minima pedida e otimista demais para o trafego disponivel -- no ritmo atual "
            "o teste passaria de 8 semanas. Revise a diferenca minima, alfa, poder ou trafego."
        ))

    if bonferroni_aplicada:
        alertas.append(Alerta(
            "info",
            f"{variantes} variantes -- correcao de Bonferroni aplicada automaticamente "
            f"(alfa efetivo por comparacao: {alfa_efetivo*100:.2f}%, em vez de {alfa*100:.2f}%)."
        ))

    if fpc_aplicada:
        alertas.append(Alerta(
            "info",
            f"A amostra requerida passa de 5% da populacao informada -- correcao de populacao "
            f"finita aplicada (n ajustado de {n} para {n_final} por braco)."
        ))

    if not alertas:
        alertas.append(Alerta("ok", "Nenhum alerta -- desenho dentro dos parametros esperados."))

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
    """Formata inteiro com separador de milhar no padrao BR (ponto)."""
    return f"{n:,}".replace(",", ".")


def _fmt_metrica(plano: PlanoTeste, valor: float, casas: int = 2) -> str:
    if plano.tipo_metrica == "proporcao":
        return _fmt_pct(valor, casas)
    return f"{valor:,.{casas}f} {plano.unidade_metrica}".replace(",", "X").replace(".", ",").replace("X", ".")


_CADASTRO_CAMPOS = [
    ("id_teste", "ID do teste"),
    ("nome", "Nome do teste"),
    ("area", "Área responsável"),
    ("objetivo", "Objetivo"),
    ("bu", "BU"),
    ("metrica_nome", "Métrica"),
    ("experimento", "Experimento"),
    ("regiao", "Região"),
    ("campanha", "Campanha"),
    ("plataforma", "Plataforma"),
    ("dispositivo", "Dispositivo"),
]


def _cadastro_preenchido(plano: PlanoTeste) -> list[tuple[str, str]]:
    """Campos de cadastro do teste que foram preenchidos (rotulo, valor)."""
    return [(rotulo, getattr(plano, campo)) for campo, rotulo in _CADASTRO_CAMPOS
            if getattr(plano, campo, "").strip()]


def build_report(plano: PlanoTeste) -> str:
    linhas = []
    linhas.append("=" * 66)
    linhas.append("DESENHO DO TESTE A/B")
    linhas.append("=" * 66)
    linhas.append("")

    cadastro = _cadastro_preenchido(plano)
    if cadastro:
        linhas.append("CADASTRO DO TESTE")
        for rotulo, valor in cadastro:
            linhas.append(f"  {rotulo + ' ':.<36} {valor}")
        linhas.append("")

    verbo = "subir" if plano.direcao == "subir" else "cair"
    linhas.append("O QUE ESTAMOS TESTANDO")
    linhas.append(f"  Como estamos hoje ................. {_fmt_metrica(plano, plano.baseline)}")
    sinal = "+" if plano.delta >= 0 else "-"
    linhas.append(f"  Queremos que {verbo} para .............. {_fmt_metrica(plano, plano.alvo)} "
                   f"({sinal}{abs(plano.delta)*100 if plano.tipo_metrica=='proporcao' else abs(plano.delta):.2f} "
                   f"{'p.p.' if plano.tipo_metrica=='proporcao' else plano.unidade_metrica}, "
                   f"{sinal}{abs(plano.lift_relativo)*100:.1f}% de {'lift' if plano.direcao=='subir' else 'reducao'})")
    linhas.append(f"  Grupos ............................. {plano.variantes} (divisao igual entre eles)")
    linhas.append("")
    linhas.append("RISCOS QUE ESTAMOS ACEITANDO")
    linhas.append(f"  Chance de achar que funcionou sem funcionar ..... {_fmt_pct(plano.alfa_efetivo, 1)}"
                   + (f"  (nominal {_fmt_pct(plano.alfa, 1)}, com Bonferroni)" if plano.bonferroni_aplicada else ""))
    linhas.append(f"  Chance de perceber, se funcionar ................ {_fmt_pct(plano.poder, 0)}")
    linhas.append("")
    linhas.append("AMOSTRA E PRAZO")
    linhas.append("  Cada grupo (braco) e uma versao sendo testada, nao uma etapa da jornada:")
    for g in plano.grupos:
        rotulo = f"Grupo {g['letra']} ({g['papel']})"
        linhas.append(f"    {rotulo:<28} {_fmt_int(g['n'])} pessoas")
    linhas.append(f"  Total do experimento (todos os grupos) .... {_fmt_int(plano.n_total)}")
    linhas.append(f"  Amostra fecha em .................... {plano.dias_fechar} dias")
    semanas = plano.dias_rodar // 7
    linhas.append(f"  Rodar por ........................... {plano.dias_rodar} dias "
                   f"({semanas} semana(s) completa(s))")
    if plano.mde_realizado_no_prazo is not None:
        linhas.append(f"  Se rodar so {plano.dias_rodar} dias, a menor diferenca que da pra ver e de "
                       f"{plano.mde_realizado_no_prazo*100 if plano.tipo_metrica=='proporcao' else plano.mde_realizado_no_prazo:.2f}"
                       f"{'% (pontos absolutos)' if plano.tipo_metrica=='proporcao' else ' ' + plano.unidade_metrica}")
    linhas.append("")
    linhas.append("CUSTO DO NIVEL DE RIGOR")
    for c in plano.comparativo_alfa:
        marcador = "  <- atual" if c["atual"] else ""
        linhas.append(f"  erro {c['alfa_pct']:>2}%: {_fmt_int(c['n_por_braco'])} por grupo, ~{c['dias']} dias{marcador}")
    linhas.append("")

    if plano.guardrails:
        linhas.append("O QUE NAO PODE PIORAR")
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
    """
    import html as _html
    from datetime import datetime

    esc = _html.escape
    _meses_pt = ["janeiro", "fevereiro", "março", "abril", "maio", "junho",
                 "julho", "agosto", "setembro", "outubro", "novembro", "dezembro"]
    _agora = datetime.now()
    hoje = f"{_agora.day:02d} de {_meses_pt[_agora.month - 1]} de {_agora.year}"
    semanas = plano.dias_rodar // 7
    palavra_efeito = "Lift" if plano.direcao == "subir" else "Redução"
    nome, area, objetivo = plano.nome, plano.area, plano.objetivo

    grupos_html = "".join(
        f'<div class="m"><div class="l">Grupo {g["letra"]} · {esc(g["papel"])}</div>'
        f'<div class="v">{_fmt_int(g["n"])} pessoas</div></div>'
        for g in plano.grupos
    )
    guardrails_html = "".join(
        f'<span class="chip">{esc(g.nome)}'
        f'{" (hoje: " + esc(g.valor_atual) + ")" if g.valor_atual.strip() else ""} '
        f'{"não sobe" if g.direcao == "nao_pode_subir" else "não cai"}</span>'
        for g in plano.guardrails
    ) or '<span class="muted">nenhum definido</span>'

    contexto_campos = [
        ("BU", plano.bu), ("Métrica", plano.metrica_nome), ("Experimento", plano.experimento),
        ("Região", plano.regiao), ("Campanha", plano.campanha),
        ("Plataforma", plano.plataforma), ("Dispositivo", plano.dispositivo),
    ]
    contexto_html = "".join(
        f'<span class="chip">{esc(rotulo)}: {esc(valor)}</span>' for rotulo, valor in contexto_campos if valor.strip()
    )

    return f"""<!doctype html>
<html lang="pt-BR"><head><meta charset="utf-8">
<title>{esc(nome) or 'Desenho de teste A/B'} — DaVinci</title>
<style>
  body {{ font-family: -apple-system, "Segoe UI", Arial, sans-serif; background:#FBF7F2; color:#241708;
         margin:0; padding:24px; }}
  .sheet {{ max-width: 720px; margin: 0 auto; background:#fff; border:1px solid #EAD9C6; border-radius:10px;
            padding:28px; }}
  h4 {{ font-size:12px; text-transform:uppercase; letter-spacing:.06em; color:#7A6752; margin:20px 0 8px; }}
  h4:first-of-type {{ margin-top:0; }}
  .head {{ display:flex; justify-content:space-between; gap:14px; border-bottom:2px solid #E85C0D; padding-bottom:14px; }}
  .title {{ font-size:20px; font-weight:700; }}
  .sub {{ font-size:12.5px; color:#7A6752; margin-top:3px; }}
  .date {{ font-size:11.5px; color:#7A6752; text-align:right; white-space:nowrap; }}
  .grid {{ display:grid; grid-template-columns:repeat(auto-fit, minmax(140px,1fr)); gap:10px; margin-top:6px; }}
  .m {{ background:#FFF1E3; border-radius:8px; padding:10px; }}
  .m .l {{ font-size:11px; text-transform:uppercase; color:#9A7D5E; font-weight:600; }}
  .m .v {{ font-family: "SFMono-Regular", Menlo, monospace; font-size:17px; font-weight:600; margin-top:3px; }}
  .big .v {{ color:#B8430A; }}
  .chip {{ display:inline-block; background:#FBF0D2; color:#6B4E00; border-radius:999px; padding:5px 11px;
           font-size:12.5px; margin:3px 6px 0 0; }}
  .muted {{ color:#9A7D5E; font-style:italic; font-size:13px; }}
  ol {{ margin:0; padding-left:18px; font-size:13px; line-height:1.7; }}
  .foot {{ margin-top:18px; padding-top:12px; border-top:1px solid #EAD9C6; font-size:11px; color:#9A7D5E; }}
  @media print {{ body {{ background:#fff; padding:0; }} .sheet {{ border:none; box-shadow:none; }} }}
</style></head>
<body>
  <div class="sheet">
    <div class="head">
      <div>
        <div class="title">{esc(nome) or 'Desenho de teste A/B'}</div>
        <div class="sub">{(esc(area) + ' · ') if area else ''}{esc(objetivo) or 'Objetivo não preenchido'}</div>
      </div>
      <div class="date">{('ID ' + esc(plano.id_teste) + '<br>') if plano.id_teste.strip() else ''}Gerado em<br>{hoje}</div>
    </div>

    <h4>O que estamos testando</h4>
    <div class="grid">
      <div class="m"><div class="l">Hoje</div><div class="v">{_fmt_metrica(plano, plano.baseline)}</div></div>
      <div class="m"><div class="l">Queremos {('subir' if plano.direcao=='subir' else 'cair')} para</div><div class="v">{_fmt_metrica(plano, plano.alvo)}</div></div>
      <div class="m"><div class="l">Diferença</div><div class="v">{'+' if plano.delta>=0 else '-'}{abs(plano.delta)*100 if plano.tipo_metrica=='proporcao' else abs(plano.delta):.2f}{'p.p.' if plano.tipo_metrica=='proporcao' else ' '+plano.unidade_metrica}</div></div>
      <div class="m"><div class="l">{palavra_efeito}</div><div class="v">{abs(plano.lift_relativo)*100:.1f}%</div></div>
    </div>

    <h4>Riscos aceitos</h4>
    <div class="grid">
      <div class="m"><div class="l">Chance de erro</div><div class="v">{_fmt_pct(plano.alfa_efetivo, 1)}</div></div>
      <div class="m"><div class="l">Chance de perceber</div><div class="v">{_fmt_pct(plano.poder, 0)}</div></div>
    </div>

    <h4>Gente e prazo</h4>
    <div class="grid big">
      {grupos_html}
      <div class="m big"><div class="l">Total</div><div class="v">{_fmt_int(plano.n_total)}</div></div>
      <div class="m big"><div class="l">Rodar por</div><div class="v">{plano.dias_rodar}d</div></div>
    </div>

    <h4>Não pode piorar</h4>
    <div>{guardrails_html}</div>

    {f'<h4>Contexto do experimento</h4><div>{contexto_html}</div>' if contexto_html else ''}

    <div class="foot">DaVinci · desenho de teste A/B · {semanas} semana(s) completa(s)</div>
  </div>
</body></html>"""
