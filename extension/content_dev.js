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
    DEBOUNCE_MS: 500, // 防抖间隔（避免 MutationObserver 频繁触发）
    PANEL_WIDTH: 420, // 侧边面板宽度（px）
  };

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
  };

  // ============================================================
  // DOM 信息提取
  // ============================================================

  /**
   * 从单个课程行提取课程信息。
   *
   * 页面结构（tbody.course-body > tr.course-tr）：
   *   td.kch > a.cv-jxb-detail[data-number]   → 课程号
   *   td.kcmc                                  → 课程名
   *   td.jsmc                                  → 授课教师（逗号分隔）
   *
   * @param {HTMLTableRowElement} row - 课程行 <tr>
   * @returns {{code: string, name: string, teacher: string}|null}
   */
  function extractCourseFromRow(row) {
    const codeAnchor = row.querySelector(".kch .cv-jxb-detail");
    const nameCell = row.querySelector(".kcmc");
    const teacherCell = row.querySelector(".jsmc");

    if (!codeAnchor || !nameCell) return null;

    return {
      code: (codeAnchor.getAttribute("data-number") || codeAnchor.textContent || "").trim(),
      name: nameCell.textContent.trim(),
      teacher: teacherCell ? teacherCell.textContent.trim() : "",
    };
  }

  /**
   * 提取页面上所有课程行信息。
   * @returns {Array<{code: string, name: string, teacher: string, row: HTMLTableRowElement}>}
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
        const controller = new AbortController();
        const timeout = setTimeout(() => controller.abort(), 2000);
        const resp = await fetch(candidate + "/", {
          signal: controller.signal,
        });
        clearTimeout(timeout);
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
   * 批量匹配课程。
   * 将页面上所有课程行一次性发送到后端，后端做三级回退搜索。
   *
   * @param {Array<{code: string, teacher: string, name: string}>} queries
   * @returns {Promise<{results: Array}|null>}
   */
  async function batchMatch(queries) {
    const base = await getApiBase();
    if (!base) return null;

    try {
      const resp = await fetch(base + CONFIG.MATCH_ENDPOINT, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ queries }),
      });
      if (!resp.ok) {
        console.warn("[Nanping] 匹配 API 返回非 200:", resp.status);
        return null;
      }
      return await resp.json();
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
      const resp = await fetch(base + CONFIG.REVIEW_ENDPOINT + "?" + params.toString());
      if (!resp.ok) return null;
      return await resp.json();
    } catch (err) {
      console.error("[Nanping] 评价获取失败:", err);
      return null;
    }
  }

  // ============================================================
  // 内联徽章注入
  // ============================================================

  /**
   * 为单个课程行注入评分徽章。
   * 在课程名下方插入一个 <div class="np-badge-row">，
   * 包含评分星级、评价数、以及查看详情按钮。
   *
   * 匹配结果命中的行和未命中的行都会注入（未命中显示"暂无评价"）。
   *
   * @param {HTMLTableRowElement} row
   * @param {{matched: Array}|null} matchResult - API 返回的单条匹配结果
   */
  function injectBadge(row, matchResult) {
    if (state.processedRows.has(row)) return;
    state.processedRows.add(row);

    var nameCell = row.querySelector(".kcmc");
    if (!nameCell) return;

    // 避免重复注入（双重保险）
    if (nameCell.querySelector(".np-badge-row")) return;

    // 在课程名单元格末尾追加徽章行
    var badgeRow = document.createElement("div");
    badgeRow.className = "np-badge-row";

    var hasMatch = matchResult && matchResult.matched && matchResult.matched.length > 0;
    var exactId = matchResult && matchResult.exact_course_id;

    if (hasMatch) {
      var best = matchResult.matched[0];
      var c = best.course;
      var ratingText = c.avg_rating != null ? "⭐ " + c.avg_rating.toFixed(1) : "";

      // 解析 match_level 生成字段标签（仅用最严格策略命中的第一个 course）
      var fieldTags = matchLevelToTags(best.match_level);
      var tagsHtml = fieldTags.map(function (t) {
        return '<span class="np-badge-tag np-tag-' + t.cls + '">匹配' + t.label + '</span>';
      }).join("");

      badgeRow.innerHTML =
        tagsHtml +
        '<span class="np-badge-rating">' + ratingText + '</span>' +
        '<span class="np-badge-count">' + c.review_count + "条评价</span>" +
        '<button class="np-badge-btn">查看评价</button>';

      // 写评价按钮
      if (exactId) {
        badgeRow.innerHTML +=
          ' <a class="np-badge-write" href="https://nanping.eznju.com/course.html?id=' + exactId + '" target="_blank">写评价</a>';
      }
    } else {
      var noReviewHtml = '<span class="np-badge-none">暂无评价</span>';
      if (exactId) {
        noReviewHtml +=
          ' <a class="np-badge-write" href="https://nanping.eznju.com/course.html?id=' + exactId + '" target="_blank">写评价</a>';
      }
      badgeRow.innerHTML = noReviewHtml;
    }

    // 点击「查看」→ 打开侧边面板
    if (hasMatch) {
      var btn = badgeRow.querySelector(".np-badge-btn");
      btn.addEventListener("click", function (e) {
        e.stopPropagation();
        e.preventDefault();
        openSidePanel(matchResult);
      });
    }

    // 把 matchResult 挂在行元素上，方便侧边面板复用
    row._npMatchResult = matchResult;

    nameCell.appendChild(badgeRow);
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
      '<a class="np-header-link" href="https://nanping.eznju.com" target="_blank">到「南评」写评价！→</a>' +
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
      ".np-rating { font-size: 17px; font-weight: 700; color: #f59e0b; }" +
      ".np-rating-none { font-size: 14px; color: #9ca3af; }" +
      ".np-review-count { font-size: 13px; color: #6b7280; }" +
      ".np-write-review-btn {" +
      "  font-size: 13px; color: #fff; background: #f59e0b;" +
      "  padding: 5px 14px; border-radius: 6px; text-decoration: none; font-weight: 600;" +
      "  margin-left: auto; white-space: nowrap; transition: background 0.15s;" +
      "}" +
      ".np-write-review-btn:hover { background: #d97706; text-decoration: none; }" +
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
      ".np-review-rating { color: #f59e0b; font-size: 13px; font-weight: 600; }" +
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
      ".np-load-more:active { background: #d1d5db; }"
    );
  }

  /**
   * 打开侧边面板并渲染内容。
   * @param {{matched: Array}} matchResult - 匹配结果（含 course + top_reviews）
   */
  async function openSidePanel(matchResult) {
    ensureSidePanel();

    // 动画显示
    state.host.style.pointerEvents = "auto";
    state.overlay.classList.add("np-open");
    state.panel.classList.add("np-open");
    state.isPanelOpen = true;
    document.body.style.overflow = "hidden";

    // 渲染内容
    renderPanelContent(matchResult);
  }

  /**
   * 关闭侧边面板。
   */
  function closeSidePanel() {
    if (!state.panel) return;
    state.overlay.classList.remove("np-open");
    state.panel.classList.remove("np-open");
    state.isPanelOpen = false;
    state.host.style.pointerEvents = "none";
    document.body.style.overflow = "";
  }

  /**
   * 渲染侧边面板的主体内容。
   * 展示所有匹配到的课程，每个课程一张卡片 + 其最新评价。
   */
  function renderPanelContent(matchResult) {
    var body = state.panel.querySelector(".np-panel-body");
    if (!body) return;

    if (!matchResult || !matchResult.matched || matchResult.matched.length === 0) {
      body.innerHTML =
        '<div class="np-empty">暂无评价数据</div>';
      return;
    }

    var html = "";
    matchResult.matched.forEach(function (item) {
      var c = item.course;
      var reviews = item.top_reviews || [];

      // 每个 course 独立解析其 match_level，生成字段标签
      var fieldTags = matchLevelToTags(item.match_level);
      var tagsHtml = fieldTags.map(function (t) {
        return '<span class="np-match-tag np-tag-' + t.cls + '">匹配' + t.label + '</span>';
      }).join("");

      html +=
        '<div class="np-course-card" data-course-id="' + c.id + '">' +
        '  <div class="np-course-header-row">' +
        '    <div>' +
        '      <div class="np-course-code">' + esc(c.code) + '</div>' +
        '      <div class="np-course-name">' + esc(c.name) + '</div>' +
        '      <div class="np-course-teacher">' + esc(c.teacher) + '</div>' +
        "    </div>" +
        '    <div style="display:flex;flex-direction:column;gap:4px;align-items:flex-end;">' + tagsHtml + '</div>' +
        "  </div>" +
        '  <div class="np-course-stats">' +
        (c.avg_rating != null
          ? '<span class="np-rating">⭐ ' + c.avg_rating.toFixed(1) + '</span>'
          : '<span class="np-rating-none">暂无评分</span>') +
        '    <span class="np-review-count">' + c.review_count + ' 条评价</span>' +
        '    <a class="np-write-review-btn" href="https://nanping.eznju.com/course.html?id=' + c.id + '" target="_blank">写评价</a>' +
        "  </div>" +
        '  <div class="np-section-title">最新评价</div>' +
        reviews.map(renderReviewHtml).join("") +
        (c.review_count > reviews.length
          ? '<button class="np-load-more" data-course-id="' + c.id + '" data-page="0">' +
            '加载更多评价 ▼</button>'
          : "") +
        "</div>";
    });

    body.innerHTML = html;

    // 绑定「加载更多」按钮
    bindLoadMoreButtons(body);
  }

  /**
   * 渲染单条评价的 HTML。
   */
  function renderReviewHtml(r) {
    var author = r.is_anonymous ? "匿名用户" : (r.user_email || "未知用户");
    var time = formatDate(r.created_at);
    return (
      '<div class="np-review-item">' +
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
          var fragment = result.items.map(renderReviewHtml).join("");
          this.insertAdjacentHTML("beforebegin", fragment);
        }

        // 是否还有更多
        var loaded = (nextPage + 1) * 20; // page 从 0 开始，pageSize=20
        // 实际上 page 参数是 1-indexed，所以 loaded = nextPage * 20
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

  /**
   * 将 match_level 字符串解析为字段标签数组。
   *
   * match_level 如 "code+teacher+name"，按 "+" 拆分后映射：
   *   code    → {label:"课程号", cls:"code"}
   *   teacher → {label:"教师",   cls:"teacher"}
   *   name    → {label:"课程名", cls:"name"}
   *
   * @param {string} level
   * @returns {Array<{label: string, cls: string}>}
   */
  function matchLevelToTags(level) {
    var FIELD_MAP = {
      code:    { label: "课程号", cls: "code" },
      teacher: { label: "教师",   cls: "teacher" },
      name:    { label: "课程名", cls: "name" },
    };
    if (!level) return [];
    return level.split("+").map(function (f) {
      return FIELD_MAP[f] || { label: f, cls: f };
    }).filter(Boolean);
  }

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
    ".np-badge-rating {" +
    "  font-weight: 700 !important; color: #f59e0b !important; white-space: nowrap !important;" +
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
    "  background: #f59e0b !important; color: #fff !important;" +
    "  border-radius: 4px !important; padding: 2px 10px !important;" +
    "  font-size: 12px !important; font-weight: 600 !important;" +
    "  text-decoration: none !important; white-space: nowrap !important;" +
    "  transition: background 0.15s !important;" +
    "}" +
    ".np-badge-write:hover {" +
    "  background: #d97706 !important; text-decoration: none !important;" +
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
    "  border-radius: 28px !important; padding: 10px 24px !important;" +
    "  display: flex !important; align-items: center !important; gap: 10px !important;" +
    "  font-size: 14px !important; font-weight: 500 !important;" +
    "  font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif !important;" +
    "  pointer-events: none !important; user-select: none !important;" +
    "  box-shadow: 0 8px 32px rgba(0,0,0,0.25) !important;" +
    "  animation: np-island-in 0.4s cubic-bezier(0.16,1,0.3,1) !important;" +
    "  max-width: calc(100vw - 32px) !important;" +
    "}" +
    ".np-island.np-island-out {" +
    "  animation: np-island-out 0.3s ease forwards !important;" +
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

    if (type === "loading") {
      island.innerHTML =
        '<span class="np-island-spinner"></span><span>' + text + '</span>';
    } else {
      var icon = type === "success" ? "✅" : "⚠️";
      island.innerHTML =
        '<span class="np-island-icon">' + icon + '</span><span>' + text + '</span>';
    }

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
    var courses = extractAllCourses();
    if (courses.length === 0) return;

    // 只处理还未注入徽章的行
    var newCourses = courses.filter(function (c) {
      return !state.processedRows.has(c.row);
    });
    if (newCourses.length === 0) return;

    // 显示加载提示（顶部条 + 灵动岛）
    showLoadingBar("「南评」正在加载评论...", "loading");
    showDynamicIsland("loading", "「南评」正在加载评论...");

    // 批量请求 API
    var queries = newCourses.map(function (c) {
      return { code: c.code, teacher: c.teacher, name: c.name };
    });
    var response = await batchMatch(queries);

    // 注入徽章
    var matchedCount = 0;
    newCourses.forEach(function (c, i) {
      var result = response && response.results ? response.results[i] : null;
      injectBadge(c.row, result);
      if (result && result.matched && result.matched.length > 0) {
        matchedCount++;
      }
    });

    // 灵动岛显示结果，1.5 秒后消失
    removeDynamicIsland();
    if (response) {
      showDynamicIsland("success", "加载成功，匹配到 " + matchedCount + " 条评价");
    } else {
      showDynamicIsland("error", "加载失败，请检查网络连接");
    }
    setTimeout(removeDynamicIsland, 1500);

    // 顶部条显示完成状态，不消失
    if (response) {
      showLoadingBar("✅ 加载成功，" + newCourses.length + " 门课程中匹配到 " + matchedCount + " 条评价", "success");
    } else {
      showLoadingBar("⚠️ 加载失败，请检查网络连接", "error");
    }
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
    injectStyles();

    // 首次处理：页面可能已有静态内容，也可能还没有（JS 渲染中）
    setTimeout(processPage, 600);

    // ---- MutationObserver：监听动态加载 ----
    var observer = new MutationObserver(function (mutations) {
      for (var i = 0; i < mutations.length; i++) {
        var mutation = mutations[i];
        if (mutation.type === "childList" && mutation.addedNodes.length > 0) {
          for (var j = 0; j < mutation.addedNodes.length; j++) {
            var node = mutation.addedNodes[j];
            if (node.nodeType === Node.ELEMENT_NODE) {
              // 检测是否有课程行被添加到 DOM
              if (
                node.matches && node.matches("tr.course-tr") ||
                node.querySelector && node.querySelector("tr.course-tr")
              ) {
                debouncedProcess();
                return;
              }
            }
          }
        }
      }
    });

    // 尽量精准地观察课程容器，退而求其次观察 body
    var target = document.querySelector(".result-container") || document.body;
    observer.observe(target, { childList: true, subtree: true });

    // ---- Tab 切换监听 ----
    // 用户点击「专业/公共/跨专业/课表查询」时清空处理状态
    document.addEventListener("click", function (e) {
      var tab = e.target.closest("#cvPageHeadTab a[data-teachingclasstype]");
      if (tab) {
        // 清空已处理标记，等新内容渲染后重新处理
        state.processedRows = new WeakSet();
        setTimeout(processPage, 800);
      }
    });

    // ---- 「加载更多」按钮监听 ----
    document.addEventListener("click", function (e) {
      if (e.target.closest(".course-table-footer")) {
        setTimeout(processPage, 1000);
      }
    });
  }

  // 启动
  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
