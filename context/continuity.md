# Continuidade do MaphiApp

Atualizado em 18/11/2026.

## Objetivo e decisões atuais

O MaphiApp é um aplicativo de catálogo e venda de bolos, com acesso de cliente
e administração do dono. A persistência transacional foi migrada de Firestore
para PostgreSQL no Supabase, atendendo à exigência de banco SQL e mantendo o
projeto dentro do uso pretendido de baixo custo. Firebase Authentication e
Firebase Storage continuam em uso.

O cliente não acessa a API REST do Supabase. As operações de catálogo, estoque,
locais de retirada, reservas e perfis passam pela Cloud Function, que valida o
Firebase ID token e acessa PostgreSQL diretamente no servidor. O papel
autoritativo está em `public.users.role`; a Function sincroniza esse papel em
`users/{uid}` no Firestore exclusivamente para as regras de acesso às imagens no
Firebase Storage.

## Arquitetura

O app segue MVC organizado por feature, sem uma migração estrutural pendente:

- Views Flet ficam em `*_view.py`.
- Models, regras de negócio e controllers das features ficam principalmente em
  `*_logic.py`.
- `MaphiApplication` coordena navegação, permissões e sincronização entre
  features.
- `maphi_api.py` concentra as chamadas autenticadas à Cloud Function.
- Firebase Authentication e Storage permanecem na integração Firebase do app.

O README contém o mapeamento mais detalhado das responsabilidades e os passos de
configuração: [README.md](../README.md).

## Backend e dados

- A implementação da API está em `functions/api.py`; ela usa Firebase Admin
  para validar tokens e `psycopg` para conversar diretamente com PostgreSQL.
- O schema para bancos novos está em `context/schema_supabase.sql`.
- A migração de bancos existentes está em
  `context/migration_supabase_app_alignment.sql`. Ela não inventa preços:
  sabores sem preço precisam ser corrigidos antes de aceitar reservas.
- As tabelas habilitam RLS sem políticas para bloquear acesso pela Data API do
  Supabase; o backend usa uma conexão de servidor.
- O segredo `SUPABASE_DB_URL` deve ficar no Secret Manager, não no app nem no
  repositório. `functions/.env` é reservado às configurações Web públicas do
  Firebase no formato dotenv.
- As rotas privadas exigem `Authorization: Bearer <Firebase ID token>`. A
  autorização de operações administrativas é verificada pela role no banco.
- Uma reserva com vários sabores/unidades é criada como uma única reserva e
  processada na mesma transação. Preço, cliente e local são preservados em
  snapshots.
- O estoque administrativo distingue unidades disponíveis e reservadas. A
  remoção em lote altera atomicamente apenas unidades disponíveis; para remover
  unidades reservadas, o dono precisa primeiro cancelar a reserva relacionada.
- O endpoint de cadastro de estoque aceita lotes de até 500 unidades por sabor.
- As datas dos locais devem incluir fuso horário; as janelas de retirada têm
  duração mínima de 15 minutos.

## App e responsividade

- O catálogo, estoque, locais, reservas e perfis carregam pela Cloud Function.
- A autenticação continua no Firebase Authentication; imagens continuam no
  Firebase Storage.
- A interface é mobile-first. Abaixo de 768 px, a escolha de local de retirada
  usa BottomSheet; em tablet e desktop usa AlertDialog.
- Cadastro de produção, novo local e novo sabor abrem formulários adaptáveis em
  tela cheia no mobile e mantêm o diálogo em telas maiores.
- Os cards de reserva usam largura fluida e conteúdo/ações adaptáveis para
  evitar textos cortados em mobile.

## Validação recente

- A última suíte executada após os ajustes responsivos passou com 70 testes.
- Os testes do app agora espelham a organização por feature em
  `tests/features/`, com diretórios separados para aplicação, configuração e
  infraestrutura.
- Após a reorganização dos arquivos, os mesmos 70 testes passaram novamente.
- O build web Flet terminou com sucesso.
- `git diff --check` passou.
- A documentação MVC foi atualizada no README.

Esses resultados são da árvore local. Não há confirmação de que o schema ou a
migração tenham sido aplicados no Supabase, nem de que as alterações mais
recentes da API e do app tenham sido publicadas. Versões anteriores podem já
estar implantadas; confira o estado remoto antes de fazer novo deploy.

## Próximos passos ao retomar

1. Verificar no Supabase se o schema atual ou a migração de alinhamento já foi
   aplicado; preencher preços existentes que ainda estejam nulos.
2. Conferir os segredos e a configuração Firebase, sem copiar credenciais para
   o repositório.
3. Publicar a Cloud Function e o Hosting quando banco e configuração estiverem
   prontos. Publicar somente Hosting não atualiza a Function.
4. Fazer um teste integrado de login, perfil, catálogo, estoque, reserva com
   vários sabores, cancelamento e fluxo de imagens.

Consulte [README.md](../README.md) para os comandos de deploy e configuração.
