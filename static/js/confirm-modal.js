
class ConfirmModal {
  constructor() {
    this.overlay = null;
    this.modal = null;
    this.resolve = null;
    this.init();
  }

  init() {
    
    if (!document.getElementById('confirm-modal-overlay')) {
      this.overlay = document.createElement('div');
      this.overlay.id = 'confirm-modal-overlay';
      this.overlay.className = 'confirm-modal-overlay';
      this.overlay.innerHTML = `
        <div class="confirm-modal">
          <div class="confirm-modal-header">
            <div class="confirm-modal-icon" id="confirm-modal-icon">
              <svg fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z"/>
              </svg>
            </div>
            <h3 class="confirm-modal-title" id="confirm-modal-title">Confirm Action</h3>
          </div>
          <div class="confirm-modal-body">
            <p class="confirm-modal-message" id="confirm-modal-message"></p>
          </div>
          <div class="confirm-modal-footer">
            <button class="confirm-modal-button confirm-modal-button-cancel" id="confirm-modal-cancel">
              Cancel
            </button>
            <button class="confirm-modal-button confirm-modal-button-confirm" id="confirm-modal-confirm">
              Confirm
            </button>
          </div>
        </div>
      `;
      document.body.appendChild(this.overlay);
      this.modal = this.overlay.querySelector('.confirm-modal');
      
      
      this.setupListeners();
    } else {
      this.overlay = document.getElementById('confirm-modal-overlay');
      this.modal = this.overlay.querySelector('.confirm-modal');
      this.setupListeners();
    }
  }

  setupListeners() {
    const cancelBtn = document.getElementById('confirm-modal-cancel');
    const confirmBtn = document.getElementById('confirm-modal-confirm');
    
    cancelBtn.addEventListener('click', () => this.hide(false));
    confirmBtn.addEventListener('click', () => this.hide(true));
    
    
    this.overlay.addEventListener('click', (e) => {
      if (e.target === this.overlay) {
        this.hide(false);
      }
    });
    
    
    document.addEventListener('keydown', (e) => {
      if (e.key === 'Escape' && this.overlay.classList.contains('show')) {
        this.hide(false);
      }
    });
  }

  show(message, options = {}) {
    return new Promise((resolve) => {
      this.resolve = resolve;
      
      const {
        title = 'Confirm Action',
        type = 'warning', 
        confirmText = 'Confirm',
        cancelText = 'Cancel',
        confirmButtonClass = 'confirm-modal-button-confirm'
      } = options;
      
      
      document.getElementById('confirm-modal-title').textContent = title;
      document.getElementById('confirm-modal-message').textContent = message;
      document.getElementById('confirm-modal-confirm').textContent = confirmText;
      document.getElementById('confirm-modal-cancel').textContent = cancelText;
      
      
      const icon = document.getElementById('confirm-modal-icon');
      icon.className = `confirm-modal-icon ${type}`;
      icon.innerHTML = this.getIcon(type);
      
      
      const confirmBtn = document.getElementById('confirm-modal-confirm');
      confirmBtn.className = `confirm-modal-button ${confirmButtonClass}`;
      
      
      this.overlay.classList.add('show');
      document.body.style.overflow = 'hidden';
    });
  }

  hide(result) {
    this.overlay.classList.remove('show');
    document.body.style.overflow = '';
    
    setTimeout(() => {
      if (this.resolve) {
        this.resolve(result);
        this.resolve = null;
      }
    }, 300);
  }

  getIcon(type) {
    const icons = {
      warning: `
        <svg fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z"/>
        </svg>
      `,
      danger: `
        <svg fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z"/>
        </svg>
      `,
      info: `
        <svg fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M13 16h-1v-4h-1m1-4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z"/>
        </svg>
      `,
      success: `
        <svg fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M5 13l4 4L19 7"/>
        </svg>
      `
    };
    return icons[type] || icons.warning;
  }
}


const confirmModal = new ConfirmModal();


window.customConfirm = function(message, options = {}) {
  return confirmModal.show(message, options);
};


window.confirmFormSubmit = function(form, message, options = {}) {
  form.addEventListener('submit', async function(e) {
    e.preventDefault();
    const result = await confirmModal.show(message, options);
    if (result) {
      form.submit();
    }
  });
};


window.confirmButtonClick = function(button, message, callback, options = {}) {
  button.addEventListener('click', async function(e) {
    e.preventDefault();
    const result = await confirmModal.show(message, options);
    if (result && callback) {
      callback();
    }
  });
};

