(() => {
  const slides = [...document.querySelectorAll('.slide')];
  const navForm = document.querySelector('[data-nav-form]');
  const pageInput = document.querySelector('[data-page-input]');
  const total = document.querySelector('[data-total]');
  const progress = document.querySelector('[data-progress]');
  const params = new URLSearchParams(location.search);
  const captureMode = params.get('capture') === '1';
  const clamp = value => Math.min(slides.length, Math.max(1, Number(value) || 1));
  let current = clamp(params.get('slide'));

  function fitDeck() {
    const navSafeSpace = captureMode ? 0 : 94;
    const scale = Math.min(innerWidth / 1920, (innerHeight - navSafeSpace) / 1080);
    const deckLeft = Math.max(0, (innerWidth - 1920 * scale) / 2);
    document.documentElement.style.setProperty('--deck-scale', String(scale));
    document.documentElement.style.setProperty('--deck-left', `${deckLeft}px`);
  }

  if (captureMode) document.body.classList.add('capture');
  addEventListener('resize', fitDeck);
  fitDeck();

  function show(number, updateUrl = true) {
    current = clamp(number);
    slides.forEach((slide, index) => {
      const active = index === current - 1;
      slide.classList.toggle('active', active);
      slide.setAttribute('aria-hidden', String(!active));
    });
    pageInput.value = String(current);
    total.textContent = String(slides.length);
    progress.style.width = `${current / slides.length * 100}%`;
    document.title = `${current}/10 · 하다 만 일 종결반`;
    if (updateUrl) {
      const url = new URL(location.href);
      url.searchParams.set('slide', String(current));
      history.replaceState(null, '', url);
    }
  }

  function next() { show(current + 1); }
  function previous() { show(current - 1); }

  document.querySelector('[data-action="next"]').addEventListener('click', next);
  document.querySelector('[data-action="prev"]').addEventListener('click', previous);
  navForm.addEventListener('submit', event => {
    event.preventDefault();
    show(pageInput.value);
    pageInput.select();
  });
  pageInput.addEventListener('change', () => show(pageInput.value));
  pageInput.addEventListener('focus', () => pageInput.select());
  document.addEventListener('keydown', event => {
    if (event.target === pageInput) return;
    if (['ArrowRight', 'PageDown', ' '].includes(event.key)) { event.preventDefault(); next(); }
    if (['ArrowLeft', 'PageUp'].includes(event.key)) { event.preventDefault(); previous(); }
    if (event.key === 'Home') { event.preventDefault(); show(1); }
    if (event.key === 'End') { event.preventDefault(); show(slides.length); }
  });
  document.querySelector('.deck').addEventListener('click', event => {
    if (event.target.closest('a,button,input,form,iframe')) return;
    event.clientX < innerWidth / 2 ? previous() : next();
  });
  addEventListener('popstate', () => show(new URLSearchParams(location.search).get('slide'), false));
  show(current, false);
})();
