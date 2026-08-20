"""
Copia linhas da aba Ciclos (por disciplina) da planilha de teste para produção.

Substitui só os ciclos da disciplina informada em produção; demais disciplinas
permanecem intactas. Garante colunas novas (Data_Inicio_Ciclo, Data_Apresentacao).

Uso (na pasta sistema-avaliacao):
    python scripts/copiar_ciclos_teste_para_producao.py --disciplina TRIB --dry-run
    python scripts/copiar_ciclos_teste_para_producao.py --disciplina TRIB --confirmar
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
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from domain.cadastros import COLUNAS_CICLOS  # noqa: E402

SECRETS_PATH = ROOT / ".streamlit" / "secrets.toml"
ESCOPO = [
    "https://spreadsheets.google.com/feeds",
    "https://www.googleapis.com/auth/drive",
]
ABA = "Ciclos"


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


def _ler_registros(spreadsheet, aba: str) -> tuple[list[str], list[dict]]:
    ws = spreadsheet.worksheet(aba)
    bruto = com_retry(ws.get_all_values)
    if not bruto:
        return list(COLUNAS_CICLOS), []
    cabecalho = [str(c).strip() for c in bruto[0]]
    linhas = bruto[1:]
    registros: list[dict] = []
    for linha in linhas:
        if not any(str(c).strip() for c in linha):
            continue
        item = {cabecalho[i]: linha[i] if i < len(linha) else "" for i in range(len(cabecalho))}
        registros.append(item)
    return cabecalho, registros


def _norm_id(valor) -> str:
    return str(valor or "").strip()


def _montar_saida(
    cabecalho_prod: list[str],
    registros_prod: list[dict],
    registros_teste_disc: list[dict],
    id_disc: str,
) -> tuple[list[str], list[list[str]]]:
    cabecalho = list(COLUNAS_CICLOS)
    for col in cabecalho_prod:
        if col not in cabecalho:
            cabecalho.append(col)

    resto = [r for r in registros_prod if _norm_id(r.get("ID_Disciplina")) != id_disc]
    merged = resto + registros_teste_disc

    def linha(rec: dict) -> list[str]:
        return [str(rec.get(col, "")).strip() for col in cabecalho]

    valores = [linha(r) for r in merged]
    return cabecalho, valores


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Copia ciclos de uma disciplina da planilha de teste para produção."
    )
    parser.add_argument(
        "--disciplina",
        default="TRIB",
        help="Código da disciplina (ex.: TRIB). Default: TRIB",
    )
    parser.add_argument("--dry-run", action="store_true", help="Só mostra o que seria gravado.")
    parser.add_argument("--confirmar", action="store_true", help="Grava na planilha de produção.")
    args = parser.parse_args()
    if not args.dry_run and not args.confirmar:
        print("Use --dry-run para conferir ou --confirmar para gravar em produção.")
        return 1

    id_disc = _norm_id(args.disciplina)
    if not id_disc:
        print("Informe --disciplina.")
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
    print(f"Disciplina:          {id_disc}")
    print()

    try:
        _, registros_teste = _ler_registros(origem, ABA)
        cab_prod, registros_prod = _ler_registros(destino, ABA)
    except WorksheetNotFound as exc:
        print(f"Aba {ABA} não encontrada: {exc}")
        return 1

    bloco_teste = [r for r in registros_teste if _norm_id(r.get("ID_Disciplina")) == id_disc]
    if not bloco_teste:
        print(f"Nenhum ciclo com ID_Disciplina={id_disc} na planilha de teste.")
        return 1

    n_prod_antes = sum(1 for r in registros_prod if _norm_id(r.get("ID_Disciplina")) == id_disc)
    cabecalho, valores = _montar_saida(cab_prod, registros_prod, bloco_teste, id_disc)

    print(f"Ciclos {id_disc} no teste:     {len(bloco_teste)}")
    print(f"Ciclos {id_disc} em prod (antes): {n_prod_antes}")
    print(f"Total de linhas em prod (depois): {len(valores)}")
    print(f"Colunas: {cabecalho}")
    print()
    for rec in bloco_teste:
        print(
            f"  - {rec.get('ID_Ciclo')} | {rec.get('Nome_Ciclo')} | "
            f"início acad. {rec.get('Data_Inicio_Ciclo', '-')} | "
            f"apresent. {rec.get('Data_Apresentacao', '-')} | "
            f"pares {rec.get('Data início', '-')} -> {rec.get('Data fim', '-')}"
        )

    if args.dry_run:
        print("\nDry-run: nada foi gravado.")
        return 0

    ws = destino.worksheet(ABA)
    com_retry(ws.clear)
    com_retry(
        ws.update,
        range_name="A1",
        values=[cabecalho] + valores,
        value_input_option="USER_ENTERED",
    )
    print(f"\nAba {ABA} atualizada em produção. Recarregue o app (ambiente=producao).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
