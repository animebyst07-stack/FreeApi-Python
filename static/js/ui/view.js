/* ui/view.js — роутер view'ов SPA.
   Шаг 0.5.11: вынесены `window.goView` и helper `updateSidebarActive`
   из inline-скрипта static/index.html.

   Все view-init функции (loadDashboard, initChatView, loadAdmin, loadReviews,
   loadDocsModels, initSupportView, renderFullModels, setDocsSection,
   initReviewsView, loadNotifications) пока остаются inline (это top-level
   classic-script `function NAME(){}` ⇒ автоматически window.NAME).
   Зовём их через window.* — после распиливания views/* останется без правок. */

const VIEWS = ['landing','dashboard','history','models','logcodes','chat','docs','admin','support','reviews','notifications','community'];
const SB_MAP = {
  landing:    'sbLanding',
  models:     'sbModels',
  docs:       'sbDocs',
  dashboard:  'sbDashboard',
  chat:       'sbChat',
  support:    'sbSupport',
  admin:      'sbAdmin',
  reviews:    'sbReviews',
  community:  'sbCommunity'
};

export function updateSidebarActive(v){
  document.querySelectorAll('.sb-item').forEach(function(el){ el.classList.remove('active'); });
  var id = SB_MAP[v];
  if (id) {
    var el = document.getElementById(id);
    if (el) el.classList.add('active');
  }
}

export function goView(v){
  if (v === 'logcodes') {
    goView('docs');
    setTimeout(function(){
      if (typeof window.setDocsSection === 'function') {
        window.setDocsSection('logcodes', document.getElementById('docsNavLogcodes'));
      }
    }, 50);
    return;
  }

  if (window.innerWidth < 900 && typeof window.closeSidebar === 'function') {
    window.closeSidebar();
  }

  VIEWS.forEach(function(n){
    var el = document.getElementById('view-' + n);
    if (el) el.classList.remove('active');
  });
  var target = document.getElementById('view-' + v);
  if (target) target.classList.add('active');

  updateSidebarActive(v);

  var noScroll = (v === 'chat' || v === 'support');
  document.body.classList.toggle('view-no-scroll', noScroll);
  if (!noScroll) window.scrollTo(0, 0);

  if (v === 'models'        && typeof window.renderFullModels === 'function') window.renderFullModels();
  if (v === 'dashboard'     && typeof window.loadDashboard    === 'function') window.loadDashboard();
  if (v === 'chat'          && typeof window.initChatView     === 'function') window.initChatView();
  if (v === 'admin'         && typeof window.loadAdmin        === 'function') window.loadAdmin();
  if (v === 'landing'       && typeof window.loadReviews      === 'function') window.loadReviews();
  if (v === 'docs'          && typeof window.loadDocsModels   === 'function') window.loadDocsModels();
  if (v === 'support'       && typeof window.initSupportView  === 'function') window.initSupportView();
  if (v === 'reviews'       && typeof window.initReviewsView  === 'function') window.initReviewsView();
  if (v === 'notifications' && typeof window.loadNotifications === 'function') window.loadNotifications();
  if (v === 'notifications' && typeof window.cmSyncNotifMuteToggle === 'function') window.cmSyncNotifMuteToggle();
  if (v === 'community'     && typeof window.initCommunityView === 'function') window.initCommunityView();
}

window.goView = goView;
window.updateSidebarActive = updateSidebarActive;
