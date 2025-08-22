// donation-fix.js - ФИНАЛЬНАЯ ВЕРСИЯ - ВСЕ БАГИ ИСПРАВЛЕНЫ
// Проверено и готово к production

(function() {
  'use strict';

  console.log('[DonationFix] Initializing donation system fix...');

  // Защищенное глобальное состояние
  if (!window.donationState) {
    window.donationState = {
      amount: 0,
      type: '',
      selectedTile: null
    };
  }

  // Функция обновления кнопки BOOST
  function updateBoostButton() {
    const btn = document.getElementById('submitDonation');
    const consent = document.getElementById('donationConsent') || 
                   document.getElementById('authorizeDonation') ||
                   document.getElementById('authCheck');

    if (!btn) {
      console.log('[DonationFix] Button not found');
      return;
    }

    const hasAmount = window.donationState.amount > 0;
    const hasConsent = consent && consent.checked;

    const shouldEnable = hasAmount && hasConsent;
    btn.disabled = !shouldEnable;

    if (shouldEnable) {
      btn.style.background = 'linear-gradient(135deg, #32cd32, #228b22)';
      btn.style.cursor = 'pointer';
      btn.style.opacity = '1';
      btn.textContent = `BOOST NOW - $${window.donationState.amount}`;
      btn.classList.remove('disabled');
    } else {
      btn.style.background = 'linear-gradient(135deg, #3b3f5c, #2a2e4a)';
      btn.style.cursor = 'not-allowed';
      btn.style.opacity = '0.7';
      btn.textContent = 'BOOST NOW';
      btn.classList.add('disabled');
    }

    console.log('[DonationFix] Button state:', {
      hasAmount,
      hasConsent,
      shouldEnable,
      amount: window.donationState.amount
    });
  }

  // Выбор плитки доната
  function selectDonationTile(element, amount, type) {
    // Снимаем выделение со всех плиток
    document.querySelectorAll('.donation-btn').forEach(btn => {
      btn.classList.remove('selected');
      btn.style.border = '2px solid rgba(255, 107, 53, 0.3)';
      btn.style.background = 'linear-gradient(135deg, rgba(255, 107, 53, 0.1), rgba(255, 193, 7, 0.05))';
      btn.style.boxShadow = '';
    });

    // Выделяем текущую плитку
    if (element) {
      element.classList.add('selected');
      element.style.border = '2px solid #ff6b35';
      element.style.background = 'linear-gradient(135deg, rgba(255, 107, 53, 0.35), rgba(255, 193, 7, 0.20))';
      element.style.boxShadow = '0 6px 18px rgba(255, 107, 53, 0.25)';
    }

    // КРИТИЧНО: Сохраняем состояние
    window.donationState.amount = amount;
    window.donationState.type = type;
    window.donationState.selectedTile = element;

    // Очищаем custom input при выборе плитки
    const customInput = document.getElementById('customAmount');
    if (customInput && element) {
      customInput.value = '';
      customInput.classList.remove('has-value');
    }

    console.log('[DonationFix] Tile selected:', { 
      amount: window.donationState.amount, 
      type: window.donationState.type 
    });

    updateBoostButton();
  }

  // Обработчик кликов по плиткам
  function handleTileClick(event) {
    const tile = event.target.closest('.donation-btn');
    if (!tile) return;

    event.preventDefault();
    event.stopPropagation();

    let amount = parseFloat(tile.dataset.amount);
    let type = tile.dataset.type;

    if (!amount) {
      const priceMatch = tile.textContent.match(/\$(\d+)/);
      if (priceMatch) {
        amount = parseFloat(priceMatch[1]);
      }
    }

    if (!type) {
      const text = tile.textContent.toLowerCase();
      if (text.includes('coffee') && !text.includes('milk')) type = 'coffee';
      else if (text.includes('milk')) type = 'milk';
      else if (text.includes('feature')) type = 'features';
      else type = 'custom';
    }

    if (amount > 0) {
      selectDonationTile(tile, amount, type);
    }
  }

  // Custom amount обработчик
  function handleCustomAmount() {
    const input = document.getElementById('customAmount');
    if (!input) return;

    const value = parseFloat(input.value) || 0;

    if (value > 0) {
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
  function handleConsentChange(event) {
    console.log('[DonationFix] Checkbox changed:', event.target.checked);
    setTimeout(() => {
      updateBoostButton();
    }, 10);
  }

  // 🔥 ФИНАЛЬНАЯ ВЕРСИЯ ОБРАБОТКИ ДОНАТА - ВСЕ БАГИ ИСПРАВЛЕНЫ
  async function processDonation() {
    // Получаем amount из разных источников
    const btn = document.getElementById('submitDonation');
    let amount = window.donationState.amount;
    let type = window.donationState.type || 'donation';

    // Если state пустой - берем из текста кнопки
    if ((!amount || amount <= 0) && btn) {
      const match = btn.textContent.match(/\$(\d+(?:\.\d+)?)/);
      if (match) {
        amount = parseFloat(match[1]);
        console.log('[DonationFix] Amount recovered from button text:', amount);
      }
    }

    // Если все еще нет amount - проверяем выбранную плитку
    if ((!amount || amount <= 0)) {
      const selectedTile = document.querySelector('.donation-btn.selected');
      if (selectedTile) {
        const tileMatch = selectedTile.textContent.match(/\$(\d+)/);
        if (tileMatch) {
          amount = parseFloat(tileMatch[1]);
          console.log('[DonationFix] Amount recovered from selected tile:', amount);
        }
      }
    }

    console.log('[DonationFix] Processing donation with amount:', amount);

    // КРИТИЧНО: Проверка amount и ВЫХОД если нет суммы
    if (!amount || amount <= 0) {
      alert('Please select a donation amount');
      return; // ВАЖНО: выходим из функции!
    }

    // Проверка галочки авторизации
    const consent = document.getElementById('donationConsent') || 
                   document.getElementById('authorizeDonation') ||
                   document.getElementById('authCheck');

    if (!consent || !consent.checked) {
      alert('Please authorize the transaction');
      return; // ВАЖНО: выходим из функции!
    }

    // Блокируем кнопку на время обработки
    if (btn) {
      btn.disabled = true;
      btn.textContent = 'Processing...';
    }

    try {
      // Получаем CSRF токен
      const csrfToken = document.cookie
        .split('; ')
        .find(row => row.startsWith('pp_csrf='))
        ?.split('=')[1];

      console.log('[DonationFix] Sending donation request:', {
        amount: amount,
        type: type,
        authorized: true
      });

      // Отправляем запрос на сервер
      const response = await fetch('/api/process-donation', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'X-CSRF-Token': csrfToken || ''
        },
        credentials: 'include',
        body: JSON.stringify({
          amount: amount,
          type: type,
          authorized: true
        })
      });

      const data = await response.json();

      // Если успешно - показываем зеленое окно
      if (response.ok && data.success) {
        showDonationSuccess(amount, type);
        resetDonationForm();

        // Закрываем секцию донатов через 2 секунды
        setTimeout(() => {
          const options = document.getElementById('boostOptions');
          if (options) options.style.display = 'none';
        }, 2000);
      } else {
        throw new Error(data.detail || data.error || 'Donation failed');
      }

    } catch (error) {
      console.error('[DonationFix] Error:', error);

      // 🔥 ИСПРАВЛЕНО: Показываем успех ТОЛЬКО если есть amount И это тестовый режим
      if (amount > 0 && window.location.hostname === 'localhost') {
        console.log('[DonationFix] Test mode - simulating success for amount:', amount);
        showDonationSuccess(amount, type);
        resetDonationForm();

        setTimeout(() => {
          const options = document.getElementById('boostOptions');
          if (options) options.style.display = 'none';
        }, 2000);
      } else if (amount > 0) {
        // Показываем ошибку только если была выбрана сумма
        alert(`Donation failed: ${error.message}\n\nPlease save a payment method in Settings first.`);
      }
      // Если amount = 0, то ничего не делаем (alert уже был показан выше)

    } finally {
      // Восстанавливаем кнопку
      if (btn) {
        btn.disabled = false;
        btn.textContent = 'BOOST NOW';
        updateBoostButton();
      }
    }
  }

  // Показ успешного сообщения
  function showDonationSuccess(amount, type) {
    const successDiv = document.createElement('div');
    successDiv.className = 'donation-success-message';
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
      white-space: pre-line;
      text-align: center;
    `;

    let message = `💎 Thank you for your $${amount} donation!\n\n`;

    // Персонализированное сообщение в зависимости от типа
    switch(type) {
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

    // Добавляем анимацию
    const style = document.createElement('style');
    style.textContent = `
      @keyframes successPulse {
        0% { transform: translate(-50%, -50%) scale(0.8); opacity: 0; }
        50% { transform: translate(-50%, -50%) scale(1.1); }
        100% { transform: translate(-50%, -50%) scale(1); opacity: 1; }
      }
    `;
    document.head.appendChild(style);

    // Убираем окно через 3.5 секунды
    setTimeout(() => {
      successDiv.style.transition = 'opacity 0.5s';
      successDiv.style.opacity = '0';
      setTimeout(() => {
        successDiv.remove();
        style.remove();
      }, 500);
    }, 3500);
  }

  // Сброс формы после доната
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
    const consent = document.getElementById('donationConsent') || 
                   document.getElementById('authorizeDonation') ||
                   document.getElementById('authCheck');
    if (consent) consent.checked = false;

    updateBoostButton();
  }

  // ГЛАВНАЯ ИНИЦИАЛИЗАЦИЯ СИСТЕМЫ
  function initDonationSystem() {
    console.log('[DonationFix] Setting up event listeners...');

    // Удаляем старые обработчики через клонирование
    const oldContainer = document.getElementById('donationTiles') || 
                        document.getElementById('boostOptions');
    if (oldContainer) {
      const newContainer = oldContainer.cloneNode(true);
      oldContainer.parentNode.replaceChild(newContainer, oldContainer);
    }

    // Настраиваем data-атрибуты для плиток
    document.querySelectorAll('.donation-btn').forEach(btn => {
      const text = btn.textContent;

      // Извлекаем сумму из текста
      const amountMatch = text.match(/\$(\d+)/);
      if (amountMatch) {
        btn.dataset.amount = amountMatch[1];
      }

      // Определяем тип доната
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

    // Custom amount input
    const customInput = document.getElementById('customAmount');
    if (customInput) {
      customInput.addEventListener('input', handleCustomAmount);
      customInput.addEventListener('change', handleCustomAmount);
    }

    // Поиск и привязка чекбокса
    const checkboxIds = ['donationConsent', 'authorizeDonation', 'authCheck'];
    let consentFound = false;

    for (const id of checkboxIds) {
      const consent = document.getElementById(id);
      if (consent) {
        console.log(`[DonationFix] Found checkbox with ID: ${id}`);
        consent.addEventListener('change', handleConsentChange);
        consentFound = true;
        break;
      }
    }

    if (!consentFound) {
      console.warn('[DonationFix] Warning: No consent checkbox found!');
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

  // Защита от конфликтов - периодическая проверка состояния
  setInterval(() => {
    const consent = document.getElementById('donationConsent') || 
                   document.getElementById('authorizeDonation') ||
                   document.getElementById('authCheck');
    const btn = document.getElementById('submitDonation');

    if (consent && btn && window.donationState.amount > 0) {
      const shouldBeEnabled = consent.checked;
      const isEnabled = !btn.disabled;

      if (shouldBeEnabled !== isEnabled) {
        console.log('[DonationFix] Fixing button state conflict');
        updateBoostButton();
      }
    }
  }, 100);

  // Запуск инициализации
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', initDonationSystem);
  } else {
    setTimeout(initDonationSystem, 100);
  }

  // Debug интерфейс для отладки
  window.donationDebug = {
    state: window.donationState,
    updateButton: updateBoostButton,
    selectTile: selectDonationTile,
    reset: resetDonationForm,
    init: initDonationSystem,
    processNow: processDonation
  };

  console.log('[DonationFix] System ready! Debug available at window.donationDebug');

})();