// brand.js - единый бренд для всех страниц
(function() {
    function addBrand() {
        // Проверяем что бренда еще нет
        if (document.querySelector('.pp-brand-logo')) return;

        // Создаем контейнер для логотипа
        const brandContainer = document.createElement('div');
        brandContainer.className = 'pp-brand-logo';
        brandContainer.style.cssText = `
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
            cursor: pointer;
            transition: transform 0.3s ease;
        `;

        brandContainer.innerHTML = '💎 ProfitPal';

        // Добавляем анимацию при наведении
        brandContainer.onmouseover = function() {
            this.style.transform = 'scale(1.1) rotate(-5deg)';
        };

        brandContainer.onmouseout = function() {
            this.style.transform = 'scale(1) rotate(0)';
        };

        // Клик = переход на главную
        brandContainer.onclick = function() {
            window.location.href = '/dashboard';
        };

        document.body.appendChild(brandContainer);
    }

    // Добавляем при загрузке
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', addBrand);
    } else {
        addBrand();
    }
})();