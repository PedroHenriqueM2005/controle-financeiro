/* ==========================================================================
   Saldo — front-end em JavaScript puro (sem dependências externas).
   Toda mutação passa pela API JSON em /api/*.
   ========================================================================== */
(() => {
  "use strict";

  const $ = (sel, root = document) => root.querySelector(sel);
  const $$ = (sel, root = document) => Array.from(root.querySelectorAll(sel));

  /* ------------------------------------------------------------ dinheiro */

  function parseMoney(value) {
    if (value === null || value === undefined) return null;
    if (typeof value === "number") return Math.round(value * 100);
    let s = String(value).trim();
    if (!s) return null;
    let neg = false;
    if (/^\(.*\)$/.test(s)) { neg = true; s = s.slice(1, -1); }
    s = s.replace(/[^0-9,.\-+]/g, "");
    if (s.startsWith("-")) { neg = true; s = s.slice(1); }
    else if (s.startsWith("+")) { s = s.slice(1); }
    if (!s) return null;
    if (s.includes(",") && s.includes(".")) {
      s = s.lastIndexOf(",") > s.lastIndexOf(".") ? s.replace(/\./g, "").replace(",", ".") : s.replace(/,/g, "");
    } else if (s.includes(",")) {
      const parts = s.split(",");
      const tail = parts[parts.length - 1];
      s = parts.length === 2 && tail.length <= 2 ? parts[0] + "." + tail : parts.join("");
    } else if (s.includes(".")) {
      const parts = s.split(".");
      const tail = parts[parts.length - 1];
      if (parts.length === 2 && tail.length === 3 && parts[0].length <= 3) s = parts[0];
    }
    const n = parseFloat(s);
    if (Number.isNaN(n)) return null;
    const c = Math.round(n * 100);
    return neg ? -c : c;
  }

  function fmtMoney(centavos, sinal = false) {
    if (centavos === null || centavos === undefined) return "—";
    const v = Math.round(centavos);
    const neg = v < 0;
    const s = String(Math.abs(v)).padStart(3, "0");
    const inteiro = s.slice(0, -2).replace(/\B(?=(\d{3})+(?!\d))/g, ".");
    const corpo = inteiro + "," + s.slice(-2);
    const prefixo = neg ? "-" : (sinal && v > 0 ? "+" : "");
    return prefixo + "R$ " + corpo;
  }

  function toInputMoney(centavos) {
    const v = Math.abs(Math.round(centavos || 0));
    const s = String(v).padStart(3, "0");
    return s.slice(0, -2) + "," + s.slice(-2);
  }

  /* ------------------------------------------------------------ infra */

  async function api(path, { method = "GET", body = null } = {}) {
    const opts = { method, headers: {} };
    if (body !== null) {
      if (body instanceof FormData) {
        opts.body = body;
      } else {
        opts.headers["Content-Type"] = "application/json";
        opts.body = JSON.stringify(body);
      }
    }
    let resp;
    try {
      resp = await fetch(path, opts);
    } catch (e) {
      throw new Error("Sem conexão com o servidor: " + e.message);
    }
    const ctype = resp.headers.get("content-type") || "";
    const data = ctype.includes("application/json") ? await resp.json() : await resp.text();
    if (!resp.ok) {
      const msg = (data && (data.detail || data.message)) || `Erro ${resp.status}`;
      throw new Error(typeof msg === "string" ? msg : JSON.stringify(msg));
    }
    return data;
  }

  let toastTimer = null;
  function toast(message, kind = "ok") {
    const el = $("#toast");
    if (!el) return;
    el.textContent = message;
    el.className = "toast show " + kind;
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => { el.className = "toast " + kind; }, 3200);
  }

  function reload(msg) {
    const url = new URL(window.location.href);
    url.searchParams.delete("erro");
    if (msg) url.searchParams.set("msg", msg); else url.searchParams.delete("msg");
    window.location.href = url.toString();
  }

  const esc = (v) => String(v ?? "").replace(/[&<>"']/g, (c) =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

  /* ------------------------------------------------------------ autocomplete */

  function attachAutocomplete(input) {
    const endpoint = input.dataset.autocomplete;
    if (!endpoint) return;
    let list = null, itens = [], index = -1, timer = null;

    const close = () => { if (list) { list.remove(); list = null; index = -1; } };

    const render = (dados) => {
      close();
      if (!dados.length) return;
      list = document.createElement("ul");
      list.className = "autocomplete-list";
      list.setAttribute("role", "listbox");
      dados.forEach((item, i) => {
        const li = document.createElement("li");
        li.setAttribute("role", "option");
        li.dataset.index = String(i);
        const direita = item.preco_medio_fmt
          ? `${item.preco_medio_fmt}${item.compras > 1 ? " · " + item.compras + " compras" : ""}`
          : (item.origem === "historico" ? "usar e salvar no catálogo" : "novo item");
        li.innerHTML = `<span>${esc(item.name)}${item.category_name ? ` <small>· ${esc(item.category_name)}</small>` : ""}</span><small>${esc(direita)}</small>`;
        li.addEventListener("mousedown", (ev) => { ev.preventDefault(); escolher(i); });
        list.appendChild(li);
      });
      input.parentElement.style.position = "relative";
      input.parentElement.appendChild(list);
    };

    const escolher = (i) => {
      const item = itens[i];
      if (!item) return;
      input.value = item.name;
      const form = input.closest("form");
      if (form) {
        const hidden = form.querySelector('input[name="item_id"]');
        if (hidden) hidden.value = item.id || "";
        const cat = form.querySelector('select[name="category_id"]');
        if (cat && item.category_id && !cat.value) cat.value = String(item.category_id);
      }
      close();
      priceCheck(form, item.id, item.preco_medio);
    };

    const buscar = async () => {
      const q = input.value.trim();
      if (q.length < 1) { close(); return; }
      try {
        itens = await api(`${endpoint}?q=${encodeURIComponent(q)}&limit=8`);
        render(itens);
      } catch (e) { /* silencioso: autocomplete é conveniência */ }
    };

    input.addEventListener("input", () => {
      const form = input.closest("form");
      if (form) { const h = form.querySelector('input[name="item_id"]'); if (h) h.value = ""; }
      clearTimeout(timer);
      timer = setTimeout(buscar, 170);
    });
    input.addEventListener("keydown", (ev) => {
      if (!list) return;
      const lis = $$("li", list);
      if (ev.key === "ArrowDown") { ev.preventDefault(); index = (index + 1) % lis.length; }
      else if (ev.key === "ArrowUp") { ev.preventDefault(); index = (index - 1 + lis.length) % lis.length; }
      else if (ev.key === "Enter" && index >= 0) { ev.preventDefault(); escolher(index); return; }
      else if (ev.key === "Escape") { close(); return; }
      else return;
      lis.forEach((li, i) => li.setAttribute("aria-selected", i === index ? "true" : "false"));
    });
    input.addEventListener("blur", () => setTimeout(close, 150));
  }

  function priceCheck(form, itemId, mediaHistorica) {
    const hint = form ? form.querySelector("[data-price-hint], #price-hint") : null;
    if (!hint) return;
    const amountInput = form.querySelector('input[name="amount"]');
    const centavos = amountInput ? parseMoney(amountInput.value) : null;
    if (!itemId || !centavos) { hint.hidden = true; hint.textContent = ""; return; }
    api(`/api/items/${itemId}/price-check?amount=${centavos}`)
      .then((r) => {
        if (!r.tem_historico) { hint.hidden = true; return; }
        hint.hidden = false;
        hint.innerHTML = `Histórico de <strong>${esc(form.querySelector('[data-autocomplete]').value || "")}</strong>: ` +
          `${r.compras} compra(s), preço médio ${r.media_fmt}. Agora: <strong>${fmtMoney(centavos)}</strong> ` +
          `(${r.variacao_fmt})${r.alerta ? " ⚠️" : ""}`;
        hint.style.color = r.alerta ? "var(--amber)" : "";
      })
      .catch(() => { hint.hidden = true; });
  }

  /* ------------------------------------------------------------ categorias por tipo */

  function filterCategories(form) {
    const tipo = (form.querySelector('input[name="type"]:checked') || {}).value || "saida";
    $$('select[name="category_id"] option', form).forEach((opt) => {
      const kind = opt.dataset.kind;
      if (!kind) return;
      opt.hidden = kind !== tipo;
      opt.disabled = kind !== tipo;
    });
    const sel = form.querySelector('select[name="category_id"]');
    if (sel && sel.selectedOptions[0] && sel.selectedOptions[0].disabled) sel.value = "";
  }

  /* ------------------------------------------------------------ formulários */

  function collectTransaction(form) {
    const dados = {
      type: (form.querySelector('input[name="type"]:checked') || {}).value || "saida",
      status: (form.querySelector('[name="status"]') || {}).value || "realizado",
      occurred_on: (form.querySelector('[name="occurred_on"]') || {}).value || null,
      description: (form.querySelector('[name="description"]') || {}).value || "",
      category_id: Number((form.querySelector('[name="category_id"]') || {}).value) || null,
      item_id: Number((form.querySelector('[name="item_id"]') || {}).value) || null,
      method: (form.querySelector('[name="method"]') || {}).value || null,
      recurring: !!(form.querySelector('[name="recurring"]') || {}).checked,
      note: (form.querySelector('[name="note"]') || {}).value || null,
      create_item: (form.querySelector('[name="create_item"]') || { checked: true }).checked,
    };
    const amountField = form.querySelector('[name="amount"]');
    const centavos = parseMoney(amountField ? amountField.value : null);
    if (centavos === null || centavos <= 0) throw new Error("Informe um valor válido (ex.: 1.250,00).");
    dados.amount_centavos = centavos;
    if (!dados.description.trim()) throw new Error("Informe uma descrição ou item.");
    return dados;
  }

  function bindQuickAdd() {
    const form = $("#form-lancamento");
    if (!form) return;
    form.addEventListener("submit", async (ev) => {
      ev.preventDefault();
      const btn = form.querySelector('button[type="submit"]');
      btn.disabled = true;
      try {
        const dados = collectTransaction(form);
        const tx = await api("/api/transactions", { method: "POST", body: dados });
        toast(`${tx.is_entrada ? "Entrada" : "Saída"} de ${tx.valor_fmt} registrada`, "ok");
        setTimeout(() => reload("Lançamento registrado: " + tx.description + " · " + tx.valor_fmt), 250);
      } catch (e) {
        toast(e.message, "err");
        btn.disabled = false;
      }
    });
    form.addEventListener("reset", () => setTimeout(() => filterCategories(form), 0));
    $$('input[name="type"]', form).forEach((r) => r.addEventListener("change", () => filterCategories(form)));
    $$("[data-autocomplete]", form).forEach(attachAutocomplete);
    const amount = form.querySelector('[name="amount"]');
    if (amount) {
      amount.addEventListener("blur", () => {
        const form2 = amount.closest("form");
        const itemId = Number((form2.querySelector('[name="item_id"]') || {}).value) || null;
        priceCheck(form2, itemId);
      });
    }
    document.addEventListener("keydown", (ev) => {
      if ((ev.ctrlKey || ev.metaKey) && ev.key === "Enter" && document.activeElement && form.contains(document.activeElement)) {
        ev.preventDefault();
        form.requestSubmit();
      }
    });
    filterCategories(form);
  }

  function openModal(id) {
    const dlg = document.getElementById(id);
    if (dlg && typeof dlg.showModal === "function") dlg.showModal();
  }
  function closeModal(dlg) { if (dlg && dlg.open) dlg.close(); }

  function bindTransactionModal() {
    const dlg = $("#modal-lancamento");
    const form = $("#form-editar");
    if (!dlg || !form) return;
    $$("[data-autocomplete]", form).forEach(attachAutocomplete);
    $$('input[name="type"]', form).forEach((r) => r.addEventListener("change", () => filterCategories(form)));

    form.addEventListener("submit", async (ev) => {
      ev.preventDefault();
      const id = form.querySelector('[name="id"]').value;
      try {
        const dados = collectTransaction(form);
        const tx = id
          ? await api(`/api/transactions/${id}`, { method: "PATCH", body: dados })
          : await api("/api/transactions", { method: "POST", body: dados });
        closeModal(dlg);
        reload("Lançamento salvo: " + tx.description + " · " + tx.valor_fmt);
      } catch (e) { toast(e.message, "err"); }
    });

    document.addEventListener("click", (ev) => {
      const btn = ev.target.closest('[data-action="edit"]');
      if (btn) {
        let tx = {};
        try { tx = JSON.parse(btn.dataset.tx || "{}"); } catch (e) { tx = {}; }
        form.querySelector('[name="id"]').value = tx.id || "";
        const radio = form.querySelector(`input[name="type"][value="${tx.type || "saida"}"]`);
        if (radio) radio.checked = true;
        filterCategories(form);
        form.querySelector('[name="amount"]').value = toInputMoney(tx.amount_centavos);
        form.querySelector('[name="occurred_on"]').value = tx.occurred_on || "";
        form.querySelector('[name="description"]').value = tx.description || "";
        form.querySelector('[name="category_id"]').value = tx.category_id ? String(tx.category_id) : "";
        form.querySelector('[name="method"]').value = tx.method || "";
        form.querySelector('[name="status"]').value = tx.status || "realizado";
        form.querySelector('[name="recurring"]').checked = !!tx.recurring;
        form.querySelector('[name="note"]').value = tx.note || "";
        openModal("modal-lancamento");
      }
      if (ev.target.closest('[data-action="new-transaction"]')) {
        form.reset();
        form.querySelector('[name="id"]').value = "";
        filterCategories(form);
        $(".modal-head h2", dlg).textContent = "Novo lançamento";
        openModal("modal-lancamento");
      }
    });
  }

  /* ------------------------------------------------------------ itens */

  function bindItems() {
    const novo = $("#form-item");
    if (novo) {
      novo.addEventListener("submit", async (ev) => {
        ev.preventDefault();
        try {
          const dados = {
            name: novo.querySelector('[name="name"]').value.trim(),
            category_id: Number(novo.querySelector('[name="category_id"]').value) || null,
            unit: novo.querySelector('[name="unit"]').value.trim() || null,
            note: novo.querySelector('[name="note"]').value.trim() || null,
          };
          if (!dados.name) throw new Error("Informe o nome do item.");
          await api("/api/items", { method: "POST", body: dados });
          reload("Item cadastrado: " + dados.name);
        } catch (e) { toast(e.message, "err"); }
      });
    }

    const dlg = $("#modal-item");
    const form = $("#form-item-editar");
    if (dlg && form) {
      form.addEventListener("submit", async (ev) => {
        ev.preventDefault();
        const id = form.querySelector('[name="id"]').value;
        try {
          const dados = {
            name: form.querySelector('[name="name"]').value.trim(),
            category_id: Number(form.querySelector('[name="category_id"]').value) || null,
            unit: form.querySelector('[name="unit"]').value.trim() || null,
            note: form.querySelector('[name="note"]').value.trim() || null,
          };
          await api(`/api/items/${id}`, { method: "PATCH", body: dados });
          closeModal(dlg);
          reload("Item atualizado.");
        } catch (e) { toast(e.message, "err"); }
      });
    }

    document.addEventListener("click", async (ev) => {
      const editar = ev.target.closest('[data-action="edit-item"]');
      if (editar && form) {
        const item = JSON.parse(editar.dataset.item || "{}");
        form.querySelector('[name="id"]').value = item.id;
        form.querySelector('[name="name"]').value = item.name || "";
        form.querySelector('[name="category_id"]').value = item.category_id ? String(item.category_id) : "";
        form.querySelector('[name="unit"]').value = item.unit || "";
        form.querySelector('[name="note"]').value = item.note || "";
        openModal("modal-item");
      }
      const apagar = ev.target.closest('[data-action="delete-item"]');
      if (apagar) {
        if (!confirm("Remover este item do catálogo? Os lançamentos continuam (ficam sem item vinculado).")) return;
        try {
          await api(`/api/items/${apagar.dataset.id}`, { method: "DELETE" });
          reload("Item removido do catálogo.");
        } catch (e) { toast(e.message, "err"); }
      }
    });
  }

  /* ------------------------------------------------------------ categorias */

  function bindCategories() {
    const novo = $("#form-categoria");
    if (novo) {
      novo.addEventListener("submit", async (ev) => {
        ev.preventDefault();
        try {
          const budgetRaw = novo.querySelector('[name="budget"]').value.trim();
          const dados = {
            name: novo.querySelector('[name="name"]').value.trim(),
            kind: novo.querySelector('[name="kind"]').value,
            color: novo.querySelector('[name="color"]').value,
            budget: budgetRaw ? Math.abs(parseMoney(budgetRaw)) : null,
          };
          if (!dados.name) throw new Error("Informe o nome da categoria.");
          await api("/api/categories", { method: "POST", body: dados });
          reload("Categoria criada: " + dados.name);
        } catch (e) { toast(e.message, "err"); }
      });
    }

    const dlg = $("#modal-categoria");
    const form = $("#form-categoria-editar");
    if (dlg && form) {
      form.addEventListener("submit", async (ev) => {
        ev.preventDefault();
        const id = form.querySelector('[name="id"]').value;
        try {
          const budgetRaw = form.querySelector('[name="budget"]').value.trim();
          const dados = {
            name: form.querySelector('[name="name"]').value.trim(),
            kind: form.querySelector('[name="kind"]').value,
            color: form.querySelector('[name="color"]').value,
            budget: budgetRaw ? Math.abs(parseMoney(budgetRaw)) : null,
            archived: form.querySelector('[name="archived"]').checked,
          };
          await api(`/api/categories/${id}`, { method: "PATCH", body: dados });
          closeModal(dlg);
          reload("Categoria atualizada.");
        } catch (e) { toast(e.message, "err"); }
      });
    }

    document.addEventListener("click", async (ev) => {
      const editar = ev.target.closest('[data-action="edit-category"]');
      if (editar && form) {
        const cat = JSON.parse(editar.dataset.cat || "{}");
        form.querySelector('[name="id"]').value = cat.id;
        form.querySelector('[name="name"]').value = cat.name || "";
        form.querySelector('[name="kind"]').value = cat.kind || "saida";
        form.querySelector('[name="color"]').value = cat.color || "#64748b";
        form.querySelector('[name="budget"]').value = cat.budget ? toInputMoney(cat.budget) : "";
        form.querySelector('[name="archived"]').checked = !!cat.archived;
        openModal("modal-categoria");
      }
      const apagar = ev.target.closest('[data-action="delete-category"]');
      if (apagar) {
        if (!confirm(`Excluir a categoria "${apagar.dataset.name}"? Os lançamentos dela ficam sem categoria.`)) return;
        try {
          await api(`/api/categories/${apagar.dataset.id}`, { method: "DELETE" });
          reload("Categoria excluída.");
        } catch (e) { toast(e.message, "err"); }
      }
    });
  }

  /* ------------------------------------------------------------ ciclo */

  function bindCycle() {
    const form = $("#form-ciclo");
    if (!form) return;
    form.addEventListener("submit", async (ev) => {
      ev.preventDefault();
      try {
        const period = form.dataset.period;
        const bruto = form.querySelector('[name="expected_income"]').value.trim();
        const dia = form.querySelector('[name="payday_day"]').value;
        const dados = {
          expected_income: bruto ? Math.abs(parseMoney(bruto)) : 0,
          payday_day: dia ? Number(dia) : null,
          note: form.querySelector('[name="note"]').value.trim() || null,
          lock: true,
        };
        const ciclo = await api(`/api/cycles/${period}`, { method: "PUT", body: dados });
        reload(`Salário previsto de ${period} definido em ${ciclo.expected_fmt}.`);
      } catch (e) { toast(e.message, "err"); }
    });
  }

  /* ------------------------------------------------------------ ações em linha */

  function bindRowActions() {
    document.addEventListener("click", async (ev) => {
      const alvo = ev.target.closest("[data-action]");
      if (!alvo) return;
      const acao = alvo.dataset.action;

      if (acao === "close-modal") {
        const dlg = alvo.closest("dialog");
        if (dlg) closeModal(dlg);
        return;
      }

      if (acao === "toggle") {
        const id = alvo.dataset.id;
        try {
          const tx = await api(`/api/transactions/${id}/toggle`, { method: "POST" });
          const tr = alvo.closest("tr");
          if (tr) {
            tr.classList.toggle("previsto", tx.is_previsto);
            alvo.textContent = tx.is_previsto ? "previsto" : "realizado";
            alvo.className = "chip " + (tx.is_previsto ? "warn" : "ok");
            const valor = tr.querySelector(".col-valor");
            if (valor) { valor.textContent = tx.valor_sinal_fmt; valor.className = "col-valor " + (tx.is_entrada ? "pos" : "neg"); }
          }
          toast(tx.is_previsto ? "Marcado como previsto" : "Marcado como realizado", "ok");
        } catch (e) { toast(e.message, "err"); }
        return;
      }

      if (acao === "delete") {
        if (!confirm("Excluir este lançamento?")) return;
        try {
          await api(`/api/transactions/${alvo.dataset.id}`, { method: "DELETE" });
          reload("Lançamento excluído.");
        } catch (e) { toast(e.message, "err"); }
        return;
      }

      if (acao === "repeat-recurring") {
        try {
          const r = await api(`/api/cycles/${alvo.dataset.period}/repeat-recurring`, { method: "POST" });
          reload(r.criados ? `${r.criados} gasto(s) fixo(s) copiado(s) como previsto.` : "Nada novo para copiar.");
        } catch (e) { toast(e.message, "err"); }
        return;
      }

      if (acao === "seed-demo") {
        if (!confirm("Gerar 4 meses de dados de demonstração? Eles serão somados aos seus lançamentos.")) return;
        try {
          const r = await api("/api/demo?months=4", { method: "POST" });
          reload(`${r.lancamentos_criados} lançamentos de demonstração criados.`);
        } catch (e) { toast(e.message, "err"); }
        return;
      }

      if (acao === "undo-import") {
        if (!confirm("Desfazer esta importação? Todos os lançamentos do lote serão removidos.")) return;
        try {
          const r = await api(`/api/imports/${alvo.dataset.id}`, { method: "DELETE" });
          reload(`Importação desfeita (${r.lancamentos_removidos} lançamento(s) removidos).`);
        } catch (e) { toast(e.message, "err"); }
        return;
      }
    });
  }

  /* ------------------------------------------------------------ importação */

  const importState = { token: null, filename: null, options: {}, mapping: {} };

  function importMeta() {
    const el = $("#import-meta");
    if (!el) return { campos: {}, categorias_saida: [] };
    try { return JSON.parse(el.textContent); } catch (e) { return { campos: {}, categorias_saida: [] }; }
  }

  function readOptions(form) {
    return {
      default_type: form.querySelector('[name="default_type"]').value,
      default_status: form.querySelector('[name="default_status"]').value,
      default_category: form.querySelector('[name="default_category"]').value || null,
      create_categories: form.querySelector('[name="create_categories"]').checked,
      create_items: form.querySelector('[name="create_items"]').checked,
      skip_duplicates: form.querySelector('[name="skip_duplicates"]').checked,
      sheet: form.querySelector('[name="sheet"]').value || 0,
    };
  }

  function renderPreview(d) {
    const card = $("#preview-card");
    if (!card) return;
    card.hidden = false;
    $("#preview-file").textContent = `${d.filename} · ${d.rows_total} linha(s) de dados`;

    $("#preview-counts").innerHTML = [
      ["Linhas lidas", d.rows_total],
      ["Válidas", d.validas],
      ["Inválidas", d.invalidas],
      ["Duplicadas", d.options && d.options.skip_duplicates === false ? 0 : d.duplicadas],
      ["Meses", d.periodos_count],
    ].map(([rotulo, valor]) => `<div class="kpi"><b>${esc(valor)}</b><span>${esc(rotulo)}</span></div>`).join("");

    $("#preview-periods").innerHTML = Object.entries(d.periodos || {})
      .slice(0, 18)
      .map(([p, n]) => `<span class="chip static">${esc(p)} · ${esc(n)}</span>`)
      .join("") || '<span class="muted">nenhum mês detectado</span>';

    if (d.modo_extrato) {
      $("#preview-periods").insertAdjacentHTML(
        "beforeend",
        '<span class="badge warn">modo extrato: positivo = entrada, negativo = saída</span>'
      );
    }

    const meta = importMeta();
    const campos = meta.campos || {};
    const options = Object.entries(campos)
      .map(([k, label]) => `<option value="${esc(k)}">${esc(label)}</option>`)
      .join("");
    const inverso = {};
    Object.entries(d.mapping || {}).forEach(([campo, col]) => { inverso[col] = campo; });

    $("#preview-mapping").innerHTML = `
      <thead><tr><th>Coluna da planilha</th><th>Amostras</th><th>Usar como</th></tr></thead>
      <tbody>
      ${d.columns.map((c) => `
        <tr>
          <td><strong>${esc(c.header)}</strong> <small class="muted">#${c.index + 1}</small></td>
          <td class="muted small">${c.samples.map(esc).join(" · ") || "—"}</td>
          <td>
            <select data-col="${c.index}" class="map-select">
              <option value="-1">— ignorar —</option>
              ${options}
            </select>
          </td>
        </tr>`).join("")}
      </tbody>`;

    $$(".map-select").forEach((sel) => {
      const campo = inverso[Number(sel.dataset.col)];
      if (campo) sel.value = campo;
      sel.addEventListener("change", () => remapear());
    });

    const cabecalho = ["Linha", "Data", "Tipo", "Situação", "Descrição", "Categoria", "Valor"];
    $("#preview-rows").innerHTML = `
      <thead><tr>${cabecalho.map((h) => `<th>${esc(h)}</th>`).join("")}</tr></thead>
      <tbody>
      ${(d.preview || []).map((r) => `
        <tr class="${r.ok ? "" : "row-bad"}">
          <td class="muted">${esc(r.line)}</td>
          <td>${esc(r.ok ? r.date : (r.date_fmt || "?"))}</td>
          <td>${esc(r.type)}</td>
          <td>${esc(r.status)}</td>
          <td>${esc(r.description || "")}${r.error ? ` <span class="badge danger">${esc(r.error)}</span>` : ""}</td>
          <td class="muted">${esc(r.category || "")}</td>
          <td class="num">${r.ok ? esc(fmtMoney(r.amount)) : "—"}</td>
        </tr>`).join("")}
      </tbody>`;

    const erros = d.errors || [];
    $("#preview-errors").innerHTML = erros.length
      ? `<h3 class="sub-title">Linhas com problema (${erros.length})</h3>
         <ul class="tips">${erros.map((e) => `<li>linha ${esc(e.row)}: ${esc(e.error)} <small class="muted">${esc(e.raw || "")}</small></li>`).join("")}</ul>`
      : "";

    if (d.sheets && d.sheets.length > 1) {
      const sel = $('[name="sheet"]');
      sel.innerHTML = d.sheets.map((nome, i) => `<option value="${i}">${esc(nome)}</option>`).join("");
      sel.value = String(d.sheet || 0);
      sel.onchange = () => reanalisar();
    }
    card.scrollIntoView({ behavior: "smooth", block: "start" });
  }

  function mappingFromSelects() {
    const mapping = {};
    $$(".map-select").forEach((sel) => {
      if (sel.value && sel.value !== "-1") mapping[sel.value] = Number(sel.dataset.col);
    });
    return mapping;
  }

  async function remapear() {
    if (!importState.token) return;
    try {
      const d = await api("/api/import/preview", {
        method: "POST",
        body: { ...importState.options, token: importState.token, filename: importState.filename, mapping: mappingFromSelects() },
      });
      renderPreview(d);
      toast("Mapeamento atualizado.", "ok");
    } catch (e) { toast(e.message, "err"); }
  }

  async function reanalisar() {
    const form = $("#form-import");
    const fileInput = form.querySelector('[name="file"]');
    if (!fileInput.files.length) return;
    const fd = new FormData(form);
    const status = $("#import-status");
    status.textContent = "reanalisando…";
    try {
      const d = await api("/api/import/upload", { method: "POST", body: fd });
      importState.token = d.token;
      importState.filename = d.filename;
      importState.options = readOptions(form);
      status.textContent = "";
      renderPreview(d);
    } catch (e) {
      status.textContent = "";
      toast(e.message, "err");
    }
  }

  function bindImport() {
    const form = $("#form-import");
    if (!form) return;

    form.addEventListener("submit", async (ev) => {
      ev.preventDefault();
      const fileInput = form.querySelector('[name="file"]');
      if (!fileInput.files.length) { toast("Escolha um arquivo primeiro.", "err"); return; }
      const status = $("#import-status");
      const btn = form.querySelector('button[type="submit"]');
      btn.disabled = true;
      status.textContent = "analisando planilha…";
      try {
        const fd = new FormData(form);
        const d = await api("/api/import/upload", { method: "POST", body: fd });
        importState.token = d.token;
        importState.filename = d.filename;
        importState.options = readOptions(form);
        importState.mapping = d.mapping;
        status.textContent = "";
        renderPreview(d);
        toast(`${d.validas} linha(s) pronta(s) para importar.`, "ok");
      } catch (e) {
        status.textContent = "";
        toast(e.message, "err");
      } finally {
        btn.disabled = false;
      }
    });

    document.addEventListener("click", async (ev) => {
      if (ev.target.closest('[data-action="cancel-import"]')) {
        importState.token = null;
        const card = $("#preview-card");
        if (card) card.hidden = true;
        return;
      }
      if (ev.target.closest('[data-action="commit-import"]')) {
        if (!importState.token) return;
        const btn = ev.target.closest("button");
        btn.disabled = true;
        btn.textContent = "importando…";
        try {
          const r = await api("/api/import/commit", {
            method: "POST",
            body: { ...importState.options, token: importState.token, filename: importState.filename, mapping: mappingFromSelects() },
          });
          window.location.href = `/relatorios?msg=${encodeURIComponent(
            `Importados ${r.imported} lançamento(s) de ${r.filename} (${r.periodos.length} mês/meses).`
          )}`;
        } catch (e) {
          toast(e.message, "err");
          btn.disabled = false;
          btn.textContent = "3. Confirmar importação";
        }
      }
    });
  }

  /* ------------------------------------------------------------ boot */

  document.addEventListener("DOMContentLoaded", () => {
    bindQuickAdd();
    bindTransactionModal();
    bindItems();
    bindCategories();
    bindCycle();
    bindRowActions();
    bindImport();
    $$("dialog").forEach((dlg) => dlg.addEventListener("click", (ev) => { if (ev.target === dlg) dlg.close(); }));
  });

  window.Saldo = { api, parseMoney, fmtMoney, toast };
})();
