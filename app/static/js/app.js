(function () {
  "use strict";

  document.addEventListener("DOMContentLoaded", function () {
    // Мобильное меню
    var toggle = document.querySelector("[data-nav-toggle]");
    var nav = document.getElementById("site-nav");
    if (toggle && nav) {
      toggle.addEventListener("click", function () {
        var open = nav.classList.toggle("is-open");
        toggle.setAttribute("aria-expanded", open ? "true" : "false");
      });
    }

    // Закрытие flash-сообщений
    document.querySelectorAll("[data-flash-close]").forEach(function (button) {
      button.addEventListener("click", function () {
        var flash = button.closest("[data-flash]");
        if (flash) {
          flash.remove();
        }
      });
    });

    // Подтверждение опасных действий
    document.querySelectorAll("form[data-confirm]").forEach(function (form) {
      form.addEventListener("submit", function (event) {
        if (!window.confirm(form.getAttribute("data-confirm"))) {
          event.preventDefault();
        }
      });
    });

    // Отображение имени выбранного файла
    document.querySelectorAll("input[type=file][data-file-input]").forEach(function (input) {
      var label = document.querySelector(input.getAttribute("data-file-input"));
      if (!label) {
        return;
      }
      input.addEventListener("change", function () {
        label.textContent = input.files && input.files.length
          ? input.files[0].name
          : "Файл не выбран";
      });
    });

    // Автоматическое скрытие уведомлений
    document.querySelectorAll("[data-flash]").forEach(function (flash) {
      window.setTimeout(function () {
        flash.style.transition = "opacity .4s ease";
        flash.style.opacity = "0";
        window.setTimeout(function () { flash.remove(); }, 420);
      }, 6000);
    });
  });
})();