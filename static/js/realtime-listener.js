let threadEventSource = null;
let presenceEventSource = null;
let threadPollingTimer = null;
let presencePollingTimer = null;
let shellStateTimer = null;
let shellStateRequestInFlight = false;
let mentionLookupTimer = null;
let mentionAbortController = null;
let threadReconnectTimer = null;
let presenceReconnectTimer = null;
let chatroomPollingTimer = null;
let chatroomRequestInFlight = false;
let chatGifSearchTimer = null;
let cachedMentionUsers = null;
const guildDmHiddenStorageKey = "dchat.hiddenGuildDmUsers";

const mentionState = {
  textarea: null,
  menu: null,
  queryStart: -1,
  queryEnd: -1,
  suggestions: [],
  activeIndex: 0,
};

async function fetchText(url) {
  const res = await fetch(url, { headers: { "X-Requested-With": "XMLHttpRequest" } });
  if (!res.ok) return "";
  return await res.text();
}

async function fetchJson(url, options = {}) {
  try {
    const res = await fetch(url, options);
    const contentType = res.headers.get("content-type") || "";
    if (!res.ok || !contentType.includes("application/json")) return null;
    return await res.json();
  } catch {
    return null;
  }
}

function csrfToken() {
  const el = document.querySelector("input[name='csrfmiddlewaretoken']");
  return el ? el.value : "";
}

function hydrateEmbeds(scope) {
  if (window.twttr && window.twttr.widgets) {
    window.twttr.widgets.load(scope);
  }
}

function embeddedMentionUsers() {
  if (cachedMentionUsers !== null) return cachedMentionUsers;
  const node = document.getElementById("mentionable-users-data");
  if (!node) {
    cachedMentionUsers = [];
    return cachedMentionUsers;
  }
  try {
    cachedMentionUsers = JSON.parse(node.textContent || "[]");
  } catch {
    cachedMentionUsers = [];
  }
  return cachedMentionUsers;
}

function getMentionMenu(textarea) {
  const composer = textarea.closest("[data-composer-root]");
  if (!composer) return null;
  return composer.querySelector("[data-mention-menu]");
}

function hideMentionMenu() {
  if (mentionLookupTimer) {
    window.clearTimeout(mentionLookupTimer);
    mentionLookupTimer = null;
  }
  if (mentionAbortController) {
    mentionAbortController.abort();
    mentionAbortController = null;
  }
  if (mentionState.menu) {
    mentionState.menu.innerHTML = "";
    mentionState.menu.classList.add("is-hidden");
  }
  mentionState.textarea = null;
  mentionState.menu = null;
  mentionState.queryStart = -1;
  mentionState.queryEnd = -1;
  mentionState.suggestions = [];
  mentionState.activeIndex = 0;
}

function getMentionToken(textarea) {
  const cursor = textarea.selectionStart ?? textarea.value.length;
  const beforeCursor = textarea.value.slice(0, cursor);
  const match = beforeCursor.match(/(?:^|[^\w@])@([A-Za-z0-9_]*)$/);
  if (!match) return null;
  return {
    query: match[1],
    start: cursor - match[1].length - 1,
    end: cursor,
  };
}

function renderMentionMenu(menu, suggestions, activeIndex) {
  menu.innerHTML = "";
  suggestions.forEach((suggestion, index) => {
    const button = document.createElement("button");
    button.type = "button";
    button.className = `mention-item${index === activeIndex ? " is-active" : ""}`;
    button.dataset.mentionUsername = suggestion.username;
    button.setAttribute("role", "option");
    button.setAttribute("aria-selected", index === activeIndex ? "true" : "false");

    const avatarWrap = document.createElement("span");
    avatarWrap.className = "mention-avatar";
    if (suggestion.avatar_url) {
      const avatar = document.createElement("img");
      avatar.src = suggestion.avatar_url;
      avatar.alt = suggestion.username;
      avatar.className = "mention-avatar-image";
      avatarWrap.appendChild(avatar);
    } else {
      avatarWrap.classList.add("mention-avatar-fallback");
      avatarWrap.textContent = suggestion.username.slice(0, 1).toUpperCase();
    }

    const label = document.createElement("span");
    label.className = "mention-name";
    label.textContent = suggestion.username;

    button.appendChild(avatarWrap);
    button.appendChild(label);
    menu.appendChild(button);
  });
  menu.classList.toggle("is-hidden", suggestions.length === 0);
}

function applyMentionSelection(username) {
  const { textarea, queryStart, queryEnd } = mentionState;
  if (!textarea || queryStart < 0 || queryEnd < queryStart) return;
  const before = textarea.value.slice(0, queryStart);
  const after = textarea.value.slice(queryEnd);
  const inserted = `@${username} `;
  textarea.value = `${before}${inserted}${after}`;
  const caret = before.length + inserted.length;
  textarea.focus();
  textarea.setSelectionRange(caret, caret);
  textarea.dispatchEvent(new Event("input", { bubbles: true }));
  hideMentionMenu();
}

async function updateMentionSuggestions(textarea) {
  const menu = getMentionMenu(textarea);
  const token = getMentionToken(textarea);
  if (!menu || !token) {
    hideMentionMenu();
    return;
  }

  mentionState.textarea = textarea;
  mentionState.menu = menu;
  mentionState.queryStart = token.start;
  mentionState.queryEnd = token.end;

  if (mentionLookupTimer) {
    window.clearTimeout(mentionLookupTimer);
  }

  mentionLookupTimer = window.setTimeout(async () => {
    const localUsers = embeddedMentionUsers();
    if (localUsers.length) {
      const query = token.query.toLowerCase();
      mentionState.suggestions = localUsers
        .filter((user) => !query || user.username.toLowerCase().includes(query))
        .slice(0, 10);
      mentionState.activeIndex = 0;
      renderMentionMenu(menu, mentionState.suggestions, mentionState.activeIndex);
      return;
    }

    if (mentionAbortController) {
      mentionAbortController.abort();
    }
    mentionAbortController = new AbortController();
    const q = encodeURIComponent(token.query);
    const payload = await fetchJson(`/accounts/mentions/?q=${q}`, { signal: mentionAbortController.signal });
    if (!payload || mentionState.textarea !== textarea) return;
    mentionState.suggestions = payload.results || [];
    mentionState.activeIndex = 0;
    renderMentionMenu(menu, mentionState.suggestions, mentionState.activeIndex);
  }, 120);
}

function cycleMentionSelection(step) {
  if (!mentionState.suggestions.length) return;
  const count = mentionState.suggestions.length;
  mentionState.activeIndex = (mentionState.activeIndex + step + count) % count;
  renderMentionMenu(mentionState.menu, mentionState.suggestions, mentionState.activeIndex);
}

function applyMarkdown(textarea, before, after) {
  const selectionStart = textarea.selectionStart ?? 0;
  const selectionEnd = textarea.selectionEnd ?? selectionStart;
  const selected = textarea.value.slice(selectionStart, selectionEnd);
  const replacement = `${before}${selected}${after}`;
  textarea.setRangeText(replacement, selectionStart, selectionEnd, "end");
  const caretStart = selectionStart + before.length;
  const caretEnd = caretStart + selected.length;
  textarea.focus();
  textarea.setSelectionRange(caretStart, caretEnd);
  textarea.dispatchEvent(new Event("input", { bubbles: true }));
}

function applyMarkdownAction(textarea, button) {
  const action = button.dataset.mdAction || "";
  if (action === "quote") {
    const selectionStart = textarea.selectionStart ?? 0;
    const selectionEnd = textarea.selectionEnd ?? selectionStart;
    const selected = textarea.value.slice(selectionStart, selectionEnd) || "quoted text";
    const quoted = selected
      .split("\n")
      .map((line) => `> ${line}`)
      .join("\n");
    textarea.setRangeText(quoted, selectionStart, selectionEnd, "end");
    textarea.focus();
    textarea.dispatchEvent(new Event("input", { bubbles: true }));
    return;
  }
  applyMarkdown(textarea, button.dataset.mdBefore || "", button.dataset.mdAfter || "");
}

function clearReplyTarget() {
  const composer = document.querySelector("[data-post-composer]");
  if (!composer) return;
  const input = composer.querySelector("[data-reply-parent-input]");
  const target = document.getElementById("reply-target");
  const label = document.getElementById("reply-target-label");
  if (input) input.value = "";
  if (label) label.textContent = "";
  if (target) target.classList.add("is-hidden");
}

function chatroomFeedRoot() {
  return document.getElementById("chatroom-feed");
}

function chatroomComposer() {
  return document.querySelector("[data-chatroom-form]");
}

function clearChatReplyTarget() {
  const composer = chatroomComposer();
  if (!composer) return;
  const input = composer.querySelector("[data-chat-reply-input]");
  const target = composer.querySelector("[data-chat-reply-target]");
  const label = composer.querySelector("[data-chat-reply-label]");
  if (input) input.value = "";
  if (label) label.textContent = "";
  if (target) target.classList.add("is-hidden");
}

function setChatReplyTarget(messageId, username) {
  const composer = chatroomComposer();
  if (!composer) return;
  const input = composer.querySelector("[data-chat-reply-input]");
  const target = composer.querySelector("[data-chat-reply-target]");
  const label = composer.querySelector("[data-chat-reply-label]");
  const textarea = composer.querySelector("[data-markdown-input]");
  if (input) input.value = messageId;
  if (label) label.textContent = `Replying to @${username}`;
  if (target) target.classList.remove("is-hidden");
  if (textarea instanceof HTMLTextAreaElement) textarea.focus();
}

function insertChatQuote(messageId, username, sourceMessage) {
  const composer = chatroomComposer();
  if (!composer) return;
  const textarea = composer.querySelector("[data-markdown-input]");
  const body = sourceMessage.querySelector(".chat-message-body");
  if (!(textarea instanceof HTMLTextAreaElement) || !(body instanceof HTMLElement)) return;
  setChatReplyTarget(messageId, username);
  const plainText = body.innerText.replace(/\n{3,}/g, "\n\n").trim();
  if (!plainText) return;
  const quoted = plainText
    .split("\n")
    .map((line) => `> ${line}`)
    .join("\n");
  const block = `> @${username} wrote:\n${quoted}\n\n`;
  const prefix = textarea.value.trim() ? "\n" : "";
  textarea.value = `${textarea.value}${prefix}${block}`;
  const caret = textarea.value.length;
  textarea.focus();
  textarea.setSelectionRange(caret, caret);
  textarea.dispatchEvent(new Event("input", { bubbles: true }));
}

function chatroomIsNearBottom(feed) {
  return feed.scrollHeight - feed.scrollTop - feed.clientHeight < 180;
}

function chatroomErrorsRoot() {
  return document.querySelector("[data-chatroom-errors]");
}

function showChatroomErrors(errorMap) {
  const root = chatroomErrorsRoot();
  if (!root) return;
  const values = Object.values(errorMap || {}).flat().filter(Boolean);
  if (!values.length) {
    root.classList.add("is-hidden");
    root.innerHTML = "";
    return;
  }
  root.replaceChildren(
    ...values.map((value) => {
      const line = document.createElement("p");
      line.textContent = value;
      return line;
    }),
  );
  root.classList.remove("is-hidden");
}

function chatGifPreviewRoot() {
  return document.querySelector("[data-chat-gif-preview]");
}

function clearChatGifSelection() {
  const composer = chatroomComposer();
  const preview = chatGifPreviewRoot();
  const image = preview?.querySelector("[data-chat-gif-preview-image]") || null;
  const input = composer?.querySelector("input[name='gif_url']") || null;
  if (input instanceof HTMLInputElement) input.value = "";
  if (image instanceof HTMLImageElement) {
    image.src = "";
    image.alt = "";
  }
  if (preview) preview.classList.add("is-hidden");
}

function setChatGifSelection(url, title) {
  const composer = chatroomComposer();
  const preview = chatGifPreviewRoot();
  const image = preview?.querySelector("[data-chat-gif-preview-image]") || null;
  const input = composer?.querySelector("input[name='gif_url']") || null;
  if (!(input instanceof HTMLInputElement) || !(image instanceof HTMLImageElement) || !preview) return;
  if (!isAllowedKlipyUrl(url)) return;
  input.value = url;
  image.src = url;
  image.alt = title || "Selected GIF";
  preview.classList.remove("is-hidden");
}

function appendChatroomMessageHtml(html) {
  const feed = chatroomFeedRoot();
  if (!feed || !html) return null;
  const template = document.createElement("template");
  template.innerHTML = html.trim();
  const node = template.content.firstElementChild;
  if (!node) return null;
  feed.appendChild(node);
  hydrateEmbeds(node);
  return node;
}

function updateChatroomParticipants(html) {
  const root = document.getElementById("chatroom-participants-root");
  if (root && html) root.innerHTML = html;
}

async function refreshChatroomUpdates() {
  const feed = chatroomFeedRoot();
  if (!feed || chatroomRequestInFlight || document.hidden) return;
  const updatesUrl = feed.dataset.chatroomUpdatesUrl || "";
  if (!updatesUrl) return;
  const lastMessageId = feed.dataset.lastMessageId || "0";
  chatroomRequestInFlight = true;
  try {
    const payload = await fetchJson(`${updatesUrl}?after=${encodeURIComponent(lastMessageId)}`, {
      headers: { "X-Requested-With": "XMLHttpRequest" },
    });
    if (!payload?.ok) return;
    const shouldStick = chatroomIsNearBottom(feed);
    const messages = Array.isArray(payload.messages) ? payload.messages : [];
    messages.forEach((message) => {
      if (!message?.html) return;
      appendChatroomMessageHtml(message.html);
    });
    if (payload.participants_html) updateChatroomParticipants(payload.participants_html);
    if (typeof payload.latest_id === "number" || typeof payload.latest_id === "string") {
      feed.dataset.lastMessageId = String(payload.latest_id || lastMessageId);
    }
    if (messages.length && shouldStick) feed.scrollTop = feed.scrollHeight;
  } finally {
    chatroomRequestInFlight = false;
  }
}

function startChatroomPolling() {
  if (chatroomPollingTimer || !chatroomFeedRoot()) return;
  const feed = chatroomFeedRoot();
  if (feed) feed.scrollTop = feed.scrollHeight;
  refreshChatroomUpdates();
  chatroomPollingTimer = window.setInterval(refreshChatroomUpdates, 2000);
}

async function submitChatroomForm(form) {
  const action = form.getAttribute("action") || "";
  if (!action) return;
  showChatroomErrors({});
  const feed = chatroomFeedRoot();
  const shouldStick = feed ? chatroomIsNearBottom(feed) : true;
  const response = await fetch(action, {
    method: "POST",
    headers: { "X-Requested-With": "XMLHttpRequest" },
    body: new FormData(form),
  });
  const payload = await response.json().catch(() => null);
  if (!response.ok || !payload?.ok) {
    showChatroomErrors(payload?.errors || { form: ["Could not send chat message."] });
    return;
  }
  if (payload.message_html) appendChatroomMessageHtml(payload.message_html);
  if (payload.participants_html) updateChatroomParticipants(payload.participants_html);
  if (feed && payload.message_id) feed.dataset.lastMessageId = String(payload.message_id);
  form.reset();
  clearChatReplyTarget();
  clearChatGifSelection();
  showChatroomErrors({});
  attachFileInputStatusHandlers();
  if (feed && shouldStick) feed.scrollTop = feed.scrollHeight;
  refreshShellState();
}

function chatGifModal() {
  return document.querySelector("[data-chat-gif-modal]");
}

function isAllowedKlipyUrl(rawUrl) {
  if (!rawUrl) return false;
  try {
    const parsed = new URL(rawUrl);
    const hostname = parsed.hostname.toLowerCase();
    return (
      (parsed.protocol === "https:" || parsed.protocol === "http:") &&
      (hostname === "klipy.com" || hostname.endsWith(".klipy.com"))
    );
  } catch {
    return false;
  }
}

function normalizeKlipyItems(payload) {
  const items = Array.isArray(payload?.data?.data) ? payload.data.data : [];
  return items
    .map((item) => {
      const file = item?.file || {};
      const preview =
        file?.xs?.webp?.url ||
        file?.xs?.gif?.url ||
        file?.sm?.jpg?.url ||
        file?.sm?.webp?.url ||
        file?.sm?.gif?.url ||
        "";
      const embed =
        file?.sm?.gif?.url ||
        file?.md?.gif?.url ||
        file?.xs?.gif?.url ||
        file?.sm?.webp?.url ||
        "";
      if (!isAllowedKlipyUrl(preview) || !isAllowedKlipyUrl(embed)) return null;
      return {
        title: item?.title || item?.slug || "GIF",
        preview,
        embed,
      };
    })
    .filter((item) => item && item.preview && item.embed);
}

function renderChatGifResults(items) {
  const modal = chatGifModal();
  const grid = modal?.querySelector("[data-chat-gif-grid]") || null;
  if (!(grid instanceof HTMLElement)) return;
  grid.replaceChildren();
  if (!items.length) {
    const empty = document.createElement("p");
    empty.className = "empty-copy";
    empty.textContent = "No GIFs found yet. Try another search.";
    grid.appendChild(empty);
    return;
  }
  grid.append(
    ...items.map((item, index) => {
      const button = document.createElement("button");
      button.type = "button";
      button.className = "chat-gif-item";
      button.dataset.chatGifSelect = String(index);
      button.dataset.chatGifUrl = item.embed;
      button.dataset.chatGifTitle = item.title;

      const image = document.createElement("img");
      image.src = item.preview;
      image.alt = item.title;
      image.loading = "lazy";

      const label = document.createElement("span");
      label.textContent = item.title;

      button.append(image, label);
      return button;
    }),
  );
}

async function searchKlipyGifs(query) {
  const modal = chatGifModal();
  if (!(modal instanceof HTMLElement)) return;
  const appKey = modal.dataset.klipyAppKey || "";
  const apiBase = (modal.dataset.klipyApiBase || "").replace(/\/$/, "");
  const contentFilter = modal.dataset.klipyContentFilter || "medium";
  const customerId = modal.dataset.klipyCustomerId || "guest-browser";
  if (!appKey || !apiBase || query.trim().length < 2) {
    renderChatGifResults([]);
    return;
  }
  const locale = (navigator.language || "en-GB").split("-").pop()?.toLowerCase() || "gb";
  const params = new URLSearchParams({
    q: query.trim(),
    page: "1",
    per_page: "18",
    customer_id: customerId,
    locale,
    content_filter: contentFilter,
    format_filter: "gif,webp,jpg",
  });
  const payload = await fetchJson(`${apiBase}/api/v1/${encodeURIComponent(appKey)}/gifs/search?${params.toString()}`);
  renderChatGifResults(normalizeKlipyItems(payload));
}

function setReplyTarget(postId, username) {
  const composer = document.querySelector("[data-post-composer]");
  if (!composer) return;
  const input = composer.querySelector("[data-reply-parent-input]");
  const target = document.getElementById("reply-target");
  const label = document.getElementById("reply-target-label");
  const textarea = composer.querySelector("[data-markdown-input]");

  if (input) input.value = postId;
  if (label) label.textContent = `Replying to @${username}`;
  if (target) target.classList.remove("is-hidden");
  if (textarea instanceof HTMLTextAreaElement) {
    textarea.focus();
    textarea.scrollIntoView({ behavior: "smooth", block: "center" });
  }
}

function insertQuote(postId, username, sourcePost) {
  const composer = document.querySelector("[data-post-composer]");
  if (!composer) return;
  const textarea = composer.querySelector("[data-markdown-input]");
  const body = sourcePost.querySelector(".forum-post-body");
  if (!(textarea instanceof HTMLTextAreaElement) || !(body instanceof HTMLElement)) return;

  setReplyTarget(postId, username);

  const plainText = body.innerText.replace(/\n{3,}/g, "\n\n").trim();
  if (!plainText) return;

  const quoted = plainText
    .split("\n")
    .map((line) => `> ${line}`)
    .join("\n");
  const block = `> @${username} wrote:\n${quoted}\n\n`;
  const prefix = textarea.value.trim() ? "\n" : "";
  textarea.value = `${textarea.value}${prefix}${block}`;
  textarea.focus();
  const caret = textarea.value.length;
  textarea.setSelectionRange(caret, caret);
  textarea.dispatchEvent(new Event("input", { bubbles: true }));
}

async function refreshThreadReplies() {
  const root = document.getElementById("thread-posts-root");
  if (!root) return;
  const threadId = root.getAttribute("data-thread-id");
  if (!threadId) return;
  const html = await fetchText(`/threads/${threadId}/posts-fragment/`);
  if (html && html !== root.innerHTML) {
    hideMentionMenu();
    root.innerHTML = html;
    hydrateEmbeds(root);
  }
}

async function openUserCard(username) {
  const overlay = document.getElementById("user-card-overlay");
  if (!overlay) return;
  const html = await fetchText(`/accounts/u/${username}/card/`);
  if (!html) return;
  overlay.innerHTML = html;
  overlay.classList.remove("hidden");
  hydrateEmbeds(overlay);
}

function attachUserCardHandlers() {
  document.addEventListener("click", (event) => {
    const target = event.target;
    if (!(target instanceof HTMLElement)) return;
    const cardTrigger = target.closest("[data-user-card]");
    if (cardTrigger instanceof HTMLElement) {
      event.preventDefault();
      const username = cardTrigger.getAttribute("data-user-card");
      if (username) openUserCard(username);
      return;
    }
    if (target.id === "user-card-overlay") {
      target.classList.add("hidden");
      target.innerHTML = "";
    }
  });
}

function attachVoteHandlers() {
  document.addEventListener("click", async (event) => {
    const target = event.target;
    if (!(target instanceof HTMLElement)) return;
    const button = target.closest(".vote-btn");
    if (!(button instanceof HTMLElement)) return;
    const wrapper = button.closest(".vote-box");
    if (!wrapper) return;
    const targetType = wrapper.getAttribute("data-target-type");
    const targetId = wrapper.getAttribute("data-target-id");
    const value = button.getAttribute("data-vote");
    const body = new URLSearchParams({
      target_type: targetType || "",
      target_id: targetId || "",
      value: value || "",
      csrfmiddlewaretoken: csrfToken(),
    });
    const res = await fetch("/vote/", {
      method: "POST",
      headers: { "Content-Type": "application/x-www-form-urlencoded" },
      body: body.toString(),
    });
    if (!res.ok) return;
    const data = await res.json();
    const scoreNode = wrapper.querySelector(".score");
    if (scoreNode && data.ok) scoreNode.textContent = String(data.score);
  });
}

function attachComposerHandlers() {
  document.addEventListener("click", (event) => {
    const target = event.target;
    if (!(target instanceof HTMLElement)) return;

    const toolbarButton = target.closest(".composer-tool");
    if (toolbarButton instanceof HTMLButtonElement && toolbarButton.id !== "reply-target-clear") {
      const composer = toolbarButton.closest("[data-composer-root]");
      const textarea = composer ? composer.querySelector("[data-markdown-input]") : null;
      if (textarea instanceof HTMLTextAreaElement) {
        event.preventDefault();
        applyMarkdownAction(textarea, toolbarButton);
      }
      return;
    }

    if (target.id === "reply-target-clear") {
      event.preventDefault();
      clearReplyTarget();
      return;
    }

    const replyButton = target.closest("[data-reply-to]");
    if (replyButton instanceof HTMLElement) {
      const postId = replyButton.getAttribute("data-reply-to");
      const username = replyButton.getAttribute("data-reply-name");
      if (postId && username) {
        event.preventDefault();
        setReplyTarget(postId, username);
      }
      return;
    }

    const quoteButton = target.closest(".quote-trigger");
    if (quoteButton instanceof HTMLElement) {
      const sourcePost = quoteButton.closest(".forum-post");
      const postId = sourcePost ? sourcePost.getAttribute("id")?.replace("post-", "") : "";
      const username = quoteButton.getAttribute("data-quote-author");
      if (sourcePost instanceof HTMLElement && postId && username) {
        event.preventDefault();
        insertQuote(postId, username, sourcePost);
      }
      return;
    }

    const mentionItem = target.closest(".mention-item");
    if (mentionItem instanceof HTMLButtonElement) {
      event.preventDefault();
      const username = mentionItem.dataset.mentionUsername;
      if (username) applyMentionSelection(username);
      return;
    }

    if (mentionState.menu && !mentionState.menu.contains(target) && target !== mentionState.textarea) {
      hideMentionMenu();
    }
  });

  document.addEventListener("input", (event) => {
    const target = event.target;
    if (target instanceof HTMLTextAreaElement && target.matches("[data-markdown-input]")) {
      updateMentionSuggestions(target);
    }
  });

  document.addEventListener("keydown", (event) => {
    const target = event.target;
    if (!(target instanceof HTMLTextAreaElement) || target !== mentionState.textarea || !mentionState.suggestions.length) {
      return;
    }

    if (event.key === "ArrowDown") {
      event.preventDefault();
      cycleMentionSelection(1);
      return;
    }

    if (event.key === "ArrowUp") {
      event.preventDefault();
      cycleMentionSelection(-1);
      return;
    }

    if (event.key === "Enter" || event.key === "Tab") {
      event.preventDefault();
      const selected = mentionState.suggestions[mentionState.activeIndex];
      if (selected) applyMentionSelection(selected.username);
      return;
    }

    if (event.key === "Escape") {
      hideMentionMenu();
    }
  });
}

function attachChatroomHandlers() {
  document.addEventListener("click", (event) => {
    const target = event.target;
    if (!(target instanceof HTMLElement)) return;

    if (!target.closest(".chat-message-menu")) {
      document.querySelectorAll(".chat-message-menu[open]").forEach((node) => {
        if (node instanceof HTMLDetailsElement) node.removeAttribute("open");
      });
    }

    const replyButton = target.closest("[data-chat-reply-to]");
    if (replyButton instanceof HTMLElement) {
      event.preventDefault();
      const messageId = replyButton.getAttribute("data-chat-reply-to");
      const username = replyButton.getAttribute("data-chat-reply-name");
      if (messageId && username) setChatReplyTarget(messageId, username);
      const menu = replyButton.closest(".chat-message-menu");
      if (menu instanceof HTMLDetailsElement) menu.removeAttribute("open");
      return;
    }

    const quoteButton = target.closest("[data-chat-quote-to]");
    if (quoteButton instanceof HTMLElement) {
      event.preventDefault();
      const sourceMessage = quoteButton.closest(".chat-message-row");
      const messageId = quoteButton.getAttribute("data-chat-quote-to");
      const username = quoteButton.getAttribute("data-chat-quote-name");
      if (sourceMessage instanceof HTMLElement && messageId && username) {
        insertChatQuote(messageId, username, sourceMessage);
      }
      const menu = quoteButton.closest(".chat-message-menu");
      if (menu instanceof HTMLDetailsElement) menu.removeAttribute("open");
      return;
    }

    if (target.closest("[data-chat-reply-clear]")) {
      event.preventDefault();
      clearChatReplyTarget();
      return;
    }

    const jumpButton = target.closest("[data-chat-jump]");
    if (jumpButton instanceof HTMLElement) {
      event.preventDefault();
      const targetId = jumpButton.getAttribute("data-chat-jump");
      const message = targetId ? document.getElementById(`chat-message-${targetId}`) : null;
      if (message instanceof HTMLElement) {
        message.scrollIntoView({ behavior: "smooth", block: "center" });
      }
      return;
    }

    if (target.closest("[data-chat-gif-open]")) {
      event.preventDefault();
      const modal = chatGifModal();
      if (modal) modal.classList.remove("hidden");
      const input = modal?.querySelector("[data-chat-gif-query]");
      if (input instanceof HTMLInputElement) input.focus();
      return;
    }

    if (target.closest("[data-chat-gif-close]") || target === chatGifModal()) {
      event.preventDefault();
      const modal = chatGifModal();
      if (modal) modal.classList.add("hidden");
      return;
    }

    if (target.closest("[data-chat-gif-clear]")) {
      event.preventDefault();
      clearChatGifSelection();
      return;
    }

    const gifButton = target.closest("[data-chat-gif-select]");
    if (gifButton instanceof HTMLElement) {
      event.preventDefault();
      const url = gifButton.getAttribute("data-chat-gif-url") || "";
      const title = gifButton.getAttribute("data-chat-gif-title") || "GIF";
      if (url) setChatGifSelection(url, title);
      const modal = chatGifModal();
      if (modal) modal.classList.add("hidden");
    }
  });

  document.addEventListener("submit", (event) => {
    const target = event.target;
    if (!(target instanceof HTMLFormElement) || !target.matches("[data-chatroom-form]")) return;
    event.preventDefault();
    submitChatroomForm(target);
  });

  document.addEventListener("input", (event) => {
    const target = event.target;
    if (!(target instanceof HTMLInputElement) || !target.matches("[data-chat-gif-query]")) return;
    if (chatGifSearchTimer) window.clearTimeout(chatGifSearchTimer);
    chatGifSearchTimer = window.setTimeout(() => searchKlipyGifs(target.value), 220);
  });

  document.addEventListener("keydown", (event) => {
    if (event.key !== "Escape") return;
    let closedMenu = false;
    document.querySelectorAll(".chat-message-menu[open]").forEach((node) => {
      if (node instanceof HTMLDetailsElement) {
        node.removeAttribute("open");
        closedMenu = true;
      }
    });
    if (closedMenu) return;
    const modal = chatGifModal();
    if (modal && !modal.classList.contains("hidden")) {
      modal.classList.add("hidden");
    }
  });
}

function attachPermalinkHandlers() {
  document.addEventListener("click", async (event) => {
    const target = event.target;
    if (!(target instanceof HTMLElement)) return;
    const link = target.closest("[data-post-link]");
    if (!(link instanceof HTMLAnchorElement)) return;

    event.preventDefault();
    const hash = link.getAttribute("data-post-link");
    if (!hash) return;
    const url = `${window.location.origin}${window.location.pathname}${hash}`;
    window.history.replaceState(null, "", hash);
    const focusTarget = document.querySelector(hash);
    if (focusTarget instanceof HTMLElement) {
      focusTarget.scrollIntoView({ behavior: "smooth", block: "center" });
    }
    if (navigator.clipboard?.writeText) {
      try {
        await navigator.clipboard.writeText(url);
      } catch {
        // Ignore clipboard failures; hash navigation still works.
      }
    }
  });
}

function attachBackButtonHandlers() {
  document.addEventListener("click", (event) => {
    const target = event.target;
    if (!(target instanceof HTMLElement)) return;
    const button = target.closest("[data-go-back]");
    if (!(button instanceof HTMLAnchorElement)) return;
    if (window.history.length <= 1) return;
    event.preventDefault();
    window.history.back();
  });
}

function hiddenGuildDmKeys() {
  try {
    const parsed = JSON.parse(window.localStorage.getItem(guildDmHiddenStorageKey) || "[]");
    return Array.isArray(parsed) ? parsed.filter((value) => typeof value === "string" && value) : [];
  } catch {
    return [];
  }
}

function writeHiddenGuildDmKeys(keys) {
  window.localStorage.setItem(guildDmHiddenStorageKey, JSON.stringify(Array.from(new Set(keys))));
}

function applyGuildDmVisibility() {
  const hiddenKeys = new Set(hiddenGuildDmKeys());
  document.querySelectorAll("[data-guild-dm-pill]").forEach((node) => {
    node.hidden = hiddenKeys.has(node.getAttribute("data-guild-dm-key") || "");
  });
  document.querySelectorAll("[data-dm-conversation-key]").forEach((node) => {
    node.hidden = hiddenKeys.has(node.getAttribute("data-dm-conversation-key") || "");
  });
}

function attachGuildDmVisibilityHandlers() {
  const contextMenu = document.getElementById("shell-context-menu");
  const actionButton = contextMenu?.querySelector("[data-shell-menu-action]") || null;

  const hideContextMenu = () => {
    if (contextMenu) contextMenu.hidden = true;
    if (actionButton instanceof HTMLButtonElement) {
      actionButton.textContent = "";
      actionButton.dataset.menuAction = "";
      actionButton.dataset.guildDmKey = "";
    }
  };

  const showContextMenu = (x, y, action, key = "") => {
    if (!(contextMenu instanceof HTMLElement) || !(actionButton instanceof HTMLButtonElement)) return;
    actionButton.dataset.menuAction = action;
    actionButton.dataset.guildDmKey = key;
    actionButton.textContent = action === "restore" ? "Show hidden chats" : "Hide chat from sidebar";
    contextMenu.style.left = `${x}px`;
    contextMenu.style.top = `${y}px`;
    contextMenu.hidden = false;
  };

  applyGuildDmVisibility();
  document.addEventListener("contextmenu", (event) => {
    const target = event.target;
    if (!(target instanceof HTMLElement)) return;

    const guildDmPill = target.closest("[data-guild-dm-pill]");
    if (guildDmPill instanceof HTMLAnchorElement) {
      event.preventDefault();
      showContextMenu(event.clientX, event.clientY, "hide", guildDmPill.dataset.guildDmKey || "");
      return;
    }

    const inboxLink = target.closest("[data-inbox-link]");
    if (inboxLink instanceof HTMLAnchorElement && hiddenGuildDmKeys().length) {
      event.preventDefault();
      showContextMenu(event.clientX, event.clientY, "restore");
      return;
    }

    hideContextMenu();
  });

  document.addEventListener("click", (event) => {
    const target = event.target;
    const hideButton = target instanceof HTMLElement ? target.closest("[data-hide-guild-dm]") : null;
    if (hideButton instanceof HTMLButtonElement) {
      event.preventDefault();
      event.stopPropagation();
      writeHiddenGuildDmKeys([...hiddenGuildDmKeys(), hideButton.dataset.hideGuildDm || ""]);
      applyGuildDmVisibility();
      hideContextMenu();
      return;
    }

    if (target instanceof HTMLElement && target.closest("[data-shell-menu-action]") && actionButton instanceof HTMLButtonElement) {
      event.preventDefault();
      event.stopPropagation();
      const action = actionButton.dataset.menuAction;
      const key = actionButton.dataset.guildDmKey;
      if (action === "hide" && key) {
        writeHiddenGuildDmKeys([...hiddenGuildDmKeys(), key]);
        applyGuildDmVisibility();
      }
      if (action === "restore") {
        window.localStorage.removeItem(guildDmHiddenStorageKey);
        applyGuildDmVisibility();
      }
    }
    hideContextMenu();
  });

  document.addEventListener("scroll", hideContextMenu, true);
  window.addEventListener("resize", hideContextMenu);
}

function attachFileInputStatusHandlers() {
  const updateStatus = (input) => {
    if (!(input instanceof HTMLInputElement)) return;
    const targetId = input.dataset.fileCountTarget || "";
    if (!targetId) return;
    const status = document.getElementById(targetId);
    if (!status) return;
    const count = input.files?.length || 0;
    status.textContent = count ? `${count} image${count === 1 ? "" : "s"} selected` : "PNG, JPG, GIF - up to 8 MB each";
  };

  document.querySelectorAll("input[type='file'][data-file-count-target]").forEach((input) => updateStatus(input));
  document.addEventListener("change", (event) => {
    const target = event.target;
    if (target instanceof HTMLInputElement && target.type === "file" && target.dataset.fileCountTarget) {
      updateStatus(target);
    }
  });
}

function updateShellCounts(payload) {
  if (!payload || typeof payload !== "object") return;
  const inboxTotal = Number(payload.inbox_total || 0);
  const unreadNotifications = Number(payload.unread_notifications_count || 0);

  document.querySelectorAll("[data-inbox-count]").forEach((node) => {
    node.textContent = inboxTotal > 0 ? ` (${inboxTotal})` : "";
    node.hidden = inboxTotal <= 0;
  });

  document.querySelectorAll("[data-inbox-unread-chip]").forEach((node) => {
    node.textContent = `${inboxTotal} unread`;
    node.hidden = inboxTotal <= 0;
  });

  document.querySelectorAll("[data-notification-unread-badge]").forEach((node) => {
    node.textContent = `${unreadNotifications} unread`;
    node.hidden = unreadNotifications <= 0;
  });
}

async function refreshShellState() {
  const url = document.body?.dataset.shellStateUrl || "";
  if (!url || shellStateRequestInFlight || document.hidden) return;
  shellStateRequestInFlight = true;
  try {
    const payload = await fetchJson(url, { headers: { "X-Requested-With": "XMLHttpRequest" } });
    if (payload) updateShellCounts(payload);
  } finally {
    shellStateRequestInFlight = false;
  }
}

function startShellStatePolling() {
  const url = document.body?.dataset.shellStateUrl || "";
  if (!url || shellStateTimer) return;
  refreshShellState();
  shellStateTimer = window.setInterval(refreshShellState, 2500);
}

function startPollingFallback() {
  if (threadPollingTimer) return;
  refreshThreadReplies();
  threadPollingTimer = window.setInterval(() => {
    if (!document.hidden) refreshThreadReplies();
  }, 8000);
}

function startPresencePollingFallback() {
  return;
}

function initThreadStream() {
  const root = document.getElementById("thread-posts-root");
  if (!root || typeof EventSource === "undefined") return false;
  const threadId = root.getAttribute("data-thread-id");
  if (!threadId) return false;
  const lastSeen = 0;
  const url = `/threads/${threadId}/events/?last_seen=${lastSeen}`;
  try {
    threadEventSource = new EventSource(url);
  } catch {
    return false;
  }
  threadEventSource.onmessage = (event) => {
    if (!event.data) return;
    try {
      const payload = JSON.parse(event.data);
      if (payload.latest_post_id) refreshThreadReplies();
    } catch {
      return;
    }
  };
  threadEventSource.onerror = () => {
    threadEventSource?.close();
    threadEventSource = null;
    if (!threadPollingTimer) startPollingFallback();
  };
  return true;
}

function initPresenceStream() {
  if (typeof EventSource === "undefined") return false;
  try {
    presenceEventSource = new EventSource("/events/presence/");
  } catch {
    return false;
  }
  presenceEventSource.onerror = () => {
    presenceEventSource?.close();
    presenceEventSource = null;
  };
  return true;
}

function initFooterLocalTime() {
  const node = document.getElementById("footer-localtime");
  if (!node) return;
  const formatter = new Intl.DateTimeFormat(undefined, {
    hour: "2-digit",
    minute: "2-digit",
  });
  const update = () => {
    node.textContent = `Local time ${formatter.format(new Date())}`;
  };
  update();
  window.setInterval(update, 60000);
}

document.addEventListener("DOMContentLoaded", () => {
  attachUserCardHandlers();
  attachVoteHandlers();
  attachComposerHandlers();
  attachChatroomHandlers();
  attachPermalinkHandlers();
  attachBackButtonHandlers();
  attachGuildDmVisibilityHandlers();
  attachFileInputStatusHandlers();
  initFooterLocalTime();
  hydrateEmbeds(document);
  startShellStatePolling();
  startChatroomPolling();
  const threadStreaming = initThreadStream();
  const presenceStreaming = initPresenceStream();
  if (!threadStreaming && document.getElementById("thread-posts-root")) startPollingFallback();
  if (!presenceStreaming) startPresencePollingFallback();
});
