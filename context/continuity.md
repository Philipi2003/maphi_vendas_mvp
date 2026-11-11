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

O catálogo ainda usa dados de demonstração. Login, cadastro, login com Google e reservas ainda não fazem operações reais no Firebase. O estado atual de autenticação é apenas local: `set_authenticated_user(name)` atualiza o nome exibido, sem UID, token ou sessão Firebase.

O login/cadastro abre como tela dedicada em larguras menores que 768 px e como modal em telas maiores ou iguais a 768 px. O modal pode ser fechado clicando fora e possui botão de fechar; a tela de cadastro também possui botão de fechar.

As regras atuais mantêm a criação/alteração de reservas bloqueada. Antes de ativar esse fluxo, implementar uma operação segura e atômica que proteja o estoque contra reservas duplicadas.

## Decisões de arquitetura e produto

- Manter `main.py` restrito à inicialização; código de tela e lógica ficam separados por feature.
- O botão de conta do cabeçalho pertence à autenticação; o catálogo recebe o controle pronto, sem conhecer seus detalhes.
- O catálogo é público; operações protegidas dependem de autenticação e autorização.
- Não criar documentos fictícios apenas para materializar coleções Firestore: as coleções aparecem quando o primeiro documento é gravado.
- Não tratar uma operação como concluída se ela ainda for apenas uma demonstração de interface.

## Próximos passos recomendados

1. Integrar Firebase Authentication ao fluxo de login/cadastro, incluindo e-mail/senha e Google.
2. Modelar sessão autenticada com os dados necessários (UID e token), carregar/criar o perfil `users/{uid}` e atualizar o botão de conta.
3. Decidir e implementar o logout/menu de conta.
4. Carregar os dados do catálogo do Firestore.
5. Projetar a reserva com atualização atômica do estoque e só então habilitar as regras necessárias para criar reservas.
6. Implementar a área do dono para publicar e gerenciar bolos.

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
