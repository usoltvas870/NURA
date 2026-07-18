/* NURA Landing v2.3C Final — production interactivity */
(() => {
  'use strict';

  /* ------------------------------------------------------------------ */
  /*  Header scroll state                                               */
  /* ------------------------------------------------------------------ */
  const header = document.querySelector('.header');

  const setHeader = () => {
    if (header) header.classList.toggle('scrolled', window.scrollY > 8);
  };

  setHeader();
  window.addEventListener('scroll', setHeader, { passive: true });

  /* ------------------------------------------------------------------ */
  /*  Mobile menu                                                       */
  /* ------------------------------------------------------------------ */
  const menuButton = document.querySelector('.menu');
  const navLinks = document.getElementById('nav-links');

  const setMenu = (open, returnFocus = false) => {
    if (!menuButton || !navLinks) return;
    menuButton.setAttribute('aria-expanded', String(open));
    navLinks.classList.toggle('open', open);
    if (returnFocus) menuButton.focus();
  };

  menuButton?.addEventListener('click', () => {
    const open = menuButton.getAttribute('aria-expanded') === 'true';
    setMenu(!open);
  });

  // Close menu when any nav link is clicked
  navLinks?.querySelectorAll('a').forEach((link) => {
    link.addEventListener('click', () => setMenu(false));
  });

  document.addEventListener('keydown', (event) => {
    if (
      event.key === 'Escape' &&
      menuButton?.getAttribute('aria-expanded') === 'true'
    ) {
      setMenu(false, true);
    }
  });

  /* ------------------------------------------------------------------ */
  /*  Report example dialog                                             */
  /* ------------------------------------------------------------------ */
  const dialog = document.getElementById('report-example-dialog');
  const dialogTrigger = document.querySelector('.report-example-v23c__trigger');

  if (dialog && dialog instanceof HTMLDialogElement && dialogTrigger) {
    let returnFocusEl = null;

    dialogTrigger.addEventListener('click', () => {
      returnFocusEl = document.activeElement;
      document.documentElement.classList.add('report-dialog-v23c-open');
      dialog.showModal();
    });

    // Close on backdrop click
    dialog.addEventListener('click', (event) => {
      if (event.target === dialog) dialog.close();
    });

    dialog.addEventListener('close', () => {
      document.documentElement.classList.remove('report-dialog-v23c-open');
      if (returnFocusEl instanceof HTMLElement) returnFocusEl.focus();
    });
  }

  /* ------------------------------------------------------------------ */
  /*  Exclusive accordions helper                                       */
  /* ------------------------------------------------------------------ */
  const wireExclusiveAccordions = (selector, scope) => {
    if (!scope) return;

    const triggers = scope.querySelectorAll(selector);

    triggers.forEach((trigger) => {
      trigger.addEventListener('click', () => {
        const panelId = trigger.getAttribute('aria-controls');
        const panel = panelId ? document.getElementById(panelId) : null;
        if (!panel) return;

        const willOpen = trigger.getAttribute('aria-expanded') !== 'true';

        // Collapse every trigger-panel pair within this scope
        triggers.forEach((other) => {
          const otherPanelId = other.getAttribute('aria-controls');
          const otherPanel = otherPanelId ? document.getElementById(otherPanelId) : null;
          other.setAttribute('aria-expanded', 'false');
          if (otherPanel) otherPanel.hidden = true;
        });

        // Expand the clicked trigger only if it was collapsed
        trigger.setAttribute('aria-expanded', String(willOpen));
        panel.hidden = !willOpen;
      });
    });
  };

  /* ------------------------------------------------------------------ */
  /*  Pricing accordions                                                */
  /* ------------------------------------------------------------------ */
  const pricing = document.querySelector('.pricing-v23c');
  if (pricing) {
    wireExclusiveAccordions('.pricing-v23c__details-trigger', pricing);
  }

  /* ------------------------------------------------------------------ */
  /*  FAQ accordions                                                    */
  /* ------------------------------------------------------------------ */
  const faq = document.querySelector('.faq-v23c');
  if (faq) {
    wireExclusiveAccordions('.faq-v23c__trigger', faq);
  }
})();