/**
 * Nanping 插件脚本加载器。
 *
 * 生产环境从 npapi.eznju.com 加载，开发环境自动回退到 localhost。
 * 真正的业务逻辑在 content_dev.js 中，修改后刷新页面即生效。
 */
(function () {
  "use strict";

  var CANDIDATES = [
    "https://npapi.eznju.com/extension/content_dev.js",
    "http://localhost:8000/extension/content_dev.js",
  ];

  // 清除旧版本
  var old = document.getElementById("np-content-script");
  if (old) old.remove();

  function tryLoad(index) {
    if (index >= CANDIDATES.length) {
      console.error("[Nanping] 所有脚本源均不可达");
      return;
    }
    var script = document.createElement("script");
    script.id = "np-content-script";
    script.src = CANDIDATES[index] + "?t=" + Date.now();
    script.onerror = function () {
      script.remove();
      tryLoad(index + 1);
    };
    document.documentElement.appendChild(script);
  }

  tryLoad(0);
})();
