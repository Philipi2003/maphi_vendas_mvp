# Contexto de continuidade do MaphiApp

Este arquivo registra o estado de desenvolvimento e as decisões tomadas nas conversas de trabalho, para retomar o projeto em outra sessão ou computador. Os documentos de visão e implementação continuam em `maphiapp_context.md` e `gemini_context.md`.

## Objetivo e escopo

O MaphiApp é um MVP para divulgar bolos disponíveis e permitir que clientes reservem unidades. A aplicação está sendo construída em Python com Flet e Firebase.

Incluído no MVP:

- Catálogo público de bolos, incluindo itens disponíveis e esgotados.
- Seleção de quantidade para itens disponíveis e início do fluxo de reserva.
- Autenticação de clientes e conta de dono.
- Publicação e gerenciamento de itens pelo dono.
- Reservas sem permitir que uma unidade seja reservada duas vezes.
- Clientes não têm limite total de unidades em reservas ativas.
- Cada documento de reserva contém até duas unidades; seleções maiores são
  divididas em várias reservas para que as regras Firestore validem cada item.
- Donos também podem criar reservas para vendas presenciais.

Fora do escopo atual:

- Encomendas de bolos.
- Limite máximo de reservas por cliente.

## Stack e infraestrutura

- Python e Flet para a interface.
- Firebase Hosting para publicar o build web, gerado em `build/web`.
- Firebase Authentication e Cloud Firestore previstos para autenticação e dados.
- A configuração Firebase do projeto está associada ao projeto `maphivendas`.
- `firebase.json` configura Hosting e Firestore Rules.
- As regras ficam em `firestore.rules`. Elas identificam o dono pelo campo `users/{uid}.role == "DONO"`; o próprio usuário não pode definir ou alterar seu papel.
- O SDK `firebase-admin` não deve ser usado no cliente WebAssembly. A estratégia documentada para o cliente é chamar as APIs REST do Firebase e confiar nas Security Rules. Não colocar segredos no código cliente.

## Estado atual

O projeto está modularizado por feature:

- `src/main.py`: inicialização do Flet.
- `src/app_config.py`: configuração e tema da aplicação.
- `src/application.py`: composição das features e coordenação de eventos compartilhados.
- `src/features/catalog/catalog_view.py` e `catalog_logic.py`: interface e lógica do catálogo demonstrativo.
- `src/features/auth/auth_view.py` e `auth_logic.py`: interface responsiva e estado demonstrativo da autenticação.
- `src/features/auth/account_button_view.py`: botão “Entrar”/nome do usuário no cabeçalho, pertencente à feature de autenticação.

Autenticação, catálogo, estoque, locais de retirada e reservas estão conectados ao
Firebase pelas APIs REST. A sessão salva o refresh token nas preferências do
dispositivo; a senha não é persistida. Reservas criam, cancelam e finalizam
unidades em transações Firestore, preservando o vínculo entre item e reserva.
Clientes veem as próprias reservas; donos veem todas, filtram por local,
cancelam, concluem vendas e removem reservas terminais. Ao remover um local, o
app o desativa, cancela as reservas ativas e só então o exclui.

O login/cadastro abre como tela dedicada em larguras menores que 768 px e como modal em telas maiores ou iguais a 768 px. O modal pode ser fechado clicando fora e possui botão de fechar; a tela de cadastro também possui botão de fechar.

As regras Firestore autorizam as transições da reserva e do estoque em conjunto.
Elas devem ser publicadas no projeto Firebase antes de usar a funcionalidade em
produção.

## Decisões de arquitetura e produto

- Manter `main.py` restrito à inicialização; código de tela e lógica ficam separados por feature.
- O botão de conta do cabeçalho pertence à autenticação; o catálogo recebe o controle pronto, sem conhecer seus detalhes.
- O catálogo é público; operações protegidas dependem de autenticação e autorização.
- Não criar documentos fictícios apenas para materializar coleções Firestore: as coleções aparecem quando o primeiro documento é gravado.
- Não tratar uma operação como concluída se ela ainda for apenas uma demonstração de interface.

## Próximos passos recomendados

1. Publicar e validar as regras Firestore atualizadas no projeto Firebase.
2. Confirmar que a conta do dono tem `users/{uid}.role == "DONO"` atribuído
   administrativamente no Console do Firebase.
3. Testar no ambiente Firebase de produção os fluxos de reserva, cancelamento,
   conclusão da venda e exclusão de locais com reservas.

## Desenvolvimento local

No Windows PowerShell, o README documenta a criação do ambiente virtual e execução com:

```powershell
py -m venv .venv
.\.venv\Scripts\python.exe -m pip install "flet>=1.1.2"
.\.venv\Scripts\flet.exe run --web
```

Para build web, definir `$env:PYTHONUTF8 = "1"` antes de executar:

```powershell
.\.venv\Scripts\flet.exe build web
```

O deploy de Hosting e das regras exige Firebase CLI instalada e autenticada no computador. Não versionar credenciais, tokens ou arquivos de configuração privada.

## Como retomar

1. Ler este arquivo e depois `README.md`.
2. Consultar `maphiapp_context.md` e `gemini_context.md` para requisitos e contexto técnico originais.
3. Verificar os arquivos e o estado atual do projeto antes de implementar; este resumo pode ficar desatualizado.
4. Próxima tarefa sugerida: integrar Firebase Authentication mantendo a arquitetura por feature e verificando build/testes focados.
