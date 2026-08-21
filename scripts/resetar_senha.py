"""
Redefine a senha de um usuário no Supabase (Auth) e volta a exigir troca no 1º acesso.

Linha de comando (na pasta sistema-avaliacao):
    python scripts/resetar_senha.py email.do.usuario@rehagro.edu.br
    python scripts/resetar_senha.py email.do.usuario@rehagro.edu.br --senha rehagro2026

Interface gráfica (atalho na Área de Trabalho ou):
    python scripts/resetar_senha.py
    python scripts/resetar_senha.py --gui
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from supabase import create_client

ROOT = Path(__file__).resolve().parents[1]
SECRETS_PATH = ROOT / ".streamlit" / "secrets.toml"
SENHA_PADRAO = "rehagro2026"


def carregar_secrets() -> dict:
    try:
        import tomllib
    except ModuleNotFoundError:
        import tomli as tomllib

    with open(SECRETS_PATH, "rb") as f:
        return tomllib.load(f)


def resetar_senha(
    email: str,
    senha: str = SENHA_PADRAO,
    *,
    exigir_troca: bool = True,
) -> str:
    """Redefine a senha e retorna mensagem de sucesso. Levanta ValueError/RuntimeError em falha."""
    if not SECRETS_PATH.exists():
        raise FileNotFoundError(f"Arquivo nao encontrado: {SECRETS_PATH}")

    email_norm = email.strip().lower()
    if not email_norm or "@" not in email_norm:
        raise ValueError("Informe um e-mail válido.")

    secrets = carregar_secrets()
    client = create_client(
        secrets["supabase"]["url"],
        secrets["supabase"]["service_role_key"],
    )

    res = (
        client.table("perfis_usuario")
        .select("id, nome, email, perfil, deve_trocar_senha")
        .eq("email", email_norm)
        .limit(1)
        .execute()
    )
    if not res.data:
        raise ValueError(f"Perfil nao encontrado: {email_norm}")

    perfil = res.data[0]
    user_id = perfil["id"]
    client.auth.admin.update_user_by_id(user_id, {"password": senha})
    client.table("perfis_usuario").update({"deve_trocar_senha": exigir_troca}).eq(
        "id", user_id
    ).execute()

    return (
        f"OK: {perfil['nome']} ({email_norm}) | perfil={perfil['perfil']}\n"
        f"Senha redefinida para: {senha}\n"
        f"Troca obrigatoria no proximo login: {exigir_troca}"
    )


def abrir_gui() -> int:
    import tkinter as tk
    from tkinter import messagebox, ttk

    root = tk.Tk()
    root.title("Resetar senha — Sistema de Avaliação")
    root.resizable(False, False)
    root.attributes("-topmost", True)

    frm = ttk.Frame(root, padding=16)
    frm.grid(row=0, column=0, sticky="nsew")

    ttk.Label(frm, text="E-mail do usuário").grid(row=0, column=0, sticky="w")
    email_var = tk.StringVar()
    email_entry = ttk.Entry(frm, textvariable=email_var, width=42)
    email_entry.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(2, 10))
    email_entry.focus_set()

    ttk.Label(frm, text="Nova senha temporária").grid(row=2, column=0, sticky="w")
    senha_var = tk.StringVar(value=SENHA_PADRAO)
    ttk.Entry(frm, textvariable=senha_var, width=42).grid(
        row=3, column=0, columnspan=2, sticky="ew", pady=(2, 10)
    )

    exigir_var = tk.BooleanVar(value=True)
    ttk.Checkbutton(
        frm,
        text="Exigir troca de senha no próximo login",
        variable=exigir_var,
    ).grid(row=4, column=0, columnspan=2, sticky="w", pady=(0, 12))

    status = tk.StringVar(value="")
    ttk.Label(frm, textvariable=status, wraplength=360).grid(
        row=6, column=0, columnspan=2, sticky="w", pady=(8, 0)
    )

    def executar() -> None:
        status.set("Processando…")
        root.update_idletasks()
        try:
            msg = resetar_senha(
                email_var.get(),
                senha_var.get() or SENHA_PADRAO,
                exigir_troca=exigir_var.get(),
            )
            status.set(msg)
            messagebox.showinfo("Senha redefinida", msg, parent=root)
        except Exception as exc:
            status.set(str(exc))
            messagebox.showerror("Erro", str(exc), parent=root)

    btns = ttk.Frame(frm)
    btns.grid(row=5, column=0, columnspan=2, sticky="e")
    ttk.Button(btns, text="Cancelar", command=root.destroy).pack(side="right", padx=(8, 0))
    ttk.Button(btns, text="Resetar senha", command=executar).pack(side="right")

    root.bind("<Return>", lambda _e: executar())
    root.mainloop()
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Redefine senha no Supabase e marca deve_trocar_senha."
    )
    parser.add_argument(
        "email",
        nargs="?",
        help="E-mail do usuário (sem isso, abre a tela gráfica)",
    )
    parser.add_argument(
        "--senha",
        default=SENHA_PADRAO,
        help=f"Nova senha (padrão: {SENHA_PADRAO})",
    )
    parser.add_argument(
        "--sem-troca-obrigatoria",
        action="store_true",
        help="Não exige nova senha no próximo login (não use para aluno real).",
    )
    parser.add_argument(
        "--gui",
        action="store_true",
        help="Abre a tela gráfica pedindo o e-mail.",
    )
    args = parser.parse_args()

    if args.gui or not args.email:
        return abrir_gui()

    try:
        print(resetar_senha(args.email, args.senha, exigir_troca=not args.sem_troca_obrigatoria))
        return 0
    except Exception as exc:
        print(str(exc))
        return 1


if __name__ == "__main__":
    sys.exit(main())
