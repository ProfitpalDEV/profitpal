// footer.js
function insertFooter() {
    const footer = document.createElement('footer');
    footer.style.cssText = 'text-align:center; padding:30px 20px; margin-top:50px; border-top:1px solid rgba(34,139,34,0.2); color:#95a5a6; font-size:14px;';
    footer.innerHTML = '© 2025 ProfitPal. A product of Denava LLC. All rights reserved.';
    document.body.appendChild(footer);
}

// Автоматически вставляем при загрузке
if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', insertFooter);
} else {
    insertFooter();
}