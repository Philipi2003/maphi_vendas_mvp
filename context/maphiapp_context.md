# MaphiApp - Contexto do Projeto para Desenvolvimento

Este documento serve como a fonte de verdade e contexto arquitetural para o desenvolvimento da aplicação **MaphiApp**, um sistema de gerenciamento de produções e reservas de bolos da **Maphi Doces**.

---

## 1. Visão Geral do Sistema

O **MaphiApp** é um sistema projetado para intermediar a venda, produção e logística de entrega de bolos. O sistema atende a dois perfis principais de atores:
- **Donos (ADMIN)**: Gerenciam a produção, catálogo de sabores, estoque de unidades físicas, locais/horários de retirada, acompanham o volume de vendas por ponto de entrega e registram vendas presenciais.
- **Clientes (USER)**: Visualizam o catálogo de sabores e o estoque disponível em tempo real, realizam agendamentos/reservas de unidades para retirada em locais com janelas de tempo predefinidas, e gerenciam suas reservas.

### Principais Pilares do Negócio
1. **Controle Estrito de Estoque**: Sabores/cardápio são separados das unidades físicas em estoque.
2. **Logística Baseada em Janelas de Tempo**: As retiradas acontecem em pontos cadastrados com horários específicos de permanência (mínimo 15 minutos).
3. **Regras de Promoção e Limite por Cliente**: Um único cliente pode reservar no máximo **2 bolos por vez** para aplicar o dinamismo de vendas e garantir controle promocional.
4. **Resiliência e Atendimento Pré-venda/Pós-venda**: Integração direta com WhatsApp para rápida resolução de imprevistos ou suporte ao cliente.

---

## 2. Requisitos e Regras de Negócio Fundamentais

### Requisitos Funcionais Principais
- **RF01**: Inserção e controle de produções/unidades de bolos.
- **RF02**: Gerenciamento de reservas (criação, cancelamento e visualização por donos e usuários).
- **RF03 / RF04**: Gestão do catálogo de sabores e gestão de itens exclusivamente sob encomenda (`isCustomOrderOnly`).
- **RF05**: Cadastro de pontos de retirada com data e hora de chegada e saída (`arrivalAt`, `departureAt`).
- **RF06**: Relatório/visualização do quantitativo de entregas pendentes por local de retirada, discriminado por tipo de venda (Promoção vs. Normal).
- **RF07**: Disparo de notificações de novos lotes de estoque para a base de usuários.

### Regras de Negócio (RNs Críticas)
- **RN01 (Catálogo Público)**: A visualização do catálogo e disponibilidade não exige autenticação.
- **RN02 (Operações Autenticadas)**: Operações de reserva, alteração de dados e acesso ao painel administrativo exigem autenticação válida (E-mail/Senha forte ou Google OAuth).
- **RN03 & RN09 (Margem Logística)**: A reserva só é permitida se o horário de encerramento do ponto de entrega for superior a **15 minutos** em relação ao momento atual.
- **RN04 (Separação Sabor vs. Unidade)**: O cadastro de um `ItemType` (Sabor) é desassociado do lançamento de instâncias físicas (`Item`).
- **RN05 (Limite de Reservas)**: Máximo de **2 unidades** reservadas por cliente ativo.
- **RN07 / RN08 (Exclusão Segura de Sabores)**: Donos só podem remover um `ItemType` da base de dados se **não** existirem unidades físicas em estoque vinculadas a ele.
- **RN10 (Distinção de Vendas)**: O sistema deve classificar a transação como `PROMOÇÃO` (reservas de até 2 unidades) ou `NORMAL` (vendas avulsas/presenciais).
- **RN11 (Critérios de Senha Forte)**: Mínimo 8 caracteres, contendo pelo menos 1 caractere especial, letras e números.
- **RN13 (Janela de Agendamento de Notificação - Batching)**: Para evitar spam, o lançamento de novas unidades aciona um timer de **30 minutos**. Lançamentos adicionais dentro dessa janela são agrupados. A notificação push consolidada só é disparada ao final dos 30 minutos.
- **RN14 (Baixa em Estoque com Impacto em Reservas)**: Se o Dono forçar a remoção de unidades de estoque em quantidade superior ao estoque livre (atingindo bolos já reservados):
  1. O sistema deve emitir um alerta explícito informando o conflito e exibindo quais reservas serão afetadas.
  2. Exigir confirmação manual e seleção das reservas a serem estornadas.
  3. Estornar as reservas, atualizar o estoque e notificar imediatamente os usuários impactados via Push/Notificação.

---

## 3. Arquitetura de Dados e Entidades (Modelo de Classes)

Com base na modelagem do sistema, utilize os seguintes atributos e enums para o schema de dados (PostgreSQL/Firestore/MongoDB):

### Enumeradores
```typescript
enum UserRole {
  DONO = 'DONO',
  CLIENTE = 'CLIENTE'
}

enum ItemStatus {
  DISPONIVEL = 'DISPONIVEL',
  RESERVADO = 'RESERVADO',
  VENDIDO_PRESENCIAL = 'VENDIDO_PRESENCIAL',
  EM_OFERTA_PRESENCIAL = 'EM_OFERTA_PRESENCIAL'
}

enum SaleType {
  PROMOCAO = 'PROMOCAO',
  NORMAL = 'NORMAL'
}

enum ReservationStatus {
  ATIVA = 'ATIVA',
  CONCLUIDA = 'CONCLUIDA',
  CANCELADA = 'CANCELADA'
}
```

### Principais Modelos de Entidades

#### User (Usuário)
- `id`: String (UUID / Auth ID)
- `name`: String
- `email`: String (Unique)
- `phone`: String
- `role`: UserRole
- `createdAt`: Timestamp

#### ItemType (Sabor do Bolo)
- `id`: String
- `name`: String
- `description`: String
- `imageUrl`: String
- `isCustomOrderOnly`: Boolean (indica se é apenas encomendado)
- `isActive`: Boolean

#### Item (Unidade Física no Estoque)
- `id`: String
- `itemTypeId`: String (FK para `ItemType`)
- `itemTypeName`: String (Denormalizado para busca rápida)
- `status`: ItemStatus
- `expirationDate`: Timestamp (Opcional)
- `createdAt`: Timestamp

#### PickupSpot (Local de Retirada)
- `id`: String
- `name`: String
- `address`: String
- `arrivalAt`: Timestamp (data e hora local de chegada)
- `departureAt`: Timestamp (data e hora local de saída)
- `isActive`: Boolean
- `createdAt`: Timestamp

Locais disponíveis para reserva devem ter uma janela de permanência mínima de
15 minutos e o horário de saída precisa estar a mais de 15 minutos do momento
atual. Locais sem uma janela válida não são exibidos aos clientes.

#### Reservation (Reserva de Pedido)
- `id`: String
- `userId`: String (FK para `User`)
- `pickupSpotId`: String (FK para `PickupSpot`)
- `itemIds`: List<String> (IDs dos `Item` reservados, máx: 2)
- `itemTypeNames`: List<String>
- `saleType`: SaleType
- `status`: ReservationStatus
- `createdAt`: Timestamp

---

## 4. Mapeamento de Casos de Uso Técnicos

Ao implementar as rotas/controllers, garanta o atendimento aos fluxos estabelecidos:

| UC ID | Nome | Atores | Detalhes de Implementação |
|---|---|---|---|
| **UC01** | Manter Conta | Cliente / Dono | Auth via E-mail/Senha ou Google OAuth. Validação de senha forte via Regex na API. |
| **UC02** | Gerenciar Sabores | Dono | CRUD de `ItemType`. Checar `RN07` antes de permitir DELETE (`Item.count({ itemTypeId, status: DISPONIVEL }) == 0`). |
| **UC03** | Adicionar Unidade ao Estoque | Dono | Cria múltiplos registros em `Item` com status `DISPONIVEL`. Dispara Worker com delay de 30 min (RN13) para envio da Push Notification. |
| **UC04** | Notificar Usuários | Sistema | Integração com serviço de Push Notification (ex: Firebase Cloud Messaging - FCM) com agendamento/debouncing. |
| **UC05** | Remover Unidades do Estoque | Dono | Se a quantidade a remover > estoque livre, retornar payload HTTP 409 (Conflict) exigindo confirmação com lista de reservas afetadas. |
| **UC06** | Gerenciar Locais de Retirada | Dono | CRUD de `PickupSpot`. Validar janela de horário (mínimo 15min de tolerância). |
| **UC07** | Entregas Pendentes por Local | Dono | Query de agregação agrupando `Reservation` ativas por `pickupSpotId`, contando totais de `SaleType.PROMOCAO` vs `SaleType.NORMAL`. |
| **UC08** | Listar Bolos em Estoque | Público / Usuário | Listar `ItemType` unindo contagem de `Item` com `status == DISPONIVEL`. Público para leitura. |
| **UC09** | Realizar Reserva | Cliente / Dono | Validar limite de 2 unidades por usuário (`RN05`). Transação atômica (DB Lock) para alterar status de `Item` para `RESERVADO` e criar `Reservation`. |
| **UC10** | Visualizar Locais Disponíveis | Usuário / Dono | Consulta pública/autenticada de `PickupSpot` onde `isActive == true`. |
| **UC11** | Desfazer Reserva | Usuário / Dono | Transação: alterar `Reservation.status` para `CANCELADA` e atualizar os `Item.status` de volta para `DISPONIVEL`. |
| **UC12** | Visualizar Reservas | Usuário / Dono | Se cliente: filtrar por `userId`. Se dono: permitir listagem global com busca e atalhos para WhatsApp. |

---

## 5. Diretrizes Tecnológicas e Boas Práticas

1. **Atomicidade e Concorrência**:
   - As operações de reserva (**UC09**) e estorno de estoque (**UC05**) dezenas de usuários podem tentar reservar a mesma unidade simultaneamente. Utilize **Transactions / Pessimistic Locking** no banco de dados para evitar *race conditions* ou *overbooking*.
2. **Notificações em Lote (Debounce Timer)**:
   - Implemente uma fila de agendamento (BullMQ, Redis, Firebase Functions Scheduled, Celery, etc.) para gerenciar a regra **RN13** de 30 minutos de tolerância antes de disparar o FCM push notification para a base global de clientes.
3. **Deep Linking / WhatsApp Direct**:
   - Os endpoints e respostas do frontend devem formatar links `https://wa.me/<PHONE>?text=<MENSAGEM_ENCODADA>` incluindo o número do pedido/reserva para facilitar a comunicação imediata em caso de dúvidas ou cancelamentos excepcionais.
4. **Respostas HTTP e Tratamento de Erros**:
   - `400 Bad Request`: Limite de reservas excedido (RN05) ou senha fraca (RN11).
   - `409 Conflict`: Tentativa de apagar sabor com unidades ativas (RN07) ou baixa de estoque atingindo reservas ativas (RN14 - onde o body retornará a estrutura de reservas em conflito para confirmação).
```

eof

---

### Resumo do Arquivo Gerado
Criei o arquivo de contexto `maphi_doces_context.md`. Ele resume o minimundo do **MaphiApp**, documenta os requisitos funcionais, regras de negócio críticas (como a margem de tempo de 15 minutos, agendamento de notificação de 30 minutos e baixa de estoque com conflito), o modelo de classes detalhado com todos os tipos/enums e o mapeamento dos 12 casos de uso para guiá-lo no desenvolvimento.

Precisa de ajustes em alguma regra específica ou quer discutir a arquitetura da stack tecnológica?