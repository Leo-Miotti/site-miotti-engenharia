
(function () {
  'use strict';

  /* --------------------------------------------------- Menu no celular */
  const botaoMenu = document.getElementById('abrirMenu');
  const menu = document.getElementById('menu');

  if (botaoMenu && menu) {
    botaoMenu.addEventListener('click', function () {
      const aberto = menu.classList.toggle('aberto');
      botaoMenu.setAttribute('aria-expanded', String(aberto));
      botaoMenu.setAttribute('aria-label', aberto ? 'Fechar menu' : 'Abrir menu');
    });

    menu.addEventListener('click', function (e) {
      if (e.target.tagName === 'A') {
        menu.classList.remove('aberto');
        botaoMenu.setAttribute('aria-expanded', 'false');
      }
    });

    document.addEventListener('keydown', function (e) {
      if (e.key === 'Escape' && menu.classList.contains('aberto')) {
        menu.classList.remove('aberto');
        botaoMenu.setAttribute('aria-expanded', 'false');
        botaoMenu.focus();
      }
    });
  }

  /* ------------------------------- Destaque da seção visível no menu */
  const secoes = Array.from(document.querySelectorAll('section[id], header[id]'));
  const links = new Map();
  document.querySelectorAll('.menu a[href*="#"]').forEach(function (a) {
    const id = a.getAttribute('href').split('#')[1];
    if (id) links.set(id, a);
  });

  if ('IntersectionObserver' in window && secoes.length) {
    const observador = new IntersectionObserver(
      function (entradas) {
        entradas.forEach(function (entrada) {
          const link = links.get(entrada.target.id);
          if (!link) return;
          if (entrada.isIntersecting) {
            links.forEach(function (l) { l.classList.remove('ativo'); });
            link.classList.add('ativo');
          }
        });
      },
      { rootMargin: '-45% 0px -50% 0px' }
    );
    secoes.forEach(function (s) { observador.observe(s); });
  }

  /* ------------------------------------------ Máscara de telefone */
  const telefone = document.getElementById('telefone');
  if (telefone) {
    telefone.addEventListener('input', function () {
      const d = telefone.value.replace(/\D/g, '').slice(0, 11);
      let saida = d;
      if (d.length > 2) saida = '(' + d.slice(0, 2) + ') ' + d.slice(2);
      if (d.length > 7) {
        const corte = d.length > 10 ? 7 : 6;
        saida = '(' + d.slice(0, 2) + ') ' + d.slice(2, corte) + '-' + d.slice(corte);
      }
      telefone.value = saida;
    });
  }

  /* ------------------------------------------ Envio do orçamento */
  const form = document.getElementById('formOrcamento');
  if (!form) return;

  const botao = document.getElementById('btnEnviar');
  const aviso = document.getElementById('avisoForm');

  function limparErros() {
    form.querySelectorAll('.erro').forEach(function (p) { p.textContent = ''; });
    form.querySelectorAll('[aria-invalid]').forEach(function (c) {
      c.removeAttribute('aria-invalid');
    });
    aviso.textContent = '';
    aviso.className = 'aviso';
  }

  function mostrarErros(erros) {
    let primeiro = null;
    Object.keys(erros).forEach(function (campo) {
      const alvo = form.querySelector('[data-erro="' + campo + '"]');
      if (alvo) alvo.textContent = erros[campo];
      const entrada = form.querySelector('[name="' + campo + '"]');
      if (entrada) {
        entrada.setAttribute('aria-invalid', 'true');
        if (!primeiro) primeiro = entrada;
      }
    });
    if (erros.geral) {
      aviso.textContent = erros.geral;
      aviso.className = 'aviso falhou';
    }
    if (primeiro) primeiro.focus({ preventScroll: false });
  }

  function coletar() {
    const dados = {
      nome: form.nome.value,
      email: form.email.value,
      telefone: form.telefone.value,
      area: form.area.value,
      comentario: form.comentario.value,
      website: form.website.value,
      servico: []
    };
    form.querySelectorAll('input[name="servico"]:checked').forEach(function (c) {
      dados.servico.push(c.value);
    });
    return dados;
  }

  form.addEventListener('submit', async function (evento) {
    evento.preventDefault();
    limparErros();

    const dados = coletar();
    botao.disabled = true;
    const rotuloOriginal = botao.textContent;
    botao.textContent = 'Enviando…';

    try {
      const resposta = await fetch('/api/orcamento', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(dados)
      });
      const corpo = await resposta.json();

      if (!corpo.ok) {
        mostrarErros(corpo.erros || { geral: 'Não foi possível enviar agora.' });
        return;
      }

      aviso.textContent = 'Pedido registrado. Abrindo o WhatsApp para você confirmar o envio.';
      aviso.className = 'aviso ok';
      form.reset();

      if (corpo.whatsapp) {
        const aba = window.open(corpo.whatsapp, '_blank', 'noopener');
        // Se o navegador bloquear a janela, oferece o link manualmente.
        if (!aba) {
          aviso.innerHTML =
            'Pedido registrado. <a href="' + corpo.whatsapp +
            '" target="_blank" rel="noopener">Toque aqui para abrir o WhatsApp</a>.';
        }
      }
    } catch (e) {
      aviso.textContent =
        'A conexão falhou. Chame no WhatsApp (55) 99935-8573 que o Renan responde por lá.';
      aviso.className = 'aviso falhou';
    } finally {
      botao.disabled = false;
      botao.textContent = rotuloOriginal;
    }
  });
})();
