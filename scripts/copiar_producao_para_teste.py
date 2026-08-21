"""
Copia o conteúdo da planilha Sistema_Avaliacao de produção para a de teste,
mantendo o mesmo ID da planilha de teste (o app local continua funcionando).

Não altera a planilha de frequência (ela é compartilhada entre os ambientes).

Uso (na pasta sistema-avaliacao):
    python scripts/copiar_producao_para_teste.py --dry-run
    python scripts/copiar_producao_para_teste.py --corrigir-nomes
    python scripts/copiar_producao_para_teste.py --confirmar

Aviso: apaga todas as abas atuais da planilha de teste e as substitui
pelas de produção (dados, fórmulas e formatação).
"""

from __future__ import annotations

import argparse
import re
import sys
import time
from pathlib import Path

import gspread
from gspread.exceptions import APIError
from oauth2client.service_account import ServiceAccountCredentials

ROOT = Path(__file__).resolve().parents[1]
SECRETS_PATH = ROOT / ".streamlit" / "secrets.toml"
PLACEHOLDER = "_sync_tmp"
PREFIXO_COPIA = re.compile(r"^(c[oó]pia de |copy of )+", re.IGNORECASE)
ESCOPO = [
    "https://spreadsheets.google.com/feeds",
    "https://www.googleapis.com/auth/drive",
]


def carregar_secrets() -> dict:
    try:
        import tomllib
    except ModuleNotFoundError:
        import tomli as tomllib

    with open(SECRETS_PATH, "rb") as f:
        return tomllib.load(f)


def cliente_gspread(secrets: dict):
    creds = ServiceAccountCredentials.from_json_keyfile_dict(
        secrets["gcp_service_account"], ESCOPO
    )
    return gspread.authorize(creds)


def _status_api(exc: APIError):
    resp = getattr(exc, "response", None)
    if resp is None:
        return None
    for attr in ("status_code", "status", "code"):
        valor = getattr(resp, attr, None)
        if valor is not None:
            try:
                return int(valor)
            except (TypeError, ValueError):
                continue
    return None


def com_retry(func, *args, max_tentativas: int = 10, **kwargs):
    retriaveis = {429, 500, 502, 503, 504}
    for tentativa in range(max_tentativas):
        try:
            return func(*args, **kwargs)
        except APIError as exc:
            status = _status_api(exc)
            if status in retriaveis and tentativa < max_tentativas - 1:
                espera = min(2**tentativa + 5, 90)
                print(f"  Limite/falha da API ({status}). Aguardando {espera}s...")
                time.sleep(espera)
                continue
            raise


def nome_aba_original(titulo: str) -> str:
    """Remove 'Cópia de' / 'Copy of' (Google Sheets em pt-BR ou en)."""
    return PREFIXO_COPIA.sub("", titulo).strip()


def corrigir_nomes(destino, dry_run: bool) -> None:
    print(f"Destino (teste): {destino.title}  [{destino.id}]")
    alteracoes = []
    for aba in destino.worksheets():
        novo_nome = nome_aba_original(aba.title)
        if novo_nome and novo_nome != aba.title:
            alteracoes.append((aba, novo_nome))
            print(f"  {aba.title} -> {novo_nome}")
        else:
            print(f"  {aba.title}")

    if not alteracoes:
        print("\nNenhuma aba precisa ser renomeada.")
        return
    if dry_run:
        print("\nDry-run: nenhuma aba foi renomeada.")
        return

    for aba, novo_nome in alteracoes:
        com_retry(aba.update_title, novo_nome)
        time.sleep(0.3)
    print("\nNomes corrigidos. O app de teste volta a encontrar as abas.")


def sincronizar(origem, destino, dry_run: bool) -> None:
    abas_origem = origem.worksheets()
    abas_destino = destino.worksheets()
    print(f"Origem  (produção): {origem.title}  [{origem.id}]")
    print(f"Destino (teste):    {destino.title}  [{destino.id}]")
    print(f"Abas na origem:  {len(abas_origem)}")
    print(f"Abas no destino: {len(abas_destino)}")
    for aba in abas_origem:
        print(f"  - {aba.title}")

    if dry_run:
        print("\nDry-run: nenhuma aba foi alterada.")
        return

    print("\nCriando aba temporária no destino...")
    existentes = {ws.title: ws for ws in destino.worksheets()}
    if PLACEHOLDER in existentes:
        placeholder = existentes[PLACEHOLDER]
        print(f"  reutilizando {PLACEHOLDER}")
    else:
        placeholder = com_retry(destino.add_worksheet, title=PLACEHOLDER, rows=1, cols=1)

    print("Removendo abas antigas do teste...")
    for aba in destino.worksheets():
        if aba.id == placeholder.id:
            continue
        print(f"  apagando {aba.title}")
        com_retry(destino.del_worksheet, aba)
        time.sleep(1.0)

    print("Copiando abas de produção...")
    for aba in abas_origem:
        print(f"  copiando {aba.title}")
        props = com_retry(aba.copy_to, destino.id)
        titulo_copiado = (props or {}).get("title") or f"Cópia de {aba.title}"
        if titulo_copiado != aba.title:
            time.sleep(1.0)
            copiada = com_retry(destino.worksheet, titulo_copiado)
            print(f"    {titulo_copiado} -> {aba.title}")
            com_retry(copiada.update_title, aba.title)
        time.sleep(1.5)

    print("Removendo aba temporária...")
    com_retry(destino.del_worksheet, placeholder)
    print("\nCópia concluída. A planilha de teste agora espelha a de produção.")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Copia Sistema_Avaliacao de produção para a planilha de teste."
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Só lista as abas; não altera a planilha de teste.",
    )
    parser.add_argument(
        "--confirmar",
        action="store_true",
        help="Obrigatório para gravar: apaga o conteúdo atual do teste.",
    )
    parser.add_argument(
        "--corrigir-nomes",
        action="store_true",
        help="Só remove o prefixo 'Cópia de' / 'Copy of' das abas de teste.",
    )
    args = parser.parse_args()

    if not args.dry_run and not args.confirmar and not args.corrigir_nomes:
        print(
            "Esta operação substitui toda a planilha de teste.\n"
            "Use --dry-run para conferir, --corrigir-nomes para só "
            "renomear, ou --confirmar para copiar de novo."
        )
        return 1

    secrets = carregar_secrets()
    ids = secrets["planilhas"]
    id_prod = ids["id_producao"]
    id_teste = ids["id_teste"]
    if id_prod == id_teste:
        print("id_producao e id_teste estão iguais. Abortando.")
        return 1

    cliente = cliente_gspread(secrets)
    destino = cliente.open_by_key(id_teste)
    if args.corrigir_nomes:
        corrigir_nomes(destino, dry_run=args.dry_run)
        return 0

    origem = cliente.open_by_key(id_prod)
    sincronizar(origem, destino, dry_run=args.dry_run)
    return 0


if __name__ == "__main__":
    sys.exit(main())
