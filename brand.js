// brand.js - НЕКЛИКАБЕЛЬНАЯ ЛИТАЯ ВЕРСИЯ
(function() {
    function addBrand() {
        // Проверяем что бренда еще нет
        if (document.querySelector('.pp-brand-logo')) return;

        // Создаем стили
        const style = document.createElement('style');
        style.textContent = `
            .pp-brand-logo {
                position: fixed;
                top: 20px;
                left: 20px;
                z-index: 1000;
                display: flex;
                align-items: center;
                gap: 10px;
                font-size: 28px;
                font-weight: 900;
                background: linear-gradient(135deg, #32cd32, #ffd700);
                -webkit-background-clip: text;
                -webkit-text-fill-color: transparent;
                background-clip: text;
                pointer-events: none;
                user-select: none;
            }
        `;
        document.head.appendChild(style);

        // Создаем логотип
        const brandContainer = document.createElement('div');
        brandContainer.className = 'pp-brand-logo';
        brandContainer.innerHTML = '💎 ProfitPal';

        document.body.appendChild(brandContainer);
    }

    // Добавляем при загрузке
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', addBrand);
    } else {
        addBrand();
    }
})();