// Copy button
document.querySelectorAll('.copy-btn').forEach(btn => {
  btn.addEventListener('click', () => {
    const text = btn.dataset.copy;
    navigator.clipboard.writeText(text).then(() => {
      btn.classList.add('copied');
      btn.textContent = 'Copied!';
      setTimeout(() => {
        btn.classList.remove('copied');
        btn.innerHTML = copyIcon();
      }, 2000);
    });
  });
});

function copyIcon() {
  return `<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="9" y="9" width="13" height="13" rx="2"/><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"/></svg>`;
}

// Tabs
document.querySelectorAll('.tab-btn').forEach(btn => {
  btn.addEventListener('click', () => {
    const group = btn.dataset.group;
    const target = btn.dataset.tab;

    document.querySelectorAll(`.tab-btn[data-group="${group}"]`).forEach(b => b.classList.remove('active'));
    document.querySelectorAll(`.tab-panel[data-group="${group}"]`).forEach(p => p.classList.remove('active'));

    btn.classList.add('active');
    document.querySelector(`.tab-panel[data-group="${group}"][data-tab="${target}"]`).classList.add('active');
  });
});

// Nav blur on scroll
const nav = document.querySelector('nav');
window.addEventListener('scroll', () => {
  nav.style.borderBottomColor = window.scrollY > 10 ? '#2a2a2a' : '#1f1f1f';
});
