"""
Configuração global do pipeline econômico do OikosLab.

Altere estas variáveis para controlar o comportamento da validação
sem tocar no código do pipeline.
"""

# Ativa ou desativa completamente a validação econômica.
# False → aplicar_validacao_economica retorna [] sem rodar nada.
ECONOMIC_VALIDATION_ENABLED: bool = True

# Controla o comportamento ao detectar violação de restrição:
#   "warning"   → adiciona ao campo economia.warnings, nunca bloqueia execução
#   "fail_fast" → lança EconomicValidationError imediatamente
ECONOMIC_VALIDATION_MODE: str = "warning"
