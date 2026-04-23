/* views/models.js — модуль раздела «Модели» (шаг 0.5d).
   Перенесён из inline-блока static/index.html (~1626..1685).

   ВНЕШНИЕ ЗАВИСИМОСТИ (из inline-скрипта, через window.*):
     - window.api          — XHR-обёртка (core/api.js)
     - window.q            — getElementById helper (inline)
     - window.esc          — html-escape helper (inline)
     - window.allModels    — массив моделей (inline state, ещё не вынесен)

   Все публичные имена дублируются на window.* для совместимости с inline
   onclick-хендлерами и view-роутером. */

(function(){
  function _api(){ return window.api; }
  function _q(id){ return window.q ? window.q(id) : document.getElementById(id); }
  function _esc(s){ return window.esc ? window.esc(s) : String(s == null ? '' : s); }

  var modelsLoaded = false;

  function loadModels(){
    if (modelsLoaded) return Promise.resolve();
    return _api()('/api/models').then(function(d){
      window.allModels = d.models || [];
      modelsLoaded = true;
      renderLandingModels(window.allModels);
      renderFullModels();
    }).catch(function(){});
  }

  function renderLandingModels(models){
    var g = _q('landModelsGrid');
    if (!g) return;
    g.innerHTML = '';
    (models || []).slice(0, 6).forEach(function(m){ g.appendChild(modelCard(m)); });
  }

  function renderFullModels(){
    if (!modelsLoaded) return;
    filterModels(window._modelsFilter || 'all', document.querySelector('.filter-btn.active') || document.querySelector('.filter-btn'));
  }

  function filterModels(type, btn){
    window._modelsFilter = type;
    window._modelsSearch = '';
    var si = _q('modelsSearch'); if (si) si.value = '';
    document.querySelectorAll('.filter-btn').forEach(function(b){ b.classList.remove('active'); });
    if (btn) btn.classList.add('active');
    var allM = window.allModels || [];
    var list = type === 'all' ? allM : allM.filter(function(m){ return m.displayName && m.displayName.toLowerCase().indexOf(type) > -1; });
    var g = _q('fullModelsGrid');
    if (!g) return;
    g.innerHTML = '';
    list.forEach(function(m){ g.appendChild(modelCard(m)); });
  }

  /* F-08: Search models */
  function searchModels(qStr){
    window._modelsSearch = (qStr || '').toLowerCase();
    var allM = window.allModels || [];
    var src = (window._modelsFilter && window._modelsFilter !== 'all')
      ? allM.filter(function(m){ return m.displayName && m.displayName.toLowerCase().indexOf(window._modelsFilter) > -1; })
      : allM;
    var list = (qStr || '').trim()
      ? src.filter(function(m){ return m.displayName && m.displayName.toLowerCase().indexOf((qStr || '').toLowerCase()) > -1; })
      : src;
    var g = _q('fullModelsGrid');
    if (!g) return;
    g.innerHTML = '';
    if (!list.length) {
      g.innerHTML = '<div style="grid-column:1/-1;text-align:center;padding:32px;color:#666;font-size:13px">Нет моделей по запросу</div>';
      return;
    }
    list.forEach(function(m){ g.appendChild(modelCard(m)); });
  }

  function modelCard(m){
    var div = document.createElement('div');
    div.className = 'model-card';
    var badge = m.isDefault ? '<span class="pill pill-white">Default</span>' : (m.isPopular ? '<span class="pill pill-dim">Popular</span>' : '');
    div.innerHTML = '<div class="model-card-row"><h4>' + _esc(m.displayName) + '</h4>' + badge + '</div>' +
      '<div class="model-meta">' +
        '<span><svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M2 3h6a4 4 0 0 1 4 4v14a3 3 0 0 0-3-3H2z"/><path d="M22 3h-6a4 4 0 0 0-4 4v14a3 3 0 0 1 3-3h7z"/></svg>' + m.contextK + 'K</span>' +
        (m.supportsVision ? '<span><svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z"/><circle cx="12" cy="12" r="3"/></svg>Vision</span>' : '') +
        '<span><svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="22 12 18 12 15 21 9 3 6 12 2 12"/></svg>' + (m.totalRequests || 0).toLocaleString('ru-RU') + '</span>' +
        (m.avgResponseMs ? '<span><svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"/><polyline points="12 6 12 12 16 14"/></svg>' + m.avgResponseMs + ' мс</span>' : '') +
      '</div>';
    return div;
  }

  /* ── Экспорт в window.* ── */
  window.loadModels          = loadModels;
  window.renderLandingModels = renderLandingModels;
  window.renderFullModels    = renderFullModels;
  window.filterModels        = filterModels;
  window.searchModels        = searchModels;
  window.modelCard           = modelCard;
})();
