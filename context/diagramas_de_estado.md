# Diagramas de Estado do MaphiApp
## 1. Sessao de autenticacao
```mermaid
stateDiagram-v2
    [*] --> Visitante

    Visitante --> Restaurando: iniciar aplicativo
    Restaurando --> Visitante: nao existe sessao salva
    Restaurando --> Visitante: refresh token invalido ou revogado
    Restaurando --> Restaurando: renovar idToken
    Restaurando --> Autenticado: perfil carregado no Supabase

    Visitante --> Autenticando: informar login ou cadastro
    Autenticando --> Visitante: credenciais invalidas
    Autenticando --> Autenticando: cadastro em andamento
    Autenticando --> Autenticado: Firebase valida conta e perfil e criado

    Autenticado --> Visitante: logout
    Autenticado --> Visitante: sessao removida ou renovacao invalidada
    Autenticado --> Autenticado: restaurar ou atualizar token
```
## 2. Papel do usuario
```mermaid
stateDiagram-v2
    [*] --> SemSessao

    SemSessao --> Cliente: login concluido com role CLIENTE
    SemSessao --> Dono: login concluido com role DONO

    Cliente --> Cliente: atualizar perfil sem mudar role
    Cliente --> Dono: administracao altera public.users.role

    Dono --> Cliente: administracao altera public.users.role
    Dono --> Dono: atualizar perfil mantendo role DONO

    Cliente --> SemSessao: logout
    Dono --> SemSessao: logout
```
## 3. Reserva
```mermaid
stateDiagram-v2
    [*] --> ATIVA: criar reserva

    ATIVA --> CANCELADA: cliente ou dono cancela
    ATIVA --> CONCLUIDA: dono conclui venda

    CANCELADA --> EXCLUIDA_LOGICAMENTE: dono exclui reserva cancelada
    CONCLUIDA --> EXCLUIDA_LOGICAMENTE: dono exclui reserva concluida

    EXCLUIDA_LOGICAMENTE --> [*]

    ATIVA --> ATIVA: conflito de estoque impede alteracao
    ATIVA --> ATIVA: reserva nao pertence ao usuario cliente
    ATIVA --> ATIVA: tentativa de cancelar reserva ja modificada
```
## 4. Unidade fisica no estoque
```mermaid
stateDiagram-v2
    [*] --> DISPONIVEL: criar unidade no lote de producao

    DISPONIVEL --> RESERVADO: reserva seleciona unidade
    DISPONIVEL --> REMOVIDO: remover unidade individual
    DISPONIVEL --> REMOVIDO: remocao atomica em lote

    RESERVADO --> DISPONIVEL: cancelar reserva
    RESERVADO --> VENDIDO: concluir reserva
    RESERVADO --> RESERVADO: alterar apenas expiration_at

    DISPONIVEL --> VENDIDO_PRESENCIAL: atualizacao administrativa manual
    DISPONIVEL --> EM_OFERTA_PRESENCIAL: atualizacao administrativa manual
    DISPONIVEL --> VENDIDO: atualizacao administrativa manual
    DISPONIVEL --> REMOVIDO: atualizacao administrativa manual

    VENDIDO_PRESENCIAL --> DISPONIVEL: atualizacao administrativa manual
    VENDIDO_PRESENCIAL --> REMOVIDO: atualizacao administrativa manual
    EM_OFERTA_PRESENCIAL --> DISPONIVEL: atualizacao administrativa manual
    EM_OFERTA_PRESENCIAL --> REMOVIDO: atualizacao administrativa manual
    VENDIDO --> DISPONIVEL: atualizacao administrativa manual
    VENDIDO --> REMOVIDO: atualizacao administrativa manual

    REMOVIDO --> DISPONIVEL: atualizacao administrativa manual
    REMOVIDO --> VENDIDO: atualizacao administrativa manual
    REMOVIDO --> VENDIDO_PRESENCIAL: atualizacao administrativa manual
    REMOVIDO --> EM_OFERTA_PRESENCIAL: atualizacao administrativa manual

    REMOVIDO --> REMOVIDO: atualizar expiration_at
```
## 5. Sabor do catalogo
```mermaid
stateDiagram-v2
    [*] --> ATIVO: criar sabor ativo
    [*] --> INATIVO: criar sabor inativo

    ATIVO --> INATIVO: desativar sabor
    INATIVO --> ATIVO: reativar sabor

    ATIVO --> ATIVO: alterar nome, descricao, preco ou imagem
    INATIVO --> INATIVO: alterar dados

    ATIVO --> EXCLUIDO: apagar quando nao possui unidades vinculadas
    INATIVO --> EXCLUIDO: apagar quando nao possui unidades vinculadas

    ATIVO --> ATIVO: tentativa de excluir com unidades vinculadas
    INATIVO --> INATIVO: tentativa de excluir com unidades vinculadas

    EXCLUIDO --> [*]
```
## 6. Local de retirada
```mermaid
stateDiagram-v2
    [*] --> ATIVO: criar local

    ATIVO --> INATIVO: dono desativa local
    INATIVO --> ATIVO: dono reativa local

    ATIVO --> ATIVO: alterar is_active ou dados
    INATIVO --> INATIVO: alterar dados permitidos

    ATIVO --> ATIVO: tentativa de alterar dados com reserva ativa
    INATIVO --> INATIVO: tentativa de alterar dados com reserva ativa

    ATIVO --> EXCLUIDO: excluir local
    INATIVO --> EXCLUIDO: excluir local

    EXCLUIDO --> [*]
```
## 7. Formulario de autenticacao
```mermaid
stateDiagram-v2
    [*] --> Login

    Login --> Cadastro: selecionar criar conta
    Cadastro --> Login: selecionar entrar

    Login --> Login: envio invalido
    Login --> Login: credencial invalida
    Cadastro --> Cadastro: envio invalido

    Login --> Encerrado: login concluido
    Cadastro --> Encerrado: cadastro concluido
    Login --> Encerrado: fechar modal ou tela
    Cadastro --> Encerrado: fechar modal ou tela

    Encerrado --> Login: abrir autenticacao novamente
```
## 8. Operacao de criacao de reserva no cliente
```mermaid
stateDiagram-v2
    [*] --> Inativa

    Inativa --> Bloqueada: usuario nao autenticado
    Bloqueada --> Inativa: fechar aviso ou abrir login

    Inativa --> SemLocal: confirmar sem local selecionado
    SemLocal --> Inativa: selecionar local

    Inativa --> SemItens: confirmar sem quantidade selecionada
    SemItens --> Inativa: selecionar pelo menos um sabor

    Inativa --> EmEnvio: enviar dados validos
    EmEnvio --> EmEnvio: impedir novo clique duplicado
    EmEnvio --> Falha: token, local, preco ou estoque invalidos
    EmEnvio --> Sucesso: transacao concluida

    Falha --> Inativa: recarregar catalogo e permitir nova tentativa
    Sucesso --> Inativa: zerar quantidades e abrir reservas
```
