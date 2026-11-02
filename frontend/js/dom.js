// Small DOM helpers shared by every module.

export const $ = (id) => document.getElementById(id);

export function escapeHtml(str) {
  return String(str)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;');
}

export function openModal(modal) {
  modal.classList.add('active');
}

export function closeModal(modal) {
  modal.classList.remove('active');
}

export function isOpen(modal) {
  return modal.classList.contains('active');
}
