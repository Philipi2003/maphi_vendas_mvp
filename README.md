# MaphiApp

Aplicação web em Python com Flet e Firebase Hosting.

O catálogo lista os sabores ativos cadastrados na coleção `itemTypes` do Firestore;
sabores de demonstração locais não são exibidos.
A autenticação por e-mail/senha já está conectada ao Firebase Authentication via REST API,
contanto que a variável de ambiente `FIREBASE_API_KEY` esteja configurada com a Web API key
exposta no projeto do Firebase. O login com Google usa o Firebase Web SDK por uma pequena
ponte JavaScript incluída nos assets do build web.

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

## Organização do código

- `src/main.py`: inicializa o app Flet.
- `src/app_config.py`: configurações da aplicação e tema.
- `src/application.py`: composição das features e estado compartilhado da aplicação.
- `src/features/catalog/catalog_view.py`: interface do catálogo.
- `src/features/catalog/catalog_card_view.py`: apresentação e interações de cada card.
- `src/features/catalog/catalog_logic.py`: carregamento, filtros e seleção do catálogo.
- `src/features/reservations/reservation_view.py` e `reservation_logic.py`:
  criação, consulta e gestão de reservas.
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
if (-not (Test-Path .env)) { throw "Arquivo .env não encontrado." }
if (Test-Path src\.env) { throw "src\.env já existe; remova-o ou faça backup antes do build." }
$publicKeys = "FIREBASE_API_KEY|AUTH_DOMAIN|PROJECT_ID|STORAGE_BUCKET|MESSAGING_SENDER_ID|APP_ID|MEASUREMENT_ID"
$publicConfig = Get-Content .env | Where-Object { $_ -match "^\s*($publicKeys)\s*=" }
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
`firebase-tools` é a CLI de deploy; a aplicação acessa Firebase Authentication e
Cloud Firestore pelas APIs REST.

## Firestore

As regras estão em `firestore.rules` e podem ser publicadas com:

```powershell
firebase deploy --only firestore:rules
```

O Firestore cria uma coleção quando o primeiro documento é gravado; não há
necessidade de semear documentos fictícios para criar coleções vazias. O MVP usa
estas coleções e campos:

- `itemTypes`: `name`, `description`, `imageUrl`, `isCustomOrderOnly`,
  `regularPrice`, `promotionalPrice` (opcional), `isActive`, `createdAt`.
  Perfis públicos e clientes listam apenas sabores ativos; o dono também pode
  visualizar sabores inativos, editar seus dados e alternar `isActive`.
  Criação, edição e exclusão exigem perfil com `role: "DONO"`. O app só oferece
  exclusão quando não há documentos de estoque associados ao sabor.
- `items`: `itemTypeId`, `itemTypeName`, `status`, `expirationDate` (opcional),
  `createdAt`. Leitura pública apenas das unidades com status `DISPONIVEL`.
- `pickupSpots`: `name`, `address`, `arrivalAt`, `departureAt`, `isActive`,
  `createdAt`. Chegada e saída são timestamps completos, inseridos no horário
  local de São Paulo (`DD/MM/AAAA HH:MM`). A janela deve ter pelo menos 15 minutos;
  para clientes, o local só aparece quando a saída ainda estiver a mais de
  15 minutos do horário atual. O dono pode criar, editar e excluir locais pelo
  catálogo, inclusive remover locais obsoletos. Ao excluir um local, ele é
  desativado primeiro, as reservas ativas são canceladas e suas unidades voltam
  ao estoque antes da remoção definitiva. Locais legados sem timestamps
  completos ficam ocultos para clientes e podem ser editados ou removidos pelo
  dono.
- `users/{uid}`: `name`, `phone`, `createdAt`. Cada usuário lê e altera apenas
  seu próprio perfil; não pode definir seu próprio papel.
- `reservations`: `userId`, `pickupSpotId`, `itemIds`, `itemTypeNames`,
  `itemTypeIds`, `unitPrices`, `totalAmount`, snapshot do local de retirada,
  `saleType`, `status` e timestamps de criação, cancelamento e conclusão.
  Leitura apenas pelo cliente proprietário ou pelo dono. Cada reserva agrupa
  até duas unidades para manter a atualização de estoque verificável pelas
  regras do Firestore; seleções maiores são divididas automaticamente em
  reservas adicionais. Não há limite total de unidades ativas por cliente.
  O dono pode criar reservas para vendas presenciais, filtrar a lista por local,
  cancelar ou concluir reservas e apagar reservas já canceladas ou concluídas.

Ao iniciar, o app carrega os `itemTypes` e conta os documentos de `items` com
status `DISPONIVEL` para exibir o estoque de cada sabor. Donos podem registrar
uma produção pelo FAB, selecionando um ou mais sabores e suas quantidades; cada
bolo é salvo como um documento individual em `items`, em uma gravação atômica
de até 500 unidades por inserção. As unidades novas começam com status
`DISPONIVEL`. Ao renomear um sabor, o app também atualiza `itemTypeName` nas
unidades de estoque associadas. A contagem exibida ao dono é de unidades não
reservadas; a remoção só exclui um documento com status `DISPONIVEL`, protegida
por transação e pelas regras Firestore.

As regras identificam o dono por `users/{uid}.role == "DONO"`. O próprio usuário
não pode criar ou editar esse campo: a conta de dono inicial deve receber o papel
por uma ação administrativa no Console do Firebase. Contas sem esse papel têm
permissões de cliente. Reservar, cancelar e concluir uma reserva atualiza
atomicamente o estado da reserva e das unidades de estoque. Clientes podem
cancelar apenas as próprias reservas; o dono pode cancelar reservas de qualquer
usuário, e essa origem fica visível na listagem do cliente.

Fotos de sabores são enviadas ao Firebase Storage, em `itemTypes/{uid}/`, antes
de o sabor ser gravado. As regras em `storage.rules` permitem leitura das imagens
do catálogo e limitam o envio a donos autenticados e a imagens JPG, PNG ou WEBP
de até 5 MB. Publique as regras com:

```powershell
firebase deploy --only storage
```

Para o Flutter Web conseguir carregar as imagens em cards, configure CORS no
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
