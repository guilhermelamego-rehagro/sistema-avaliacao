"""
Importa usuários da aba Base_Alunos (Google Sheets) para o Supabase Auth + perfis_usuario.

Uso (na pasta sistema-avaliacao):
    python scripts/import_usuarios_supabase.py --dry-run
    python scripts/import_usuarios_supabase.py
    python scripts/import_usuarios_supabase.py --email usuario@rehagro.edu.br

Requisitos:
    pip install supabase gspread oauth2client pandas tomli
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import gspread
import pandas as pd
from oauth2client.service_account import ServiceAccountCredentials
from supabase import create_client

ROOT = Path(__file__).resolve().parents[1]
SECRETS_PATH = ROOT / ".streamlit" / "secrets.toml"

PERFIS_VALIDOS = {"Aluno", "Professor", "Secretaria"}
TIPOS_PROFESSOR = {"Orientador", "Especialista", "Ambos"}


def carregar_secrets() -> dict:
    try:
        import tomllib
    except ModuleNotFoundError:
        import tomli as tomllib

    with open(SECRETS_PATH, "rb") as f:
        return tomllib.load(f)


def ambiente_planilha(secrets: dict) -> str:
    valor = secrets.get("ambiente")
    if valor is None:
        valor = secrets.get("planilhas", {}).get("ambiente")
    if valor is None:
        valor = secrets.get("gcp_service_account", {}).get("ambiente")
    ambiente = str(valor or "teste").strip().lower()
    if ambiente in {"producao", "produção", "production", "prod"}:
        return "producao"
    return "teste"


def conectar_planilha(secrets: dict):
    escopo = [
        "https://spreadsheets.google.com/feeds",
        "https://www.googleapis.com/auth/drive",
    ]
    creds = ServiceAccountCredentials.from_json_keyfile_dict(
        secrets["gcp_service_account"], escopo
    )
    cliente = gspread.authorize(creds)
    chave = "id_producao" if ambiente_planilha(secrets) == "producao" else "id_teste"
    return cliente.open_by_key(secrets["planilhas"][chave])


def normalizar_perfil(valor: str) -> str | None:
    perfil = str(valor or "").strip().title()
    if perfil == "Aluno":
        return "Aluno"
    if perfil == "Professor":
        return "Professor"
    if perfil in {"Secretaria", "Secretária"}:
        return "Secretaria"
    return None


def normalizar_tipo_professor(valor) -> str | None:
    if valor is None or (isinstance(valor, float) and pd.isna(valor)):
        return None
    tipo = str(valor).strip().title()
    if tipo in TIPOS_PROFESSOR:
        return tipo
    if tipo in {"", "Nan", "None"}:
        return None
    return None


def ler_base_alunos(planilha) -> pd.DataFrame:
    df = pd.DataFrame(planilha.worksheet("Base_Alunos").get_all_records())
    if df.empty:
        return df

    df.columns = [str(c).strip() for c in df.columns]
    return df


def filtrar_usuarios_ativos(df: pd.DataFrame, email_filtro: str | None) -> pd.DataFrame:
    col_status = "Status_Geral"
    col_email = "Email_Pessoal"
    col_nome = "Nome_Completo"
    col_perfil = "Perfil"

    obrigatorias = [col_email, col_nome, col_perfil, col_status]
    faltando = [c for c in obrigatorias if c not in df.columns]
    if faltando:
        raise ValueError(f"Colunas ausentes em Base_Alunos: {faltando}")

    ativos = df[df[col_status].astype(str).str.strip().str.lower() == "ativo"].copy()
    ativos["email"] = ativos[col_email].astype(str).str.strip().str.lower()
    ativos["nome"] = ativos[col_nome].astype(str).str.strip()
    ativos["perfil"] = ativos[col_perfil].apply(normalizar_perfil)

    col_tipo = None
    for candidata in ("Tipo_Professor", "Tipo Professor", "Tipo"):
        if candidata in ativos.columns:
            col_tipo = candidata
            break

    if col_tipo:
        ativos["tipo_professor"] = ativos[col_tipo].apply(normalizar_tipo_professor)
    else:
        ativos["tipo_professor"] = None

    ativos = ativos[ativos["perfil"].isin(PERFIS_VALIDOS)]
    ativos = ativos[ativos["email"].str.contains("@", na=False)]

    if email_filtro:
        ativos = ativos[ativos["email"] == email_filtro.strip().lower()]

    return ativos.drop_duplicates(subset=["email"], keep="first")


def listar_emails_auth(admin_client) -> set[str]:
    emails = set()
    pagina = 1
    while True:
        resposta = admin_client.auth.admin.list_users(page=pagina, per_page=200)
        usuarios = resposta if isinstance(resposta, list) else getattr(resposta, "users", [])
        if not usuarios:
            break
        for usuario in usuarios:
            email = getattr(usuario, "email", None)
            if email:
                emails.add(email.lower())
        if len(usuarios) < 200:
            break
        pagina += 1
    return emails


def perfil_ja_existe(admin_client, user_id: str) -> bool:
    resposta = (
        admin_client.table("perfis_usuario")
        .select("id")
        .eq("id", user_id)
        .limit(1)
        .execute()
    )
    return bool(resposta.data)


def obter_usuario_auth_por_email(admin_client, email: str):
    pagina = 1
    email = email.lower()
    while True:
        resposta = admin_client.auth.admin.list_users(page=pagina, per_page=200)
        usuarios = resposta if isinstance(resposta, list) else getattr(resposta, "users", [])
        if not usuarios:
            return None
        for usuario in usuarios:
            if getattr(usuario, "email", "").lower() == email:
                return usuario
        if len(usuarios) < 200:
            return None
        pagina += 1


def importar_usuario(admin_client, row, senha: str, emails_auth: set[str], dry_run: bool) -> str:
    email = row["email"]
    nome = row["nome"]
    perfil = row["perfil"]
    tipo_professor = row.get("tipo_professor")

    if perfil == "Professor" and not tipo_professor:
        tipo_professor = "Orientador"
    if perfil != "Professor":
        tipo_professor = None

    payload_perfil = {
        "email": email,
        "nome": nome,
        "perfil": perfil,
        "tipo_professor": tipo_professor,
        "deve_trocar_senha": True,
        "ativo": True,
    }

    if email in emails_auth:
        if dry_run:
            return f"DRY-RUN: perfil existente ou a criar para {email} | {perfil}"
        usuario = obter_usuario_auth_por_email(admin_client, email)
        if not usuario:
            return f"ERRO: auth existe mas usuário não encontrado: {email}"
        if perfil_ja_existe(admin_client, usuario.id):
            return f"PULADO (já existe): {email}"
        admin_client.table("perfis_usuario").insert({"id": usuario.id, **payload_perfil}).execute()
        return f"PERFIL CRIADO: {email} | {perfil} | tipo={tipo_professor}"

    if dry_run:
        return f"DRY-RUN: criaria {email} | {perfil} | tipo={tipo_professor}"

    try:
        criado = admin_client.auth.admin.create_user(
            {
                "email": email,
                "password": senha,
                "email_confirm": True,
                "user_metadata": {"nome": nome, "perfil": perfil},
            }
        )
        user_id = criado.user.id
    except Exception as e:
        if "already been registered" in str(e):
            usuario = obter_usuario_auth_por_email(admin_client, email)
            if usuario and not perfil_ja_existe(admin_client, usuario.id):
                admin_client.table("perfis_usuario").insert(
                    {"id": usuario.id, **payload_perfil}
                ).execute()
                return f"PERFIL CRIADO (auth existia): {email}"
            return f"PULADO (já existe): {email}"
        raise

    admin_client.table("perfis_usuario").insert({"id": user_id, **payload_perfil}).execute()
    return f"OK: {email} | {perfil} | tipo={tipo_professor}"


def main():
    parser = argparse.ArgumentParser(description="Importa usuários Base_Alunos -> Supabase")
    parser.add_argument("--dry-run", action="store_true", help="Só simula, não grava")
    parser.add_argument("--email", help="Importa apenas um e-mail")
    parser.add_argument(
        "--senha",
        help="Senha temporária (padrão: secrets.senha_temporaria_padrao ou rehagro2026)",
    )
    args = parser.parse_args()

    if not SECRETS_PATH.exists():
        print(f"Arquivo não encontrado: {SECRETS_PATH}")
        sys.exit(1)

    secrets = carregar_secrets()
    senha = args.senha or secrets.get("supabase", {}).get("senha_temporaria_padrao") or secrets.get(
        "senha_temporaria_padrao", "rehagro2026"
    )

    supa = secrets["supabase"]
    admin_client = create_client(supa["url"], supa["service_role_key"])

    planilha = conectar_planilha(secrets)
    df = ler_base_alunos(planilha)
    usuarios = filtrar_usuarios_ativos(df, args.email)

    if usuarios.empty:
        print("Nenhum usuário ativo encontrado para importar.")
        sys.exit(0)

    print(f"Ambiente planilha: {ambiente_planilha(secrets)}")
    print(f"Usuários a processar: {len(usuarios)}")
    if args.dry_run:
        print("Modo DRY-RUN — nada será gravado no Supabase.\n")

    emails_auth = listar_emails_auth(admin_client)

    for _, row in usuarios.iterrows():
        try:
            msg = importar_usuario(admin_client, row, senha, emails_auth, args.dry_run)
            print(msg)
        except Exception as e:
            print(f"ERRO em {row['email']}: {e}")


if __name__ == "__main__":
    main()
