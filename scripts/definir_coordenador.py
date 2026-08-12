"""Define usuário(s) como coordenador no Supabase (coluna coordenador = true)."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import toml
from supabase import create_client


def carregar_secrets() -> dict:
    caminho = Path(__file__).resolve().parent.parent / ".streamlit" / "secrets.toml"
    if not caminho.exists():
        print(f"Arquivo não encontrado: {caminho}")
        sys.exit(1)
    return toml.load(caminho)


def main():
    parser = argparse.ArgumentParser(description="Marcar e-mail(s) como coordenador no Supabase.")
    parser.add_argument("emails", nargs="+", help="E-mails dos coordenadores")
    parser.add_argument("--remover", action="store_true", help="Remove a função de coordenador")
    args = parser.parse_args()

    secrets = carregar_secrets()
    client = create_client(secrets["supabase"]["url"], secrets["supabase"]["service_role_key"])

    for email in args.emails:
        email = email.strip().lower()
        res = client.table("perfis_usuario").select("id, nome, email").eq("email", email).execute()
        if not res.data:
            print(f"⚠️  Perfil não encontrado: {email}")
            continue
        user_id = res.data[0]["id"]
        nome = res.data[0]["nome"]
        client.table("perfis_usuario").update({"coordenador": not args.remover}).eq("id", user_id).execute()
        acao = "removido de" if args.remover else "definido como"
        print(f"✅ {nome} ({email}) — {acao} coordenador")


if __name__ == "__main__":
    main()
