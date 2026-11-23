# Diagramas de Atividade do MaphiApp
## 1. Fluxo geral da aplicacao
```mermaid
flowchart TD
    A([Inicio]) --> B[Inicializar aplicacao Flet]
    B --> C[Configurar pagina e tema]
    C --> D[Tentar restaurar sessao]
    D --> E[Carregar catalogo]
    E --> F[Carregar locais de retirada]
    F --> G{Usuario autenticado?}

    G -->|Nao| H[Exibir catalogo publico]
    G -->|Sim| I[Carregar perfil e permissoes]
    I --> J{Perfil do usuario e DONO?}

    J -->|Nao| K[Exibir funcionalidades de cliente]
    J -->|Sim| L[Exibir funcionalidades administrativas]

    H --> M[Escolher atividade]
    K --> M
    L --> M

    M --> N{Atividade selecionada}
    N -->|Entrar| O[Fluxo de autenticacao]
    N -->|Selecionar produto| P[Fluxo de reserva]
    N -->|Consultar reservas| Q[Fluxo de listagem]
    N -->|Gerenciar sabor| R[Fluxo administrativo de sabores]
    N -->|Gerenciar estoque| S[Fluxo administrativo de estoque]
    N -->|Gerenciar local| T[Fluxo administrativo de locais]
    N -->|Sair| U[Fluxo de logout]

    O --> V[Atualizar interface]
    P --> V
    Q --> V
    R --> V
    S --> V
    T --> V
    U --> V
    V --> M
```
## 2. Inicializacao e restauracao da sessao
```mermaid
flowchart TD
    A([Abrir aplicacao]) --> B[MaphiApplication cria controllers e views]
    B --> C[AuthController verifica sessao persistida]
    C --> D{Existe refresh token?}

    D -->|Nao| E[Iniciar como visitante]
    D -->|Sim| F[Solicitar novo idToken ao Firebase]
    F --> G{Renovacao valida?}

    G -->|Nao| H[Remover sessao invalida]
    H --> E

    G -->|Sim| I[Consultar dados da conta no Firebase]
    I --> J[POST /api/v1/profile com Bearer token]
    J --> K{Perfil carregado?}

    K -->|Nao| L[Informar falha e iniciar como visitante]
    K -->|Sim| M[Definir nome, uid, idToken e role]
    M --> N[Atualizar botoes da conta]

    E --> O[Buscar catalogo conforme papel]
    L --> O
    N --> O

    O --> P{Usuario e dono?}
    P -->|Nao| Q[GET /api/v1/catalog]
    P -->|Sim| R[GET /api/v1/admin/item-types]

    Q --> S[Processar sabores ativos e nao exclusivos]
    R --> T[Processar sabores ativos e inativos]

    S --> U[Buscar locais]
    T --> U

    U --> V{Usuario e dono?}
    V -->|Nao| W[GET /api/v1/pickup-spots]
    V -->|Sim| X[GET /api/v1/admin/pickup-spots]

    W --> Y[Filtrar locais ativos e disponiveis]
    X --> Z[Manter locais nao excluidos]
    Y --> AA([Catalogo pronto])
    Z --> AA
```
## 3. Autenticacao
```mermaid
flowchart TD
    A([Usuario abre login]) --> B{Modo escolhido}

    B -->|Email e senha| C{Cadastrar ou entrar?}
    B -->|Google| D[Carregar ponte JavaScript]

    C -->|Cadastrar| E[Validar nome, email e senha]
    C -->|Entrar| F[Enviar email e senha ao Firebase]

    E --> G[Firebase signUp]
    F --> H{Credenciais validas?}

    G --> I{Conta criada?}
    I -->|Nao| J[Exibir erro de cadastro]
    I -->|Sim| K[Obter idToken, refreshToken e uid]

    H -->|Nao| L[Exibir credencial invalida]
    H -->|Sim| K

    D --> M{Login Google disponivel no navegador?}
    M -->|Nao| N[Informar que exige build WebAssembly]
    M -->|Sim| O[Abrir popup do Google]
    O --> P{Popup concluido?}

    P -->|Cancelado, bloqueado ou dominio invalido| Q[Exibir erro do Google]
    P -->|Sucesso| R[Obter idToken, refreshToken, uid e email]
    R --> K

    K --> S[POST /api/v1/profile]
    S --> T[Cloud Function verifica token]
    T --> U[Upsert do perfil no Supabase]
    U --> V[Recuperar role autoritativo]
    V --> W[Sincronizar users uid role no Firestore]
    W --> X[Persistir refreshToken e provider]
    X --> Y[Atualizar usuario e interface]
    Y --> Z[Recarregar catalogo e locais]
    Z --> AA([Usuario autenticado])

    J --> AB([Permanece fora da sessao])
    L --> AB
    N --> AB
    Q --> AB
```
## 4. Logout
```mermaid
flowchart TD
    A([Usuario seleciona sair]) --> B{Provider utilizado foi Google?}
    B -->|Sim| C[Encerrar sessao Firebase no bridge JavaScript]
    B -->|Nao| D[Ignorar signOut externo]
    C --> E[Remover sessao persistida]
    D --> E
    E --> F[Limpar idToken, refreshToken, uid e nome]
    F --> G[Definir role como CLIENTE]
    G --> H[Recarregar catalogo publico]
    H --> I[Recarregar locais publicos]
    I --> J([Aplicacao volta ao modo visitante])
```
## 5. Navegacao e selecao no catalogo
```mermaid
flowchart TD
    A([Catalogo exibido]) --> B[Aplicar filtro Todos, Disponiveis ou Esgotados]
    B --> C[Aplicar pesquisa pelo nome]
    C --> D[Exibir cards]
    D --> E{Usuario seleciona uma acao}

    E -->|Aumentar quantidade| F[Validar estoque do sabor]
    F --> G{Quantidade menor que estoque?}
    G -->|Sim| H[Incrementar quantidade]
    G -->|Nao| I[Manter limite do estoque]

    E -->|Escolher local| J[Exibir locais]
    J --> K{Local ativo e janela valida?}
    K -->|Nao| L[Nao permitir selecao]
    K -->|Sim| M[Selecionar local]

    E -->|Abrir reservas| N[Fluxo de reservas]
    E -->|Adicionar estoque| O[Fluxo administrativo de estoque]
    E -->|Editar ou criar sabor| P[Fluxo administrativo de sabores]
    E -->|Editar ou excluir local| Q[Fluxo administrativo de locais]
```
## 6. Criacao de reserva
```mermaid
flowchart TD
    A([Usuario seleciona Reservar]) --> B{Usuario autenticado?}
    B -->|Nao| C[Solicitar login]
    C --> D([Fim da tentativa])

    B -->|Sim| E{Local selecionado?}
    E -->|Nao| F[Exibir selecione um local]
    F --> D

    E -->|Sim| G[Reunir sabores com quantidade maior que zero]
    G --> H{Existe ao menos um sabor?}
    H -->|Nao| I[Exibir selecione ao menos um bolo]
    I --> D

    H -->|Sim| J{Envio ja em andamento?}
    J -->|Sim| J1[Ignorar novo clique]
    J1 --> D
    J -->|Nao| K[Impedir novos envios enquanto aguarda]
    K --> L[POST /api/v1/reservations]
    L --> M{Token valido?}
    M -->|Nao| N[Retornar 401]
    N --> D

    M -->|Sim| O[Abrir transacao no Supabase]
    O --> P[Resolver perfil pelo auth_uid]
    P --> Q[Validar local ativo e nao excluido]
    Q --> R{Local valido e janela >= 15 minutos?}
    R -->|Nao| S[Retornar pickup_unavailable]
    S --> D

    R -->|Sim| T[Para cada sabor selecionado]
    T --> U{Sabor ativo e permitido?}
    U -->|Nao| V[Retornar items_unavailable]
    V --> D

    U -->|Sim| W{Preco normal definido?}
    W -->|Nao| X[Retornar price_unavailable]
    X --> D

    W -->|Sim| Y[Selecionar unidades DISPONIVEL com SKIP LOCKED]
    Y --> Z{Quantidade encontrada?}
    Z -->|Nao| AA[Retornar estoque insuficiente]
    AA --> D

    Z -->|Sim| AB[Alterar unidades para RESERVADO]
    AB --> AC{Todas as unidades alteradas?}
    AC -->|Nao| AA
    AC -->|Sim| AD{Mais sabores?}
    AD -->|Sim| T
    AD -->|Nao| AE[Definir sale_type]
    AE --> AF{Perfil e dono?}
    AF -->|Sim| AG[Usar preco normal e sale_type NORMAL]
    AF -->|Nao| AH[Usar promocional quando existir e sale_type PROMOCAO]

    AG --> AI[Criar reserva ATIVA]
    AH --> AI
    AI --> AJ[Salvar snapshots do usuario, local e janela]
    AJ --> AK[Salvar reservation_items com preco unitario]
    AK --> AL[Confirmar transacao]
    AL --> AM[Zerar quantidades selecionadas]
    AM --> AN[Recarregar catalogo]
    AN --> AO[Abrir tela de reservas]
    AO --> AP([Reserva criada])
```
## 7. Cancelamento, conclusao e exclusao logica de reservas
```mermaid
flowchart TD
    A([Usuario escolhe acao da reserva]) --> B{Acao}

    B -->|Cancelar| C[POST /reservations/id/cancel]
    B -->|Concluir| D{Usuario e dono?}
    B -->|Apagar| E{Usuario e dono?}

    D -->|Nao| F[Exibir apenas o dono pode concluir]
    D -->|Sim| G[PATCH /admin/reservations/id]

    E -->|Nao| H[Exibir apenas o dono pode apagar]
    E -->|Sim| I[DELETE /admin/reservations/id]

    C --> J[Resolver perfil e verificar permissao]
    J --> K[Buscar reserva ativa]
    K --> L{Reserva existe e pertence ao usuario ou dono?}
    L -->|Nao| M[Retornar reserva nao encontrada]
    L -->|Sim| N{Status e ATIVA?}

    N -->|Nao| O[Retornar reserva nao ativa]
    N -->|Sim| P[Bloquear unidades reservadas]
    P --> Q{Todas continuam RESERVADO?}
    Q -->|Nao| R[Retornar conflito de estoque]
    Q -->|Sim| S[Voltar unidades para DISPONIVEL]
    S --> T[Definir CANCELADA e cancelled_by]
    T --> U[Registrar cancelled_at]
    U --> V[Recarregar catalogo e reservas]

    G --> W[Verificar perfil DONO no backend]
    W --> X{Reserva ativa e unidades reservadas?}
    X -->|Nao| Y[Retornar conflito ou reserva inexistente]
    X -->|Sim| Z[Alterar unidades para VENDIDO]
    Z --> AA[Definir reserva como CONCLUIDA]
    AA --> AB[Registrar completed_at]
    AB --> AC[Recarregar catalogo e reservas]

    I --> AD{Status e CANCELADA ou CONCLUIDA?}
    AD -->|Nao| AE[Impede excluir reserva ativa]
    AD -->|Sim| AF[Marcar deleted_at=now]
    AF --> AG[Remover da listagem]

    F --> AH([Operacao encerrada])
    H --> AH
    M --> AH
    O --> AH
    R --> AH
    Y --> AH
    AE --> AH
    V --> AH
    AC --> AH
    AG --> AH
```
## 8. Gerenciamento de estoque
```mermaid
flowchart TD
    A([Dono abre painel de estoque]) --> B{Acao selecionada}

    B -->|Adicionar unidades| C[Selecionar sabor e quantidade]
    C --> D[Validar sabor ativo e nao exclusivo]
    D --> E{Quantidade inteira positiva?}
    E -->|Nao| F[Exibir quantidade invalida]
    E -->|Sim| G{Total do lote <= 500?}
    G -->|Nao| H[Exibir limite de 500 unidades]
    G -->|Sim| I[POST /api/v1/admin/items]
    I --> J[Verificar role DONO]
    J --> K[Gerar unidades DISPONIVEL]
    K --> L[Atualizar estoque local]

    B -->|Remover unidades disponiveis| M[Informar sabor e quantidade]
    M --> N{Quantidade entre 1 e estoque disponivel local?}
    N -->|Nao| O[Exibir quantidade invalida]
    N -->|Sim| P[POST /api/v1/admin/items/remove]
    P --> Q[Verificar role DONO]
    Q --> R[Buscar unidades DISPONIVEL com SKIP LOCKED]
    R --> S{Quantidade suficiente?}
    S -->|Nao| T[Retornar conflito sem remocao parcial]
    S -->|Sim| U[Marcar unidades como REMOVIDO]
    U --> V[Atualizar estoque local]

    B -->|Alterar unidade individual| W[PATCH /api/v1/admin/items/id]
    W --> X{Unidade esta reservada?}
    X -->|Sim| Y[Impede alteracao manual]
    X -->|Nao| Z[Validar status e expiration_at]
    Z --> AA[Atualizar unidade]

    B -->|Excluir unidade individual| AB[DELETE /api/v1/admin/items/id]
    AB --> AC{Unidade esta DISPONIVEL?}
    AC -->|Nao| AD[Impede exclusao]
    AC -->|Sim| AE[Marcar como REMOVIDO]

    F --> AF([Operacao encerrada])
    H --> AF
    L --> AF
    O --> AF
    T --> AF
    V --> AF
    Y --> AF
    AA --> AF
    AD --> AF
    AE --> AF
```
## 9. Gerenciamento de sabores
```mermaid
flowchart TD
    A([Dono seleciona sabor]) --> B{Acao}

    B -->|Criar| C[Informar dados do sabor]
    B -->|Editar| D[Carregar dados existentes]
    D --> C
    B -->|Excluir| E[Solicitar exclusao]

    C --> F[Validar nome e preco normal]
    F --> G{Precos validos?}
    G -->|Nao| H[Exibir erro de nome ou preco]
    G -->|Sim| I{Preco promocional informado?}

    I -->|Sim| J{Promocional menor que normal?}
    J -->|Nao| H
    J -->|Sim| K[Continuar]
    I -->|Nao| K

    K --> L{Nova foto selecionada?}
    L -->|Nao| M[Manter ou remover imageUrl conforme formulario]
    L -->|Sim| N{Formato JPG, PNG ou WEBP <= 5 MB?}
    N -->|Nao| O[Exibir foto invalida]
    N -->|Sim| P[Upload em itemTypes/uid/uuid.ext]
    P --> Q{Regras do Storage aprovaram?}
    Q -->|Nao| R[Exibir falha no upload]
    Q -->|Sim| S[Obter imageUrl]

    M --> T{Criar ou editar?}
    S --> T
    T -->|Criar| U[POST /api/v1/admin/item-types]
    T -->|Editar| V[PATCH /api/v1/admin/item-types/id]
    U --> W[Verificar role DONO]
    V --> W
    W --> X[Validar e salvar item_type no Supabase]
    X --> Y{Edicao substituiu foto antiga?}
    Y -->|Nao| Z[Atualizar catalogo local]
    Y -->|Sim| AA[Excluir foto antiga no Storage]
    AA --> AB{Exclusao da foto antiga falhou?}
    AB -->|Sim| AC[Salvar sabor e informar falha na limpeza]
    AB -->|Nao| Z

    E --> AD[GET /api/v1/admin/items?item_type_id=id&limit=1]
    AD --> AE{Existe unidade vinculada?}
    AE -->|Sim| AF[Impede excluir sabor]
    AE -->|Nao| AG[DELETE /api/v1/admin/item-types/id]
    AG --> AH[Backend confirma que nao existem unidades]
    AH --> AI{Exclusao permitida?}
    AI -->|Nao| AF
    AI -->|Sim| AJ[Excluir sabor do Supabase]
    AJ --> AK{Sabor possui imagem?}
    AK -->|Sim| AL[Excluir imagem no Storage]
    AK -->|Nao| AM[Atualizar catalogo local]
    AL --> AM

    H --> AN([Operacao encerrada])
    O --> AN
    R --> AN
    Z --> AN
    AC --> AN
    AF --> AN
    AM --> AN
```
## 10. Gerenciamento de locais de retirada
```mermaid
flowchart TD
    A([Dono seleciona local]) --> B{Acao}

    B -->|Criar| C[Informar nome, endereco, chegada e saida]
    B -->|Editar| D[Carregar local existente]
    D --> C
    B -->|Excluir| E[Solicitar exclusao do local]

    C --> F[Validar formato DD/MM/AAAA HH:MM]
    F --> G{Saida posterior a chegada?}
    G -->|Nao| H[Exibir janela invalida]
    G -->|Sim| I{Janela >= 15 minutos?}
    I -->|Nao| H
    I -->|Sim| J{Criar ou editar?}

    J -->|Criar| K[POST /api/v1/admin/pickup-spots]
    J -->|Editar| L[PATCH /api/v1/admin/pickup-spots/id]

    K --> M[Verificar role DONO]
    L --> M
    M --> N{Edicao altera dados com reservas ATIVA?}
    N -->|Sim| O[Impede alterar local em uso]
    N -->|Nao| P[Validar janela no backend]
    P --> Q{Dados validos?}
    Q -->|Nao| H
    Q -->|Sim| R[Salvar local no Supabase]
    R --> S[Atualizar opcoes no catalogo]

    E --> T[Desativar local antes da exclusao]
    T --> U[PATCH is_active=false]
    U --> V[Listar reservas ATIVA do local]
    V --> W[Cancelar cada reserva ativa]
    W --> X[Devolver unidades reservadas]
    X --> Y[DELETE /api/v1/admin/pickup-spots/id]
    Y --> Z[Backend busca reservas ATIVA restantes]
    Z --> AA[Cancelar reservas e devolver unidades]
    AA --> AB[Marcar local deleted_at=now]
    AB --> AC[Atualizar catalogo e reservas]

    H --> AD([Operacao encerrada])
    O --> AD
    S --> AD
    AC --> AD
```
## 11. Listagem de reservas
```mermaid
flowchart TD
    A([Usuario abre Reservas]) --> B{Usuario autenticado?}
    B -->|Nao| C[Solicitar login]
    C --> D([Fim])

    B -->|Sim| E[GET /api/v1/reservations ou admin/reservations]
    E --> F{Perfil e dono?}

    F -->|Nao| G[Verificar perfil pelo auth_uid]
    G --> H[Buscar reservas do usuario interno]
    F -->|Sim| I{Filtro por local informado?}
    I -->|Nao| J[Buscar todas as reservas]
    I -->|Sim| K[Buscar reservas do local selecionado]

    H --> L[Incluir itens e snapshots]
    J --> L
    K --> L
    L --> M[Agregar valor total]
    M --> N[Ordenar pela data de criacao]
    N --> O{Papel do usuario}

    O -->|Cliente| P[Exibir apenas suas reservas]
    O -->|Dono| Q[Exibir todas ou reservas filtradas]
    Q --> R[Permitir cancelar, concluir ou apagar]
    P --> S[Permitir cancelar suas reservas ATIVA]
    R --> T([Listagem atualizada])
    S --> T
```
## 12. Tratamento de uma requisicao da Cloud Function
```mermaid
flowchart TD
    A([Requisicao chega no Hosting]) --> B{Origem permitida?}
    B -->|Nao| C[Retornar 403 origin_not_allowed]
    B -->|Sim| D{Metodo OPTIONS?}
    D -->|Sim| E[Retornar 204 com CORS]
    D -->|Nao| F[Extrair path e metodo]

    F --> G{Rota}
    G -->|GET /health| H[Retornar status ok]
    G -->|GET /catalog| I[Consultar catalogo publico no Supabase]
    G -->|GET /pickup-spots| J[Consultar locais publicos no Supabase]
    G -->|Rota privada| K[Resolver rota e metodo]

    K --> L{Metodo permitido?}
    L -->|Nao| M[Retornar 405]
    L -->|Sim| N[Ler Authorization Bearer]
    N --> O{Token presente e valido?}
    O -->|Nao| P[Retornar 401]
    O -->|Sim| Q[Abrir conexao Supabase]

    Q --> R{Rota administrativa?}
    R -->|Sim| S[Buscar perfil pelo auth_uid]
    S --> T{Perfil role=DONO?}
    T -->|Nao| U[Retornar 403]
    T -->|Sim| V[Sincronizar role no Firestore]
    R -->|Nao| W[Executar rota do usuario]
    V --> X[Executar operacao administrativa]

    X --> Y{Operacao respeitou validacoes?}
    W --> Y
    Y -->|Nao| Z[Retornar erro 400 ou 409]
    Y -->|Sim| AA{Banco falhou ou indisponivel?}
    AA -->|Falha SQL| AB[Retornar 400, 409 ou 503]
    AA -->|Sucesso| AC[Confirmar contexto da transacao]
    AC --> AD[Retornar JSON e status HTTP]

    C --> AE([Fim])
    E --> AE
    H --> AE
    I --> AE
    J --> AE
    M --> AE
    P --> AE
    U --> AE
    Z --> AE
    AB --> AE
    AD --> AE
```
## 13. Pipeline de CI/CD
```mermaid
flowchart TD
    A([Commit enviado]) --> B{Evento do GitHub}

    B -->|Pull Request para main| C[Iniciar workflow]
    B -->|Push para main| C

    C --> D[Checkout do repositorio]
    D --> E[Configurar Python 3.11]
    E --> F[Instalar projeto e dependencias de teste]
    F --> G[Executar pytest]

    G --> H{Testes passaram?}
    H -->|Nao| I[Encerrar workflow com falha]
    H -->|Sim| J[Preparar src/.env]

    J --> K{Evento e Pull Request?}
    K -->|Sim| L[Nao exigir todas as variaveis de deploy]
    K -->|Nao| M[Exigir configuracoes publicas do Firebase]
    M --> N{Variaveis presentes?}
    N -->|Nao| O[Encerrar workflow com falha]
    N -->|Sim| P[Gravar src/.env]
    L --> P

    P --> Q[Flet build web com --include .env]
    Q --> R{Build concluiu?}
    R -->|Nao| S[Encerrar workflow com falha]
    R -->|Sim| T[Remover src/.env temporario]
    T --> U{Evento e Pull Request?}

    U -->|Sim| V[Validar apenas o build]
    V --> W([Nao publicar no Firebase])

    U -->|Nao| X[Verificar FIREBASE_SERVICE_ACCOUNT]
    X --> Y{Credencial configurada?}
    Y -->|Nao| Z[Encerrar workflow com falha]
    Y -->|Sim| AA[Action Firebase Hosting publica canal live]
    AA --> AB{Deploy concluido?}
    AB -->|Nao| AC[Encerrar workflow com falha]
    AB -->|Sim| AD([Aplicacao publicada])

    I --> AE([Fim com erro])
    O --> AE
    S --> AE
    Z --> AE
    AC --> AE
```
