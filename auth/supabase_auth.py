"""Autenticação Supabase para o portal de avaliações."""

from __future__ import annotations

from urllib.parse import parse_qs

import streamlit as st
from supabase import Client, create_client

from auth.url_fragment import ler_fragmento_url

SENHA_MINIMA = 6


@st.cache_resource
def cliente_anon() -> Client:
    return create_client(st.secrets["supabase"]["url"], st.secrets["supabase"]["anon_key"])


@st.cache_resource
def cliente_admin() -> Client:
    return create_client(
        st.secrets["supabase"]["url"], st.secrets["supabase"]["service_role_key"]
    )


def ambiente_app() -> str:
    valor = st.secrets.get("ambiente")
    ambiente = str(valor or "teste").strip().lower()
    if ambiente in {"producao", "produção", "production", "prod"}:
        return "producao"
    return "teste"


def recuperacao_senha_habilitada() -> bool:
    """Em produção fica oculto até liberarmos a Fase 0."""
    flag = st.secrets.get("supabase", {}).get("recuperacao_senha")
    if flag is not None:
        return str(flag).strip().lower() in {"1", "true", "sim", "yes"}
    return ambiente_app() != "producao"


def url_redirect_recuperacao() -> str:
    base = str(
        st.secrets.get("supabase", {}).get("url_app") or "http://localhost:8501"
    ).rstrip("/")
    return f"{base}/?recuperar=1"


def validar_senha(senha: str) -> str | None:
    if len(senha) < SENHA_MINIMA:
        return f"A senha deve ter pelo menos {SENHA_MINIMA} caracteres."
    return None

def restaurar_sessao_supabase() -> Client | None:
    access = st.session_state.get("sb_access_token")
    refresh = st.session_state.get("sb_refresh_token")
    if not access or not refresh:
        return None
    client = cliente_anon()
    try:
        client.auth.set_session(access, refresh)
        return client
    except Exception:
        return None


@st.cache_data(ttl=300, show_spinner=False)
def _buscar_perfil_cached(user_id: str) -> dict | None:
    resposta = (
        cliente_admin()
        .table("perfis_usuario")
        .select("*")
        .eq("id", user_id)
        .limit(1)
        .execute()
    )
    if resposta.data:
        return resposta.data[0]
    return None


def buscar_perfil(user_id: str) -> dict | None:
    return _buscar_perfil_cached(user_id)


def montar_usuario_logado(session, perfil: dict) -> dict:
    return {
        "id": perfil["id"],
        "email": perfil["email"],
        "nome": perfil["nome"],
        "perfil": perfil["perfil"],
        "tipo_professor": perfil.get("tipo_professor"),
        "coordenador": bool(perfil.get("coordenador", False)),
        "deve_trocar_senha": perfil.get("deve_trocar_senha", False),
    }


def fazer_login(email: str, senha: str) -> tuple[dict | None, str | None]:
    email = email.strip().lower()
    client = cliente_anon()
    try:
        auth = client.auth.sign_in_with_password({"email": email, "password": senha})
    except Exception as e:
        msg = str(e)
        if "Invalid login credentials" in msg:
            return None, "E-mail ou senha incorretos."
        return None, "Não foi possível entrar. Tente novamente."

    if not auth.session or not auth.user:
        return None, "Falha na autenticação."

    perfil = buscar_perfil(auth.user.id)
    if not perfil:
        return None, "Usuário autenticado, mas sem perfil cadastrado. Contate o suporte."
    if not perfil.get("ativo", True):
        return None, "Cadastro inativo. Contate a secretaria."

    st.session_state["sb_access_token"] = auth.session.access_token
    st.session_state["sb_refresh_token"] = auth.session.refresh_token
    usuario = montar_usuario_logado(auth.session, perfil)
    st.session_state["usuario_logado"] = usuario
    return usuario, None


def trocar_senha(nova_senha: str) -> str | None:
    erro = validar_senha(nova_senha)
    if erro:
        return erro

    client = restaurar_sessao_supabase()
    if not client:
        return "Sessão expirada. Faça login novamente."

    try:
        client.auth.update_user({"password": nova_senha})
    except Exception as e:
        return f"Não foi possível alterar a senha: {e}"

    user_id = st.session_state["usuario_logado"]["id"]
    cliente_admin().table("perfis_usuario").update(
        {"deve_trocar_senha": False}
    ).eq("id", user_id).execute()

    st.session_state["usuario_logado"]["deve_trocar_senha"] = False
    st.session_state.pop("_recuperacao_senha", None)
    return None


def _senha_temporaria_padrao() -> str:
    return str(
        st.secrets.get("supabase", {}).get("senha_temporaria_padrao")
        or st.secrets.get("senha_temporaria_padrao")
        or "rehagro2026"
    )


def _flag_deve_trocar_senha(valor) -> bool:
    if valor is True:
        return True
    if valor is False or valor is None:
        return False
    return str(valor).strip().lower() in {"true", "1", "sim", "yes", "t"}


def _buscar_perfil_por_email(email: str) -> dict | None:
    """Busca perfil por e-mail (case-insensitive)."""
    res = (
        cliente_admin()
        .table("perfis_usuario")
        .select("id, email, deve_trocar_senha, ativo")
        .ilike("email", email)
        .limit(1)
        .execute()
    )
    if res.data:
        return res.data[0]
    # Fallback: alguns projetos gravam e-mail com espaços/casing diferente.
    res2 = (
        cliente_admin()
        .table("perfis_usuario")
        .select("id, email, deve_trocar_senha, ativo")
        .eq("email", email)
        .limit(1)
        .execute()
    )
    if res2.data:
        return res2.data[0]
    return None


def solicitar_recuperacao_senha(email: str) -> tuple[str, str | None]:
    """
    Solicita redefinição de senha.

    Retorna (tipo, mensagem):
      - ("email_enviado", None) — disparou o e-mail do Supabase
      - ("senha_temporaria", senha) — ainda deve trocar senha; não envia e-mail
      - ("erro", msg) — falha / validação
    """
    email = email.strip().lower()
    if not email or "@" not in email:
        return "erro", "Informe um e-mail válido."

    # Quem nunca trocou a senha temporária: orientar sem gastar SMTP.
    try:
        perfil = _buscar_perfil_por_email(email)
    except Exception as exc:
        if ambiente_app() != "producao":
            return (
                "erro",
                "Não foi possível consultar o perfil para atalhar a senha temporária. "
                f"Detalhe (teste): {exc}",
            )
        perfil = None

    if perfil is not None and _flag_deve_trocar_senha(perfil.get("deve_trocar_senha")):
        # Segundo valor = senha temporária (a UI monta o destaque visual).
        return "senha_temporaria", _senha_temporaria_padrao()

    client = cliente_anon()
    try:
        client.auth.reset_password_for_email(
            email,
            {"redirect_to": url_redirect_recuperacao()},
        )
    except Exception as exc:
        msg = str(exc).lower()
        # Cota do e-mail embutido do Supabase é baixa; após vários testes some o envio.
        if any(
            trecho in msg
            for trecho in (
                "rate",
                "429",
                "over_email",
                "email rate",
                "too many",
                "exceeded",
            )
        ):
            return (
                "erro",
                "O Supabase limitou o envio de e-mails por excesso de tentativas. "
                "Aguarde alguns minutos (às vezes 1h) e tente de novo, "
                "ou configure SMTP próprio no painel Auth → Emails.",
            )
        if ambiente_app() != "producao":
            return (
                "erro",
                "Não foi possível solicitar a redefinição. "
                f"Detalhe (só no ambiente de teste): {exc}",
            )
        # Em produção: mensagem genérica (não revelar se o e-mail existe).
        return "email_enviado", None
    return "email_enviado", None


def _ativar_sessao_recuperacao(access_token: str, refresh_token: str) -> str | None:
    client = cliente_anon()
    try:
        client.auth.set_session(access_token, refresh_token)
        user = client.auth.get_user()
    except Exception:
        return "Link inválido ou expirado. Solicite uma nova redefinição."

    user_id = getattr(getattr(user, "user", None), "id", None)
    if not user_id:
        return "Não foi possível validar o link de recuperação."

    perfil = buscar_perfil(user_id)
    if not perfil:
        return "Usuário autenticado, mas sem perfil cadastrado. Contate o suporte."
    if not perfil.get("ativo", True):
        return "Cadastro inativo. Contate a secretaria."

    st.session_state["sb_access_token"] = access_token
    st.session_state["sb_refresh_token"] = refresh_token
    st.session_state["usuario_logado"] = montar_usuario_logado(None, perfil)
    st.session_state["_recuperacao_senha"] = True
    return None


def _limpar_params_recuperacao() -> None:
    for chave in (
        "recuperar",
        "access_token",
        "refresh_token",
        "type",
        "token_hash",
        "token",
    ):
        try:
            del st.query_params[chave]
        except Exception:
            pass


def processar_retorno_recuperacao() -> str | None:
    """
    Lê retorno do e-mail de reset.
    Retorna:
      None — nada a fazer ou sessão de recovery já ativada
      "_pending" — aguardando hash/redirect (UI de espera no app)
      str — mensagem de erro
    """
    if not recuperacao_senha_habilitada():
        return None
    if st.session_state.get("_recuperacao_senha"):
        return None
    if st.session_state.get("usuario_logado"):
        return None

    params = st.query_params
    token_hash = params.get("token_hash") or params.get("token")
    tipo = (params.get("type") or "").lower()
    access = params.get("access_token")
    refresh = params.get("refresh_token") or ""
    veio_recuperar = params.get("recuperar") == "1"

    # 1) Query params (após o JS promover o hash, ou SMTP customizado)
    if token_hash and tipo in {"recovery", "email"}:
        client = cliente_anon()
        try:
            auth = client.auth.verify_otp(
                {"token_hash": token_hash, "type": "recovery"}
            )
        except Exception:
            return "Link inválido ou expirado. Solicite uma nova redefinição."
        if not auth.session:
            return "Link inválido ou expirado. Solicite uma nova redefinição."
        erro = _ativar_sessao_recuperacao(
            auth.session.access_token, auth.session.refresh_token or ""
        )
        _limpar_params_recuperacao()
        return erro

    if access and (tipo == "recovery" or veio_recuperar):
        erro = _ativar_sessao_recuperacao(access, refresh)
        _limpar_params_recuperacao()
        return erro

    # 2) Hash da URL — só quando o redirect trouxe ?recuperar=1
    if not veio_recuperar:
        return None

    fragmento = ler_fragmento_url()
    if fragmento is None or fragmento == "redirecting":
        return "_pending"

    bruto = fragmento[1:] if fragmento.startswith("#") else fragmento
    # Só ?recuperar=1 sem hash: usuário pedindo de novo / URL residual — não é erro.
    if not bruto or "access_token" not in bruto:
        return None

    parsed = {k: v[0] for k, v in parse_qs(bruto).items() if v}
    tipo_hash = (parsed.get("type") or "").lower()
    access_hash = parsed.get("access_token") or ""
    refresh_hash = parsed.get("refresh_token") or ""
    if access_hash and (tipo_hash == "recovery" or veio_recuperar):
        erro = _ativar_sessao_recuperacao(access_hash, refresh_hash)
        _limpar_params_recuperacao()
        st.session_state.pop("_url_fragment_key", None)
        st.session_state.pop("_url_fragment_tentativas", None)
        return erro

    return "Link inválido ou expirado. Solicite uma nova redefinição."


def fazer_logout():
    client = restaurar_sessao_supabase()
    if client:
        try:
            client.auth.sign_out()
        except Exception:
            pass

    for chave in list(st.session_state.keys()):
        del st.session_state[chave]


def professor_e_orientador(usuario: dict) -> bool:
    if usuario.get("perfil") != "Professor":
        return False
    tipo = usuario.get("tipo_professor") or "Orientador"
    return tipo in {"Orientador", "Ambos"}


def professor_e_especialista(usuario: dict) -> bool:
    if usuario.get("perfil") != "Professor":
        return False
    tipo = usuario.get("tipo_professor") or "Orientador"
    return tipo in {"Especialista", "Ambos", "Orientador"}


def usuario_e_coordenador(usuario: dict) -> bool:
    if usuario.get("perfil") != "Professor":
        return False
    if usuario.get("coordenador"):
        return True
    emails_cfg = st.secrets.get("coordenacao", {}).get("emails", [])
    email = str(usuario.get("email", "")).lower().strip()
    return email in [str(e).lower().strip() for e in emails_cfg]
