"""
Testes de validacao.

1) Reproduz os numeros exatos do cenario da mentoria (secao 6 do PDF
   "Design de Teste A/B - notas de brainstorm"): proporcao, direcao "subir".
2) Confere que "cair" (ex.: churn) da os MESMOS numeros que "subir" quando
   o baseline e exatamente 50% (caso simetrico, bom pra pegar erro de sinal).
3) Confere a formula de metrica de MEDIA (duracao, R$, etc.) contra um
   calculo fechado feito na mao.
"""

from ab_design import (
    montar_plano,
    build_report,
    build_html_summary,
    DEFAULT_GUARDRAILS,
    Guardrail,
    sample_size_two_means,
    min_detectable_effect_media,
    z_two_sided,
    z_power,
)


def aprox(a, b, tol):
    return abs(a - b) <= tol


def test_cenario_mentoria_proporcao_subir():
    plano = montar_plano(
        tipo_metrica="proporcao", direcao="subir",
        baseline_valor=32, sigma=None, unidade_metrica="%",
        mde_valor=10, mde_tipo="relativo",
        alfa_pct=1, poder_pct=80, trafego_dia=800,
        variantes=2, populacao=None, janela_tem_sazonalidade=False,
        guardrails=DEFAULT_GUARDRAILS,
    )

    print(build_report(plano))
    print()

    checks = [
        ("n por braco == 5088", plano.n_por_braco == 5088),
        ("n total == 10176", plano.n_total == 10176),
        ("dias para fechar amostra == 13", plano.dias_fechar == 13),
        ("dias para rodar == 14", plano.dias_rodar == 14),
    ]

    mde_ok = plano.mde_realizado_no_prazo is not None and aprox(plano.mde_realizado_no_prazo, 0.0305, 0.001)
    checks.append((f"MDE minimo em 14 dias ~= 3.05% (obtido {plano.mde_realizado_no_prazo*100:.3f}%)", mde_ok))

    comp = {c["alfa_pct"]: c for c in plano.comparativo_alfa}
    checks.append(("comparativo alfa=1% -> n=5088", comp[1]["n_por_braco"] == 5088))
    checks.append((f"comparativo alfa=5% -> n=3419 (obtido {comp[5]['n_por_braco']})",
                    aprox(comp[5]["n_por_braco"], 3419, 2)))
    checks.append((f"comparativo alfa=10% -> n=2694 (obtido {comp[10]['n_por_braco']})",
                    aprox(comp[10]["n_por_braco"], 2694, 2)))

    ok = True
    for nome, resultado in checks:
        print(f"[{'OK ' if resultado else 'FALHOU'}] {nome}")
        ok = ok and resultado
    assert ok


def test_direcao_cair_e_simetrica_em_50pct():
    """Em 50%, subir X p.p. ou cair X p.p. tem que dar o MESMO n (caso simetrico)."""
    comum = dict(
        baseline_valor=50, sigma=None, unidade_metrica="%",
        mde_valor=5, mde_tipo="absoluto",
        alfa_pct=5, poder_pct=80, trafego_dia=1000,
        variantes=2, populacao=None, janela_tem_sazonalidade=False, guardrails=[],
    )
    subir = montar_plano(tipo_metrica="proporcao", direcao="subir", **comum)
    cair = montar_plano(tipo_metrica="proporcao", direcao="cair", **comum)

    assert subir.n_por_braco == cair.n_por_braco, (subir.n_por_braco, cair.n_por_braco)
    assert aprox(subir.alvo, 0.55, 1e-9)
    assert aprox(cair.alvo, 0.45, 1e-9)
    assert cair.delta < 0 < subir.delta
    assert cair.lift_relativo < 0 < subir.lift_relativo


def test_direcao_cair_caso_churn_assimetrico():
    """Churn caindo de 32% pra 30% -- caso do usuario. So confere que roda e faz sentido."""
    plano = montar_plano(
        tipo_metrica="proporcao", direcao="cair",
        baseline_valor=32, sigma=None, unidade_metrica="%",
        mde_valor=2, mde_tipo="absoluto",
        alfa_pct=5, poder_pct=80, trafego_dia=800,
        variantes=2, populacao=None, janela_tem_sazonalidade=False, guardrails=[],
    )
    assert aprox(plano.baseline, 0.32, 1e-9)
    assert aprox(plano.alvo, 0.30, 1e-9)
    assert plano.delta < 0
    assert plano.n_por_braco > 0
    texto = build_report(plano)
    assert "cair" in texto


def test_metrica_media_formula_fechada():
    """
    Metrica de media (ex.: duracao de sessao em segundos): confere a
    formula fechada n = 2*sigma^2*(za+zb)^2/delta^2 batendo com o calculo
    manual, e o inverso (MDE dado n) batendo tambem.
    """
    media_hoje = 30.0   # segundos
    sigma = 12.0         # desvio padrao estimado
    alfa_pct, poder_pct = 5, 80

    plano = montar_plano(
        tipo_metrica="media", direcao="cair",
        baseline_valor=media_hoje, sigma=sigma, unidade_metrica="segundos",
        mde_valor=15, mde_tipo="absoluto",  # quer cair 15 segundos: 30 -> 15
        alfa_pct=alfa_pct, poder_pct=poder_pct, trafego_dia=500,
        variantes=2, populacao=None, janela_tem_sazonalidade=False, guardrails=[],
    )

    za = z_two_sided(alfa_pct / 100)
    zb = z_power(poder_pct / 100)
    delta = 15.0
    n_manual = 2 * (sigma ** 2) * ((za + zb) ** 2) / (delta ** 2)
    import math
    n_manual = math.ceil(n_manual)

    assert plano.n_por_braco == n_manual, (plano.n_por_braco, n_manual)
    assert aprox(plano.alvo, 15.0, 1e-9)

    # inverso: MDE dado n deveria devolver (aprox) o delta original quando n == n_manual.
    # Como n_manual foi arredondado pra cima (ceil), o efeito minimo detectavel com
    # esse n fica um pouco MENOR que o delta pedido -- tolerancia generosa porque n
    # e pequeno aqui (arredondamento pesa mais em amostras pequenas).
    mde_de_volta = min_detectable_effect_media(n_manual, sigma, alfa_pct / 100, poder_pct / 100)
    assert mde_de_volta <= delta + 1e-9, mde_de_volta
    assert aprox(mde_de_volta, delta, delta * 0.10), mde_de_volta

    # sample_size_two_means direto, mesma conta
    assert sample_size_two_means(sigma, delta, alfa_pct / 100, poder_pct / 100) == n_manual


def test_bonferroni_tres_variantes():
    plano = montar_plano(
        tipo_metrica="proporcao", direcao="subir",
        baseline_valor=32, sigma=None, unidade_metrica="%",
        mde_valor=10, mde_tipo="relativo", alfa_pct=5,
        poder_pct=80, trafego_dia=800, variantes=3, populacao=None,
        janela_tem_sazonalidade=False, guardrails=[],
    )
    assert aprox(plano.alfa_efetivo, 0.025, 1e-9), plano.alfa_efetivo
    assert plano.bonferroni_aplicada


def test_populacao_finita():
    plano = montar_plano(
        tipo_metrica="proporcao", direcao="subir",
        baseline_valor=32, sigma=None, unidade_metrica="%",
        mde_valor=10, mde_tipo="relativo", alfa_pct=5,
        poder_pct=80, trafego_dia=800, variantes=2, populacao=50000,
        janela_tem_sazonalidade=False, guardrails=[],
    )
    assert plano.fpc_aplicada


def test_comparativo_alfa_tem_dias_fechar_e_alfa_efetivo():
    """
    A tabela "custo do nivel de rigor" agora precisa trazer o Z(erro) usado
    (via alfa_efetivo) e o prazo bruto antes de arredondar pra semana cheia
    (dias_fechar), pra dar pra explicar por que o numero muda de linha pra
    linha -- pedido feito depois de tirar o acompanhamento/checklist do
    escopo da ferramenta.
    """
    plano = montar_plano(
        tipo_metrica="proporcao", direcao="subir",
        baseline_valor=32, sigma=None, unidade_metrica="%",
        mde_valor=10, mde_tipo="relativo", alfa_pct=1,
        poder_pct=80, trafego_dia=800, variantes=2, populacao=None,
        janela_tem_sazonalidade=False, guardrails=[],
    )
    comp = {c["alfa_pct"]: c for c in plano.comparativo_alfa}
    for alfa_pct in (1, 5, 10):
        assert "dias_fechar" in comp[alfa_pct]
        assert "alfa_efetivo" in comp[alfa_pct]
        assert comp[alfa_pct]["dias_fechar"] <= comp[alfa_pct]["dias"]
    assert aprox(comp[1]["alfa_efetivo"], 0.01, 1e-9)
    # bate com o cenario ja validado: 1% e 5% cabem na mesma semana (14 dias),
    # 10% fecha numa semana a menos (7 dias) -- exatamente o efeito de
    # arredondamento que precisa ficar claro na explicacao.
    assert comp[1]["dias"] == 14, comp[1]["dias"]
    assert comp[5]["dias"] == 14, comp[5]["dias"]
    assert comp[10]["dias"] == 7, comp[10]["dias"]


def test_cadastro_do_teste_aparece_no_relatorio():
    """
    Campos de cadastro (BU, metrica, experimento, regiao, campanha,
    plataforma, dispositivo, alem de nome/area/objetivo) sao so metadados
    -- nao podem mudar nenhuma conta -- mas precisam aparecer tanto no
    relatorio em texto quanto no resumo HTML, pra servir de handoff pra
    quem for medir o resultado depois.
    """
    comuns = dict(
        tipo_metrica="proporcao", direcao="subir",
        baseline_valor=32, sigma=None, unidade_metrica="%",
        mde_valor=10, mde_tipo="relativo", alfa_pct=1,
        poder_pct=80, trafego_dia=800, variantes=2, populacao=None,
        janela_tem_sazonalidade=False, guardrails=[],
    )
    sem_cadastro = montar_plano(**comuns)
    com_cadastro = montar_plano(
        **comuns,
        nome="Checkout em uma etapa", area="Produto / Growth",
        objetivo="Aumentar conversao do checkout",
        bu="Varejo (e-commerce)", metrica_nome="Taxa de conversao do checkout",
        experimento="Checkout em uma etapa", regiao="Nacional",
        campanha="Sem campanha (organico)", plataforma="App", dispositivo="iOS",
    )

    # o cadastro nao pode influenciar nenhum numero do dimensionamento
    assert com_cadastro.n_por_braco == sem_cadastro.n_por_braco
    assert com_cadastro.dias_rodar == sem_cadastro.dias_rodar

    # sem cadastro preenchido, a secao nao aparece (sem poluir o relatorio)
    texto_sem = build_report(sem_cadastro)
    assert "CADASTRO DO TESTE" not in texto_sem

    # com cadastro preenchido, tudo aparece no relatorio em texto...
    texto_com = build_report(com_cadastro)
    assert "CADASTRO DO TESTE" in texto_com
    for valor in ("Checkout em uma etapa", "Varejo (e-commerce)", "Taxa de conversao do checkout",
                  "Nacional", "Sem campanha (organico)", "App", "iOS"):
        assert valor in texto_com, valor

    # ...e no resumo HTML (versao "bonita" pra exportar)
    html_com = build_html_summary(com_cadastro)
    for valor in ("Varejo (e-commerce)", "Taxa de conversao do checkout", "Checkout em uma etapa",
                  "Nacional", "Sem campanha (organico)", "App", "iOS"):
        assert valor in html_com, valor
    html_sem = build_html_summary(sem_cadastro)
    assert "Contexto do experimento" not in html_sem


def test_baseline_zero_e_rejeitado_nos_dois_tipos_de_metrica():
    """
    "Hoje" (baseline) precisa ser > 0 nos dois tipos de metrica, e a
    diferenca minima (mde) tambem -- sem isso nao ha nada pra comparar
    entre teste e controle. Pedido explicito: os campos tem que "se
    conversar" e travar esses casos com uma mensagem clara, em vez de
    deixar passar um resultado sem sentido.
    """
    comuns_prop = dict(
        tipo_metrica="proporcao", direcao="subir", sigma=None, unidade_metrica="%",
        mde_tipo="relativo", mde_valor=10, alfa_pct=5, poder_pct=80, trafego_dia=800,
        variantes=2, populacao=None, janela_tem_sazonalidade=False, guardrails=[],
    )
    try:
        montar_plano(baseline_valor=0, **comuns_prop)
        assert False, "deveria ter rejeitado baseline=0 (proporcao)"
    except ValueError:
        pass

    comuns_media = dict(
        tipo_metrica="media", direcao="cair", sigma=12.0, unidade_metrica="segundos",
        mde_tipo="absoluto", mde_valor=5, alfa_pct=5, poder_pct=80, trafego_dia=800,
        variantes=2, populacao=None, janela_tem_sazonalidade=False, guardrails=[],
    )
    try:
        montar_plano(baseline_valor=0, **comuns_media)
        assert False, "deveria ter rejeitado baseline=0 (media)"
    except ValueError:
        pass

    # mde (diferenca entre teste e controle) tambem precisa ser > 0, nos dois tipos
    try:
        montar_plano(baseline_valor=32, **{**comuns_prop, "mde_valor": 0})
        assert False, "deveria ter rejeitado mde_valor=0 (proporcao)"
    except ValueError:
        pass
    try:
        montar_plano(baseline_valor=30, **{**comuns_media, "mde_valor": 0})
        assert False, "deveria ter rejeitado mde_valor=0 (media)"
    except ValueError:
        pass


def test_guardrail_com_valor_atual_aparece_no_texto_e_no_relatorio():
    """
    Guardrail agora carrega o valor atual (o quanto esta hoje), pra ficar
    registrado junto da regra -- pedido explicito: "nos guardrails vamos
    deixar obrigatorio colocar o valor atual". A obrigatoriedade em si e
    validada na camada de UI (app.py); aqui confere que, quando o valor
    atual vem preenchido, ele aparece no texto do guardrail e propaga pro
    relatorio e pro resumo HTML.
    """
    g = Guardrail(nome="custo por cliente", direcao="nao_pode_subir", valor_atual="R$ 45")
    assert "R$ 45" in g.texto()
    assert "custo por cliente" in g.texto()
    assert "nao pode subir" in g.texto()

    # guardrail sem valor_atual preenchido (compatibilidade com codigo antigo) continua funcionando
    g_sem_valor = Guardrail(nome="tempo de cadastro", direcao="nao_pode_subir")
    assert g_sem_valor.valor_atual == ""
    assert "(hoje:" not in g_sem_valor.texto()

    comuns = dict(
        tipo_metrica="proporcao", direcao="subir",
        baseline_valor=32, sigma=None, unidade_metrica="%",
        mde_valor=10, mde_tipo="relativo", alfa_pct=1,
        poder_pct=80, trafego_dia=800, variantes=2, populacao=None,
        janela_tem_sazonalidade=False, guardrails=[g],
    )
    plano = montar_plano(**comuns)
    texto = build_report(plano)
    assert "R$ 45" in texto
    html = build_html_summary(plano)
    assert "R$ 45" in html


def test_id_teste_aparece_no_cadastro_e_no_resumo():
    """
    ID do teste e gerado automaticamente na UI assim que um teste novo e
    criado (pra rastrear e casar com o historico salvo) -- aqui confere
    que, entrando no plano, ele aparece no relatorio em texto e no resumo
    HTML, e nao muda nenhuma conta.
    """
    comuns = dict(
        tipo_metrica="proporcao", direcao="subir",
        baseline_valor=32, sigma=None, unidade_metrica="%",
        mde_valor=10, mde_tipo="relativo", alfa_pct=1,
        poder_pct=80, trafego_dia=800, variantes=2, populacao=None,
        janela_tem_sazonalidade=False, guardrails=[],
    )
    sem_id = montar_plano(**comuns)
    com_id = montar_plano(**comuns, id_teste="DV-20260828-AB12", nome="Checkout em uma etapa")

    assert com_id.n_por_braco == sem_id.n_por_braco

    texto = build_report(com_id)
    assert "DV-20260828-AB12" in texto
    assert "ID do teste" in texto

    html = build_html_summary(com_id)
    assert "DV-20260828-AB12" in html


if __name__ == "__main__":
    test_cenario_mentoria_proporcao_subir()
    test_direcao_cair_e_simetrica_em_50pct()
    test_direcao_cair_caso_churn_assimetrico()
    test_metrica_media_formula_fechada()
    test_bonferroni_tres_variantes()
    test_populacao_finita()
    test_comparativo_alfa_tem_dias_fechar_e_alfa_efetivo()
    test_cadastro_do_teste_aparece_no_relatorio()
    test_baseline_zero_e_rejeitado_nos_dois_tipos_de_metrica()
    test_guardrail_com_valor_atual_aparece_no_texto_e_no_relatorio()
    test_id_teste_aparece_no_cadastro_e_no_resumo()
    print("\nTodos os testes passaram.")
