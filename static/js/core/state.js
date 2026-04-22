/* core/state.js — глобальное состояние SPA.
   Шаг 0.5.2: пустая структура. Вынос реальных переменных (user, accountState,
   allModels, allKeys, currentKeyId и т.п.) запланирован отдельным подшагом
   ПОСЛЕ распиливания IIFE в static/index.html (см. план шага 0.5.5+). */

export const state = {};

/* Прокидываем как глобал, чтобы переходные window.state.* читались
   и из inline-кода, и из других модулей. */
if (typeof window !== 'undefined') {
  window.state = state;
}
