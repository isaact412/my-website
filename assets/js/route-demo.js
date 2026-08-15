/* =========================================================
   Carolina Care — Interactive Route Demo
   Charleston Medical Center  →  Aiken, SC (demonstration route)
   ========================================================= */
(function () {
  "use strict";

  var svg = document.getElementById("route-svg");
  if (!svg) return;

  var roadPath = document.getElementById("progress-path");
  var vanGroup = document.getElementById("van-group");
  var markerCharleston = document.getElementById("marker-charleston");
  var markerAiken = document.getElementById("marker-aiken");
  var pickupPins = document.getElementById("pickup-pins");
  var labelCharleston = document.getElementById("label-charleston");
  var labelPickup = document.getElementById("label-pickup");
  var labelConnected = document.getElementById("label-connected");

  var btnStart = document.getElementById("btn-start");
  var btnReplay = document.getElementById("btn-replay");
  var btnReturn = document.getElementById("btn-return");

  var statusRoute = document.getElementById("status-route");
  var statusState = document.getElementById("status-state");
  var statusDot = document.getElementById("status-dot");
  var statusPatients = document.getElementById("status-patients");
  var storyText = document.getElementById("story-text");

  var pathLength = roadPath.getTotalLength();
  roadPath.style.strokeDasharray = pathLength;
  roadPath.style.strokeDashoffset = pathLength;

  var DURATION = 6200; // ms for a full one-way traversal
  var rafId = null;
  var isReversed = false;

  function pointAt(t, reversed) {
    var len = reversed ? pathLength * (1 - t) : pathLength * t;
    return roadPath.getPointAtLength(len);
  }

  function setVan(t, reversed) {
    var p = pointAt(t, reversed);
    var lookAheadT = Math.min(Math.max(t + (reversed ? -0.01 : 0.01), 0), 1);
    var p2 = pointAt(lookAheadT, reversed);
    var angle = Math.atan2(p2.y - p.y, p2.x - p.x) * (180 / Math.PI);
    vanGroup.setAttribute("transform", "translate(" + p.x + "," + p.y + ") rotate(" + angle + ")");
  }

  function setProgressLine(t, reversed) {
    // Reveal the line from the direction of travel
    if (!reversed) {
      roadPath.style.strokeDashoffset = pathLength * (1 - t);
    } else {
      roadPath.style.strokeDashoffset = pathLength * t;
    }
  }

  function showLabel(el) {
    if (el) el.classList.add("show");
  }
  function hideLabel(el) {
    if (el) el.classList.remove("show");
  }

  function setStatus(routeText, stateText, live) {
    statusRoute.textContent = routeText;
    statusState.textContent = stateText;
    statusDot.classList.toggle("live", !!live);
  }

  function setStory(text) {
    storyText.style.opacity = 0;
    window.setTimeout(function () {
      storyText.textContent = text;
      storyText.style.opacity = 1;
    }, 180);
  }

  function setButtons(state) {
    // state: 'idle' | 'running' | 'finished'
    if (state === "idle") {
      btnStart.style.display = "";
      btnReplay.style.display = "none";
      btnReturn.style.display = "none";
      btnStart.disabled = false;
    } else if (state === "running") {
      btnStart.style.display = "none";
      btnReplay.style.display = "none";
      btnReturn.style.display = "none";
    } else if (state === "finished-forward") {
      btnStart.style.display = "none";
      btnReplay.style.display = "";
      btnReturn.style.display = "";
    } else if (state === "finished-return") {
      btnStart.style.display = "none";
      btnReplay.style.display = "";
      btnReturn.style.display = "none";
    }
  }

  function resetScene(reversed) {
    if (rafId) cancelAnimationFrame(rafId);
    hideLabel(labelCharleston);
    hideLabel(labelPickup);
    hideLabel(labelConnected);
    pickupPins.classList.remove("show");
    markerCharleston.classList.remove("active");
    markerAiken.classList.remove("active");
    setVan(reversed ? 1 : 0, false);
    roadPath.style.strokeDashoffset = pathLength;
  }

  function animate(reversed, onDone) {
    var start = null;
    isReversed = reversed;

    function frame(ts) {
      if (start === null) start = ts;
      var elapsed = ts - start;
      var t = Math.min(elapsed / DURATION, 1);
      var easedT = t < 0.5 ? 2 * t * t : -1 + (4 - 2 * t) * t; // ease-in-out

      setVan(easedT, reversed);
      setProgressLine(easedT, reversed);

      // Story / stage triggers
      if (!reversed) {
        if (t < 0.06) {
          markerCharleston.classList.add("active");
          showLabel(labelCharleston);
          setStatus("Charleston → Aiken", "Charleston Hub", true);
          setStory("A hospital identifies patients who need transportation support.");
        } else if (t >= 0.06 && t < 0.55) {
          hideLabel(labelCharleston);
          setStatus("Charleston → Aiken", "En Route", true);
          if (t < 0.08 || storyText.dataset.stage !== "road") {
            storyText.dataset.stage = "road";
            setStory("Carolina Care coordinates shared routes to make long-distance transportation more efficient.");
          }
        } else if (t >= 0.55 && t < 0.9) {
          if (storyText.dataset.stage !== "pickup") {
            storyText.dataset.stage = "pickup";
            pickupPins.classList.add("show");
            showLabel(labelPickup);
            setStatus("Charleston → Aiken", "Patient Pickup", true);
            setStory("Patients are picked up near their communities.");
          }
        } else if (t >= 0.9) {
          if (storyText.dataset.stage !== "arrive") {
            storyText.dataset.stage = "arrive";
            markerAiken.classList.add("active");
            hideLabel(labelPickup);
            setStatus("Charleston → Aiken", "Arriving in Aiken", true);
          }
        }
      } else {
        if (t < 0.08) {
          setStatus("Aiken → Charleston", "Departing Aiken", true);
        } else if (t >= 0.08 && t < 0.85) {
          if (storyText.dataset.stage !== "return-road") {
            storyText.dataset.stage = "return-road";
            setStory("Patients are connected with advanced hospital care without having to solve the transportation barrier alone.");
          }
          setStatus("Aiken → Charleston", "Returning", true);
        } else {
          setStatus("Aiken → Charleston", "Arriving in Charleston", true);
        }
      }

      if (t < 1) {
        rafId = requestAnimationFrame(frame);
      } else {
        storyText.dataset.stage = "";
        onDone();
      }
    }
    rafId = requestAnimationFrame(frame);
  }

  function startRoute() {
    resetScene(false);
    setButtons("running");
    statusPatients.textContent = "3";
    setStatus("Charleston → Aiken", "Preparing Route", false);
    setStory("A hospital identifies patients who need transportation support.");

    window.setTimeout(function () {
      animate(false, function () {
        markerAiken.classList.add("active");
        showLabel(labelConnected);
        setStatus("Charleston → Aiken", "Patients Connected to Care", true);
        setStory("Patients arrive at Aiken and are connected to the specialty care their hospital referred them for.");
        setButtons("finished-forward");
      });
    }, 500);
  }

  function replayRoute() {
    resetScene(false);
    startRoute();
  }

  function returnRoute() {
    hideLabel(labelConnected);
    markerAiken.classList.remove("active");
    setButtons("running");
    setStory("The van begins its return trip toward Charleston Medical Center.");

    animate(true, function () {
      markerCharleston.classList.add("active");
      showLabel(labelCharleston);
      setStatus("Aiken → Charleston", "Back at Charleston Hub", false);
      setStory("Carolina Care Van 01 is back at Charleston Medical Center, ready for its next scheduled route.");
      setButtons("finished-return");
    });
  }

  btnStart.addEventListener("click", startRoute);
  btnReplay.addEventListener("click", replayRoute);
  btnReturn.addEventListener("click", returnRoute);

  // initial idle state
  resetScene(false);
  setButtons("idle");
  setStatus("Charleston → Aiken", "Ready", false);
  statusPatients.textContent = "—";
})();
