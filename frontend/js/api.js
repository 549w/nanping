/* ============================================================
   api.js — 后端 API 封装
   所有与后端通信的逻辑集中于此，返回统一的 { ok, status, data, error } 格式。

   依赖：auth.js（令牌注入）、utils.js（工具函数）
   ============================================================ */

import { getToken, isLoggedIn } from "./auth.js";

/** 后端 API 基地址，部署时修改此处即可。 */
const API_BASE = "https://npapi.eznju.com";

// ---- 内部请求封装 ----

/**
 * 发起后端 API 请求。
 * @param {string} method - HTTP 方法
 * @param {string} path - 路径（如 "/courses"）
 * @param {object|null} body - 请求体 JSON
 * @returns {Promise<{ok: boolean, status?: number, data?: any, error?: string}>}
 */
async function request(method, path, body = null) {
  const headers = { "Content-Type": "application/json" };

  // 注入认证头
  if (isLoggedIn()) {
    const token = getToken();
    if (token) {
      headers["Authorization"] = `Bearer ${token}`;
    }
  }

  let response;
  try {
    response = await fetch(`${API_BASE}${path}`, {
      method,
      headers,
      body: body ? JSON.stringify(body) : undefined,
    });
  } catch (err) {
    console.error("[Nanping API] 网络请求失败:", path, err);
    return { ok: false, error: "NETWORK", message: "网络连接失败，请检查网络后重试" };
  }

  let data;
  try {
    data = await response.json();
  } catch {
    data = null;
  }

  if (!response.ok) {
    console.error("[Nanping API] 请求错误:", method, path, response.status, data);
    // 401 Unauthorized
    if (response.status === 401) {
      return { ok: false, status: 401, error: "UNAUTHORIZED" };
    }
    // 422 Validation Error — 提取字段级错误
    if (response.status === 422 && data?.detail) {
      const messages = Array.isArray(data.detail)
        ? data.detail.map((d) => d.msg).join("；")
        : String(data.detail);
      return { ok: false, status: 422, error: messages };
    }
    // 429 Rate Limit
    if (response.status === 429) {
      return { ok: false, status: 429, error: "操作过于频繁，请稍后再试" };
    }
    // 其它错误
    const detail = data?.detail || data?.message || `请求失败（${response.status}）`;
    return { ok: false, status: response.status, error: String(detail) };
  }

  return { ok: true, status: response.status, data };
}

// ---- 公开接口 ----

/**
 * 搜索课程。
 * @param {{code?: string, name?: string, teacher?: string, page?: number, pageSize?: number}} params
 * @returns {Promise<{ok, status?, data?: {items, total, page, page_size}, error?}>}
 */
export async function searchCourses({ code, name, teacher, page = 1, pageSize = 20 } = {}) {
  const query = new URLSearchParams();
  if (code) query.set("code", code);
  if (name) query.set("name", name);
  if (teacher) query.set("teacher", teacher);
  query.set("page", String(page));
  query.set("page_size", String(Math.min(100, Math.max(1, pageSize))));

  return request("GET", `/courses?${query.toString()}`);
}

/**
 * 获取课程详情（含开课学期列表）。
 * @param {number} courseId
 * @returns {Promise<{ok, status?, data?: object, error?}>}
 */
export async function getCourseDetail(courseId) {
  return request("GET", `/courses/${courseId}`);
}

/**
 * 获取课程评价列表。
 * @param {number} courseId
 * @param {number} [page=1]
 * @param {number} [pageSize=20]
 */
export async function getReviews(courseId, page = 1, pageSize = 20) {
  const query = new URLSearchParams();
  query.set("course_id", String(courseId));
  query.set("page", String(page));
  query.set("page_size", String(Math.min(100, Math.max(1, pageSize))));

  return request("GET", `/review?${query.toString()}`);
}

// ---- 认证接口 ----

/**
 * 发送验证码。
 * @param {string} email
 */
export async function sendCode(email) {
  return request("POST", "/auth/send-code", { email });
}

/**
 * 注册新用户。
 * @param {string} email
 * @param {string} code - 6 位验证码
 * @param {string} password
 */
export async function register(email, code, password) {
  return request("POST", "/auth/register", { email, code, password });
}

/**
 * 登录。
 * @param {string} email
 * @param {string} password
 */
export async function login(email, password) {
  const result = await request("POST", "/auth/login", { email, password });
  // 登录成功时自动保存令牌
  if (result.ok && result.data?.access_token) {
    // 先导入并保存（避免循环依赖 — auth.js 不 import api.js）
    const { setToken: save } = await import("./auth.js");
    save(result.data.access_token);
  }
  return result;
}

// ---- 需认证接口 ----

/**
 * 提交课程评价。
 * @param {{courseId: number, rating: number, content: string, semester?: string, isAnonymous?: boolean}} params
 */
export async function addReview({ courseId, rating, content, semester, isAnonymous = false, referrer = null }) {
  const body = {
    course_id: courseId,
    rating,
    content,
    semester: semester || null,
    is_anonymous: isAnonymous,
  };
  if (referrer) {
    body.referrer = referrer;
  }
  return request("POST", "/review/add", body);
}

/**
 * 软删除评价（仅限本人）。
 * @param {number} reviewId
 */
export async function deleteReview(reviewId) {
  return request("DELETE", "/review/delete", { review_id: reviewId });
}

/**
 * 获取当前用户的评价列表。
 * @param {number} [page=1]
 * @param {number} [pageSize=20]
 */
export async function getMyReviews(page = 1, pageSize = 20) {
  const query = new URLSearchParams();
  query.set("page", String(page));
  query.set("page_size", String(Math.min(100, Math.max(1, pageSize))));

  return request("GET", `/review/me?${query.toString()}`);
}

// ---- 挂载到 window 供非模块脚本和内联脚本访问 ----
window.NanpingAPI = {
  searchCourses,
  getCourseDetail,
  getReviews,
  sendCode,
  register,
  login,
  addReview,
  deleteReview,
  getMyReviews,
};
