# MaphiApp

Aplicação web em Python com Flet, Firebase Authentication, Firebase Hosting,
Firebase Cloud Functions e PostgreSQL no Supabase.

O app usa Firebase Authentication para login e Cloud Functions como backend da
aplicação. A função autentica cada requisição com o Firebase ID token e acessa
o PostgreSQL do Supabase diretamente pelo servidor; catálogo, estoque, locais,
reservas e perfis não são lidos nem gravados pela API REST do Supabase.
As imagens do catálogo continuam no Firebase Storage.

O acesso abre uma tela dedicada em aparelhos com largura menor que 768 px e um
modal em telas maiores. Ambos oferecem login por e-mail/senha, acesso com Google
e alternância para cadastro. O fluxo de e-mail/senha já foi integrado ao Firebase
Authentication e usa a Web API Key do projeto para autenticar usuários via REST API.
Credenciais inválidas são informadas diretamente no formulário de login para que
o usuário possa corrigir os dados sem fechar a tela.
Após entrar, o refresh token do Firebase é guardado nas preferências persistentes do
dispositivo pelo Flet. Ao abrir o app novamente, o token é renovado e o perfil é
carregado; sair da conta remove a sessão salva. A senha nunca é armazenada. Como o
refresh token permite recuperar a sessão, ele deve ser tratado como uma credencial:
use o logout em dispositivos compartilhados e limpe os dados do navegador se necessário.

## Configuração do Firebase Authentication

Em PowerShell, defina a Web API key do projeto Firebase antes de iniciar a aplicação:

```powershell
$env:FIREBASE_API_KEY = "SUA_API_KEY_DO_FIREBASE"
```

Essa chave é pública no cliente e deve ser obtida nas configurações do projeto Firebase
(Web API Key). Não é um segredo do servidor e não deve ser confundida com a Private Key
em arquivos de serviço.

Para o Google Sign-In, habilite Google em **Firebase Console → Authentication →
Sign-in method** e autorize os domínios de teste e produção em **Authentication →
Settings → Authorized domains**. Nunca coloque OAuth client secrets ou credenciais
de service account no `.env` do cliente.

## Arquitetura MVC e organização do código

O app usa MVC organizado por feature:

- **Model**: entidades e estado de domínio, como `Cake`, `PickupSpot` e
  `Reservation`, com suas regras e operações de dados nos módulos
  `src/features/*/*_logic.py`.
- **Controller**: classes `*Controller` nesses módulos executam as operações
  da feature. `src/application.py` atua como controller da aplicação: compõe
  as telas, coordena os controllers, aplica as verificações de acesso e
  sincroniza as atualizações entre modelo e interface.
- **View**: módulos `src/features/*/*_view.py` constroem os controles Flet e
  encaminham ações por callbacks. As Views não fazem chamadas HTTP nem acessam
  diretamente o PostgreSQL.
- **Serviços de infraestrutura**: `src/maphi_api.py` concentra as chamadas à
  Cloud Function; `src/firebase_rest.py` concentra as operações REST usadas
  com os serviços Firebase.

O fluxo é: **View → controller da aplicação/feature → Model e serviço → View**.
As classes de modelo e os controllers de cada feature ficam co-localizados em
`*_logic.py`; essa convenção mantém cada feature reunida sem misturar a
apresentação com o acesso a dados.

Arquivos principais:

- `src/main.py`: inicializa o app Flet.
- `src/app_config.py`: configurações da aplicação e tema.
- `src/application.py`: controller e composição das features.
- `src/features/catalog/catalog_view.py` e `catalog_card_view.py`: catálogo e
  apresentação dos cards.
- `src/features/catalog/catalog_logic.py`: modelo e controller do catálogo.
- `src/features/reservations/reservation_view.py` e `reservation_logic.py`:
  telas, modelo e controller de reservas.
- `src/features/auth/auth_view.py` e `auth_logic.py`: telas e controller de
  autenticação.
- `src/features/auth/account_button_view.py`: componente de apresentação da
  conta no cabeçalho.

## Ambiente local (Windows / PowerShell)

```powershell
py -m venv .venv
.\.venv\Scripts\python.exe -m pip install "flet>=1.1.2" "tzdata>=2024.2"
.\.venv\Scripts\flet.exe run --web
```

## Build e deploy

### CI/CD com GitHub Actions

O workflow `.github/workflows/firebase-hosting.yml` executa os testes e o build
Web em pull requests direcionados a `main`. Ao enviar um commit para `main`,
repete as validações e publica `build/web` no canal de produção do Firebase
Hosting. O deploy não roda em pull requests, para não expor a credencial de
deploy a código ainda não integrado.

Configure estas **Actions variables** no repositório, em **Settings → Secrets
and variables → Actions → Variables**:

- `FIREBASE_API_KEY`
- `AUTH_DOMAIN`
- `PROJECT_ID`
- `STORAGE_BUCKET`
- `MESSAGING_SENDER_ID`
- `APP_ID`
- `MEASUREMENT_ID`

São valores da configuração Web pública do Firebase, incorporados ao app
estático durante o build. `PROJECT_ID` deve corresponder ao projeto padrão em
`.firebaserc`.

Configure também o secret **`FIREBASE_SERVICE_ACCOUNT`** em **Settings →
Secrets and variables → Actions → Secrets**, com o JSON da conta de serviço
autorizada a publicar no Firebase Hosting. Essa credencial é usada somente no
deploy de commits em `main`; nunca a coloque em variáveis públicas, `.env` do
cliente ou no repositório.

### Build e deploy local

Instale e autentique a Firebase CLI uma vez:

```powershell
npm install -g firebase-tools
firebase login
```

Após associar este diretório ao projeto Firebase, gere os arquivos web e publique:

```powershell
$env:PYTHONUTF8 = "1"
$configPath = if (Test-Path .env) { ".env" } elseif (Test-Path functions\.env) { "functions\.env" } else { $null }
if (-not $configPath) { throw "Arquivo .env não encontrado na raiz nem em functions\." }
if (Test-Path src\.env) { throw "src\.env já existe; remova-o ou faça backup antes do build." }
$aliases = @{
    apiKey = "FIREBASE_API_KEY"
    authDomain = "AUTH_DOMAIN"
    projectId = "PROJECT_ID"
    storageBucket = "STORAGE_BUCKET"
    messagingSenderId = "MESSAGING_SENDER_ID"
    appId = "APP_ID"
    measurementId = "MEASUREMENT_ID"
    MAPHI_FIREBASE_API_KEY = "FIREBASE_API_KEY"
    MAPHI_AUTH_DOMAIN = "AUTH_DOMAIN"
    MAPHI_PROJECT_ID = "PROJECT_ID"
    MAPHI_STORAGE_BUCKET = "STORAGE_BUCKET"
    MAPHI_MESSAGING_SENDER_ID = "MESSAGING_SENDER_ID"
    MAPHI_APP_ID = "APP_ID"
    MAPHI_MEASUREMENT_ID = "MEASUREMENT_ID"
}
$publicKeys = @("FIREBASE_API_KEY", "AUTH_DOMAIN", "PROJECT_ID", "STORAGE_BUCKET", "MESSAGING_SENDER_ID", "APP_ID", "MEASUREMENT_ID")
$publicConfig = foreach ($line in Get-Content $configPath) {
    if ($line -match "^\s*([^#:=\s]+)\s*[:=]\s*(.*?)\s*$") {
        $key = $matches[1]
        $value = $matches[2].Trim().TrimEnd(",").Trim([char]34, [char]39)
        if ($aliases.ContainsKey($key)) { $key = $aliases[$key] }
        if (($publicKeys -contains $key) -and $value) { "$key=$value" }
    }
}
if (-not $publicConfig) { throw "Nenhuma configuração pública do Firebase foi encontrada no .env." }
try {
    $publicConfig | Set-Content src\.env -Encoding ascii
    .\.venv\Scripts\flet.exe build web --include .env
    if ($LASTEXITCODE -ne 0) { throw "O build web falhou." }
}
finally {
    Remove-Item src\.env -Force
}
firebase deploy --only hosting
```

O build copia apenas as sete configurações públicas do Firebase para o pacote web.
Não coloque segredos ou credenciais de servidor no `.env`, pois o conteúdo incluído
no app estático pode ser lido por qualquer visitante.

O Google Sign-In via ponte JavaScript é executado no build estático WebAssembly.
Para testar localmente esse fluxo, sirva o build com `.\.venv\Scripts\flet.exe serve build\web`;
`flet run --web` executa o app pelo servidor Python e não fornece o runtime Pyodide usado
pela ponte.

O build é gerado em `build/web`, diretório configurado como origem do Firebase Hosting
em `firebase.json`.

O pacote npm `firebase` é o SDK JavaScript e não é usado pela aplicação Python.
`firebase-tools` é a CLI de deploy; a aplicação usa Firebase Authentication e
Firebase Storage, enquanto dados transacionais passam pela Cloud Function para
o PostgreSQL do Supabase.

O build web usa o caminho relativo `/api/v1/catalog`, encaminhado pelo Firebase
Hosting à Cloud Function. O modo desktop usa `https://maphivendas.web.app` por
padrão; para apontá-lo a outro ambiente, defina `MAPHI_API_URL` com a URL base da API.

## API e Supabase

Para um banco novo, execute `context/schema_supabase.sql` no SQL Editor do
Supabase. Para um banco criado com a versão anterior do schema, execute
`context/migration_supabase_app_alignment.sql` antes de publicar a nova função.
Essa migração não inventa preços: confira os `item_types` retornados pelo SELECT
final e preencha `regular_price` no SQL Editor antes de permitir reservas.
`promotional_price` é opcional e deve ser menor que `regular_price`.
`window_start` e `window_end` são `timestamptz`.

A função fica em `functions/` e é encaminhada pelo Hosting em `/api/**`.

Rotas implementadas:

- `GET /api/v1/catalog` e `GET /api/v1/pickup-spots`: leitura pública.
- `GET|POST /api/v1/profile`: perfil do usuário autenticado.
- `GET|POST /api/v1/reservations` e `POST /api/v1/reservations/{id}/cancel`.
- `/api/v1/admin/item-types`: `GET`, `POST`, `PATCH` e `DELETE`.
- `/api/v1/admin/items`: `GET`, `POST`, `PATCH` e `DELETE`.
- `POST /api/v1/admin/items/remove`: remove atomicamente uma quantidade
  informada de unidades não reservadas de um sabor.
- `/api/v1/admin/pickup-spots`: `GET`, `POST`, `PATCH` e `DELETE`.
- `/api/v1/admin/reservations`: `GET`, `PATCH` e `DELETE`.
- As rotas `/api/v1/admin/...` exigem `public.users.role = 'DONO'`.
- `GET /api/v1/health`: verifica se a função está respondendo, sem consultar o banco.

As rotas privadas exigem `Authorization: Bearer <Firebase ID token>`. A função
verifica o token com Firebase Admin e busca o papel no banco; o cliente não pode
se promover a dono. O login/cadastro continua no Firebase Authentication e o
perfil com papel é obtido pela rota `/profile`.

Na listagem administrativa de sabores, `stock` conta unidades disponíveis e
`reserved_stock` conta unidades vinculadas a reservas ativas. O botão de remoção
altera apenas unidades disponíveis; para remover estoque que está reservado, o
dono precisa cancelar primeiro uma reserva que contenha aquele sabor.

O corpo de `POST /api/v1/reservations` usa `pickup_spot_id` e uma lista de
`items`, cada qual com `item_type_id` e `quantity`. O preço aplicável e as
unidades de estoque são definidos pelo servidor, dentro da transação do banco,
e gravados como snapshots. Todos os sabores e unidades selecionados são
gravados em uma única reserva e processados na mesma transação. O corpo de
`POST /api/v1/admin/items` aceita `items` com pares
`item_type_id`/`quantity` (até 500 unidades por lote) e `expiration_at`
opcional por sabor. As datas de locais devem ser ISO 8601 com fuso horário.
Excluir reservas e locais é lógico para preservar o histórico; excluir um
local também cancela eventuais reservas ativas. Unidades removidas do estoque
mantêm seu registro com status `REMOVIDO`.

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

Publicar somente o Hosting atualiza o app, mas não atualiza a Cloud Function.
Para publicar apenas o backend da API após mudanças em `functions/`, use
`firebase deploy --only functions:api`.

Se usar `functions/.env` para as configurações Web públicas do Firebase, cada
linha deve estar no formato dotenv (`MAPHI_AUTH_DOMAIN="..."`), sem `:` ou
vírgulas finais. Use as chaves `MAPHI_FIREBASE_API_KEY`, `MAPHI_AUTH_DOMAIN`,
`MAPHI_PROJECT_ID`, `MAPHI_STORAGE_BUCKET`, `MAPHI_MESSAGING_SENDER_ID`,
`MAPHI_APP_ID` e `MAPHI_MEASUREMENT_ID`. Não use o prefixo reservado
`FIREBASE_` nesse arquivo. Não coloque a connection string do Supabase nele; use
o Secret Manager como mostrado acima.

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

Saia e entre novamente na conta após alterar o papel. O login recarrega o perfil
do Supabase e sincroniza o papel usado pelas regras do Firebase Storage.

As tabelas têm RLS habilitado sem políticas para bloquear acesso direto pela API
do Supabase. A Cloud Function usa a connection string do banco somente no
servidor; não a inclua no build web. O dono inicial precisa criar o perfil e
receber o papel `DONO` por uma atualização administrativa no SQL Editor.
O papel autoritativo é `public.users.role`; a Cloud Function espelha esse valor
em `users/{uid}` no Firestore somente para que as regras do Firebase Storage
possam autorizar uploads e exclusões de imagens.

Preços ficam em `public.item_types`; o estoque individual fica em
`public.items`. `public.reservations` e `public.reservation_items` armazenam
reservas, unidades vinculadas, preços e descrições imutáveis do momento da
operação. Os snapshots preservam o histórico quando o nome do sabor ou os
dados do local são alterados posteriormente.
Os locais usam timestamps com fuso hor?rio e janelas m?nimas de 15 minutos.
O app carrega cat?logo, estoque, locais, reservas e perfis pela Cloud Function.
A API grava pre?os e dados do cliente/local como snapshots para preservar o
hist?rico; unidades removidas, reservas apagadas e locais exclu?dos s?o mantidos
com estado l?gico apropriado.

Fotos de sabores são enviadas ao Firebase Storage, em `itemTypes/{uid}/`, antes
de o sabor ser gravado. As regras em `storage.rules` permitem leitura das imagens
do catálogo e limitam o envio a donos autenticados e a imagens JPG, PNG ou WEBP
de até 5 MB. Publique as regras com:

```powershell
firebase deploy --only storage
```

Para o Flet Web conseguir carregar as imagens em cards, configure CORS no
bucket. O bucket deve ser atualizado com uma conta Google Cloud que tenha
permissão para administrar o Storage:

```powershell
$storageBucketLine = Get-Content .env | Where-Object { $_ -match "^\s*STORAGE_BUCKET\s*=" } | Select-Object -First 1
if (-not $storageBucketLine) { throw "STORAGE_BUCKET não encontrado no .env." }
$storageBucket = (($storageBucketLine -split "=", 2)[1]).Trim().Trim('"').Trim("'")
gcloud storage buckets update "gs://$storageBucket" --cors-file=storage.cors.json
```

Essa configuração libera requisições cross-origin de leitura, envio e exclusão
de imagens; as regras do Firebase Storage continuam controlando o acesso aos objetos.
