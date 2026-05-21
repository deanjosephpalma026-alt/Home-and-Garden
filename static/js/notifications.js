
class NotificationManager {
  constructor() {
    this.container = null;
    this.init();
  }

  init() {
    
    if (!document.getElementById('notification-container')) {
      this.container = document.createElement('div');
      this.container.id = 'notification-container';
      this.container.className = 'notification-container';
      document.body.appendChild(this.container);
    } else {
      this.container = document.getElementById('notification-container');
    }
  }

  show(message, type = 'success', duration = 5000) {
    const notification = document.createElement('div');
    notification.className = `notification ${type}`;
    
    
    const icon = this.getIcon(type);
    
    notification.innerHTML = `
      <div class="notification-icon">
        ${icon}
      </div>
      <div class="notification-content">
        <div class="notification-title">${this.getTitle(type)}</div>
        <div class="notification-message">${message}</div>
      </div>
      <button class="notification-close" onclick="this.parentElement.remove()">
        <svg fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12"/>
        </svg>
      </button>
      <div class="notification-progress"></div>
    `;
    
    this.container.appendChild(notification);
    
    
    setTimeout(() => {
      notification.classList.add('show');
    }, 10);
    
    
    setTimeout(() => {
      this.remove(notification);
    }, duration);
  }

  getIcon(type) {
    const icons = {
      success: `
        <svg fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M5 13l4 4L19 7"/>
        </svg>
      `,
      error: `
        <svg fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12"/>
        </svg>
      `,
      info: `
        <svg fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M13 16h-1v-4h-1m1-4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z"/>
        </svg>
      `,
      warning: `
        <svg fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z"/>
        </svg>
      `
    };
    return icons[type] || icons.success;
  }

  getTitle(type) {
    const titles = {
      success: 'Success!',
      error: 'Error',
      info: 'Information',
      warning: 'Warning'
    };
    return titles[type] || 'Notification';
  }

  remove(notification) {
    notification.classList.remove('show');
    notification.classList.add('hide');
    setTimeout(() => {
      if (notification.parentElement) {
        notification.remove();
      }
    }, 400);
  }

  success(message, duration) {
    this.show(message, 'success', duration);
  }

  error(message, duration) {
    this.show(message, 'error', duration);
  }

  info(message, duration) {
    this.show(message, 'info', duration);
  }

  warning(message, duration) {
    this.show(message, 'warning', duration);
  }
}


const notificationManager = new NotificationManager();


function showFlashNotifications() {
  
  const flashMessages = document.querySelectorAll('[data-flash-message]');
  flashMessages.forEach(element => {
    const message = element.getAttribute('data-flash-message');
    const category = element.getAttribute('data-flash-category') || 'success';
    const type = category === 'error' ? 'error' : category === 'warning' ? 'warning' : category === 'info' ? 'info' : 'success';
    
    notificationManager.show(message, type, 5000);
    element.remove(); 
  });
}


document.addEventListener('DOMContentLoaded', function() {
  showFlashNotifications();
});


window.showNotification = function(message, type, duration) {
  notificationManager.show(message, type, duration);
};

window.showSuccess = function(message, duration) {
  notificationManager.success(message, duration);
};

window.showError = function(message, duration) {
  notificationManager.error(message, duration);
};

window.showInfo = function(message, duration) {
  notificationManager.info(message, duration);
};

window.showWarning = function(message, duration) {
  notificationManager.warning(message, duration);
};

// Custom confirmation dialog
window.customConfirm = function(message, options = {}) {
  return new Promise((resolve) => {
    const {
      title = 'Confirm',
      type = 'warning',
      confirmText = 'Confirm',
      cancelText = 'Cancel',
      confirmButtonClass = 'confirm-modal-button-primary'
    } = options;

    // Create overlay
    const overlay = document.createElement('div');
    overlay.className = 'fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50';
    overlay.id = 'confirm-dialog-overlay';

    // Create dialog
    const dialog = document.createElement('div');
    dialog.className = 'bg-white rounded-lg shadow-lg max-w-sm w-full mx-4 overflow-hidden';
    
    dialog.innerHTML = `
      <div class="px-6 py-4 border-b border-gray-200">
        <h2 class="text-lg font-semibold text-gray-900">${title}</h2>
      </div>
      <div class="px-6 py-4">
        <p class="text-gray-600 text-sm">${message}</p>
      </div>
      <div class="px-6 py-4 bg-gray-50 flex gap-3 justify-end border-t border-gray-200">
        <button class="px-4 py-2 rounded-lg border border-gray-300 text-gray-700 text-sm font-medium hover:bg-gray-100 transition cancel-btn">
          ${cancelText}
        </button>
        <button class="px-4 py-2 rounded-lg text-white text-sm font-medium transition ${confirmButtonClass} confirm-btn" style="background-color: #dc2626;">
          ${confirmText}
        </button>
      </div>
    `;

    overlay.appendChild(dialog);
    document.body.appendChild(overlay);

    // Handle button clicks
    const confirmBtn = dialog.querySelector('.confirm-btn');
    const cancelBtn = dialog.querySelector('.cancel-btn');

    confirmBtn.addEventListener('click', () => {
      overlay.remove();
      resolve(true);
    });

    cancelBtn.addEventListener('click', () => {
      overlay.remove();
      resolve(false);
    });

    // Handle escape key
    const handleEscape = (e) => {
      if (e.key === 'Escape') {
        document.removeEventListener('keydown', handleEscape);
        overlay.remove();
        resolve(false);
      }
    };
    document.addEventListener('keydown', handleEscape);
  });
};
