/**
 * Nanping — 南大课程评价浏览器插件
 *
 * 在南京大学选课系统（xk.nju.edu.cn）的课程列表中：
 *   1. 每门课程行内注入评分徽章 + 查看按钮
 *   2. 点击「查看」滑出侧边面板，展示匹配课程的评价详情
 *
 * 依赖：后端 POST /courses/match 批量匹配端点
 */

(function () {
  "use strict";

  // ============================================================
  // 全局错误处理
  // ============================================================

  const HOMEPAGE_URL = "https://nanping.eznju.com";
  const CONTACT_INFO = "QQ群：1048569521";

  /**
   * 显示全局错误横幅（仅在严重错误时调用）。
   * 提供一个可见的提示，包含首页链接和联系方式。
   */
  function showFatalError(message) {
    // 防止重复显示
    if (document.getElementById("np-fatal-error")) return;

    console.error("[Nanping] 严重错误:", message);

    var banner = document.createElement("div");
    banner.id = "np-fatal-error";
    banner.style.cssText = [
      "position: fixed",
      "top: 10px",
      "left: 50%",
      "transform: translateX(-50%)",
      "z-index: 9999999",
      "background: #fef2f2",
      "border: 2px solid #ef4444",
      "border-radius: 12px",
      "padding: 16px 24px",
      "max-width: 600px",
      "box-shadow: 0 8px 32px rgba(239, 68, 68, 0.3)",
      "font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif",
      "font-size: 14px",
      "line-height: 1.6",
      "color: #991b1b",
      "pointer-events: auto",
    ].join(" !important;") + " !important;";

    banner.innerHTML = [
      '<div style="display: flex; align-items: flex-start; gap: 12px;">',
      '  <span style="font-size: 24px; flex-shrink: 0;">⚠️</span>',
      '  <div style="flex: 1;">',
      '    <div style="font-weight: 600; margin-bottom: 8px;">南评插件遇到问题</div>',
      '    <div style="margin-bottom: 12px; color: #7f1d1d;">' + escapeHtml(message) + '</div>',
      '    <div style="display: flex; gap: 16px; flex-wrap: wrap;">',
      '      <a href="' + HOMEPAGE_URL + '" target="_blank" style="color: #2563eb; text-decoration: underline; font-weight: 500;">访问南评首页</a>',
      '      <span style="color: #6b7280;">联系方式：' + CONTACT_INFO + '</span>',
      '    </div>',
      '  </div>',
      '  <button id="np-fatal-close" style="background: none; border: none; font-size: 20px; color: #991b1b; cursor: pointer; padding: 0; line-height: 1;">×</button>',
      '</div>',
    ].join("\n");

    document.body.appendChild(banner);

    // 绑定关闭按钮
    var closeBtn = document.getElementById("np-fatal-close");
    if (closeBtn) {
      closeBtn.addEventListener("click", function () {
        banner.remove();
      });
    }
  }

  /**
   * 安全地执行函数，捕获所有错误。
   * @param {Function} fn - 要执行的函数
   * @param {string} context - 错误上下文描述
   * @param {*} fallback - 出错时的返回值
   */
  function safeExec(fn, context, fallback) {
    try {
      return fn();
    } catch (err) {
      console.error("[Nanping] " + context + " 出错:", err);
      return fallback;
    }
  }

  /**
   * 安全地执行异步函数，捕获所有错误。
   * @param {Function} fn - 要执行的异步函数
   * @param {string} context - 错误上下文描述
   * @param {*} fallback - 出错时的返回值
   */
  async function safeExecAsync(fn, context, fallback) {
    try {
      return await fn();
    } catch (err) {
      console.error("[Nanping] " + context + " 出错:", err);
      return fallback;
    }
  }

  /**
   * 带超时的 fetch 封装。
   * @param {string} url - 请求 URL
   * @param {object} options - fetch 选项
   * @param {number} timeoutMs - 超时时间（毫秒），默认 10 秒
   */
  async function fetchWithTimeout(url, options, timeoutMs) {
    timeoutMs = timeoutMs || 10000;
    var controller = new AbortController();
    var timeoutId = setTimeout(function () {
      controller.abort();
    }, timeoutMs);

    try {
      var response = await fetch(url, Object.assign({}, options, { signal: controller.signal }));
      clearTimeout(timeoutId);
      return response;
    } catch (err) {
      clearTimeout(timeoutId);
      if (err.name === "AbortError") {
        throw new Error("请求超时（" + timeoutMs + "ms）");
      }
      throw err;
    }
  }

  /**
   * 安全的 DOM 查询，返回 null 而不是抛出错误。
   */
  function safeQuerySelector(selector) {
    try {
      return document.querySelector(selector);
    } catch (err) {
      console.warn("[Nanping] DOM 查询失败:", selector, err);
      return null;
    }
  }

  function safeQuerySelectorAll(selector) {
    try {
      return document.querySelectorAll(selector);
    } catch (err) {
      console.warn("[Nanping] DOM 查询失败:", selector, err);
      return [];
    }
  }

  // ============================================================
  // 配置
  // ============================================================

  const CONFIG = {
    /** API 候选地址列表 —— 按优先级排列，首个连通者被记住 */
    API_CANDIDATES: [
      "https://npapi.eznju.com",
      "http://localhost:8000",
    ],
    MATCH_ENDPOINT: "/courses/match",
    REVIEW_ENDPOINT: "/review",
    NEWS_ENDPOINT: "/news",
    DEBOUNCE_MS: 500, // 防抖间隔（避免 MutationObserver 频繁触发）
    PANEL_WIDTH: 420, // 侧边面板宽度（px）
    TOKEN_KEY: "nanping_token", // localStorage key（与前端 auth.js 一致）
  };

  // ============================================================
  // 认证 primitive（增值服务预留，MVP 阶段不活跃）
  // ============================================================

  function getAuthToken() {
    try { return localStorage.getItem(CONFIG.TOKEN_KEY) || ""; } catch (_) { return ""; }
  }
  function setAuthToken(token) {
    try { localStorage.setItem(CONFIG.TOKEN_KEY, token); } catch (_) {}
  }
  function clearAuthToken() {
    try { localStorage.removeItem(CONFIG.TOKEN_KEY); } catch (_) {}
  }

  /** 运行时确定的 API 基地址（null = 尚未探测） */
  let apiBase = null;

  // ============================================================
  // 运行状态
  // ============================================================

  const state = {
    /** 已注入徽章的行（WeakSet 自动处理 DOM 移除后的 GC） */
    processedRows: new WeakSet(),
    /** Shadow DOM 根节点 */
    shadowRoot: null,
    /** 侧边面板 DOM */
    panel: null,
    /** 背景遮罩 DOM */
    overlay: null,
    /** Shadow DOM 宿主元素 */
    host: null,
    /** 面板是否展开 */
    isPanelOpen: false,
    /** 防抖计时器 ID */
    debounceTimer: null,
    /** /plugin v2 缓存的公告卡片 HTML */
    newsHtml: "",
    /** /plugin 响应缓存的 toast 文案配置 */
    toastConfig: null,
  };

  // ============================================================
  // DOM 信息提取
  // ============================================================

  /**
   * 从单个课程行提取全部可见字段。
   *
   * 页面结构（tbody.course-body > tr.course-tr）：
   *   td.kch > a.cv-jxb-detail[data-number]   → 课程号
   *   td.kcmc                                  → 课程名
   *   td.xf                                    → 学分
   *   td.jsmc                                  → 授课教师
   *   td.sjdd                                  → 时间地点
   *   td.xq                                    → 校区
   *   td.nj                                    → 年级
   *   td.kkdw                                  → 开课单位
   *
   * @param {HTMLTableRowElement} row - 课程行 <tr>
   * @returns {object|null}
   */
  function extractCourseFromRow(row) {
    const codeAnchor = row.querySelector(".kch .cv-jxb-detail");
    const nameCell = row.querySelector(".kcmc");
    if (!codeAnchor || !nameCell) return null;

    var getText = function (sel) {
      var el = row.querySelector(sel);
      return el ? el.textContent.trim() : "";
    };

    return {
      code: (codeAnchor.getAttribute("data-number") || codeAnchor.textContent || "").trim(),
      name: nameCell.textContent.trim(),
      credits: getText(".xf"),
      teacher: getText(".jsmc"),
      schedule: getText(".sjdd"),
      campus: getText(".xq"),
      grade: getText(".nj"),
      department: getText(".kkdw"),
    };
  }

  /**
   * 提取页面上所有课程行信息。
   * @returns {Array<{code, name, credits, teacher, schedule, campus, grade, department, row}>}
   */
  function extractAllCourses() {
    const rows = document.querySelectorAll("tbody.course-body tr.course-tr");
    const courses = [];
    rows.forEach((row) => {
      const info = extractCourseFromRow(row);
      if (info) {
        courses.push({ ...info, row });
      }
    });
    return courses;
  }

  // ============================================================
  // API 调用
  // ============================================================

  /**
   * 探测可用的 API 地址。
   * 按 CONFIG.API_CANDIDATES 顺序尝试，首个连通者缓存到 apiBase。
   * 每个候选地址有 2 秒超时。
   *
   * @returns {Promise<string|null>} 可用的 API 基地址，或 null
   */
  async function discoverApi() {
    if (apiBase) return apiBase;

    for (const candidate of CONFIG.API_CANDIDATES) {
      try {
        const resp = await fetchWithTimeout(candidate + "/", {}, 2000);
        if (resp.ok) {
          apiBase = candidate;
          console.log("[Nanping] API 地址:", apiBase);
          return apiBase;
        }
      } catch (_) {
        // 此候选不通，继续尝试下一个
      }
    }
    console.error("[Nanping] 所有 API 候选地址均不可达:", CONFIG.API_CANDIDATES);
    return null;
  }

  /**
   * 获取 API 基地址（首次调用时自动探测）。
   */
  async function getApiBase() {
    if (apiBase) return apiBase;
    return await discoverApi();
  }

  /**
   * 从页面提取当前登录用户名。
   * @returns {string} 用户名，若找不到则返回空字符串
   */
  function extractUsername() {
    var el = document.querySelector(".username");
    return el ? el.textContent.trim() : "";
  }

  /**
   * 从页面提取当前登录用户性别头像文件名。
   * 通过 user-img 的 src 提取，如 "men.png" / "women.png"。
   * @returns {string} 图片文件名，若找不到则返回空字符串
   */
  function extractUserGender() {
    var img = document.querySelector(".user-img");
    if (!img) return "";
    var src = img.getAttribute("src") || "";
    var match = src.match(/([^/]+\.\w+)(?:\?|$)/);
    return match ? match[1] : "";
  }

  /**
   * 批量匹配课程。
   * 将页面上所有课程行一次性发送到后端，后端做三级回退搜索。
   *
   * @param {Array<{code: string, teacher: string, name: string}>} queries
   * @param {string} username - 页面登录用户名
   * @param {string} gender - 用户性别（"male" / "female" / ""）
   * @returns {Promise<{results: Array}|null>}
   */
  async function batchMatch(queries, username, gender) {
    const base = await getApiBase();
    if (!base) return null;

    var body = { queries: queries };
    if (username) {
      body.username = username;
    }
    if (gender) {
      body.gender = gender;
    }

    try {
      const resp = await fetchWithTimeout(base + CONFIG.MATCH_ENDPOINT, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      }, 15000); // 批量匹配可能需要更长时间

      if (!resp.ok) {
        console.warn("[Nanping] 匹配 API 返回非 200:", resp.status);
        return null;
      }

      const data = await resp.json();
      // 验证响应结构
      if (!data || !Array.isArray(data.results)) {
        console.warn("[Nanping] 匹配 API 返回数据格式错误:", data);
        return null;
      }

      return data;
    } catch (err) {
      console.error("[Nanping] 匹配 API 请求失败:", err);
      return null;
    }
  }

  /**
   * 分页获取某课程的评价列表。
   *
   * @param {number} courseId
   * @param {number} page
   * @param {number} pageSize
   * @returns {Promise<{items: Array, total: number}|null>}
   */
  async function fetchReviews(courseId, page = 1, pageSize = 20) {
    const base = await getApiBase();
    if (!base) return null;

    const params = new URLSearchParams({
      course_id: String(courseId),
      page: String(page),
      page_size: String(pageSize),
    });

    try {
      const resp = await fetchWithTimeout(
        base + CONFIG.REVIEW_ENDPOINT + "?" + params.toString(),
        {},
        10000
      );
      if (!resp.ok) {
        console.warn("[Nanping] 评价 API 返回非 200:", resp.status);
        return null;
      }

      const data = await resp.json();
      // 验证响应结构
      if (!data || !Array.isArray(data.items)) {
        console.warn("[Nanping] 评价 API 返回数据格式错误:", data);
        return null;
      }

      return data;
    } catch (err) {
      console.error("[Nanping] 评价获取失败:", err);
      return null;
    }
  }

  /**
   * 获取最新公告。
   * @returns {Promise<Array|null>}
   */
  async function fetchNews() {
    var base = await getApiBase();
    if (!base) return null;
    try {
      var resp = await fetchWithTimeout(base + CONFIG.NEWS_ENDPOINT + "?limit=3", {}, 5000);
      if (!resp.ok) {
        console.warn("[Nanping] 公告 API 返回非 200:", resp.status);
        return null;
      }
      const data = await resp.json();
      // 验证响应结构
      if (!Array.isArray(data)) {
        console.warn("[Nanping] 公告 API 返回数据格式错误:", data);
        return null;
      }
      return data;
    } catch (err) {
      console.warn("[Nanping] 公告获取失败:", err);
      return null;
    }
  }

  /**
   * 统一插件数据请求（万能接口）。
   * 一次 POST /plugin 获取匹配结果、公告和提示配置。
   *
   * @param {Array<{code: string, teacher: string, name: string}>} queries
   * @param {string} username
   * @param {string} gender
   * @returns {Promise<{toast: object, news: Array, results: Array}|null>}
   */
  async function fetchPluginData(queries, username, gender) {
    var base = await getApiBase();
    if (!base) return null;

    var body = { queries: queries };
    if (username) body.username = username;
    if (gender) body.gender = gender;

    try {
      var headers = { "Content-Type": "application/json" };
      var token = getAuthToken();
      if (token) headers["Authorization"] = "Bearer " + token;

      var resp = await fetchWithTimeout(base + "/plugin", {
        method: "POST",
        headers: headers,
        body: JSON.stringify(body),
      }, 15000);

      if (!resp.ok) {
        console.warn("[Nanping] 插件 API 返回非 200:", resp.status);
        return null;
      }

      var data = await resp.json();
      // v2 响应: {toast, news_html, courses, widgets}
      if (!data || !Array.isArray(data.courses)) {
        console.warn("[Nanping] 插件 API v2 返回数据格式错误:", data);
        return null;
      }

      return data;
    } catch (err) {
      console.error("[Nanping] 插件 API 请求失败:", err);
      return null;
    }
  }

  /**
   * 获取最新公告（供侧边面板使用，旧版回退）。
   * @returns {Promise<{title: string, content: string}|null>}
   */
  async function getLatestNews() {
    try {
      var newsList = await fetchNews();
      if (!newsList || newsList.length === 0) return null;
      return newsList[0];
    } catch (err) {
      console.error("[Nanping] getLatestNews 出错:", err);
      return null;
    }
  }

  // ============================================================
  // 内联徽章注入
  // ============================================================

  /**
   * 渲染星级评分 HTML。
   * @param {number} rating - 评分 (0-5)
  /**
   * 为单个课程行注入评分徽章（v2：后端预渲染 HTML）。
   *
   * @param {HTMLTableRowElement} row
   * @param {object|null} courseData - API 返回的 PluginCourseResult
   */
  function injectBadge(row, courseData) {
    try {
      if (state.processedRows.has(row)) return;
      state.processedRows.add(row);

      var nameCell = row.querySelector(".kcmc");
      if (!nameCell) return;

      // 避免重复注入
      if (nameCell.querySelector(".np-badge-row")) return;

      // 在课程名单元格末尾追加徽章行（后端预渲染的 HTML）
      var badgeRow = document.createElement("div");
      badgeRow.className = "np-badge-row";
      badgeRow.innerHTML = courseData ? courseData.badge_html : '<span class="np-badge-none">暂无评价</span>';

      // 绑定「查看评价」按钮 → 打开侧边面板
      var btn = badgeRow.querySelector(".np-badge-btn");
      if (btn && courseData) {
        btn.addEventListener("click", function (e) {
          e.stopPropagation();
          e.preventDefault();
          safeExecAsync(function () {
            return openSidePanel(courseData);
          }, "打开侧边面板", null);
        });
      }

      // 把 courseData 挂在行元素上，方便侧边面板复用
      row._npCourseData = courseData;

      nameCell.appendChild(badgeRow);
    } catch (err) {
      console.error("[Nanping] injectBadge 出错:", err);
    }
  }

  // ============================================================
  // 侧边面板（Shadow DOM）
  // ============================================================

  /**
   * 创建侧边面板（首次调用时执行，之后复用）。
   *
   * 结构：
   *   <div id="np-host">               ← 挂载到 document.body
   *     #shadow-root
   *       <style>                       ← 完全隔离的样式
   *       <div.np-overlay>              ← 半透明遮罩
   *       <div.np-panel>                ← 滑出面板
   *         <div.np-panel-header>
   *         <div.np-panel-body>
   */
  function ensureSidePanel() {
    if (state.shadowRoot) return;

    // ---- 宿主元素 ----
    var host = document.createElement("div");
    host.id = "np-side-panel-host";
    host.style.cssText =
      "position:fixed;top:0;right:0;bottom:0;left:0;z-index:99999;pointer-events:none;";
    document.body.appendChild(host);
    state.host = host;

    var shadow = host.attachShadow({ mode: "open" });
    state.shadowRoot = shadow;

    // ---- 样式（完全隔离，不受页面 CSS 影响） ----
    var style = document.createElement("style");
    style.textContent = getPanelStyles();
    shadow.appendChild(style);

    // ---- 遮罩层 ----
    var overlay = document.createElement("div");
    overlay.className = "np-overlay";
    overlay.addEventListener("click", closeSidePanel);
    shadow.appendChild(overlay);
    state.overlay = overlay;

    // ---- 面板主体 ----
    var panel = document.createElement("div");
    panel.className = "np-panel";
    panel.innerHTML =
      '<div class="np-panel-header">' +
      '<div>' +
      '<h2 class="np-panel-title">课程评价</h2>' +
      '<a class="np-header-link" href="https://nanping.eznju.com?from=plugin_v0.1.0_panel" target="_blank">到「南评」写评价！→</a>' +
      "</div>" +
      '<button class="np-close-btn">✕</button>' +
      "</div>" +
      '<div class="np-panel-body">' +
      '<div class="np-loading">加载中...</div>' +
      "</div>";
    shadow.appendChild(panel);
    state.panel = panel;

    // 关闭按钮 + 面板点击阻止冒泡
    panel.querySelector(".np-close-btn").addEventListener("click", closeSidePanel);
    panel.addEventListener("click", function (e) {
      e.stopPropagation();
    });

    // ESC 键关闭
    document.addEventListener("keydown", function (e) {
      if (e.key === "Escape" && state.isPanelOpen) {
        closeSidePanel();
      }
    });
  }

  /**
   * Shadow DOM 内的全部样式。
   * 使用 :host 上下文，完全不受页面 CSS 污染。
   */
  function getPanelStyles() {
    return (
      /* ===== 重置 ===== */
      "* { box-sizing: border-box; margin: 0; padding: 0; }" +
      /* ===== 遮罩 ===== */
      ".np-overlay {" +
      "  position: fixed; top: 0; left: 0; right: 0; bottom: 0; z-index: 1;" +
      "  background: rgba(0,0,0,0.35);" +
      "  opacity: 0; transition: opacity 0.3s ease;" +
      "  pointer-events: none;" +
      "}" +
      ".np-overlay.np-open { opacity: 1; pointer-events: auto; }" +
      /* ===== 面板 ===== */
      ".np-panel {" +
      "  position: fixed; top: 0; right: 0; bottom: 0; z-index: 2;" +
      "  width: " + CONFIG.PANEL_WIDTH + "px; max-width: 100vw;" +
      "  background: #ffffff;" +
      "  box-shadow: -4px 0 20px rgba(0,0,0,0.12);" +
      "  transform: translateX(100%); transition: transform 0.3s ease;" +
      "  display: flex; flex-direction: column;" +
      "  font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif;" +
      "  font-size: 14px; color: #1f2937; line-height: 1.5;" +
      "  pointer-events: none;" +
      "}" +
      ".np-panel.np-open { transform: translateX(0); pointer-events: auto; }" +
      /* ===== 面板头部 ===== */
      ".np-panel-header {" +
      "  display: flex; align-items: center; justify-content: space-between;" +
      "  padding: 18px 20px; border-bottom: 1px solid #e5e7eb;" +
      "  flex-shrink: 0;" +
      "}" +
      ".np-panel-title { font-size: 18px; font-weight: 600; color: #111827; }" +
      ".np-header-link {" +
      "  font-size: 13px; color: #2563eb; text-decoration: none; font-weight: 500;" +
      "  display: inline-block; margin-top: 2px;" +
      "}" +
      ".np-header-link:hover { color: #1d4ed8; text-decoration: underline; }" +
      ".np-close-btn {" +
      "  background: none; border: none; font-size: 20px; color: #9ca3af;" +
      "  cursor: pointer; padding: 4px 10px; line-height: 1; border-radius: 6px;" +
      "  transition: background 0.15s, color 0.15s;" +
      "}" +
      ".np-close-btn:hover { background: #f3f4f6; color: #374151; }" +
      /* ===== 面板内容区 ===== */
      ".np-panel-body {" +
      "  flex: 1; overflow-y: auto; padding: 16px 20px;" +
      "  -webkit-overflow-scrolling: touch;" +
      "}" +
      ".np-panel-body::-webkit-scrollbar { width: 6px; }" +
      ".np-panel-body::-webkit-scrollbar-thumb { background: #d1d5db; border-radius: 3px; }" +
      /* ===== 状态提示 ===== */
      ".np-loading { text-align: center; color: #9ca3af; padding: 60px 0; font-size: 15px; }" +
      ".np-error { text-align: center; color: #ef4444; padding: 24px; font-size: 14px; }" +
      ".np-empty { text-align: center; color: #9ca3af; padding: 60px 0; font-size: 15px; }" +
      /* ===== 课程卡片 ===== */
      ".np-course-card {" +
      "  background: #f9fafb; border: 1px solid #e5e7eb;" +
      "  border-radius: 10px; padding: 16px; margin-bottom: 16px;" +
      "}" +
      ".np-course-card:last-child { margin-bottom: 0; }" +
      ".np-course-header-row {" +
      "  display: flex; align-items: flex-start; justify-content: space-between;" +
      "  gap: 8px;" +
      "}" +
      ".np-course-code { font-size: 12px; color: #6b7280; font-weight: 500; }" +
      ".np-course-name { font-size: 16px; font-weight: 600; color: #111827; margin: 3px 0 2px; }" +
      ".np-course-teacher { font-size: 13px; color: #6b7280; }" +
      ".np-course-stats {" +
      "  display: flex; align-items: center; gap: 10px; margin-top: 10px;" +
      "  padding-top: 10px; border-top: 1px solid #e5e7eb;" +
      "}" +
      ".np-rating { font-size: 17px; font-weight: 700; color: #6B1C6C; }" +
      ".np-rating-none { font-size: 14px; color: #9ca3af; }" +
      ".np-review-count { font-size: 13px; color: #6b7280; }" +
      ".np-write-review-btn {" +
      "  font-size: 13px; color: #fff; background: #6B1C6C;" +
      "  padding: 5px 14px; border-radius: 6px; text-decoration: none; font-weight: 600;" +
      "  margin-left: auto; white-space: nowrap; transition: background 0.15s;" +
      "}" +
      ".np-write-review-btn:hover { background: #4E1450; text-decoration: none; }" +
      ".np-match-tag {" +
      "  display: inline-block; font-size: 12px; font-weight: 600;" +
      "  padding: 4px 10px; border-radius: 6px; white-space: nowrap;" +
      "  flex-shrink: 0;" +
      "}" +
      ".np-match-tag.np-tag-code {" +
      "  background: #dbeafe; color: #1d4ed8;" +
      "}" +
      ".np-match-tag.np-tag-teacher {" +
      "  background: #fef3c7; color: #92400e;" +
      "}" +
      ".np-match-tag.np-tag-name {" +
      "  background: #dcfce7; color: #15803d;" +
      "}" +
      /* ===== 评价列表 ===== */
      ".np-section-title {" +
      "  font-size: 13px; font-weight: 600; color: #9ca3af;" +
      "  margin: 14px 0 6px; text-transform: uppercase; letter-spacing: 0.5px;" +
      "}" +
      ".np-review-item {" +
      "  padding: 12px 0; border-bottom: 1px solid #f3f4f6;" +
      "}" +
      ".np-review-item:last-child { border-bottom: none; }" +
      ".np-review-header {" +
      "  display: flex; justify-content: space-between; align-items: center; margin-bottom: 6px;" +
      "}" +
      ".np-review-author { font-size: 13px; color: #6b7280; font-weight: 500; }" +
      ".np-review-rating { color: #6B1C6C; font-size: 13px; font-weight: 600; }" +
      ".np-review-content {" +
      "  font-size: 14px; line-height: 1.65; color: #374151; white-space: pre-wrap; word-break: break-word;" +
      "}" +
      ".np-review-meta {" +
      "  display: flex; justify-content: space-between; margin-top: 6px;" +
      "}" +
      ".np-review-semester { font-size: 12px; color: #9ca3af; }" +
      ".np-review-time { font-size: 12px; color: #9ca3af; }" +
      /* ===== 加载更多按钮 ===== */
      ".np-load-more {" +
      "  display: block; width: 100%; padding: 10px; margin-top: 10px;" +
      "  background: #f3f4f6; border: none; border-radius: 8px;" +
      "  color: #6b7280; cursor: pointer; font-size: 13px; font-weight: 500;" +
      "  transition: background 0.15s;" +
      "}" +
      ".np-load-more:hover { background: #e5e7eb; color: #374151; }" +
      ".np-load-more:active { background: #d1d5db; }" +
      /* ===== 公告卡片（侧边栏顶部）===== */
      ".np-news-card {" +
      "  background: linear-gradient(135deg, #6B1C6C 0%, #8B2D8B 100%);" +
      "  border-radius: 10px; padding: 14px 16px; margin-bottom: 16px;" +
      "  color: #ffffff;" +
      "}" +
      ".np-news-card-header {" +
      "  display: flex; align-items: center; gap: 6px; margin-bottom: 8px;" +
      "}" +
      ".np-news-card-icon { font-size: 16px; line-height: 1; }" +
      ".np-news-card-label {" +
      "  font-size: 11px; font-weight: 600; opacity: 0.85;" +
      "  text-transform: uppercase; letter-spacing: 0.5px;" +
      "}" +
      ".np-news-card-title {" +
      "  font-size: 14px; font-weight: 600; line-height: 1.5; margin-bottom: 6px;" +
      "}" +
      ".np-news-card-preview {" +
      "  font-size: 12px; line-height: 1.6; opacity: 0.9; margin-bottom: 10px;" +
      "}" +
      ".np-news-card-link {" +
      "  display: inline-block; font-size: 12px; color: #fff;" +
      "  text-decoration: underline; font-weight: 500; opacity: 0.9;" +
      "  transition: opacity 0.15s;" +
      "}" +
      ".np-news-card-link:hover { opacity: 1; }"
    );
  }

  /**
   * 打开侧边面板并渲染内容（v2：后端预渲染 HTML）。
   * @param {object} courseData - PluginCourseResult {badge_html, panel_html, ...}
   */
  async function openSidePanel(courseData) {
    try {
      ensureSidePanel();

      if (state.host) state.host.style.pointerEvents = "auto";
      if (state.overlay) state.overlay.classList.add("np-open");
      if (state.panel) state.panel.classList.add("np-open");
      state.isPanelOpen = true;
      document.body.style.overflow = "hidden";

      // 组装面板内容：公告卡片（缓存） + 课程面板（后端预渲染）
      var newsHtml = state.newsHtml || "";
      var panelHtml = courseData ? courseData.panel_html : "";

      renderPanelContent(newsHtml, panelHtml);
    } catch (err) {
      console.error("[Nanping] openSidePanel 出错:", err);
      safeExec(closeSidePanel, "关闭面板", null);
    }
  }

  /**
   * 关闭侧边面板。
   */
  function closeSidePanel() {
    try {
      if (!state.panel) return;
      if (state.overlay) state.overlay.classList.remove("np-open");
      if (state.panel) state.panel.classList.remove("np-open");
      state.isPanelOpen = false;
      if (state.host) state.host.style.pointerEvents = "none";
      document.body.style.overflow = "";
    } catch (err) {
      console.error("[Nanping] closeSidePanel 出错:", err);
      state.isPanelOpen = false;
      document.body.style.overflow = "";
    }
  }

  /**
   * 渲染侧边面板主体内容（v2：后端预渲染 HTML + load-more 绑定）。
   * @param {string} newsHtml - 公告卡片 HTML（可为空）
   * @param {string} panelHtml - 课程卡片 + 评价列表 HTML
   */
  function renderPanelContent(newsHtml, panelHtml) {
    try {
      var body = state.panel ? state.panel.querySelector(".np-panel-body") : null;
      if (!body) return;

      if (!panelHtml) {
        body.innerHTML = '<div class="np-empty">暂无评价数据</div>';
        return;
      }

      body.innerHTML = (newsHtml || "") + panelHtml;

      // 绑定「加载更多」按钮（load-more 仍需客户端 JS）
      safeExec(function () {
        bindLoadMoreButtons(body);
      }, "绑定加载更多按钮", null);
    } catch (err) {
      console.error("[Nanping] renderPanelContent 出错:", err);
      var body2 = state.panel ? state.panel.querySelector(".np-panel-body") : null;
      if (body2) {
        body2.innerHTML = '<div class="np-empty">渲染评价时出错</div>';
      }
    }
  }

  /**
   * 渲染单条评价的 HTML。
   */
  function renderReviewHtml(r) {
    var author = r.is_anonymous ? "匿名用户" : (r.user_email || "未知用户");
    var time = formatDate(r.created_at);
    return (
      '<div class="np-review-item" data-review-id="' + r.id + '">' +
      '  <div class="np-review-header">' +
      '    <span class="np-review-author">' + esc(author) + '</span>' +
      (r.rating ? '<span class="np-review-rating">⭐ ' + r.rating + '</span>' : "") +
      "  </div>" +
      '  <div class="np-review-content">' + esc(r.content) + "</div>" +
      '  <div class="np-review-meta">' +
      '    <span class="np-review-semester">' + esc(r.semester || "") + '</span>' +
      '    <span class="np-review-time">' + time + "</span>" +
      "  </div>" +
      "</div>"
    );
  }

  /**
   * 为面板中所有「加载更多」按钮绑定点击事件。
   */
  function bindLoadMoreButtons(container) {
    container.querySelectorAll(".np-load-more").forEach(function (btn) {
      btn.addEventListener("click", async function () {
        var courseId = parseInt(this.dataset.courseId);
        var nextPage = parseInt(this.dataset.page) + 1;

        this.textContent = "加载中...";
        this.disabled = true;

        var result = await fetchReviews(courseId, nextPage);

        if (!result || !result.items) {
          this.textContent = "加载失败，请重试";
          this.disabled = false;
          return;
        }

        if (result.items.length > 0) {
          // 去重：排除已渲染的评价
          var existingIds = new Set();
          this.parentElement.querySelectorAll(".np-review-item").forEach(function (el) {
            var id = el.dataset.reviewId;
            if (id) existingIds.add(id);
          });
          var newItems = result.items.filter(function (r) { return !existingIds.has(String(r.id)); });
          if (newItems.length > 0) {
            var fragment = newItems.map(renderReviewHtml).join("");
            this.insertAdjacentHTML("beforebegin", fragment);
          }
        }

        // 是否还有更多
        var totalLoaded = nextPage * 20;
        if (totalLoaded >= result.total || result.items.length === 0) {
          this.remove();
        } else {
          this.dataset.page = String(nextPage);
          this.textContent = "加载更多评价 ▼";
          this.disabled = false;
        }
      });
    });
  }

  // ============================================================
  // 工具函数
  // ============================================================

  /** HTML 转义 */
  function esc(str) {
    if (!str) return "";
    var div = document.createElement("div");
    div.appendChild(document.createTextNode(str));
    return div.innerHTML;
  }

  /** 日期格式化 */
  function formatDate(isoStr) {
    if (!isoStr) return "";
    try {
      var d = new Date(isoStr);
      return d.toLocaleDateString("zh-CN", {
        year: "numeric",
        month: "2-digit",
        day: "2-digit",
      });
    } catch (_) {
      return isoStr.slice(0, 10);
    }
  }

  // ============================================================
  // 页面样式注入（内联徽章用，非 Shadow DOM）
  // ============================================================

  var INLINE_STYLES =
    ".np-badge-row {" +
    "  display: flex !important; align-items: center !important; gap: 8px !important;" +
    "  margin-top: 6px !important; font-size: 13px !important; line-height: 1.4 !important;" +
    "  flex-wrap: wrap !important;" +
    "}" +
    ".np-stars {" +
    "  display: inline-flex !important; align-items: center !important; gap: 1px !important;" +
    "  font-size: 14px !important; line-height: 1 !important; white-space: nowrap !important;" +
    "}" +
    ".np-star-full {" +
    "  color: #6B1C6C !important;" +
    "}" +
    ".np-star-half {" +
    "  color: #6B1C6C !important;" +
    "  opacity: 0.5 !important;" +
    "}" +
    ".np-star-empty {" +
    "  color: #C9A0CB !important;" +
    "}" +
    ".np-badge-rating {" +
    "  font-weight: 700 !important; color: #6B1C6C !important; white-space: nowrap !important;" +
    "  margin-left: 4px !important;" +
    "}" +
    ".np-badge-count {" +
    "  color: #6b7280 !important; white-space: nowrap !important;" +
    "}" +
    ".np-badge-btn {" +
    "  background: #eff6ff !important; color: #2563eb !important;" +
    "  border: 1px solid #bfdbfe !important; border-radius: 4px !important;" +
    "  padding: 2px 10px !important; font-size: 12px !important;" +
    "  cursor: pointer !important; white-space: nowrap !important;" +
    "  transition: background 0.15s !important;" +
    "}" +
    ".np-badge-btn:hover {" +
    "  background: #dbeafe !important;" +
    "}" +
    ".np-badge-write {" +
    "  background: #6B1C6C !important; color: #fff !important;" +
    "  border-radius: 4px !important; padding: 2px 10px !important;" +
    "  font-size: 12px !important; font-weight: 600 !important;" +
    "  text-decoration: none !important; white-space: nowrap !important;" +
    "  transition: background 0.15s !important;" +
    "}" +
    ".np-badge-write:hover {" +
    "  background: #4E1450 !important; text-decoration: none !important;" +
    "}" +
    ".np-badge-none {" +
    "  color: #9ca3af !important; font-size: 12px !important; white-space: nowrap !important;" +
    "}" +
    ".np-badge-tag {" +
    "  display: inline-block !important; font-size: 11px !important; font-weight: 600 !important;" +
    "  padding: 1px 7px !important; border-radius: 4px !important; white-space: nowrap !important;" +
    "}" +
    ".np-badge-tag.np-tag-code {" +
    "  background: #dbeafe !important; color: #1d4ed8 !important;" +
    "}" +
    ".np-badge-tag.np-tag-teacher {" +
    "  background: #fef3c7 !important; color: #92400e !important;" +
    "}" +
    ".np-badge-tag.np-tag-name {" +
    "  background: #dcfce7 !important; color: #15803d !important;" +
    "}" +
    /* ===== 加载提示条 ===== */
    ".np-loading-bar {" +
    "  display: flex !important; align-items: center !important; gap: 10px !important;" +
    "  padding: 10px 16px !important; margin: 8px 0 !important;" +
    "  background: #eff6ff !important; border: 1px solid #bfdbfe !important;" +
    "  border-radius: 8px !important; font-size: 14px !important; color: #1d4ed8 !important;" +
    "}" +
    ".np-loading-bar.np-success {" +
    "  background: #f0fdf4 !important; border-color: #bbf7d0 !important; color: #15803d !important;" +
    "}" +
    ".np-loading-bar.np-error {" +
    "  background: #fef2f2 !important; border-color: #fecaca !important; color: #b91c1c !important;" +
    "}" +
    ".np-loading-spinner {" +
    "  display: inline-block !important; width: 16px !important; height: 16px !important;" +
    "  border: 2px solid #bfdbfe !important; border-top-color: #2563eb !important;" +
    "  border-radius: 50% !important; animation: np-spin 0.8s linear infinite !important;" +
    "}" +
    "@keyframes np-spin { to { transform: rotate(360deg); } }" +
    /* ===== 灵动岛加载提示 ===== */
    ".np-island {" +
    "  position: fixed !important; top: 16px !important;" +
    "  left: 50% !important; transform: translateX(-50%) !important;" +
    "  z-index: 2147483647 !important;" +
    "  background: rgba(31,41,55,0.92) !important; color: #fff !important;" +
    "  border-radius: 32px !important; padding: 12px 28px !important;" +
    "  display: flex !important; align-items: center !important; gap: 12px !important;" +
    "  font-size: 15px !important; font-weight: 500 !important;" +
    "  font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif !important;" +
    "  pointer-events: none !important; user-select: none !important;" +
    "  box-shadow: 0 8px 32px rgba(0,0,0,0.25) !important;" +
    "  animation: np-island-in 0.4s cubic-bezier(0.16,1,0.3,1) !important;" +
    "  max-width: calc(100vw - 32px) !important;" +
    "}" +
    ".np-island.np-island-out {" +
    "  animation: np-island-out 0.3s ease forwards !important;" +
    "}" +
    ".np-island-brand {" +
    "  font-family: 'Noto Serif SC', '思源宋体', 'Source Han Serif SC', serif !important;" +
    "  font-weight: 700 !important; font-size: 16px !important;" +
    "  color: #C9A0CB !important; flex-shrink: 0 !important;" +
    "  letter-spacing: 2px !important;" +
    "}" +
    ".np-island-spinner {" +
    "  display: inline-block !important; width: 16px !important; height: 16px !important;" +
    "  border: 2px solid rgba(255,255,255,0.3) !important;" +
    "  border-top-color: #fff !important; border-radius: 50% !important;" +
    "  animation: np-spin 0.8s linear infinite !important; flex-shrink: 0 !important;" +
    "}" +
    ".np-island-icon { font-size: 18px !important; line-height: 1 !important; flex-shrink: 0 !important; }" +
    "@keyframes np-island-in {" +
    "  from { opacity: 0; transform: translateX(-50%) translateY(-12px) scale(0.9); }" +
    "  to   { opacity: 1; transform: translateX(-50%) translateY(0) scale(1); }" +
    "}" +
    "@keyframes np-island-out {" +
    "  from { opacity: 1; transform: translateX(-50%) translateY(0) scale(1); }" +
    "  to   { opacity: 0; transform: translateX(-50%) translateY(-12px) scale(0.9); }" +
    "}";

  function injectStyles() {
    if (document.getElementById("np-inline-styles")) return;
    var styleEl = document.createElement("style");
    styleEl.id = "np-inline-styles";
    styleEl.textContent = INLINE_STYLES;
    document.head.appendChild(styleEl);
  }

  // ============================================================
  // 加载提示
  // ============================================================

  /**
   * 在页面顶部「推荐选课模块」区域显示加载提示条。
   * 每次调用会先移除旧的提示条。
   *
   * @param {string} text - 提示文字
   * @param {"loading"|"success"|"error"} type - 提示类型
   */
  function showLoadingBar(text, type) {
    removeLoadingBar();
    var topArea = document.querySelector("article#course-main .top");
    if (!topArea) return;
    var bar = document.createElement("div");
    bar.className = "np-loading-bar";
    if (type === "success") bar.classList.add("np-success");
    if (type === "error") bar.classList.add("np-error");
    bar.id = "np-loading-bar";
    if (type === "loading") {
      bar.innerHTML =
        '<span class="np-loading-spinner"></span><span>' + text + "</span>";
    } else {
      bar.textContent = text;
    }
    topArea.appendChild(bar);
  }

  /** 移除加载提示条。 */
  function removeLoadingBar() {
    var existing = document.getElementById("np-loading-bar");
    if (existing) existing.remove();
  }

  /**
   * 灵动岛提示。
   * 页面顶部居中浮条，pointer-events: none 不阻挡任何操作。
   *
   * @param {"loading"|"success"|"error"} type
   * @param {string} text - 提示文字
   */
  function showDynamicIsland(type, text) {
    removeDynamicIsland();
    var island = document.createElement("div");
    island.className = "np-island";
    island.id = "np-island";

    var brandHtml = '<span class="np-island-brand">南评</span>';

    if (type === "loading") {
      island.innerHTML =
        brandHtml + '<span class="np-island-spinner"></span><span>' + text + '</span>';
    } else {
      var icon = type === "success" ? "✅" : "⚠️";
      island.innerHTML =
        brandHtml + '<span class="np-island-icon">' + icon + '</span><span>' + text + '</span>';
    }

    // 避免遮挡官方菜单：检测页面 header 高度，灵动岛定位在 header 下方
    var header = document.querySelector(".cv-page-header");
    var top = 16;
    if (header) {
      var rect = header.getBoundingClientRect();
      top = Math.max(16, rect.bottom + 8);
    }
    island.style.top = top + "px";

    document.body.appendChild(island);
  }

  /** 移除灵动岛（带出场动画）。 */
  function removeDynamicIsland() {
    var existing = document.getElementById("np-island");
    if (!existing) return;
    existing.classList.add("np-island-out");
    setTimeout(function () {
      if (existing.parentNode) existing.remove();
    }, 300);
  }

  // ============================================================
  // Widget 渲染（v2 增值服务插槽）
  // ============================================================

  /**
   * 渲染后端下发的 widgets。
   * 支持类型：inline_badge（课程行内标签）、input_bar（页面输入框）、banner（横幅）。
   *
   * @param {Array<{type: string, query_index: number, position: string, html: string, endpoint: string}>} widgets
   * @param {Array} courses - extractAllCourses() 的返回值，用于 query_index 定位
   */
  function renderWidgets(widgets, courses) {
    widgets.forEach(function (w) {
      try {
        if (!w.html) return;

        if (w.type === "inline_badge" && w.query_index != null) {
          // 在对应课程行的 badge-row 内追加 HTML
          var c = courses[w.query_index];
          if (!c) return;
          var nameCell = c.row.querySelector(".kcmc");
          if (!nameCell) return;
          var badgeRow = nameCell.querySelector(".np-badge-row");
          if (badgeRow) {
            badgeRow.insertAdjacentHTML("beforeend", w.html);
          }
        } else if (w.type === "input_bar") {
          // 在课程表上方或下方插入输入框
          var topArea = document.querySelector("article#course-main .top");
          if (topArea) {
            var position = w.position === "before_table" ? "beforebegin" : "afterend";
            topArea.insertAdjacentHTML(position, w.html);
            // 绑定提交事件（如果提供了 endpoint）
            if (w.endpoint) {
              setTimeout(function () {
                var widgetEl = document.getElementById("np-widget-input-bar");
                if (!widgetEl) return;
                var btn = widgetEl.querySelector("button");
                var input = widgetEl.querySelector("input");
                if (btn && input) {
                  btn.addEventListener("click", function () {
                    var value = input.value.trim();
                    if (!value) return;
                    // 向指定 endpoint 发送用户输入
                    fetchPluginData([], "", "");
                    console.log("[Nanping] Widget input:", value, "→", w.endpoint);
                  });
                }
              }, 100);
            }
          }
        } else if (w.type === "banner") {
          // 在页面指定位置插入横幅
          var container = document.querySelector("article#course-main");
          if (container) {
            container.insertAdjacentHTML(w.position === "after_table" ? "beforeend" : "afterbegin", w.html);
          }

        } else if (w.type === "login_banner" || w.type === "login_modal") {
          // auth primitive：后端下发的登录 UI
          document.body.insertAdjacentHTML("beforeend", w.html);
          setTimeout(function () {
            var closeBtn = document.querySelector(".np-auth-close");
            if (closeBtn) closeBtn.addEventListener("click", function () {
              var el = document.querySelector(".np-auth-overlay, .np-auth-banner");
              if (el) el.remove();
            });
            var loginBtn = document.querySelector(".np-auth-login-btn");
            if (loginBtn && w.endpoint) {
              loginBtn.addEventListener("click", function () {
                if (w.endpoint) window.open(w.endpoint, "_blank");
              });
            }
          }, 100);
        }
      } catch (err) {
        console.error("[Nanping] renderWidgets 出错:", err, w);
      }
    });
  }

  // ============================================================
  // 主处理逻辑
  // ============================================================

  /**
   * 扫描页面课程行 → 批量请求 API → 注入徽章。
   *
   * 核心流程：
   *   1. 从 DOM 提取所有课程行信息
   *   2. 筛选未处理过的行
   *   3. 一次性 POST /courses/match
   *   4. 逐行注入评分徽章
   */
  async function processPage() {
    try {
      var courses = extractAllCourses();
      if (courses.length === 0) return;

      // 只处理还未注入徽章的行
      var newCourses = courses.filter(function (c) {
        return !state.processedRows.has(c.row);
      });
      if (newCourses.length === 0) return;

      // 显示加载提示（优先用缓存 toast 配置，否则硬编码兜底）
      safeExec(function () {
        var loadingText = (state.toastConfig && state.toastConfig.loading)
          ? state.toastConfig.loading
          : "「南评」正在加载评论...";
        showDynamicIsland("loading", loadingText);
      }, "显示加载提示", null);

      // 统一请求 /plugin v2（全量字段 + 后端预渲染 HTML）
      var username = safeExec(extractUsername, "提取用户名", "");
      var gender = safeExec(extractUserGender, "提取性别", "");
      var queries = newCourses.map(function (c) {
        return {
          code: c.code,
          name: c.name,
          teacher: c.teacher,
          credits: c.credits || "",
          schedule: c.schedule || "",
          campus: c.campus || "",
          grade: c.grade || "",
          department: c.department || "",
        };
      });
      var response = await fetchPluginData(queries, username, gender);

      // 注入徽章（后端预渲染 HTML，直接 innerHTML）
      newCourses.forEach(function (c, i) {
        try {
          var courseData = response && response.courses ? response.courses[i] : null;
          injectBadge(c.row, courseData);
        } catch (err) {
          console.error("[Nanping] 注入徽章失败:", err);
        }
      });

      // 缓存 news_html 和 toast 配置
      if (response) {
        state.newsHtml = response.news_html || "";
        state.toastConfig = response.toast || null;
      }

      // 渲染 widgets（v2 增值服务插槽）
      if (response && response.widgets && response.widgets.length > 0) {
        safeExec(function () {
          renderWidgets(response.widgets, newCourses);
        }, "渲染 widgets", null);
      }

      // toast 文案优先取响应配置（常驻，手动 × 关闭）
      safeExec(function () {
        removeDynamicIsland();
        if (response && state.toastConfig) {
          showDynamicIsland("success", state.toastConfig.success);
        } else if (response) {
          showDynamicIsland("success", "加载成功");
        } else {
          var errorMsg = (state.toastConfig && state.toastConfig.error)
            ? state.toastConfig.error
            : "加载失败，请检查网络连接";
          showDynamicIsland("error", errorMsg);
        }
      }, "显示灵动岛", null);
    } catch (err) {
      console.error("[Nanping] processPage 出错:", err);
      safeExec(function () {
        removeDynamicIsland();
        var errorMsg = (state.toastConfig && state.toastConfig.error)
          ? state.toastConfig.error
          : "处理页面时出错";
        showDynamicIsland("error", errorMsg);
      }, "显示错误提示", null);
    }
  }

  function escapeHtml(text) {
    return String(text)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  /**
   * 带防抖的 processPage。
   * MutationObserver 可能在短时间内多次触发（逐行渲染时），
   * 用防抖合并为一次调用。
   */
  function debouncedProcess() {
    if (state.debounceTimer) clearTimeout(state.debounceTimer);
    state.debounceTimer = setTimeout(processPage, CONFIG.DEBOUNCE_MS);
  }

  // ============================================================
  // 初始化
  // ============================================================

  function init() {
    try {
      injectStyles();

      // 首次处理：页面可能已有静态内容，也可能还没有（JS 渲染中）
      setTimeout(function () {
        safeExec(processPage, "首次处理页面", null);
      }, 600);

      // ---- MutationObserver：监听动态加载 ----
      var observer = new MutationObserver(function (mutations) {
        try {
          for (var i = 0; i < mutations.length; i++) {
            var mutation = mutations[i];
            if (mutation.type === "childList" && mutation.addedNodes.length > 0) {
              for (var j = 0; j < mutation.addedNodes.length; j++) {
                var node = mutation.addedNodes[j];
                if (node.nodeType === Node.ELEMENT_NODE) {
                  // 检测是否有课程行被添加到 DOM
                  if (
                    (node.matches && node.matches("tr.course-tr")) ||
                    (node.querySelector && node.querySelector("tr.course-tr"))
                  ) {
                    debouncedProcess();
                    return;
                  }
                }
              }
            }
          }
        } catch (err) {
          console.error("[Nanping] MutationObserver 处理出错:", err);
        }
      });

      // 尽量精准地观察课程容器，退而求其次观察 body
      var target = safeQuerySelector(".result-container") || document.body;
      if (target) {
        observer.observe(target, { childList: true, subtree: true });
      }

      // ---- Tab 切换监听 ----
      // 用户点击「专业/公共/跨专业/课表查询」时清空处理状态
      document.addEventListener("click", function (e) {
        try {
          var tab = e.target.closest("#cvPageHeadTab a[data-teachingclasstype]");
          if (tab) {
            // 清空已处理标记，等新内容渲染后重新处理
            state.processedRows = new WeakSet();
            setTimeout(function () {
              safeExec(processPage, "Tab 切换后处理", null);
            }, 800);
          }
        } catch (err) {
          console.error("[Nanping] Tab 切换监听出错:", err);
        }
      });

      // ---- 「加载更多」按钮监听 ----
      document.addEventListener("click", function (e) {
        try {
          if (e.target.closest(".course-table-footer")) {
            setTimeout(function () {
              safeExec(processPage, "加载更多后处理", null);
            }, 1000);
          }
        } catch (err) {
          console.error("[Nanping] 加载更多监听出错:", err);
        }
      });

      console.log("[Nanping] 插件初始化成功");
    } catch (err) {
      console.error("[Nanping] 插件初始化失败:", err);
      showFatalError("插件初始化失败，请刷新页面重试。如问题持续，请联系作者。");
    }
  }

  // 启动
  try {
    if (document.readyState === "loading") {
      document.addEventListener("DOMContentLoaded", init);
    } else {
      init();
    }
  } catch (err) {
    console.error("[Nanping] 插件启动失败:", err);
    showFatalError("插件启动失败，请刷新页面重试。如问题持续，请联系作者。");
  }
})();
