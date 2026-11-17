# MaphiApp

Aplicação web em Python com Flet, Firebase Authentication, Firebase Hosting,
Firebase Cloud Functions e PostgreSQL no Supabase.

O catálogo carrega os sabores e o estoque atual do endpoint público da Cloud
Function, que consulta o PostgreSQL no Supabase. Login e reserva ainda não estão
conectados ao Firebase; a interface informa isso explicitamente e não confirma
nenhuma operação real.

O acesso abre uma tela dedicada em aparelhos com largura menor que 768 px e um
modal em telas maiores. Ambos oferecem login por e-mail/senha, acesso com Google
e alternância para cadastro; a autenticação ainda será integrada ao Firebase.

## Organização do código

- `src/main.py`: inicializa o app Flet.
- `src/app_config.py`: configurações da aplicação e tema.
- `src/application.py`: composição das features e estado compartilhado da aplicação.
- `src/features/catalog/catalog_view.py`: interface do catálogo.
- `src/features/catalog/catalog_logic.py`: modelo, filtros e seleção do catálogo.
- `src/features/catalog/catalog_api.py`: leitura e validação da resposta do catálogo.
- `src/features/auth/auth_view.py`: formulários de login/cadastro e layouts responsivos.
- `src/features/auth/auth_logic.py`: estado e regras da interface de autenticação.
- `src/features/auth/account_button_view.py`: botão de login/nome do usuário no cabeçalho.

## Ambiente local (Windows / PowerShell)

```powershell
py -m venv .venv
.\.venv\Scripts\python.exe -m pip install "flet>=1.1.2"
.\.venv\Scripts\flet.exe run --web
```

## Build e deploy

Instale e autentique a Firebase CLI uma vez:

```powershell
npm install -g firebase-tools
firebase login
```

Após associar este diretório ao projeto Firebase, gere os arquivos web e publique:

```powershell
$env:PYTHONUTF8 = "1"
.\.venv\Scripts\flet.exe build web
firebase deploy --only hosting,functions
```

O build é gerado em `build/web`, diretório configurado como origem do Firebase Hosting
em `firebase.json`.

O pacote npm `firebase` não é usado pela interface Python. A autenticação Firebase
é validada no backend; as operações de dados da API usam conexão PostgreSQL direta
com o Supabase, sem a API REST do Supabase.

O build web usa o caminho relativo `/api/v1/catalog`, encaminhado pelo Firebase
Hosting à Cloud Function. O modo desktop usa `https://maphivendas.web.app` por
padrão; para apontá-lo a outro ambiente, defina `MAPHI_API_URL` com a URL base da API.

## API e Supabase

O script de tabelas está em `context/schema_supabase.sql`. Execute-o no SQL Editor
do projeto Supabase antes de chamar a API. A função fica em `functions/` e é
encaminhada pelo Hosting em `/api/**`.

Rotas implementadas:

- `GET /api/v1/catalog` e `GET /api/v1/pickup-spots`: leitura pública.
- `GET|POST /api/v1/profile`: perfil do usuário autenticado.
- `GET|POST /api/v1/reservations` e `POST /api/v1/reservations/{id}/cancel`.
- `/api/v1/admin/item-types`: `GET`, `POST`, `PATCH` e `DELETE`.
- `/api/v1/admin/items`: `POST`, `PATCH` e `DELETE`.
- `/api/v1/admin/pickup-spots`: `GET`, `POST`, `PATCH` e `DELETE`.
- `/api/v1/admin/reservations`: `GET` e `PATCH`.
- As rotas `/api/v1/admin/...` exigem `public.users.role = 'DONO'`.
- `GET /api/v1/health`: verifica se a função está respondendo, sem consultar o banco.

As rotas privadas exigem `Authorization: Bearer <Firebase ID token>`. A função
verifica o token com Firebase Admin e busca o papel no banco; o cliente não pode
se promover a dono. O cadastro/login do Firebase Auth e a conexão dessas rotas à
interface Flet ainda precisam ser integrados.

O corpo de `POST /api/v1/reservations` usa `pickup_spot_id` e uma lista de
`item_ids`. O corpo de `POST /api/v1/admin/items` usa `item_type_id`, `quantity`
e, opcionalmente, `expiration_at`. As datas de locais de retirada devem ser ISO
8601 com fuso horário. A reserva bloqueia as unidades em uma única transação;
unidades reservadas não podem ser removidas ou alteradas pelo endpoint de estoque.

### Configurar e publicar a função

O deploy de Cloud Functions exige o plano Blaze e uma conta de faturamento no
projeto Firebase. Há cotas gratuitas, mas cobranças podem ocorrer se forem
excedidas.

Na primeira configuração, crie o ambiente Python que a Firebase CLI usa para
descobrir a função e instale as dependências:

```powershell
py -m venv functions\venv
.\functions\venv\Scripts\python.exe -m pip install -r functions\requirements.txt
```

Cadastre a connection string PostgreSQL do Supabase como segredo; use a string
do pooler de conexão e não a inclua no app ou no repositório:

```powershell
firebase functions:secrets:set SUPABASE_DB_URL
firebase deploy --only functions,hosting
```

O comando de segredo solicitará o valor de forma interativa. A função está na
região `southamerica-east1`; alinhe essa região à região do banco Supabase se
necessário.

Para testar localmente rotas que acessam o banco, crie `functions/.secret.local`
com `SUPABASE_DB_URL=<connection-string>`. Esse arquivo é ignorado pelo Git e não
deve ser compartilhado. O emulador não acessa automaticamente os segredos do
projeto de produção.

Para criar o perfil inicial do dono, primeiro autentique essa conta e chame
`POST /api/v1/profile`. Depois atribua o papel administrativamente no SQL Editor:

```sql
UPDATE public.users
SET role = 'DONO'
WHERE auth_uid = '<UID_FIREBASE_DO_DONO>';
```

As tabelas têm RLS habilitado sem políticas para bloquear acesso direto pela API
do Supabase. A Cloud Function usa credenciais de banco apenas no servidor; não
coloque a connection string nem credenciais privilegiadas no build web.
