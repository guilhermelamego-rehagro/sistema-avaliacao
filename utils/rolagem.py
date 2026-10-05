"""Volta a página ao topo quando a tela muda (o Streamlit mantém a rolagem entre reruns)."""

from __future__ import annotations

import streamlit as st
import streamlit.components.v1 as components

_CHAVE_TELA = "_rolagem_tela_atual"
_CHAVE_NONCE = "_rolagem_nonce"

# Repete por ~2,5 s porque o conteúdo chega aos poucos; para se o usuário rolar.
_SCRIPT = """
<script>
(function () {
  const doc = window.parent.document;
  let cancelado = false;
  const cancelar = () => { cancelado = true; };
  ["wheel", "touchstart", "keydown", "mousedown"].forEach((ev) =>
    doc.addEventListener(ev, cancelar, { once: true, passive: true })
  );
  const topo = () => {
    if (cancelado) return;
    [doc.querySelector('[data-testid="stMain"]'), doc.querySelector("section.main"), doc.scrollingElement]
      .forEach((el) => { if (el) el.scrollTop = 0; });
    window.parent.scrollTo(0, 0);
  };
  topo();
  [100, 300, 600, 1000, 1500, 2500].forEach((t) => setTimeout(topo, t));
})();
</script>
<!-- %s -->
"""


def rolar_topo_ao_trocar_tela(tela: str) -> None:
    if st.session_state.get(_CHAVE_TELA) == tela:
        return
    st.session_state[_CHAVE_TELA] = tela
    nonce = int(st.session_state.get(_CHAVE_NONCE, 0)) + 1
    st.session_state[_CHAVE_NONCE] = nonce
    with st.sidebar:
        components.html(_SCRIPT % nonce, height=0)
