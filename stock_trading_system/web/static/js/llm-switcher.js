/**
 * LLM Provider Switcher — sidebar + topbar dual dropdown.
 *
 * On load: fetches current provider state from GET /api/settings/llm-provider.
 * On change: POST to switch, with toast feedback and rollback on error.
 * Both selects (sidebar + topbar) stay in sync.
 */

(function () {
  'use strict';

  // Two selects: sidebar (desktop) and topbar (always visible)
  var SELECTORS = ['llm-provider-select', 'llm-provider-select-topbar'];
  var LOCK_IDS = ['llm-lock-icon', 'llm-lock-icon-topbar'];
  var STATUS_ID = 'bot-status';

  function showToast(msg, type) {
    if (typeof window.showToast === 'function') {
      window.showToast(msg, type);
      return;
    }
    console.log('[' + type + '] ' + msg);
  }

  function getAllSelects() {
    var sels = [];
    for (var i = 0; i < SELECTORS.length; i++) {
      var el = document.getElementById(SELECTORS[i]);
      if (el) sels.push(el);
    }
    return sels;
  }

  async function initLLMSwitcher() {
    var selects = getAllSelects();
    if (selects.length === 0) return;

    try {
      var resp = await fetch('/api/settings/llm-provider');
      if (!resp.ok) return;

      var data = await resp.json();
      var active = data.active;
      var has_qwen_key = data.has_qwen_key;
      var has_gemini_key = data.has_gemini_key;
      var locked_by_env = data.locked_by_env;

      selects.forEach(function (sel) {
        sel.value = active;
        sel.dataset.previous = active;

        for (var j = 0; j < sel.options.length; j++) {
          var opt = sel.options[j];
          if (opt.value === 'qwen' && !has_qwen_key) opt.disabled = true;
          if (opt.value === 'gemini' && !has_gemini_key) opt.disabled = true;
        }

        if (locked_by_env) {
          sel.disabled = true;
        } else {
          sel.addEventListener('change', onSwitch);
        }
      });

      // Show lock icons if env locked
      if (locked_by_env) {
        LOCK_IDS.forEach(function (id) {
          var lock = document.getElementById(id);
          if (lock) lock.style.display = 'inline';
        });
      }

      updateStatus(active);
    } catch (e) {
      console.warn('LLM switcher init failed:', e);
    }
  }

  async function onSwitch(ev) {
    var provider = ev.target.value;
    var previous = ev.target.dataset.previous || 'qwen';

    try {
      var resp = await fetch('/api/settings/llm-provider', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ provider: provider }),
      });

      if (!resp.ok) {
        var body = {};
        try { body = await resp.json(); } catch (_) {}
        showToast(body.message || '切换失败: ' + (body.reason || resp.status), 'error');
        syncAll(previous);
        return;
      }

      syncAll(provider);
      var label = provider === 'qwen' ? 'Qwen' : 'Gemini';
      showToast('已切换到 ' + label + '，下次分析生效', 'success');
      updateStatus(provider);
    } catch (e) {
      showToast('切换失败: 网络错误', 'error');
      syncAll(previous);
    }
  }

  function syncAll(provider) {
    getAllSelects().forEach(function (sel) {
      sel.value = provider;
      sel.dataset.previous = provider;
    });
  }

  function updateStatus(provider) {
    var el = document.getElementById(STATUS_ID);
    if (el) {
      var label = provider === 'qwen' ? 'Qwen' : 'Gemini';
      el.textContent = label + ' 在线';
    }
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', initLLMSwitcher);
  } else {
    initLLMSwitcher();
  }
})();
