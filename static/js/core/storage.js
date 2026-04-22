/* core/storage.js — обёртки над localStorage для FreeApi.
   Шаг 0.5.6: вынесены прямые вызовы localStorage.{get,set,remove}Item
   из static/index.html.

   Все функции безопасны: при недоступности localStorage (приватный режим,
   квота, ошибки сериализации) возвращают дефолт / тихо проглатывают.

   Ключи оставлены AS IS (не переименовываются), чтобы не сломать данные
   у существующих пользователей:
     'freeapi_review_draft'  — черновик отзыва (text)
     'freeapi.chat.<keyId>'  — история чата по ключу (JSON-массив)

   Экспорт ESM + window.lsGet / window.lsSet / window.lsDel — чтобы
   inline-classic-handlers (oninput=…) и onclick=… могли пользоваться
   обёртками после загрузки модуля. */

export function lsGet(key, fallback){
  try {
    var raw = window.localStorage.getItem(key);
    return raw == null ? (fallback == null ? '' : fallback) : raw;
  } catch (_) {
    return (fallback == null ? '' : fallback);
  }
}

export function lsSet(key, value){
  try {
    window.localStorage.setItem(key, String(value == null ? '' : value));
    return true;
  } catch (_) {
    return false;
  }
}

export function lsDel(key){
  try {
    window.localStorage.removeItem(key);
    return true;
  } catch (_) {
    return false;
  }
}

window.lsGet = lsGet;
window.lsSet = lsSet;
window.lsDel = lsDel;
