# Contexto do Projeto: PWA em Python com Flet e Firebase Hosting

Este arquivo reúne todo o contexto técnico, diretrizes de arquitetura, restrições e padrões definidos para a construção do projeto. Utilize estas instruções para orientar o desenvolvimento e a geração de código.

---

## 1. Visão Geral e Requisitos
* **Objetivo:** Desenvolver uma aplicação web progressiva (PWA) rápida, responsiva e instalável.
* **Requisito do Projeto:** A aplicação deve ser desenvolvida em **Python**.
* **Paradigma de Interface:** Declaração de UI baseada na estrutura e estilização do **Flutter** (widgets e componentes nativos).
* **Hospedagem:** Firebase Hosting (entrega de arquivos estáticos via CDN global sobre HTTPS).

---

## 2. Stack Tecnológica
* **Front-end & UI:** [Flet](https://flet.dev/) (Framework Python construído sobre a engine do Flutter).
* **Compilação Web/PWA:** Flet WebAssembly (`flet build web`) executado via Pyodide/Wasm no navegador.
* **Estilização:** Sistema nativo de propriedades de estilo do Flet/Flutter (sem CSS ou Tailwind).
* **Back-end & Banco de Dados (BaaS):** Firebase (Authentication e Firestore / Realtime Database).
* **Hospedagem & Deploy:** Firebase Hosting CLI.

---

## 3. Arquitetura e Decisões Técnicas

### 3.1. Execução Client-Side (Sem servidor Python dedicado)
A aplicação é totalmente empacotada em arquivos estáticos (HTML, JS, WASM e assets do PWA) gerados durante o processo de build:
```bash
flet build web
```
A pasta de saída (ex: `build/web`) é o artefato a ser publicado diretamente no Firebase Hosting.

### 3.2. Integração com o Firebase
* **Restrição de ambiente:** O SDK nativo de servidor de Python (`firebase-admin`) **não funciona** no ambiente WebAssembly do navegador.
* **Abordagem de Comunicação:** Requisições via APIs REST públicas do Firebase utilizando bibliotecas HTTP compativeis com Pyodide (como `httpx` ou `pyrebase4`).
* **Segurança:** A segurança do acesso aos dados é controlada integralmente pelas **Firestore Security Rules** e restrições de referenciadores HTTP (HTTP Referrers) no Google Cloud Console, e **não por segredos no código-fonte**.

---

## 4. Estrutura do Arquivo de Deploy (`firebase.json`)

Para publicar o PWA no Firebase Hosting, a configuração deve garantir o roteamento de rotas e entrega dos arquivos estáticos:

```json
{
  "hosting": {
    "public": "build/web",
    "ignore": [
      "firebase.json",
      "**/.*",
      "**/node_modules/**"
    ],
    "rewrites": [
      {
        "source": "**",
        "destination": "/index.html"
      }
    ]
  }
}
```

---

## 5. Padrões de Código e UI (Flet)

1. **Estilização Declarativa:**
   * Utilizar propriedades nativas do Flet para `padding`, `margin`, `color`, `border_radius`, `alignment`.
   * Exemplo: `ft.Container(padding=ft.padding.all(16), bgcolor=ft.Colors.BLUE_600)`.
2. **Gerenciamento de Estado de Tela:**
   * Atualização reativa de componentes chamando o método `page.update()` após mutações de dados na interface.
3. **Persistência / Autenticação:**
   * Utilizar o `idToken` retornado pela REST API de Auth para autorizar requisições HTTP aos dados do Firestore.

---

## 6. Próximos Passos para a IA Agêntica
Ao gerar código ou planejar a implementação:
* Escreva os componentes em código **100% Python** utilizando a biblioteca `flet`.
* Não utilize CSS, JS nativo ou HTML templates.
* Certifique-se de que todas as chamadas ao Firebase sejam feitas via cliente HTTP REST (`httpx` / `pyrebase4`).