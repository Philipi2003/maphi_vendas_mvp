# MaphiApp

Aplicação web em Python com Flet e Firebase Hosting.

O catálogo inicial em `src/features/catalog/catalog_logic.py` usa bolos e quantidades de demonstração.
Login e reserva ainda não estão conectados ao Firebase; a interface informa isso
explicitamente e não confirma nenhuma operação real.

O acesso abre uma tela dedicada em aparelhos com largura menor que 768 px e um
modal em telas maiores. Ambos oferecem login por e-mail/senha, acesso com Google
e alternância para cadastro; a autenticação ainda será integrada ao Firebase.

## Organização do código

- `src/main.py`: inicializa o app Flet.
- `src/app_config.py`: configurações da aplicação e tema.
- `src/application.py`: composição das features e estado compartilhado da aplicação.
- `src/features/catalog/catalog_view.py`: interface do catálogo.
- `src/features/catalog/catalog_logic.py`: dados de demonstração, filtros e seleção.
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
firebase deploy --only hosting
```

O build é gerado em `build/web`, diretório configurado como origem do Firebase Hosting
em `firebase.json`.

O pacote npm `firebase` é o SDK JavaScript e não é usado pela aplicação Python.
`firebase-tools` é a CLI de deploy; a integração com os serviços Firebase será feita
em Python por APIs REST.

## Firestore

As regras estão em `firestore.rules` e podem ser publicadas com:

```powershell
firebase deploy --only firestore:rules
```

O Firestore cria uma coleção quando o primeiro documento é gravado; não há
necessidade de semear documentos fictícios para criar coleções vazias. O MVP usa
estas coleções e campos:

- `itemTypes`: `name`, `description`, `imageUrl`, `isActive`, `createdAt`.
  Leitura pública apenas dos documentos ativos.
- `items`: `itemTypeId`, `itemTypeName`, `status`, `expirationDate` (opcional),
  `createdAt`. Leitura pública apenas das unidades com status `DISPONIVEL`.
- `pickupSpots`: `name`, `address`, `timeWindow`, `isActive`, `createdAt`.
  Leitura pública apenas dos locais ativos.
- `users/{uid}`: `name`, `phone`, `createdAt`. Cada usuário lê e altera apenas
  seu próprio perfil; não pode definir seu próprio papel.
- `reservations`: `userId`, `pickupSpotId`, `itemIds`, `itemTypeNames`,
  `saleType`, `status`, `createdAt`. Leitura apenas pelo cliente proprietário
  ou pelo dono.

As regras identificam o dono por `users/{uid}.role == "DONO"`. O próprio usuário
não pode criar ou editar esse campo: a conta de dono inicial deve receber o papel
por uma ação administrativa no Console do Firebase. Contas sem esse papel têm
permissões de cliente. A criação e alteração de reservas pelo cliente permanecem
bloqueadas até implementarmos uma operação transacional confiável para atualizar
reserva e estoque em conjunto. O limite de reservas por cliente e os bolos sob
encomenda não fazem parte deste MVP.
