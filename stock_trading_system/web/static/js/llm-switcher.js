/**
 * LLM Provider Switcher — Nav sidebar dropdown.
 *
 * On load: fetches current provider state from GET /api/settings/llm-provider.
 * On change: POST to switch, with toast feedback and rollback on error.
 */

(function () {
  'use strict';

  const SEL_ID = 'llm-provider-select';
  const LOCK_ID = 'llm-lock-icon';
  const STATUS_ID = 'bot-status';

  function showToast(msg, type) {
    // Reuse existing toast helper if available (app.js defines one)
    if (typeof window.showToast === 'function') {
      window.showToast(msg, type);
      return;
    }
    // Minimal fallback
    console.log(`[${type}] ${msg}`);
  }

  async function initLLMSwitcher() {
    const sel = document.getElementById(SEL_ID);
    if (!sel) return;

    try {
      const resp = await fetch('/api/settings/llm-provider');
      if (!resp.ok) return;

      const { active, has_qwen_key, has_gemini_key, locked_by_env } = await resp.json();

      sel.value = active;
      sel.dataset.previous = active;

      // Disable options for missing keys
      for (const opt of sel.options) {
        if (opt.value === 'qwen' && !has_qwen_key) opt.disabled = true;
        if (opt.value === 'gemini' && !has_gemini_key) opt.disabled = true;
      }

      // Env lock
      if (locked_by_env) {
        sel.disabled = true;
        const lock = document.getElementById(LOCK_ID);
        if (lock) lock.style.display = 'inline';
        return;
      }

      sel.addEventListener('change', onSwitch);

      // Update status text
      updateStatus(active);
    } catch (e) {
      console.warn('LLM switcher init failed:', e);
    }
  }

  async function onSwitch(ev) {
    const provider = ev.target.value;
    const previous = ev.target.dataset.previous || 'qwen';

    try {
      const resp = await fetch('/api/settings/llm-provider', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ provider }),
      });

      if (!resp.ok) {
        const body = await resp.json().catch(() => ({}));
        showToast(body.message || `切换失败: ${body.reason || resp.status}`, 'error');
        ev.target.value = previous;
        return;
      }

      ev.target.dataset.previous = provider;
      const label = provider === 'qwen' ? 'Qwen' : 'Gemini';
      showToast(`已切换到 ${label}，下次分析生效`, 'success');
      updateStatus(provider);
    } catch (e) {
      showToast('切换失败: 网络错误', 'error');
      ev.target.value = previous;
    }
  }

  function updateStatus(provider) {
    const el = document.getElementById(STATUS_ID);
    if (el) {
      const label = provider === 'qwen' ? 'Qwen' : 'Gemini';
      el.textContent = `${label} 在线`;
    }
  }

  // Initialize after DOM ready
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', initLLMSwitcher);
  } else {
    initLLMSwitcher();
  }
})();
