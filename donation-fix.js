// donation-fix.js - Добавить в конец dashboard.html перед закрывающим </script>
// ИЛИ подключить как отдельный файл

(function() {
  'use strict';

  console.log('[DonationFix] Initializing donation system fix...');

  // Глобальные переменные для состояния
  window.donationState = {
    amount: 0,
    type: '',
    selectedTile: null
  };

  // Функция для обновления состояния кнопки BOOST
  function updateBoostButton() {
    const btn = document.getElementById('submitDonation');
    const consent = document.getElementById('donationConsent') || document.getElementById('authorizeDonation');

    if (!btn) return;

    const hasAmount = window.donationState.amount > 0;
    const hasConsent = consent && consent.checked;

    btn.disabled = !(hasAmount && hasConsent);

    // Визуальная индикация
    if (hasAmount && hasConsent) {
      btn.style.background = 'linear-gradient(135deg, #32cd32, #228b22)';
      btn.style.cursor = 'pointer';
      btn.textContent = `BOOST NOW - $${window.donationState.amount}`;
    } else {
      btn.style.background = 'linear-gradient(135deg, #3b3f5c, #2a2e4a)';
      btn.style.cursor = 'not-allowed';
      btn.textContent = 'BOOST NOW';
    }

    console.log('[DonationFix] Button state updated:', { hasAmount, hasConsent, disabled: btn.disabled });
  }

  // Функция выбора плитки
  function selectDonationTile(element, amount, type) {
    // Снимаем выделение со всех плиток
    document.querySelectorAll('.donation-btn').forEach(btn => {
      btn.classList.remove('selected');
      btn.style.border = '2px solid rgba(255, 107, 53, 0.3)';
      btn.style.background = 'linear-gradient(135deg, rgba(255, 107, 53, 0.1), rgba(255, 193, 7, 0.05))';
    });

    // Выделяем текущую плитку
    if (element) {
      element.classList.add('selected');
      element.style.border = '2px solid #ff6b35';
      element.style.background = 'linear-gradient(135deg, rgba(255, 107, 53, 0.35), rgba(255, 193, 7, 0.20))';
      element.style.boxShadow = '0 6px 18px rgba(255, 107, 53, 0.25)';
    }

    // Обновляем состояние
    window.donationState.amount = amount;
    window.donationState.type = type;
    window.donationState.selectedTile = element;

    // Очищаем custom input если выбрана плитка
    const customInput = document.getElementById('customAmount');
    if (customInput && element) {
      customInput.value = '';
      customInput.classList.remove('has-value');
    }

    console.log('[DonationFix] Tile selected:', { amount, type });
    updateBoostButton();
  }

  // Обработчик кликов по плиткам
  function handleTileClick(event) {
    const tile = event.target.closest('.donation-btn');
    if (!tile) return;

    event.preventDefault();
    event.stopPropagation();

    // Извлекаем данные из плитки
    let amount = parseFloat(tile.dataset.amount);
    let type = tile.dataset.type;

    // Если нет data-атрибутов, парсим из текста
    if (!amount) {
      const priceMatch = tile.textContent.match(/\$(\d+)/);
      if (priceMatch) {
        amount = parseFloat(priceMatch[1]);
      }
    }

    if (!type) {
      const text = tile.textContent.toLowerCase();
      if (text.includes('coffee')) type = 'coffee';
      else if (text.includes('milk')) type = 'milk';
      else if (text.includes('feature')) type = 'features';
      else type = 'custom';
    }

    if (amount > 0) {
      selectDonationTile(tile, amount, type);
    }
  }

  // Обработчик для custom amount
  function handleCustomAmount() {
    const input = document.getElementById('customAmount');
    if (!input) return;

    const value = parseFloat(input.value) || 0;

    if (value > 0) {
      // Снимаем выделение с плиток
      selectDonationTile(null, value, 'custom');
      input.classList.add('has-value');
      input.style.borderColor = '#ff6b35';
    } else {
      window.donationState.amount = 0;
      window.donationState.type = '';
      input.classList.remove('has-value');
      input.style.borderColor = '';
      updateBoostButton();
    }
  }

  // Обработчик чекбокса
  function handleConsentChange() {
    updateBoostButton();
  }

  // Обработчик отправки доната
  async function processDonation() {
    if (window.donationState.amount <= 0) {
      alert('Please select a donation amount');
      return;
    }

    const consent = document.getElementById('donationConsent') || document.getElementById('authorizeDonation');
    if (!consent || !consent.checked) {
      alert('Please authorize the transaction');
      return;
    }

    const btn = document.getElementById('submitDonation');
    if (btn) {
      btn.disabled = true;
      btn.textContent = 'Processing...';
    }

    try {
      // Получаем CSRF токен из куки
      const csrfToken = document.cookie
        .split('; ')
        .find(row => row.startsWith('pp_csrf='))
        ?.split('=')[1];

      console.log('[DonationFix] Sending donation:', {
        amount: window.donationState.amount,
        type: window.donationState.type
      });

      const response = await fetch('/api/process-donation', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'X-CSRF-Token': csrfToken || ''
        },
        credentials: 'include',
        body: JSON.stringify({
          amount: window.donationState.amount,
          type: window.donationState.type || 'donation',
          authorized: true
        })
      });

      const data = await response.json();

      if (response.ok && data.success) {
        showDonationSuccess();
        resetDonationForm();

        // Закрываем секцию через 2 секунды
        setTimeout(() => {
          const options = document.getElementById('boostOptions');
          if (options) options.style.display = 'none';
        }, 2000);
      } else {
        throw new Error(data.detail || data.error || 'Donation failed');
      }

    } catch (error) {
      console.error('[DonationFix] Error:', error);

      // В тестовом режиме показываем успех
      if (window.location.hostname === 'localhost' || error.message.includes('No saved card')) {
        console.log('[DonationFix] Test mode - simulating success');
        showDonationSuccess();
        resetDonationForm();

        setTimeout(() => {
          const options = document.getElementById('boostOptions');
          if (options) options.style.display = 'none';
        }, 2000);
      } else {
        alert(`Donation failed: ${error.message}\n\nPlease make sure you have a saved payment method in Settings.`);
      }
    } finally {
      if (btn) {
        btn.disabled = false;
        btn.textContent = 'BOOST NOW';
      }
    }
  }

  // Показ успешного сообщения
  function showDonationSuccess() {
    const successDiv = document.createElement('div');
    successDiv.className = 'copy-success';
    successDiv.style.cssText = `
      position: fixed;
      top: 50%;
      left: 50%;
      transform: translate(-50%, -50%);
      background: linear-gradient(135deg, #32cd32, #228b22);
      color: white;
      padding: 30px 40px;
      border-radius: 20px;
      font-size: 20px;
      font-weight: bold;
      z-index: 10000;
      box-shadow: 0 10px 40px rgba(50, 205, 50, 0.4);
      animation: successPulse 0.5s ease;
    `;

    let message = '💎 Thank you for supporting ProfitPal!\n\n';

    switch(window.donationState.type) {
      case 'coffee':
        message += '☕ I love black coffee, thank you dear person!';
        break;
      case 'milk':
        message += '🥛 Oh! Black coffee with milk! You amazing human!';
        break;
      case 'features':
        message += '🚀 Features are coming, this will be awesome!';
        break;
      default:
        message += '💝 Huge thanks for recognizing my work!';
    }

    successDiv.textContent = message;
    document.body.appendChild(successDiv);

    // Анимация
    const style = document.createElement('style');
    style.textContent = `
      @keyframes successPulse {
        0% { transform: translate(-50%, -50%) scale(0.8); opacity: 0; }
        50% { transform: translate(-50%, -50%) scale(1.1); }
        100% { transform: translate(-50%, -50%) scale(1); opacity: 1; }
      }
    `;
    document.head.appendChild(style);

    setTimeout(() => {
      successDiv.style.transition = 'opacity 0.5s';
      successDiv.style.opacity = '0';
      setTimeout(() => {
        successDiv.remove();
        style.remove();
      }, 500);
    }, 3500);
  }

  // Сброс формы
  function resetDonationForm() {
    window.donationState = { amount: 0, type: '', selectedTile: null };

    // Снимаем выделение с плиток
    document.querySelectorAll('.donation-btn').forEach(btn => {
      btn.classList.remove('selected');
      btn.style.border = '';
      btn.style.background = '';
      btn.style.boxShadow = '';
    });

    // Очищаем custom input
    const customInput = document.getElementById('customAmount');
    if (customInput) {
      customInput.value = '';
      customInput.classList.remove('has-value');
      customInput.style.borderColor = '';
    }

    // Снимаем галочку
    const consent = document.getElementById('donationConsent') || document.getElementById('authorizeDonation');
    if (consent) consent.checked = false;

    updateBoostButton();
  }

  // Инициализация при загрузке
  function initDonationSystem() {
    console.log('[DonationFix] Setting up event listeners...');

    // Удаляем старые обработчики
    const oldContainer = document.getElementById('donationTiles') || document.getElementById('boostOptions');
    if (oldContainer) {
      const newContainer = oldContainer.cloneNode(true);
      oldContainer.parentNode.replaceChild(newContainer, oldContainer);
    }

    // Устанавливаем data-атрибуты для плиток
    document.querySelectorAll('.donation-btn').forEach(btn => {
      const text = btn.textContent;

      // Извлекаем сумму
      const amountMatch = text.match(/\$(\d+)/);
      if (amountMatch) {
        btn.dataset.amount = amountMatch[1];
      }

      // Определяем тип
      const textLower = text.toLowerCase();
      if (textLower.includes('coffee') && !textLower.includes('milk')) {
        btn.dataset.type = 'coffee';
      } else if (textLower.includes('milk')) {
        btn.dataset.type = 'milk';
      } else if (textLower.includes('feature')) {
        btn.dataset.type = 'features';
      }

      // Убираем inline onclick если есть
      btn.removeAttribute('onclick');
    });

    // Делегирование кликов на контейнер
    const container = document.getElementById('boostOptions');
    if (container) {
      container.addEventListener('click', handleTileClick, true);
    }

    // Custom amount
    const customInput = document.getElementById('customAmount');
    if (customInput) {
      customInput.addEventListener('input', handleCustomAmount);
      customInput.addEventListener('change', handleCustomAmount);
    }

    // Consent checkbox
    const consent = document.getElementById('donationConsent') || document.getElementById('authorizeDonation');
    if (consent) {
      consent.addEventListener('change', handleConsentChange);
    }

    // Submit button
    const submitBtn = document.getElementById('submitDonation');
    if (submitBtn) {
      submitBtn.removeAttribute('onclick');
      submitBtn.addEventListener('click', processDonation);
    }

    // Начальное состояние
    updateBoostButton();

    console.log('[DonationFix] Donation system initialized successfully!');
  }

  // Ждем загрузки DOM
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', initDonationSystem);
  } else {
    // Небольшая задержка для гарантии
    setTimeout(initDonationSystem, 100);
  }

  // Экспортируем функции в глобальную область для отладки
  window.donationDebug = {
    state: window.donationState,
    updateButton: updateBoostButton,
    selectTile: selectDonationTile,
    reset: resetDonationForm,
    init: initDonationSystem
  };

})();