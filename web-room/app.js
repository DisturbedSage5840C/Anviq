/**
 * Web room: hold to talk, one turn to POST /web/turn, reply shown and played.
 * Nothing is persisted: a recording lives in Blob memory only until the turn is sent, and
 * the transcript lives only in this page. A refresh forgets everything, on purpose.
 */
"use strict";

(() => {
  // The API base can be set per deployment: config.js holds a default, a ?api= query overrides it.
  const params = new URLSearchParams(location.search);
  const apiBase = (params.get("api") || window.ANVIQ_API_BASE || "").replace(/\/+$/, "");

  // The same audio shapes the API allows, most-preferred first (Chrome picks webm/opus, Safari mp4).
  const ALLOWED_MIMES = [
    "audio/webm;codecs=opus",
    "audio/webm",
    "audio/ogg;codecs=opus",
    "audio/ogg",
    "audio/mp4",
    "audio/wav",
    "audio/x-wav",
  ];
  const CODE_SHAPE = /^[A-Za-z0-9_-]{22}$/;

  // Closing words from the rehearsal flow: the session ends when the teacher has had enough,
  // and the page is never shown a machine declaration of itself as a robot.
  const STOP_WORDS = ["बस", "bas", "stop", "बंद", "enough"];

  const els = {
    gate: document.getElementById("gate"),
    gateError: document.getElementById("gate-error"),
    code: document.getElementById("code"),
    start: document.getElementById("start"),
    session: document.getElementById("session"),
    status: document.getElementById("turn-status"),
    reset: document.getElementById("reset"),
    transcript: document.getElementById("transcript"),
    record: document.getElementById("record"),
    recordLabel: document.getElementById("record-label"),
    text: document.getElementById("text"),
    sendText: document.getElementById("send-text"),
  };

  let code = "";
  let mediaRecorder = null;
  let recorderMime = "";
  let chunks = [];
  let holdTimer = null;
  let holding = false;
  let busy = false;

  function say(node, message) {
    node.textContent = message;
    node.hidden = false;
  }

  function addBubble(role, text) {
    const li = document.createElement("li");
    li.className = `bubble ${role}`;
    li.textContent = text;
    els.transcript.append(li);
    li.scrollIntoView({ block: "nearest", behavior: "smooth" });
    return li;
  }

  function setStatus(kind, message) {
    els.status.className = kind === "ok" ? "pill" : `pill ${kind}`;
    els.status.textContent = message;
  }

  function resetError() {
    els.gateError.hidden = true;
  }

  function pickMime() {
    if (!window.MediaRecorder) return "";
    for (const mime of ALLOWED_MIMES) {
      if (MediaRecorder.isTypeSupported(mime)) return mime;
    }
    return "";
  }

  async function openRecorder() {
    const stream = await navigator.mediaDevices.getUserMedia({
      audio: { channelCount: 1, echoCancellation: true, noiseSuppression: true },
    });
    recorderMime = pickMime();
    mediaRecorder = recorderMime
      ? new MediaRecorder(stream, { mimeType: recorderMime })
      : new MediaRecorder(stream);
    chunks = [];
    mediaRecorder.addEventListener("dataavailable", (event) => {
      if (event.data && event.data.size > 0) chunks.push(event.data);
    });
    mediaRecorder.start(250);
  }

  function closeRecorder() {
    return new Promise((resolve) => {
      const recorder = mediaRecorder;
      if (!recorder) return resolve();
      recorder.addEventListener("stop", () => {
        recorder.stream.getTracks().forEach((track) => track.stop());
        resolve();
      }, { once: true });
      if (recorder.state !== "inactive") recorder.stop();
      else recorder.stream.getTracks().forEach((track) => track.stop());
    });
  }

  async function postTurn(body, contentType) {
    const response = await fetch(`${apiBase}/web/turn`, {
      method: "POST",
      headers: { "Content-Type": contentType, "X-Demo-Code": code },
      body,
    });
    const reply = await response.json().catch(() => ({}));
    if (!response.ok) {
      const detail = reply && reply.detail ? reply.detail : "";
      throw new Error(friendly(response.status, detail));
    }
    return reply;
  }

  function friendly(status, detail) {
    if (status === 401) return detail || "यह कोड काम नहीं कर रहा। टीम से नया कोड लीजिए।";
    if (status === 413) return "यह बहुत लंबा है। थोड़ा छोटा कीजिए।";
    if (status === 415) return "यह रिकॉर्डिंग का प्रकार नहीं चलेगा। फिर से कोशिश कीजिए, या टाइप कीजिए।";
    if (status === 429) return "बहुत ज़्यादा बार पूछा। थोड़ी देर में फिर कीजिए।";
    return detail || "कुछ गड़बड़ हुई। एक बार फिर कोशिश कीजिए।";
  }

  function showReply(reply) {
    const li = addBubble("anviq", reply.text);
    const bytes = base64ToBytes(reply.audio_base64);
    if (bytes) {
      const url = URL.createObjectURL(new Blob([bytes], { type: reply.audio_mime || "audio/wav" }));
      const play = document.createElement("button");
      play.type = "button";
      play.textContent = "▶ फिर से सुनिए";
      play.addEventListener("click", () => {
        const audio = new Audio(url);
        audio.play().catch(() => {
          play.textContent = "❗ ब्राउज़र ने आवाज़ रोकी — फिर दबाइए";
        });
      });
      li.append(play);
    }
  }

  function base64ToBytes(encoded) {
    if (!encoded) return null;
    const binary = atob(encoded);
    const bytes = new Uint8Array(binary.length);
    for (let i = 0; i < binary.length; i++) bytes[i] = binary.charCodeAt(i);
    return bytes;
  }

  function ended(text) {
    return STOP_WORDS.includes(text.trim());
  }

  async function submitRecording() {
    if (busy) return;
    try {
      await closeRecorder();
    } catch (_) {
      /* the recorder already stopped itself */
    }
    const blob = new Blob(chunks, { type: recorderMime || "audio/webm" });
    if (blob.size < 2000) {
      setStatus("ok", "तैयार");
      addBubble("anviq", "बहुत छोटी रिकॉर्डिंग — थोड़ी देर दबाकर बोलिए।");
      return;
    }
    busy = true;
    setStatus("busy", "भेजा जा रहा है…");
    try {
      const reply = await postTurn(blob, blob.type);
      showReply(reply);
      setStatus("ok", "तैयार");
      if (ended(reply.text)) endSession();
    } catch (error) {
      setStatus("error", error.message);
      addBubble("anviq", error.message);
    } finally {
      busy = false;
    }
  }

  function endSession() {
    code = "";
    mediaRecorder = null;
    chunks = [];
    els.transcript.replaceChildren();
    els.session.hidden = true;
    els.gate.hidden = false;
    els.recordLabel.textContent = "दबाकर बोलिए";
    setStatus("ok", "तैयार");
  }

  els.start.addEventListener("click", () => {
    resetError();
    const entered = els.code.value.trim();
    if (!CODE_SHAPE.test(entered)) {
      say(els.gateError, "कोड 22 अक्षरों का होता है। सही कोड टीम से लीजिए।");
      return;
    }
    code = entered;
    els.gate.hidden = true;
    els.session.hidden = false;
    setStatus("ok", "तैयार");
    addBubble("anviq", "नमस्ते! आज के अभ्यास या कोई सवाल, जो कहना चाहें कहिए। रुकना हो तो 'बस' कहिए।");
  });

  els.code.addEventListener("keydown", (event) => {
    if (event.key === "Enter") els.start.click();
  });

  els.reset.addEventListener("click", endSession);

  const HOLD_DELAY_MS = 350;
  els.record.addEventListener("pointerdown", (event) => {
    if (busy || holding) return;
    event.preventDefault();
    holding = true;
    els.record.setPointerCapture(event.pointerId);
    els.record.classList.add("holding");
    els.recordLabel.textContent = "तैयार…";
    holdTimer = setTimeout(() => {
      openRecorder()
        .then(() => {
          els.record.classList.add("recording");
          els.recordLabel.textContent = "रिकॉर्ड हो रहा है — छोड़ें";
        })
        .catch(() => {
          holding = false;
          endHoldVisual();
          setStatus("error", "माइक की इजाज़त नहीं मिली — टाइप करके भी बात कर सकते हैं।");
        });
    }, HOLD_DELAY_MS);
  });

  function endHoldVisual() {
    els.record.classList.remove("holding", "recording");
    els.recordLabel.textContent = "दबाकर बोलिए";
  }

  function endHold() {
    if (!holding) return;
    holding = false;
    clearTimeout(holdTimer);
    endHoldVisual();
    if (mediaRecorder && mediaRecorder.state === "recording") submitRecording();
  }

  els.record.addEventListener("pointerup", endHold);
  els.record.addEventListener("pointercancel", endHold);

  els.sendText.addEventListener("click", async () => {
    const message = els.text.value.trim();
    if (!message || busy) return;
    busy = true;
    addBubble("mine", message);
    els.text.value = "";
    setStatus("busy", "जवाब तैयार…");
    try {
      const reply = await postTurn(message, "text/plain; charset=utf-8");
      showReply(reply);
      setStatus("ok", "तैयार");
      if (ended(reply.text)) endSession();
    } catch (error) {
      setStatus("error", error.message);
      addBubble("anviq", error.message);
    } finally {
      busy = false;
    }
  });

  // Enter in the textarea sends, like chat.
  els.text.addEventListener("keydown", (event) => {
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault();
      els.sendText.click();
    }
  });
})();
