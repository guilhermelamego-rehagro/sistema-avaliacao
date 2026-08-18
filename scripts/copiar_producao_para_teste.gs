/**
 * Cópia semanal: produção -> teste, mantendo o mesmo ID da planilha de teste.
 *
 * Como instalar:
 * 1. Abra a planilha de TESTE no Google Sheets.
 * 2. Extensões > Apps Script.
 * 3. Cole este arquivo e salve.
 * 4. Executar copiarProducaoParaTeste uma vez (autorize a conta).
 * 5. Acionadores (ícone do relógio) > Adicionar acionador:
 *    - Função: copiarProducaoParaTeste
 *    - Tipo: baseado em tempo
 *    - Semanal, no dia/hora que preferir (ex.: segunda 06:00).
 *
 * A conta que autorizar o script precisa ser editor nas duas planilhas.
 * Não copie a planilha de frequência: ela é compartilhada entre os ambientes.
 */
const ID_PRODUCAO = "1miHasJXm7Gs5GwQxP0T2w6kbUipnesXSV90taXVbqtg";
const ID_TESTE = "1Nym-jb1Za1ArIPBEFmZaa3AkfxcqDwdUB9kTKwN9-PE";
const PLACEHOLDER = "_sync_tmp";

function copiarProducaoParaTeste() {
  if (ID_PRODUCAO === ID_TESTE) {
    throw new Error("IDs de produção e teste estão iguais.");
  }

  const origem = SpreadsheetApp.openById(ID_PRODUCAO);
  const destino = SpreadsheetApp.openById(ID_TESTE);
  const abasOrigem = origem.getSheets();

  const placeholder = destino.insertSheet(PLACEHOLDER);
  destino
    .getSheets()
    .filter((aba) => aba.getSheetId() !== placeholder.getSheetId())
    .forEach((aba) => destino.deleteSheet(aba));

  abasOrigem.forEach((aba) => {
    const copiada = aba.copyTo(destino);
    const nome = aba.getName();
    if (copiada.getName() !== nome) {
      copiada.setName(nome);
    }
  });

  destino.deleteSheet(placeholder);
}
