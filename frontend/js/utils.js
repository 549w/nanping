/* ============================================================
   utils.js — 通用工具函数
   无外部依赖，所有导出函数均为纯函数或纯 DOM 副作用
   ============================================================ */

/**
 * 密码哈希（SHA-256）。
 * 在前端加密密码，避免明文传输。
 * @param {string} password - 明文密码
 * @returns {Promise<string>} SHA-256 哈希值（hex 格式）
 */
export async function hashPassword(password) {
  const encoder = new TextEncoder();
  const data = encoder.encode(password);
  const hashBuffer = await crypto.subtle.digest('SHA-256', data);
  const hashArray = Array.from(new Uint8Array(hashBuffer));
  return hashArray.map(b => b.toString(16).padStart(2, '0')).join('');
}

/**
 * 转义 HTML 特殊字符，防止 XSS。
 * @param {string} str - 原始字符串
 * @returns {string} 转义后的安全字符串
 */
export function escapeHtml(str) {
  const map = {
    "&": "&amp;",
    "<": "&lt;",
    ">": "&gt;",
    '"': "&quot;",
    "'": "&#39;",
  };
  return String(str).replace(/[&<>"']/g, (ch) => map[ch]);
}

/**
 * 将 ISO 日期字符串格式化为中文日期。
 * @param {string} isoStr - ISO 8601 日期字符串
 * @returns {string} 如 "2025年6月1日"
 */
export function formatDate(isoStr) {
  if (!isoStr) return "";
  try {
    const d = new Date(isoStr);
    if (isNaN(d.getTime())) return isoStr;
    return `${d.getFullYear()}年${d.getMonth() + 1}月${d.getDate()}日`;
  } catch {
    return isoStr;
  }
}

/**
 * 解析 URL 查询参数。
 * @param {string} name - 参数名
 * @returns {string|null} 参数值，不存在返回 null
 */
export function getQueryParam(name) {
  const params = new URLSearchParams(window.location.search);
  return params.get(name);
}

/**
 * 渲染星星评分 HTML。
 * @param {number|null} rating - 评分 1-5，null 表示无评分
 * @returns {string} HTML 字符串
 */
export function renderStars(rating) {
  if (rating == null) {
    return '<span class="star-rating" style="color:#999;font-size:0.85rem;">暂无评分</span>';
  }
  const r = Math.round(rating);
  let html = '<span class="star-rating" title="' + r + ' 分">';
  for (let i = 1; i <= 5; i++) {
    if (i <= r) {
      html += '<span class="material-symbols-outlined star-filled">&#xF09A;</span>';
    } else {
      html += '<span class="material-symbols-outlined star-empty">&#xF09A;</span>';
    }
  }
  html += "</span>";
  return html;
}

/**
 * 显示 toast 通知。多个 toast 会堆叠显示，3 秒后自动消失。
 * @param {string} message - 消息文本
 * @param {'success'|'error'|'info'} type - 类型
 */
export function showToast(message, type = "info") {
  let container = document.getElementById("toast-container");
  if (!container) {
    container = document.createElement("div");
    container.className = "toast-container";
    container.id = "toast-container";
    document.body.appendChild(container);
  }

  const toast = document.createElement("div");
  toast.className = `toast toast-${type}`;
  toast.textContent = message;
  container.appendChild(toast);

  // 自动移除
  const timer = setTimeout(() => {
    toast.classList.add("toast-removing");
    toast.addEventListener("animationend", () => {
      toast.remove();
      if (container.children.length === 0) {
        container.remove();
      }
    });
  }, 3000);

  // 点击立即关闭
  toast.addEventListener("click", () => {
    clearTimeout(timer);
    toast.remove();
    if (container.children.length === 0) {
      container.remove();
    }
  });
}

/**
 * 渲染分页控件 HTML。
 * @param {number} page - 当前页码
 * @param {number} pageSize - 每页条数
 * @param {number} total - 总条数
 * @returns {string} HTML 字符串
 */
export function renderPagination(page, pageSize, total) {
  if (total === 0) return "";

  const totalPages = Math.ceil(total / pageSize);
  if (totalPages <= 1) return "";

  let html = '<div class="pagination">';
  html += `<button data-page="${page - 1}"${page <= 1 ? " disabled" : ""}>上一页</button>`;
  html += `<span class="page-info">第 ${page} 页 / 共 ${totalPages} 页（${total} 条）</span>`;
  html += `<button data-page="${page + 1}"${page >= totalPages ? " disabled" : ""}>下一页</button>`;
  html += "</div>";

  return html;
}

/**
 * 设置按钮加载状态。
 * @param {HTMLButtonElement} button
 * @param {boolean} isLoading
 */
export function setButtonLoading(button, isLoading) {
  if (!button) return;

  if (isLoading) {
    if (!button.dataset.originalText) {
      button.dataset.originalText = button.textContent;
    }
    button.disabled = true;
    button.classList.add("is-loading");
    button.innerHTML = '<span class="btn-spinner"></span>' + button.dataset.originalText;
  } else {
    button.disabled = false;
    button.classList.remove("is-loading");
    button.textContent = button.dataset.originalText || button.textContent;
  }
}


// ---- 全局错误捕获 ----

window.addEventListener("error", function (event) {
  console.error("[Nanping] 未捕获错误:", event.message, event.filename, event.lineno, event.error);
});

window.addEventListener("unhandledrejection", function (event) {
  console.error("[Nanping] 未处理的 Promise 拒绝:", event.reason);
});
