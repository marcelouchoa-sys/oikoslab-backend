"""
Orquestrador central do pipeline de simulação econômica do OikosLab.

Nenhum código externo chama o solver diretamente — todo fluxo passa por
EconomyEngine, que garante a sequência obrigatória e o hard gate econômico.

Pipeline (todas as etapas são obrigatórias e sequenciais):
  Parse → Classify → LaTeX → Detect → Solve →
  ConsistênciaPorEquação → ConsistênciaEstrutural →
  EconomicGate → Elasticidades → Series → ResultGate+Format
"""
from __future__ import annotations

import sympy as sp
import numpy as np

from services.motor_sistemas import _resolve_sistema as _resolver_sistema, _split_equacao
from services.validador import (
    classificar_variaveis,
    validar_solucao,
    validar_consistencia_estrutural,
    EconomicValidationError,
    aplicar_validacao_economica,
    RESTRICOES_PADRAO,
)


class EconomyEngine:
    """
    Único ponto de entrada para resolução de modelos econômicos.

    Uso:
        EconomyEngine.run(equacoes, parametros, variavel_livre, sensibilidades)
        EconomyEngine.resolve_single(equacoes, parametros)   ← simulação de cenários
    """

    # ──────────────────────────────────────────────────────────────────────────
    #  ENTRY POINTS
    # ──────────────────────────────────────────────────────────────────────────

    @classmethod
    def run(
        cls,
        equacoes: list,
        parametros: dict[str, float],
        variavel_livre=None,
        sensibilidades: list | None = None,
    ) -> dict:
        """
        Pipeline completo — retorna o contrato {valores, matematica, solucao, economia}.

        Em fail_fast com violações bloqueantes: retorna {status:'invalid_solution', ...}
        sem nenhum valor numérico da solução.
        """
        if sensibilidades is None:
            sensibilidades = []

        # ── 1. PARSE + DEDUP ────────────────────────────────────────────────
        equacoes_unicas, equacoes_norm = cls._parse(equacoes)

        # ── 2. CLASSIFY ──────────────────────────────────────────────────────
        classificacao = classificar_variaveis(equacoes_unicas, parametros)

        # ── 3. LaTeX das equações de entrada ─────────────────────────────────
        latex_map = cls._build_latex(equacoes_unicas)

        # ── 4. DETECT ENDOGENOUS ─────────────────────────────────────────────
        endogenas, param_detectados, endogenas_ordered = cls._detect(equacoes_unicas, parametros)

        # ── 5. SOLVE ─────────────────────────────────────────────────────────
        sol_num, sol_sym, erros = _resolver_sistema(equacoes_unicas, parametros, endogenas_ordered)

        if sol_sym:
            for var, expr in sol_sym.items():
                try:
                    latex_map[f"sol_{var}"] = f"{var} = {sp.latex(expr)}"
                except Exception:
                    latex_map[f"sol_{var}"] = f"{var} = {str(expr)}"

        # ── 6. CONSISTÊNCIA POR EQUAÇÃO ───────────────────────────────────────
        erros_consist = validar_solucao(equacoes_unicas, sol_num)

        # ── 7. CONSISTÊNCIA ESTRUTURAL (Y=C+I+G, Qd=Qs, Md=Ms) ──────────────
        consist_estrutural = validar_consistencia_estrutural(sol_num)

        # ── 8. ECONOMIC HARD GATE ─────────────────────────────────────────────
        # Não bypassável. Em fail_fast com valid=False: interrompe aqui,
        # retorna invalid_solution SEM valores numéricos da solução.
        try:
            validation = aplicar_validacao_economica(sol_num)
        except EconomicValidationError as exc:
            return cls._format_invalid(exc.result, erros_consist, consist_estrutural)

        # ── 9. ELASTICIDADES / DERIVADAS ANALÍTICAS ──────────────────────────
        elasticidades, dependencias = cls._compute_elasticidades(
            sol_sym, parametros, param_detectados
        )

        # ── 10. SERIES (variável livre + sensibilidades) ──────────────────────
        all_sensis = list(sensibilidades)
        if variavel_livre:
            all_sensis.append(variavel_livre)
        series = cls._compute_series(sol_sym, parametros, all_sensis) if (all_sensis and sol_sym) else None

        # ── 11. RESULT GATE + FORMAT ──────────────────────────────────────────
        return cls._format_result(
            sol_num=sol_num,
            sol_sym=sol_sym,
            equacoes_norm=equacoes_norm,
            classificacao=classificacao,
            latex_map=latex_map,
            endogenas=endogenas,
            param_detectados=param_detectados,
            series=series,
            erros=erros,
            erros_consist=erros_consist,
            consist_estrutural=consist_estrutural,
            validation=validation,
            elasticidades=elasticidades,
            dependencias=dependencias,
        )

    @classmethod
    def resolve_single(cls, equacoes: list, parametros: dict[str, float]) -> dict:
        """
        Pipeline mínimo para simulação de cenários: Parse → Solve → EconomicGate.

        Sempre passa pelo hard gate. Em fail_fast com violação: retorna valores={}.

        Returns:
            {'valores': dict[str, float], 'valid': bool, 'violations': list}
        """
        equacoes_unicas, _ = cls._parse(equacoes)
        _, _, endogenas_ordered = cls._detect(equacoes_unicas, parametros)
        sol_num, _, _ = _resolver_sistema(equacoes_unicas, parametros, endogenas_ordered)

        try:
            validation = aplicar_validacao_economica(sol_num)
            return {
                'valores':    {k: v for k, v in sol_num.items() if isinstance(v, (int, float))},
                'valid':      validation['valid'],
                'violations': validation['violations'],
            }
        except EconomicValidationError as exc:
            return {
                'valores':    {},
                'valid':      False,
                'violations': exc.result['violations'],
            }

    # ──────────────────────────────────────────────────────────────────────────
    #  PRIVATE PIPELINE STAGES
    # ──────────────────────────────────────────────────────────────────────────

    @staticmethod
    def _parse(equacoes: list) -> tuple[list, list[str]]:
        """Deduplicação simbólica + normalização para 'lhs = rhs'."""
        vistas: set[str] = set()
        unicas: list = []
        parts: list[tuple[str, str]] = []

        for eq in equacoes:
            lhs, rhs = _split_equacao(eq)
            if not lhs or not rhs:
                continue
            try:
                canon = str(sp.expand(sp.sympify(lhs) - sp.sympify(rhs)))
            except Exception:
                canon = f"{lhs}={rhs}"
            if canon not in vistas:
                vistas.add(canon)
                unicas.append(eq)
                parts.append((lhs, rhs))

        norm = [f"{lhs.strip()} = {rhs.strip()}" for lhs, rhs in parts]
        return unicas, norm

    @staticmethod
    def _build_latex(equacoes: list) -> dict[str, str]:
        """Mapa de LaTeX das equações de entrada."""
        latex_map: dict[str, str] = {}
        for eq in equacoes:
            lhs, rhs = _split_equacao(eq)
            key = lhs or getattr(eq, 'nome', '') or ''
            try:
                latex_map[key] = f"{lhs} = {sp.latex(sp.sympify(rhs))}"
            except Exception:
                latex_map[key] = f"{lhs} = {rhs}"
        return latex_map

    @staticmethod
    def _detect(
        equacoes: list, parametros: dict[str, float]
    ) -> tuple[set[str], set[str], list[str]]:
        """
        Detecta variáveis endógenas e parâmetros.

        endogenas_lhs  = aparecem no LHS de alguma equação
        faltando       = aparecem em expressões mas não estão em parametros
                         → tratados como endógenas adicionais
        endogenas_ordered preserva LHS antes de faltando para SymPy.
        """
        endogenas_lhs: set[str] = set()
        todos: set[str] = set()

        for eq in equacoes:
            lhs, rhs = _split_equacao(eq)
            if not lhs or not rhs:
                continue
            if lhs.isidentifier():
                endogenas_lhs.add(lhs)
                todos.add(lhs)
            try:
                for s in sp.sympify(rhs).free_symbols:
                    todos.add(str(s))
            except Exception:
                pass

        param_nomes = set(parametros.keys())
        param_detectados_raw = todos - endogenas_lhs
        faltando = param_detectados_raw - param_nomes

        endogenas = endogenas_lhs | faltando
        param_detectados = todos - endogenas
        endogenas_ordered = sorted(endogenas_lhs) + sorted(faltando)

        return endogenas, param_detectados, endogenas_ordered

    @staticmethod
    def _compute_elasticidades(
        sol_sym: dict | None,
        parametros: dict[str, float],
        param_detectados: set[str],
    ) -> tuple[dict[str, dict], list[str]]:
        """Derivadas analíticas dEndogena/dParametro para cada par resolvido."""
        elasticidades: dict[str, dict] = {}
        dependencias: list[str] = []
        if not sol_sym:
            return elasticidades, dependencias

        param_subs = {sp.Symbol(k): v for k, v in parametros.items()}

        for endog, expr in sol_sym.items():
            nome_e = str(endog)
            derivs: dict[str, float] = {}
            for pnome in sorted(param_detectados):
                try:
                    d = sp.diff(expr, sp.Symbol(pnome))
                    d_val = float(d.subs(param_subs).evalf())
                    if abs(d_val) > 1e-9:
                        derivs[pnome] = round(d_val, 4)
                        seta = "↑" if d_val > 0 else "↓"
                        dependencias.append(f"↑ {pnome} -> {seta} {nome_e}")
                except Exception:
                    pass
            if derivs:
                elasticidades[nome_e] = derivs

        return elasticidades, dependencias

    @staticmethod
    def _compute_series(
        sol_sym: dict,
        parametros: dict[str, float],
        sensibilidades: list,
    ) -> dict[str, list]:
        """Séries numéricas para gráficos (variável livre ou sensibilidades)."""
        series: dict[str, list] = {}
        sym_keys = [str(k) for k in sol_sym.keys()]

        for sl in sensibilidades:
            grid = np.linspace(sl.min, sl.max, sl.pontos)
            series[sl.nome] = grid.tolist()
            alvos = sl.mostrar or sym_keys
            for alvo in alvos:
                if alvo not in sym_keys:
                    continue
                expr = sol_sym[sp.Symbol(alvo)]
                serie: list = []
                for x in grid:
                    subs = {sp.Symbol(k): v for k, v in parametros.items()}
                    subs[sp.Symbol(sl.nome)] = x
                    try:
                        serie.append(float(expr.subs(subs).evalf()))
                    except Exception:
                        serie.append(None)
                series[f"{alvo}_vs_{sl.nome}"] = serie

        return series

    # ──────────────────────────────────────────────────────────────────────────
    #  RESULT GATE
    # ──────────────────────────────────────────────────────────────────────────

    @staticmethod
    def _format_invalid(
        result: dict,
        erros_consist: list,
        consist_estrutural: list,
    ) -> dict:
        """fail_fast path — nenhum valor numérico retornado."""
        return {
            "status":     "invalid_solution",
            "errors":     [v["mensagem"] for v in result["errors"]],
            "violations": result["violations"],
            "economia": {
                "valid":                   False,
                "warnings":                result["warnings"],
                "errors":                  result["errors"],
                "violations":              result["violations"],
                "restricoes":              RESTRICOES_PADRAO,
                "consistencia":            erros_consist,
                "consistencia_estrutural": consist_estrutural,
                "interpretacao":           [],
            },
        }

    @staticmethod
    def _format_result(
        sol_num: dict,
        sol_sym: dict | None,
        equacoes_norm: list[str],
        classificacao: dict,
        latex_map: dict[str, str],
        endogenas: set[str],
        param_detectados: set[str],
        series,
        erros: list[str],
        erros_consist: list,
        consist_estrutural: list,
        validation: dict,
        elasticidades: dict,
        dependencias: list[str],
    ) -> dict:
        """warning/ok path — output completo com bloco economia."""
        sol_simbolica_str = {str(k): str(v) for k, v in sol_sym.items()} if sol_sym else {}

        return {
            # campos legados — compatibilidade com frontend
            "status":                "ok" if not erros else "parcial",
            "valores":               sol_num,
            "endogenas":             sorted(endogenas),
            "parametros_detectados": sorted(param_detectados),
            "series":                series,
            "erros":                 erros,
            "latex":                 latex_map,
            "dependencias":          sorted(set(dependencias)),
            "elasticidades":         elasticidades,
            # blocos estruturados
            "matematica": {
                "equacoes_normalizadas": equacoes_norm,
                "variaveis":             classificacao,
            },
            "solucao": {
                "numerica":  sol_num,
                "simbolica": sol_simbolica_str,
            },
            "economia": {
                "valid":                   validation["valid"],
                "interpretacao":           sorted(set(dependencias)),
                "restricoes":              RESTRICOES_PADRAO,
                "warnings":                validation["warnings"],
                "errors":                  validation["errors"],
                "violations":              validation["violations"],
                "consistencia":            erros_consist,
                "consistencia_estrutural": consist_estrutural,
            },
        }

    # ──────────────────────────────────────────────────────────────────────────
    #  IS-LM-BP ENTRY POINTS
    #  Toda computação do modelo IS-LM passa por run() — sem bypass.
    # ──────────────────────────────────────────────────────────────────────────

    @classmethod
    def run_islm(cls, config: dict) -> dict:
        """
        Modelo IS-LM-BP via equações simbólicas → EconomyEngine.run().

        config: dict com os campos de ParametrosISLM (aberta, kf, c0, c1, ...).
        Retorna o contrato de run() + chave 'equilibrio' para compatibilidade.
        """
        equacoes, parametros = cls._build_islm_equations(config)
        result = cls.run(equacoes, parametros)
        if result.get("status") == "invalid_solution":
            return result
        vals = result.get("valores", {})
        return {
            **result,
            "equilibrio": {
                "Y":  vals.get("Y"),
                "r":  vals.get("r", config.get("r_star", 0.0)),
                "C":  vals.get("C"),
                "I":  vals.get("I"),
                "NX": vals.get("NX", 0.0),
                "e":  config.get("e", 1.0),
            },
        }

    @classmethod
    def run_islm_curvas(cls, config: dict) -> dict:
        """IS-LM curves (IS e LM) + equilíbrio. Usa run_islm() internamente."""
        result = cls.run_islm(config)
        if result.get("status") == "invalid_solution":
            return result

        Y_center = (result.get("equilibrio") or {}).get("Y") or 1000.0
        Y_grid = np.linspace(max(100.0, Y_center - 800), Y_center + 800, 200)

        b  = float(config.get("b",  50))
        c0 = float(config.get("c0", 100))
        c1 = float(config.get("c1", 0.75))
        T  = float(config.get("T",  200))
        I0 = float(config.get("I0", 200))
        G  = float(config.get("G",  300))
        k  = float(config.get("k",  0.5))
        h  = float(config.get("h",  100))
        M  = float(config.get("M",  1000))
        P  = float(config.get("P",  1.0))

        r_IS = [(c0 - c1*T + I0 + G - (1 - c1)*Y) / b for Y in Y_grid]
        r_LM = [(k*Y - M/P) / h for Y in Y_grid]

        return {
            **result,
            "Y_grid": Y_grid.tolist(),
            "r_IS":   r_IS,
            "r_LM":   r_LM,
        }

    @staticmethod
    def _build_islm_equations(config: dict) -> tuple[list, dict]:
        """
        Constrói equações simbólicas do IS-LM-BP.

        Usa SimpleNamespace para evitar import circular com routers.modelo_proprio.
        _split_equacao aceita qualquer objeto com .expressao e .variavel.
        """
        from types import SimpleNamespace

        def _eq(variavel: str = "", expressao: str = "") -> object:
            return SimpleNamespace(variavel=variavel, expressao=expressao, nome="")

        aberta = bool(config.get("aberta", False))
        kf     = float(config.get("kf", 0))

        if not aberta:
            # Economia fechada: IS + LM
            # Endógenas: C, I, Y, r   |   Parâmetros: c0,c1,T,I0,b,G,M,P,k,h
            equacoes = [
                _eq("C",  "c0 + c1*(Y - T)"),
                _eq("I",  "I0 - b*r"),
                _eq("Y",  "C + I + G"),
                _eq("",   "k*Y - h*r = M/P"),   # LM: Md = Ms inline
            ]
            chaves = ("c0", "c1", "T", "I0", "b", "G", "M", "P", "k", "h")

        elif kf >= 1e5:
            # Mobilidade perfeita (Mundell-Fleming): IS + BP (r = r*)
            # Endógenas: C, I, NX, Y, r
            equacoes = [
                _eq("C",  "c0 + c1*(Y - T)"),
                _eq("I",  "I0 - b*r"),
                _eq("r",  "r_star"),               # interest parity
                _eq("NX", "x0 + x1*e - m0 - m1*Y"),
                _eq("Y",  "C + I + G + NX"),
            ]
            chaves = ("c0", "c1", "T", "I0", "b", "G", "r_star", "x0", "x1", "e", "m0", "m1")

        else:
            # Mobilidade imperfeita: IS + NX + BP (sem LM explícita)
            # Endógenas: C, I, NX, Y, r
            equacoes = [
                _eq("C",  "c0 + c1*(Y - T)"),
                _eq("I",  "I0 - b*r"),
                _eq("NX", "x0 + x1*e - m0 - m1*Y"),
                _eq("Y",  "C + I + G + NX"),
                _eq("r",  "r_star - NX/kf"),       # BP: balanço de pagamentos
            ]
            chaves = ("c0", "c1", "T", "I0", "b", "G", "r_star", "kf",
                      "x0", "x1", "e", "m0", "m1")

        parametros = {k: float(config[k]) for k in chaves if k in config}
        return equacoes, parametros
