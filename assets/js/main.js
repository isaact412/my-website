/* =========================================================
   Carolina Care — Shared Site Behavior
   ========================================================= */
(function () {
  "use strict";

  /* ---------- Header scroll shadow ---------- */
  var header = document.querySelector(".site-header");
  if (header) {
    var onScroll = function () {
      header.classList.toggle("scrolled", window.scrollY > 8);
    };
    onScroll();
    window.addEventListener("scroll", onScroll, { passive: true });
  }

  /* ---------- Mobile menu ---------- */
  var hamburger = document.getElementById("hamburger");
  var mobileMenu = document.getElementById("mobile-menu");
  function closeMenu() {
    if (!mobileMenu) return;
    mobileMenu.classList.remove("open");
    hamburger.setAttribute("aria-expanded", "false");
    document.body.style.overflow = "";
  }
  function openMenu() {
    mobileMenu.classList.add("open");
    hamburger.setAttribute("aria-expanded", "true");
    document.body.style.overflow = "hidden";
  }
  if (hamburger && mobileMenu) {
    hamburger.addEventListener("click", function () {
      var isOpen = mobileMenu.classList.contains("open");
      if (isOpen) { closeMenu(); } else { openMenu(); }
    });
    mobileMenu.querySelectorAll("a").forEach(function (a) {
      a.addEventListener("click", closeMenu);
    });
    document.addEventListener("keydown", function (e) {
      if (e.key === "Escape") closeMenu();
    });
  }

  /* ---------- Active nav highlighting ---------- */
  var currentPage = (window.location.pathname.split("/").pop() || "index.html").toLowerCase();
  if (currentPage === "") currentPage = "index.html";
  document.querySelectorAll(".main-nav a, .mobile-menu a").forEach(function (a) {
    var href = (a.getAttribute("href") || "").split("#")[0].toLowerCase();
    if (href === currentPage) {
      a.setAttribute("aria-current", "page");
    }
  });

  /* ---------- Footer year ---------- */
  document.querySelectorAll("[data-year]").forEach(function (el) {
    el.textContent = new Date().getFullYear();
  });

  /* ---------- Reveal on scroll ---------- */
  var revealEls = document.querySelectorAll(".reveal");
  if ("IntersectionObserver" in window && revealEls.length) {
    var io = new IntersectionObserver(
      function (entries) {
        entries.forEach(function (entry) {
          if (entry.isIntersecting) {
            entry.target.classList.add("in-view");
            io.unobserve(entry.target);
          }
        });
      },
      { threshold: 0.12, rootMargin: "0px 0px -40px 0px" }
    );
    revealEls.forEach(function (el) { io.observe(el); });
  } else {
    revealEls.forEach(function (el) { el.classList.add("in-view"); });
  }

  /* ---------- Phone auto-format ---------- */
  document.querySelectorAll('input[type="tel"]').forEach(function (input) {
    input.addEventListener("input", function () {
      var digits = input.value.replace(/\D/g, "").slice(0, 10);
      var formatted = digits;
      if (digits.length > 6) {
        formatted = "(" + digits.slice(0, 3) + ") " + digits.slice(3, 6) + "-" + digits.slice(6);
      } else if (digits.length > 3) {
        formatted = "(" + digits.slice(0, 3) + ") " + digits.slice(3);
      } else if (digits.length > 0) {
        formatted = digits;
      }
      input.value = formatted;
    });
  });

  /* ---------- Generic form handling ---------- */
  var EMAIL_RE = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
  var PHONE_DIGITS_RE = /\d{10}/;

  function showError(field, message) {
    field.classList.add("error");
    var msg = field.querySelector(".error-msg");
    if (msg) msg.textContent = message;
  }
  function clearError(field) {
    field.classList.remove("error");
  }

  function validateForm(form) {
    var valid = true;
    var fields = form.querySelectorAll("[data-field]");
    fields.forEach(function (field) {
      var input = field.querySelector("input, select, textarea");
      if (!input) return;
      clearError(field);

      var required = input.hasAttribute("required");
      var value = input.type === "checkbox" ? input.checked : input.value.trim();

      if (required && (value === "" || value === false)) {
        showError(field, field.dataset.errorRequired || "This field is required.");
        valid = false;
        return;
      }
      if (input.type === "email" && value && !EMAIL_RE.test(value)) {
        showError(field, "Please enter a valid email address.");
        valid = false;
        return;
      }
      if (input.type === "tel" && value) {
        var digits = value.replace(/\D/g, "");
        if (digits.length !== 10) {
          showError(field, "Please enter a valid 10-digit phone number.");
          valid = false;
          return;
        }
      }
    });
    return valid;
  }

  function collectData(form) {
    var data = {};
    form.querySelectorAll("[name]").forEach(function (input) {
      if (input.type === "checkbox") {
        data[input.name] = input.checked;
      } else if (input.type === "radio") {
        if (input.checked) data[input.name] = input.value;
      } else {
        data[input.name] = input.value;
      }
    });
    data.submitted_at = new Date().toISOString();
    return data;
  }

  function saveSubmission(storageKey, data) {
    try {
      var existing = JSON.parse(localStorage.getItem(storageKey) || "[]");
      existing.push(data);
      localStorage.setItem(storageKey, JSON.stringify(existing));
    } catch (e) {
      /* localStorage unavailable — safe to ignore for this demo */
    }
  }

  document.querySelectorAll("form[data-carolina-form]").forEach(function (form) {
    var storageKey = form.dataset.carolinaForm;
    var submitBtn = form.querySelector('button[type="submit"]');
    var successEl = document.getElementById(form.dataset.successTarget);

    form.addEventListener("submit", function (e) {
      e.preventDefault();
      var ok = validateForm(form);
      if (!ok) {
        var firstError = form.querySelector(".field.error input, .field.error select, .field.error textarea");
        if (firstError) firstError.focus();
        return;
      }

      if (submitBtn) submitBtn.classList.add("loading");
      if (submitBtn) submitBtn.disabled = true;

      window.setTimeout(function () {
        var data = collectData(form);
        saveSubmission(storageKey, data);

        if (submitBtn) { submitBtn.classList.remove("loading"); submitBtn.disabled = false; }
        form.classList.add("submitted-hide");
        if (successEl) {
          successEl.classList.add("show");
          successEl.setAttribute("tabindex", "-1");
          successEl.focus();
          successEl.scrollIntoView({ behavior: "smooth", block: "center" });
        }
      }, 700);
    });

    // clear individual field errors as user corrects them
    form.querySelectorAll("[data-field] input, [data-field] select, [data-field] textarea").forEach(function (input) {
      input.addEventListener("input", function () {
        var field = input.closest("[data-field]");
        if (field) clearError(field);
      });
      input.addEventListener("change", function () {
        var field = input.closest("[data-field]");
        if (field) clearError(field);
      });
    });
  });

  /* reset-and-submit-another buttons */
  document.querySelectorAll("[data-reset-form]").forEach(function (btn) {
    btn.addEventListener("click", function () {
      var formId = btn.dataset.resetForm;
      var form = document.getElementById(formId);
      var successEl = document.getElementById(form.dataset.successTarget);
      form.reset();
      form.classList.remove("submitted-hide");
      if (successEl) successEl.classList.remove("show");
      form.scrollIntoView({ behavior: "smooth", block: "start" });
    });
  });

  /* ---------- Affordability calculator ---------- */
  var calcForm = document.getElementById("calc-form");
  if (calcForm) {
    var incomeInput = document.getElementById("calc-income");
    var sizeInput = document.getElementById("calc-size");
    var distanceInput = document.getElementById("calc-distance");
    var amountEl = document.getElementById("calc-amount");
    var labelEl = document.getElementById("calc-label");
    var descEl = document.getElementById("calc-desc");

    function computeEstimate() {
      var income = parseFloat(incomeInput.value) || 0;
      var size = parseInt(sizeInput.value, 10) || 1;
      var distance = parseFloat(distanceInput.value) || 0;

      // Illustrative poverty-guideline-style baseline (example only, not official figures)
      var baseline = 15060 + (size - 1) * 5380;
      var ratio = income > 0 ? income / baseline : 0;
      var longTrip = distance >= 75;

      var tier;
      if (income <= 0 || ratio <= 1.5) {
        tier = { label: "High financial need", amount: "$0", desc: "Based on the details provided, this trip could qualify for fully subsidized transportation." };
      } else if (ratio <= 3) {
        tier = longTrip
          ? { label: "Moderate financial need", amount: "$15–$25", desc: "This trip could qualify for a reduced, income-based fare, with a modest adjustment for the longer distance." }
          : { label: "Moderate financial need", amount: "$10–$25", desc: "This trip could qualify for a reduced, income-based fare." };
      } else {
        tier = longTrip
          ? { label: "Higher income", amount: "$35–$50+", desc: "A standard income-based contribution would likely apply, adjusted for the longer trip distance." }
          : { label: "Higher income", amount: "$25–$50+", desc: "A standard income-based contribution would likely apply." };
      }

      labelEl.textContent = tier.label;
      amountEl.textContent = tier.amount;
      descEl.textContent = tier.desc;
    }

    ["input", "change"].forEach(function (evt) {
      calcForm.addEventListener(evt, function (e) {
        if (e.target.matches("input, select")) computeEstimate();
      });
    });
    computeEstimate();
  }
})();
