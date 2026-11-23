// Interface text in English and Simplified Chinese, from i18n/<language>.json.
"use strict";

window.I18n = (() => {
  const LANGUAGES = ["en", "zh-CN"];
  const STORAGE_KEY = "lrg.language";
  const dictionaries = {};
  let language = "en";

  function preferred() {
    try {
      const saved = localStorage.getItem(STORAGE_KEY);
      if (LANGUAGES.includes(saved)) return saved;
    } catch (error) { /* storage may be blocked */ }
    return (navigator.language || "").toLowerCase().startsWith("zh") ? "zh-CN" : "en";
  }

  async function load(name) {
    if (!dictionaries[name]) {
      const response = await fetch(`i18n/${name}.json`);
      dictionaries[name] = await response.json();
    }
    return dictionaries[name];
  }

  function lookup(dictionary, key) {
    return key.split(".").reduce((value, part) => (value && typeof value === "object" ? value[part] : undefined), dictionary);
  }

  /** The text for key, with {name} placeholders filled from vars. */
  function t(key, vars) {
    let text = lookup(dictionaries[language], key);
    if (typeof text !== "string") text = lookup(dictionaries.en, key);
    if (typeof text !== "string") return key;
    return vars ? text.replace(/\{(\w+)\}/g, (match, name) => (name in vars ? String(vars[name]) : match)) : text;
  }

  /** Whether a key exists (to fall back to names that come from the server). */
  function has(key) {
    return typeof lookup(dictionaries[language], key) === "string";
  }

  function apply(root = document) {
    root.querySelectorAll("[data-i18n]").forEach((element) => { element.textContent = t(element.dataset.i18n); });
    root.querySelectorAll("[data-i18n-placeholder]").forEach((element) => { element.placeholder = t(element.dataset.i18nPlaceholder); });
    document.documentElement.lang = language;
    document.title = t("app.title");
  }

  async function use(name) {
    language = LANGUAGES.includes(name) ? name : "en";
    await Promise.all([load("en"), load(language)]);
    try { localStorage.setItem(STORAGE_KEY, language); } catch (error) { /* ignore */ }
    apply();
    document.dispatchEvent(new CustomEvent("languagechange"));
  }

  return {
    init: () => use(preferred()),
    use,
    t,
    has,
    apply,
    get language() { return language; },
    other: () => (language === "en" ? "zh-CN" : "en"),
  };
})();
