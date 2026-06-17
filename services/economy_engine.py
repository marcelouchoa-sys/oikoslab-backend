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

from services.motor_sistemas import resolve_sistema as _resolver_sistema, _split_equacao
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
