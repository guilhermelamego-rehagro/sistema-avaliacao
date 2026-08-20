"""
Copia o cadastro acadêmico da planilha de teste para a de produção.

Não apaga notas, avaliações, Entrância nem a planilha de frequência.
Só substitui as abas listadas em ABAS_CADASTRO.

Uso (na pasta sistema-avaliacao):
    python scripts/copiar_teste_para_producao.py --dry-run
    python scripts/copiar_teste_para_producao.py --confirmar
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

import gspread
from gspread.exceptions import APIError, WorksheetNotFound
from oauth2client.service_account import ServiceAccountCredentials

ROOT = Path(__file__).resolve().parents[1]
SECRETS_PATH = ROOT / ".streamlit" / "secrets.toml"
ESCOPO = [
    "https://spreadsheets.google.com/feeds",
    "https://www.googleapis.com/auth/drive",
]

ABAS_CADASTRO = [
    "Disciplinas",
    "Encontro_Presencial_Datas",
    "Matrizes",
    "Matriz_Itens",
    "Carrosseis",
    "Carrossel_Itens",
    "Turmas",
    "Trimestres",
    "Ofertas",
    "Oferta_Turmas",
    "Oferta_Excecoes",
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


def com_retry(func, *args, max_tentativas: int = 6, **kwargs):
    for tentativa in range(max_tentativas):
        try:
            return func(*args, **kwargs)
        except APIError as exc:
            status = getattr(getattr(exc, "response", None), "status_code", None)
            if status == 429 and tentativa < max_tentativas - 1:
                espera = 8 * (tentativa + 1)
                print(f"  Limite da API (429). Aguardando {espera}s...")
                time.sleep(espera)
                continue
            raise


def copiar_aba(origem, destino, nome: str, dry_run: bool) -> str:
    try:
        ws_o = origem.worksheet(nome)
    except WorksheetNotFound:
        return "ausente no teste - pulada"

    valores = com_retry(ws_o.get_all_values)
    n_linhas = max(len(valores) - 1, 0) if valores else 0
    n_cols = len(valores[0]) if valores else 0
    extra = f"{n_linhas} linha(s), {n_cols} coluna(s)"

    try:
        destino.worksheet(nome)
        destino_existe = True
    except WorksheetNotFound:
        destino_existe = False

    if dry_run:
        acao = "substituiria aba existente" if destino_existe else "criaria aba"
        return f"{extra} -> {acao}"

    if not destino_existe:
        ws_d = com_retry(
            destino.add_worksheet,
            title=nome,
            rows=max(len(valores) + 20, 50),
            cols=max(n_cols, 8),
        )
    else:
        ws_d = destino.worksheet(nome)

    com_retry(ws_d.clear)
    if valores:
        com_retry(
            ws_d.update,
            range_name="A1",
            values=valores,
            value_input_option="USER_ENTERED",
        )
    return f"{extra} -> gravada em producao"


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Copia disciplinas, matriz, carrosséis, turmas e ofertas do teste para produção."
    )
    parser.add_argument("--dry-run", action="store_true", help="Só lista; não grava.")
    parser.add_argument(
        "--confirmar",
        action="store_true",
        help="Grava nas abas de cadastro da planilha de produção.",
    )
    args = parser.parse_args()
    if not args.dry_run and not args.confirmar:
        print("Use --dry-run para conferir ou --confirmar para gravar em produção.")
        return 1

    secrets = carregar_secrets()
    ids = secrets["planilhas"]
    id_prod = ids["id_producao"]
    id_teste = ids["id_teste"]
    if id_prod == id_teste:
        print("id_producao e id_teste estão iguais. Abortando.")
        return 1

    cliente = cliente_gspread(secrets)
    origem = cliente.open_by_key(id_teste)
    destino = cliente.open_by_key(id_prod)
    print(f"Origem  (teste):     {origem.title}  [{origem.id}]")
    print(f"Destino (produção):  {destino.title}  [{destino.id}]")
    print("Frequência, notas, Entrância e ciclos: não alterados.")
    print()

    for nome in ABAS_CADASTRO:
        print(f"{nome}...", end=" ", flush=True)
        msg = copiar_aba(origem, destino, nome, dry_run=args.dry_run)
        print(msg)
        time.sleep(0.5)

    if args.dry_run:
        print("\nDry-run: nada foi gravado.")
    else:
        print("\nCadastro copiado para produção. Recarregue o app de produção.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
